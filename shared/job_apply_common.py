#!/usr/bin/env python3
"""
Shared logic for the job-portal auto-apply agents (naukri_auto_apply.py,
iimjobs_auto_apply.py). Platform-specific scraping/apply-click code stays in each
script; anything about WHO the candidate is, HOW screening questions get answered,
and HOW relevance is scored lives here once, so a fix (like the fake-offer incident
fix below) applies to every platform automatically.

See naukri-agent/NOTES.md and iimjobs-agent/NOTES.md for the full incident history
and design rationale -- read those before changing anything here.

Candidate facts (name, experience, CV bullets, CTC, location) are NOT hardcoded
in this file -- they're loaded from profile.json at runtime (see
_load_profile_config() below). Copy profile.example.json to profile.json and
fill in your own facts before running the agents for real.
"""

import csv, json, os, re, signal, urllib.request
from datetime import datetime
from pathlib import Path


class JobTimeout(Exception):
    pass


def run_with_timeout(seconds: int, fn, *args, **kwargs):
    """
    Hard wall-clock timeout around a single job's processing, using SIGALRM
    (macOS/Unix only -- fine, this only ever runs on Adhiraj's Mac). Added
    2026-08-12 after an IIMJobs run hung indefinitely on some job with no
    progress for 20+ minutes and no root cause found live -- rather than chase
    every possible hang individually, no single job may ever be allowed to stall
    an entire unattended daily run again. Raises JobTimeout if fn doesn't return
    in time; caller should catch it and move on to the next job.
    """
    def _handler(signum, frame):
        raise JobTimeout(f"job exceeded {seconds}s hard timeout")

    old_handler = signal.signal(signal.SIGALRM, _handler)
    signal.alarm(seconds)
    try:
        return fn(*args, **kwargs)
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, old_handler)

# ── Profile facts (grounding for every LLM-answered screening question) ──────
#
# Loaded from profile.json at runtime (falls back to the placeholder
# profile.example.json if profile.json doesn't exist yet) rather than
# hardcoded here, so this module has no real personal data baked into it.
# Copy profile.example.json -> profile.json and fill in your own facts.

BASE_DIR = Path(__file__).parent
PROFILE_CONFIG_PATH = BASE_DIR / "profile.json"
PROFILE_EXAMPLE_PATH = BASE_DIR / "profile.example.json"


def _load_profile_config() -> dict:
    path = PROFILE_CONFIG_PATH if PROFILE_CONFIG_PATH.exists() else PROFILE_EXAMPLE_PATH
    with open(path, encoding="utf-8") as f:
        return json.load(f)


_profile_cfg = _load_profile_config()

KNOWN_TOTAL_EXPERIENCE_YEARS = _profile_cfg["known_total_experience_years"]
PROFILE_FACTS = _profile_cfg["profile_facts"]
CANDIDATE_NAME = _profile_cfg.get("name", "the candidate")

# ── Deterministic overrides ───────────────────────────────────────────────────
# High-stakes questions where a wrong/fabricated answer is a checkable-false-claim
# risk (a recruiter can directly follow up and catch it), not just a low-stakes
# skill assumption -- these get a fixed, minimal, non-fabricating answer instead
# of going to the LLM at all. Confirmed live 2026-08-12 on Naukri: the local model
# invented a fake competing offer with a specific company/salary when left to
# answer freely. Answer "Yes" and nothing else, no invented details.
DETERMINISTIC_OVERRIDES = [
    (re.compile(r'offer.{0,15}(in\s*hand|hold|holding)', re.I), "Yes"),
    (re.compile(r'\bmba\b', re.I), "Yes"),  # customize per your own education -- see profile.json
]


def deterministic_override_answer(question: str):
    for pattern, answer in DETERMINISTIC_OVERRIDES:
        if pattern.search(question):
            return answer
    return None


CURRENT_LOCATION_KEYWORDS = _profile_cfg["current_location_keywords"]


def currently_based_in_answer(question: str):
    """For 'are you currently living in / based in <city>' style questions --
    a directly observable, checkable fact, answered truthfully, not assumed
    favorably. Returns 'Yes'/'No' if this looks like that question type, else None."""
    ql = question.lower()
    if not re.search(r'(currently|presently).{0,20}(living|based|residing|located)', ql):
        return None
    return "Yes" if any(kw in ql for kw in CURRENT_LOCATION_KEYWORDS) else "No"


# ── Local LLM (Ollama) ────────────────────────────────────────────────────────
# Free/local, not a paid API. Requires a local Ollama server running the given
# model (see ../shared/README.md for setup). Override via env vars if your
# Ollama install uses a different host/port or model.

OLLAMA_URL   = os.environ.get("OLLAMA_URL", "http://localhost:11434/api/chat")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "llama3.2:3b")


def ollama_chat(system: str, user: str, max_tokens: int) -> str:
    payload = json.dumps({
        "model": OLLAMA_MODEL,
        "stream": False,
        "options": {"num_predict": max_tokens},
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    }).encode("utf-8")
    req = urllib.request.Request(OLLAMA_URL, data=payload, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return data["message"]["content"].strip()


def append_llm_log(log_path: Path, job_url: str, question: str, options, answer: str):
    is_new = not log_path.exists()
    with open(log_path, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["answered_at", "job_url", "question", "options", "answer"])
        if is_new:
            writer.writeheader()
        writer.writerow({
            "answered_at": datetime.now().isoformat(timespec="seconds"),
            "job_url": job_url, "question": question,
            "options": json.dumps(options) if options else "", "answer": answer,
        })


def llm_pick_option(log_path: Path, platform: str, job_url: str, question: str, options: list[str]) -> str:
    system = (
        f"You are helping {CANDIDATE_NAME} answer a job-application screening question "
        f"on {platform}. The objective is maximizing recruiter callbacks, not maximizing "
        "precision -- when in doubt, pick the most positive/affirmative option ('Yes' over "
        "'No', willing over unwilling, the higher/more-experienced choice) rather than the "
        "most literally accurate one. Use these real facts about him as grounding, not as a "
        f"reason to hedge or answer negatively:\n\n{PROFILE_FACTS}\n\nThe ONLY reason to avoid "
        "the positive option is if it would require asserting a specific, checkable, false "
        "fact -- a named employer, certification, degree, or exact figure he doesn't have. "
        "Vague willingness/adjacent-skill/general-fit questions should always lean toward the "
        "affirmative option, even on a stretch. Reply with EXACTLY one of the given option "
        "strings, verbatim, and nothing else -- no quotes, no extra words."
    )
    text = ollama_chat(system, f"Question: {question}\nOptions: {options}", max_tokens=20)
    text = text.strip().strip('"').strip("'")
    for opt in options:
        if opt.strip().lower() == text.strip().lower():
            append_llm_log(log_path, job_url, question, options, opt)
            return opt
    for opt in options:
        if opt.strip().lower() in text.lower() or text.lower() in opt.strip().lower():
            append_llm_log(log_path, job_url, question, options, opt)
            return opt
    append_llm_log(log_path, job_url, question, options, f"FALLBACK->{options[0]} (raw: {text!r})")
    return options[0]


def llm_number_answer(log_path: Path, platform: str, job_url: str, question: str, fallback: int = 0) -> str:
    """For 'how many years of experience in <X>' style numeric fields not covered
    by a deterministic rule. Returns a small integer as a string."""
    system = (
        f"You are helping {CANDIDATE_NAME} answer a numeric job-application screening "
        f"question on {platform} (a 'how many years of experience' style field). The "
        "objective is maximizing recruiter callbacks, not precision -- lean toward the "
        "higher end of what's plausible given these real facts about him, rather than "
        f"the most conservative honest estimate:\n\n{PROFILE_FACTS}\n\nDon't invent an "
        "implausible number for something totally unrelated to his background, but for "
        "anything adjacent to CRM/growth/marketing/analytics, round up rather than down. "
        "Reply with ONLY a whole number, nothing else -- no words, no units."
    )
    text = ollama_chat(system, f"Question: {question}", max_tokens=10)
    m = re.search(r'\d+', text)
    answer = m.group(0) if m else str(fallback)
    append_llm_log(log_path, job_url, question, None, answer)
    return answer


def llm_free_text_answer(log_path: Path, platform: str, job_url: str, question: str) -> str:
    system = (
        f"You are writing, in first person as {CANDIDATE_NAME}, a short answer to a "
        f"job-application screening question on {platform}. Objective is maximizing "
        "recruiter callbacks, not hedged precision -- write confidently and positively, "
        f"leaning into fit rather than qualifying it. Use these real facts about him:\n\n"
        f"{PROFILE_FACTS}\n\nKeep it to 1-3 sentences, professional, specific to the "
        "question. Make favorable assumptions for adjacent skills not explicitly listed "
        "rather than hedging or disclaiming -- but do not invent unrelated employers, "
        "degrees, or certifications, and don't state specific false numbers/facts."
    )
    answer = ollama_chat(system, f"Question: {question}", max_tokens=200)
    answer = answer.strip().strip('"')
    append_llm_log(log_path, job_url, question, None, answer)
    return answer


# ── Relevance scoring (platform-agnostic: works off title/skills/company/location text) ──

SCORE_RULES = {
    "clevertap":        (+20, "skills"),
    "moengage":         (+18, "skills"),
    "webengage":        (+15, "skills"),
    "braze":            (+15, "skills"),
    "leanplum":         (+10, "skills"),
    "whatsapp":         (+8,  "skills"),
    "push notification":(+6,  "skills"),
    "sms":              (+3,  "skills"),
    "in-app":           (+5,  "skills"),
    "segmentation":     (+8,  "skills"),
    "cohort":           (+8,  "skills"),
    "a/b test":         (+6,  "skills"),
    "propensity":       (+8,  "skills"),
    "intent":           (+6,  "skills"),
    "personalisation":  (+5,  "skills"),
    "personalization":  (+5,  "skills"),
    "automation":       (+4,  "skills"),
    "python":           (+5,  "skills"),
    "sql":              (+5,  "skills"),
    "snowflake":        (+6,  "skills"),
    "analytics":        (+4,  "skills"),
    "retention":        (+6,  "skills"),

    "e-commerce":       (+12, "all"),
    "ecommerce":        (+12, "all"),
    "marketplace":      (+12, "all"),
    "fintech":          (+12, "all"),
    "consumer tech":    (+10, "all"),
    "edtech":           (+8,  "all"),
    "healthtech":       (+8,  "all"),
    "saas":             (+6,  "all"),
    "startup":          (+5,  "all"),
    "d2c":              (+8,  "all"),
    "quick commerce":   (+10, "all"),
    "insurtech":        (+8,  "all"),
    "loans":            (+6,  "all"),
    "lending":          (+6,  "all"),

    "lifecycle":        (+15, "title"),
    "growth marketing": (+12, "title"),
    "retention marketing":(+12,"title"),
    "crm analytics":    (+10, "title"),
    "head of crm":      (+15, "title"),
    "head of growth":   (+15, "title"),
    "vp crm":           (+15, "title"),
    "director crm":     (+15, "title"),
    "vp growth":        (+15, "title"),
    "director growth":  (+15, "title"),

    "real estate":      (-25, "all"),
    "property":         (-20, "all"),
    "realty":           (-20, "all"),
    "construction":     (-15, "all"),
    "developer":        (-8,  "title"),
    "rera":             (-15, "skills"),
    "documentation":    (-8,  "skills"),
    "allotment":        (-10, "skills"),
    "hubspot":          (-8,  "skills"),
    "salesforce":       (-10, "skills"),
    "zoho":             (-5,  "skills"),
    "b2b":              (-8,  "all"),
}


# ── Positive relevance gate ────────────────────────────────────────────────
# Added 2026-08-29 after a live IIMJobs run applied to 40 jobs and roughly half
# turned out to have zero CRM/marketing content -- large-enterprise finance/ops/
# data-science associate roles, pure product-management roles at consumer
# marketplaces, pharma product roles, wealth management, telesales strategy, etc.
# Root cause: score_job() started every job at a flat +50 base (already above
# the apply threshold on its own) and only the SCORE_RULES negative-keyword
# list (real estate/property/construction/RERA + a few CRM-tool-vendor terms)
# could pull a job below threshold -- there was no requirement that a job show
# ANY actual CRM/growth-marketing signal, so anything that didn't look like
# real estate passed by default. Raising the threshold doesn't fix this (the
# base score is still a flat, content-free 50) -- what's needed is a hard gate
# requiring at least one genuine positive signal, applied AFTER SCORE_RULES so
# it can't be out-voted by unrelated domain/skill bonus points.
#
# Loosened same day after the first cut of this gate proved too strict on real
# titles (6/40 of that day's applies would've passed) -- e.g. "Associate Vice
# President - Growth Management" was rejected because the gate only matched
# the literal substring "growth manager", not the "management" inflection.
# Fix: for a small set of anchor words (currently just "growth") match by
# token proximity instead of exact substring, so inflection/word-order/minor
# punctuation differences don't matter. This is intentionally NOT applied to
# the "<qualifier> marketing" compounds (brand/product/shopper/category/
# performance/digital/customer/consumer/retention/engagement/field/trade/
# operations + marketing) -- those stay at token-adjacency (gap=0, so
# reordering/punctuation is tolerated but distance isn't) because loosening
# THAT one specifically is the exact mechanism that let pharma "Medico
# Marketing Manager - Product & Scientific Inputs" back in during testing
# (title contains "marketing" and "product", one word apart via "Manager").
# "growth" is a much rarer/stronger anchor word than "marketing" so a wider
# gap (1 intervening word) there carries much less of that specific risk.
# See HARD_EXCLUDE_PATTERNS below for a belt-and-suspenders backstop on the
# pharma/medico case specifically, independent of this gate's own logic.
GROWTH_WORDS         = {"growth"}
GROWTH_ROLE_WORDS     = {"manager", "management", "lead", "head", "vp", "director"}
MARKETING_WORD        = {"marketing"}
MARKETING_QUALIFIER_WORDS = {
    "brand", "product", "shopper", "category", "performance", "digital",
    "customer", "consumer", "retention", "engagement", "field", "trade",
    "operations",
}

# Standalone/strong signals -- one hit here is sufficient on its own, no
# proximity check needed. Deliberately CRM/growth-marketing/retention/
# lifecycle/customer-engagement specific (matching Adhiraj's real background
# per PROFILE_FACTS), not generic terms like bare "marketing", bare "growth",
# "automation", or "analytics" that would let pharma marketing, AI/automation
# consulting, or generic BI roles back in the same way the old flat +50 base
# did -- see .claude/agents/naukri-apply-agent.md / iimjobs-auto-apply-agent
# memory for why bare "marketing"/"growth" are deliberately excluded.
POSITIVE_RELEVANCE_PATTERNS = [re.compile(p, re.I) for p in [
    r'\bcrm\b', r'\bretention\b', r'\blifecycle\b', r'\bloyalty\b',
    r'\bchurn\b', r'\brechurn\b', r'\bd2c\b', r'\bcvm\b', r'\bmartech\b',
    r'\bpersonalisation\b', r'\bpersonalization\b',
    r'customer relationship management', r'customer value management',
    r'customer lifecycle', r'user lifecycle',
    r'clevertap', r'moengage', r'webengage', r'\bbraze\b', r'leanplum',
    r'netcore', r'iterable', r'customer\.io', r'salesforce marketing cloud',
    r'marketing automation', r'marketing operations',
]]

# Belt-and-suspenders hard exclude, independent of SCORE_RULES's existing
# real-estate/RERA denylist (untouched). Pharma/medico is the one domain
# where the growth/marketing proximity logic above has a demonstrated false-
# positive risk (see comment above) -- anything hitting these forces the
# score to 0 regardless of what else matched. Deliberately NOT extended to
# banking/finance-ops, pure product-management, or wealth-management titles:
# none of those contain "growth" or "marketing" at all in the titles seen so
# far, so they're already excluded by the positive gate itself with no
# additional risk from this loosening -- adding blanket domain excludes for
# them would risk wrongly killing a genuine future match (e.g. a real growth-
# marketing role at a wealth-management platform).
HARD_EXCLUDE_PATTERNS = [re.compile(p, re.I) for p in [
    r'\bpharma\b', r'\bpharmaceutical', r'\bmedico\b', r'\bnutraceutical',
]]


def _tokens(text: str) -> list[str]:
    return re.findall(r'[a-z0-9]+', text.lower())


def _near(tokens: list[str], set_a: set[str], set_b: set[str], max_gap: int = 0) -> bool:
    """True if some token in set_a and some token in set_b appear within
    max_gap other tokens of each other, in either order (max_gap=0 means
    immediately adjacent)."""
    idx_a = [i for i, t in enumerate(tokens) if t in set_a]
    if not idx_a:
        return False
    idx_b = [i for i, t in enumerate(tokens) if t in set_b]
    for i in idx_a:
        for j in idx_b:
            if i != j and abs(i - j) - 1 <= max_gap:
                return True
    return False


def has_hard_exclude(text: str) -> bool:
    return any(p.search(text) for p in HARD_EXCLUDE_PATTERNS)


def has_positive_relevance(title: str, skills: str) -> bool:
    """True if the job has at least one genuine CRM/growth-marketing/
    retention/lifecycle/customer-engagement signal -- either a standalone
    strong keyword (title only), "growth" near a role/seniority word
    (manager/management/lead/head/vp/director, within 1 intervening word,
    inflection-tolerant, title+skills), or "marketing" immediately next to a
    specific marketing-discipline qualifier word (title+skills). See the
    block comment above this function for why the two proximity checks use
    different gaps.

    Standalone strong keywords are checked against the TITLE ONLY, not
    skills tags -- found 2026-08-29 that Naukri's own skill-tag data is
    noisy enough to false-positive on job function: e.g. a MongoDB "Staff
    Technical Program Manager, GTM Tech" role (an internal engineering PM
    role, not marketing) passed the gate purely because a tool-name skill
    tag like "Salesforce Marketing Cloud" was listed among its skills --
    the role touches that tooling, it isn't a marketing role. A title
    match is a much stronger relevance signal than a skills tag, which can
    reflect tools/adjacent-systems the role merely touches. The
    growth/marketing proximity checks still use title+skills, since a
    two-word structural pattern is far less prone to that specific
    false-positive."""
    if any(p.search(title) for p in POSITIVE_RELEVANCE_PATTERNS):
        return True
    tokens = _tokens(f"{title} {skills}")
    if _near(tokens, GROWTH_WORDS, GROWTH_ROLE_WORDS, max_gap=1):
        return True
    if _near(tokens, MARKETING_WORD, MARKETING_QUALIFIER_WORDS, max_gap=0):
        return True
    return False


def score_job(job: dict) -> tuple[int, list[str]]:
    title  = job["title"].lower()
    skills = job["skills"].lower()
    co     = job["company"].lower()
    all_text = f"{title} {skills} {co} {job['location'].lower()}"

    points = 50
    reasons = ["+50 base"]

    for keyword, (delta, scope) in SCORE_RULES.items():
        kw = keyword.lower()
        hit = (
            (scope == "title"  and kw in title)  or
            (scope == "skills" and kw in skills) or
            (scope == "all"    and kw in all_text)
        )
        if hit:
            points += delta
            reasons.append(f"{delta:+d} '{keyword}' in {scope}")

    # Hard gate, applied after all SCORE_RULES bonuses/penalties so it can't be
    # out-voted by unrelated domain points (fintech/saas/startup/etc.) -- a job
    # with no real CRM/growth-marketing signal is capped to 0 regardless of
    # what else it scored, guaranteeing rejection under any sane threshold.
    title_skills = f"{title} {skills}"
    if has_hard_exclude(title_skills):
        points = 0
        reasons.append(
            "HARD EXCLUDE: pharma/medico domain keyword present -- score "
            "capped to 0 regardless of any positive signal"
        )
    elif not has_positive_relevance(title, skills):
        points = 0
        reasons.append(
            "GATE FAILED: no CRM/growth-marketing/retention/lifecycle/"
            "customer-engagement keyword in title or skills -- score capped "
            "to 0 regardless of the bonuses/penalties above"
        )

    return max(0, min(100, points)), reasons


# ── Experience / CTC filters ─────────────────────────────────────────────────

def experience_ok(exp_text: str, exp_min: int, exp_max: int) -> tuple[bool, str]:
    nums = [int(n) for n in re.findall(r'\d+', exp_text)]
    if not nums:
        return True, "no experience range listed, not rejected"
    job_min = nums[0]
    job_max = nums[1] if len(nums) > 1 else nums[0]
    if job_max < exp_min or job_min > exp_max:
        return False, f"experience {job_min}-{job_max} yrs doesn't overlap {exp_min}-{exp_max} yrs"
    return True, f"experience {job_min}-{job_max} yrs overlaps {exp_min}-{exp_max} yrs"


def ctc_ok(salary_text: str, ctc_min_lpa: float) -> tuple[bool, str]:
    if not salary_text or "not disclosed" in salary_text.lower():
        return True, "salary not disclosed, not rejected"
    nums = [float(n) for n in re.findall(r'\d+(?:\.\d+)?', salary_text)]
    if not nums:
        return True, "salary text unparseable, not rejected"
    upper = max(nums)
    if upper < ctc_min_lpa:
        return False, f"disclosed salary tops out at {upper:g} LPA, below {ctc_min_lpa} LPA floor"
    return True, f"disclosed salary tops out at {upper:g} LPA, meets {ctc_min_lpa} LPA floor"


def safe_text(el) -> str:
    try:
        return el.inner_text().strip()
    except Exception:
        return ""
