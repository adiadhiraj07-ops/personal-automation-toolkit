#!/usr/bin/env python3
"""
Naukri Auto-Apply — searches for target roles, filters by experience/CTC/relevance,
and applies automatically to qualifying jobs. Runs daily via launchd
(com.adhiraj.naukri-auto-apply.plist, 9:00 AM).

Every job found is written to the report with a status and a reason — nothing is
silently dropped — so the filtering logic can be audited before trusting it to run
unattended.

FIRST RUN:
    python3 naukri_login.py          # one-time manual login, saves session

DRY RUN (default — scrapes, scores, shows what WOULD happen, applies to nothing):
    python3 naukri_auto_apply.py

LIVE RUN (actually clicks Apply on qualifying jobs):
    python3 naukri_auto_apply.py --live

OPTIONS:
    python3 naukri_auto_apply.py --keyword "growth marketing manager"
    python3 naukri_auto_apply.py --pages 2
    python3 naukri_auto_apply.py --live --headless
"""

import csv, json, time, random, argparse, re, subprocess, os, sys
from datetime import datetime
from pathlib import Path
from playwright.sync_api import sync_playwright, TimeoutError as PwTimeout

# job_apply_common.py lives in the sibling shared/ directory (split out of a
# single flat folder for this repo) -- add it to the import path.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "shared"))
import job_apply_common as jac

# ── Config ────────────────────────────────────────────────────────────────────

BASE_DIR     = Path(__file__).parent
PROFILE_DIR  = os.environ.get("NAUKRI_PROFILE_DIR", str(BASE_DIR / ".naukri-profile"))
APPLIED_LOG  = BASE_DIR / "naukri_applied_log.csv"
OUTPUT_HTML  = BASE_DIR / "naukri_auto_apply_report.html"
OUTPUT_CSV   = BASE_DIR / "naukri_auto_apply_report.csv"
MANUAL_LIST_CSV  = BASE_DIR / "naukri_manual_apply_list.csv"
MANUAL_DASHBOARD = BASE_DIR / "naukri_manual_apply_dashboard.html"
LLM_LOG      = BASE_DIR / "naukri_llm_answers_log.csv"
PLATFORM_NAME = "Naukri.com"

# Role-title keywords — derived from Adhiraj's Naukri profile headline
# ("General Manager - CRM & Growth | Multi-channel Automation & CRM Strategies")
# and key skills (CRM Strategy, Retention, Marketing Automation, WhatsApp Marketing,
# Journey Builder, Customer Acquisition). Edit freely — this is a first cut.
TARGET_KEYWORDS = [
    "head of CRM",
    "CRM manager",
    "lifecycle marketing manager",
    "growth marketing manager",
    "retention marketing manager",
    "CRM analytics",
    "head of growth marketing",
    "marketing automation manager",
    "customer retention manager",
]

EXPERIENCE_MIN     = 5
EXPERIENCE_MAX     = 15
CTC_MIN_LPA        = 30      # only rejects when salary IS disclosed and its upper end is below this

# Per Adhiraj's 2026-08-12 instruction: apply broadly to maximize callback volume,
# not just to "strong fit" roles. This threshold is set low enough to include the
# old "rejected_score" bucket (generic titles with no negative signal, scored ~42-54)
# while still excluding jobs that hit real negative signals (real estate/property/
# realty/construction, which net out at ~22-27) -- those exclusions were deliberate,
# not noise, so the floor stays above them rather than going to zero.
APPLY_SCORE_THRESHOLD = 35
MAX_APPLIES_PER_RUN   = 40    # safety cap against a scraper/scoring bug mass-applying in one run

# Per Adhiraj's 2026-08-12 instruction: the daily run must land at least this many
# applies. If the initial keyword/page sweep comes up short (live mode only), run()
# escalates by fetching more pages per keyword, in increments, up to MAX_ESCALATION_PAGES,
# stopping early if every keyword runs out of fresh results first.
MIN_APPLIES_TARGET     = 40
ESCALATION_STEP_PAGES  = 5
MAX_ESCALATION_PAGES   = 20

# Used to answer screening-chatbot questions that are structurally proven to be
# a pure "how many years..." bracket (every option matches a numeric-years pattern --
# see answer_experience_bracket()). Source: Naukri profile "7 Years 2 Months" (Aug 2026).
# Update this if it goes stale.
KNOWN_TOTAL_EXPERIENCE_YEARS = jac.KNOWN_TOTAL_EXPERIENCE_YEARS
PROFILE_FACTS = jac.PROFILE_FACTS
deterministic_override_answer = jac.deterministic_override_answer
currently_based_in_answer = jac.currently_based_in_answer

def llm_pick_option(job_url: str, question: str, options: list[str]) -> str:
    return jac.llm_pick_option(LLM_LOG, PLATFORM_NAME, job_url, question, options)

def llm_free_text_answer(job_url: str, question: str) -> str:
    return jac.llm_free_text_answer(LLM_LOG, PLATFORM_NAME, job_url, question)

def append_llm_log(job_url: str, question: str, options, answer: str):
    jac.append_llm_log(LLM_LOG, job_url, question, options, answer)

SCORE_RULES = jac.SCORE_RULES

def score_job(job: dict) -> tuple[int, list[str]]:
    return jac.score_job(job)

CSV_COLUMNS = [
    "decision", "reason", "score", "title", "company", "location", "experience",
    "salary", "skills", "posted", "url", "keyword_searched", "naukri_button_text",
]

def experience_ok(exp_text: str) -> tuple[bool, str]:
    return jac.experience_ok(exp_text, EXPERIENCE_MIN, EXPERIENCE_MAX)

def ctc_ok(salary_text: str) -> tuple[bool, str]:
    return jac.ctc_ok(salary_text, CTC_MIN_LPA)



# ── Applied log (cross-run dedup) ────────────────────────────────────────────

def load_applied_log() -> set:
    if not APPLIED_LOG.exists():
        return set()
    with open(APPLIED_LOG, newline="", encoding="utf-8") as f:
        return {row["url"] for row in csv.DictReader(f)}


def append_applied_log(job: dict):
    is_new = not APPLIED_LOG.exists()
    with open(APPLIED_LOG, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["applied_at", "title", "company", "url", "score"])
        if is_new:
            writer.writeheader()
        writer.writerow({
            "applied_at": datetime.now().isoformat(timespec="seconds"),
            "title": job["title"], "company": job["company"],
            "url": job["url"], "score": job["score"],
        })


# ── Scraper (same selectors as naukri_search.py) ─────────────────────────────

def slug(keyword: str) -> str:
    return keyword.strip().lower().replace(" ", "-")

def build_url(keyword: str, page: int = 1) -> str:
    base   = f"https://www.naukri.com/{slug(keyword)}-jobs"
    params = f"?experience={EXPERIENCE_MIN}&experienceto={EXPERIENCE_MAX}"
    if page > 1:
        params += f"&pageNo={page}"
    return base + params

def wait(lo=1.5, hi=3.0):
    time.sleep(random.uniform(lo, hi))

def safe_text(el) -> str:
    try:
        return el.inner_text().strip()
    except Exception:
        return ""

def salary_text(card) -> str:
    sal_wrap = card.query_selector(".sal-wrap")
    if not sal_wrap:
        return "Not disclosed"
    for span in sal_wrap.query_selector_all("span"):
        txt = safe_text(span)
        if txt and re.search(r'\d', txt):
            return txt
    return "Not disclosed"

def scrape_page(page, url: str, keyword: str) -> list[dict]:
    jobs = []
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=30000)
    except PwTimeout:
        print(f"  [timeout] {url}")
        return jobs
    except Exception as e:
        # A transient nav error (e.g. net::ERR_NETWORK_CHANGED) must never crash
        # the whole run uncaught -- the report only saves at the very end, so one
        # bad page would lose every result from the run. Skip and keep going.
        print(f"  [nav error, skipping page] {url}: {e}")
        return jobs
    try:
        page.wait_for_selector(".srp-jobtuple-wrapper", timeout=12000)
    except PwTimeout:
        print(f"  [no results] {url}")
        return jobs

    wait(1.0, 1.5)
    cards = page.query_selector_all(".srp-jobtuple-wrapper")
    print(f"  {len(cards)} cards.")

    for card in cards:
        try:
            title_el  = card.query_selector("a.title")
            title     = safe_text(title_el) if title_el else ""
            job_url   = (title_el.get_attribute("href") or "") if title_el else ""
            comp_el   = card.query_selector("a.comp-name")
            company   = safe_text(comp_el) if comp_el else ""
            exp_el    = card.query_selector(".expwdth")
            exp       = safe_text(exp_el) if exp_el else ""
            loc_el    = card.query_selector(".locWdth")
            location  = safe_text(loc_el) if loc_el else ""
            salary    = salary_text(card)
            skills    = ", ".join([safe_text(s) for s in card.query_selector_all("li.tag-li")[:6] if safe_text(s)])
            posted_el = card.query_selector(".job-post-day")
            posted    = safe_text(posted_el) if posted_el else ""

            if title and company:
                jobs.append({
                    "title": title, "company": company, "location": location,
                    "experience": exp, "salary": salary, "skills": skills,
                    "posted": posted, "url": job_url, "keyword_searched": keyword,
                })
        except Exception as e:
            print(f"  [card error] {e}")
    return jobs


def deduplicate(jobs: list[dict]) -> list[dict]:
    seen, unique = set(), []
    for j in jobs:
        key = (j["title"].lower(), j["company"].lower())
        if key not in seen:
            seen.add(key)
            unique.append(j)
    return unique


# ── Apply flow ────────────────────────────────────────────────────────────────

def get_button_state(detail_page) -> str:
    """Returns 'apply' | 'company_site' | 'applied' | 'unknown'.
    The post-apply confirmation is a <span id="already-applied">, NOT the
    apply button -- checked first since it's the ground truth."""
    if detail_page.query_selector("#already-applied"):
        return "applied"
    if detail_page.query_selector("#company-site-button"):
        return "company_site"
    btn = detail_page.query_selector("#apply-button")
    if btn:
        txt = safe_text(btn).lower()
        if "applied" in txt:
            return "applied"
        return "apply"
    return "unknown"


def wait_for_modal(detail_page, timeout_ms=4000):
    try:
        detail_page.wait_for_selector(".chatbot_Drawer", state="visible", timeout=timeout_ms)
        return detail_page.query_selector(".chatbot_Drawer")
    except PwTimeout:
        return None


def capture_modal(detail_page, drawer, note: str) -> str:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    dump_path = BASE_DIR / f"naukri_modal_capture_{ts}"
    try:
        detail_page.screenshot(path=str(dump_path) + ".png")
        text = drawer.inner_text() if drawer else ""
        dump_path.with_suffix(".txt").write_text(f"{note}\n\n{text}", encoding="utf-8")
    except Exception:
        pass
    return dump_path.name


def parse_years_bracket(label: str):
    """Returns (lo, hi) in years if label is a pure numeric-years bracket, else None."""
    label = label.strip().lower()
    m = re.match(r'^less than\s*(\d+(?:\.\d+)?)\s*years?$', label)
    if m: return (0.0, float(m.group(1)))
    m = re.match(r'^(\d+(?:\.\d+)?)\s*-\s*(\d+(?:\.\d+)?)\s*years?$', label)
    if m: return (float(m.group(1)), float(m.group(2)))
    m = re.match(r'^(\d+(?:\.\d+)?)\+\s*years?$', label)
    if m: return (float(m.group(1)), float('inf'))
    m = re.match(r'^(\d+(?:\.\d+)?)\s*years?$', label)
    if m: return (float(m.group(1)), float(m.group(1)))
    return None


def answer_experience_bracket(option_labels: list[str], years: float):
    """Only returns an answer if EVERY option is structurally a numeric-years
    bracket -- this proves the question is a pure experience-bracket question
    regardless of how it's worded, rather than guessing from the question text
    (which could be domain/tool-specific, e.g. 'years managing Meta Ads')."""
    brackets = [(opt, parse_years_bracket(opt)) for opt in option_labels]
    if any(b is None for _, b in brackets):
        return None
    for opt, (lo, hi) in brackets:
        if lo <= years <= hi:
            return opt
    return max(brackets, key=lambda x: x[1][1])[0]  # years exceeds all brackets -> pick highest


def current_question_text(drawer) -> str:
    msgs = drawer.query_selector_all(".botMsg")
    if not msgs:
        return ""
    return safe_text(msgs[-1])


# deterministic_override_answer() comes from job_apply_common (aliased above) --
# shared across platforms so fixes like the MBA/offer-in-hand rules apply everywhere.


def handle_chatbot_modal(detail_page, drawer, job_url: str) -> tuple[str, str]:
    """
    Walks a Naukri screening-chatbot flow to completion. Pure years-of-experience
    bracket questions (see answer_experience_bracket) are answered deterministically
    for free. Everything else -- other radio questions and free-text questions --
    is answered by the LLM using Adhiraj's real profile facts (PROFILE_FACTS),
    per his 2026-08-12 instruction to answer with best judgement rather than skip,
    favoring callback likelihood. Every LLM answer is logged to
    naukri_llm_answers_log.csv for audit. Returns (result, detail):
      result = 'answered_all' | 'unrecognized' | 'error'
    """
    for step in range(1, 7):
        drawer = detail_page.query_selector(".chatbot_Drawer")
        if not drawer or not drawer.is_visible():
            if detail_page.query_selector("#already-applied"):
                return "answered_all", f"answered {step-1} question(s), application submitted"
            return "error", f"drawer disappeared after {step-1} answered question(s) with no confirmation"

        question = current_question_text(drawer)
        radios = drawer.query_selector_all("input[type='radio']")

        if radios:
            options = []
            for r in radios:
                rid = r.get_attribute("id") or ""
                label_el = drawer.query_selector(f"label[for='{rid}']")
                options.append((rid, safe_text(label_el) or rid))
            option_labels = [label for _, label in options]

            chosen_label = answer_experience_bracket(option_labels, KNOWN_TOTAL_EXPERIENCE_YEARS)
            if chosen_label is None:
                override = deterministic_override_answer(question)
                if override is not None:
                    # match override to closest real option rather than typing it verbatim
                    chosen_label = next((o for o in option_labels if o.strip().lower() == override.lower()), None) \
                                   or next((o for o in option_labels if override.lower() in o.lower()), None) \
                                   or option_labels[0]
                    append_llm_log(job_url, question, option_labels, f"OVERRIDE->{chosen_label}")
                else:
                    try:
                        chosen_label = llm_pick_option(job_url, question, option_labels)
                    except Exception as e:
                        note = capture_modal(detail_page, drawer, f"LLM call failed: {e}")
                        return "unrecognized", f"LLM answer failed -- captured to {note}.png"

            rid_to_click = next(rid for rid, label in options if label == chosen_label)
            label_el = drawer.query_selector(f"label[for='{rid_to_click}']")
            if not label_el:
                return "error", f"couldn't find label for chosen option {chosen_label!r}"
            label_el.click()
            time.sleep(0.8)

        else:
            text_area = drawer.query_selector(".textArea[contenteditable='true']")
            if not text_area:
                # No input control -- could be a genuinely unknown question type, or
                # (confirmed live) a trailing closing message like "Thank you for
                # your responses" after the last real question, where the flow has
                # already completed. Check ground truth before giving up.
                if detail_page.query_selector("#already-applied"):
                    return "answered_all", f"answered {step-1} question(s), application submitted"
                note = capture_modal(detail_page, drawer, "no radio and no text input found -- unknown question type")
                return "unrecognized", f"unknown question control type -- captured to {note}.png"
            override = deterministic_override_answer(question)
            if override is not None:
                answer = override
                append_llm_log(job_url, question, None, f"OVERRIDE->{answer}")
            else:
                try:
                    answer = llm_free_text_answer(job_url, question)
                except Exception as e:
                    note = capture_modal(detail_page, drawer, f"LLM call failed: {e}")
                    return "unrecognized", f"LLM answer failed -- captured to {note}.png"
            # Re-locate fresh right before interacting -- the LLM call takes a few
            # seconds and the drawer's DOM can re-render in that window, which
            # detaches any element handle grabbed before the call (confirmed bug).
            try:
                locator = detail_page.locator(".chatbot_Drawer .textArea[contenteditable='true']").last
                locator.click(timeout=5000)
                detail_page.keyboard.type(answer, delay=15)
            except Exception as e:
                if detail_page.query_selector("#already-applied"):
                    return "answered_all", f"answered {step-1} question(s), application submitted (flow closed before this exchange)"
                note = capture_modal(detail_page, drawer, f"couldn't type answer into text area: {e}")
                return "error", f"text area interaction failed -- captured to {note}.png"
            time.sleep(0.5)

        send = detail_page.query_selector(".sendMsg")
        if not send:
            note = capture_modal(detail_page, drawer, "answered but no send/submit control found")
            return "error", f"no submit control after answering -- captured to {note}.png"
        send.click()
        time.sleep(2.0)

    return "unrecognized", "more than 6 questions in the chain, aborting rather than looping indefinitely"


def click_apply(detail_page, job_url: str) -> tuple[str, str]:
    """
    Clicks the internal Apply button. Returns (result, detail):
      result = 'applied' | 'modal_skipped' | 'error'

    Naukri's UI doesn't reliably reflect the post-click state on the same page
    instance (confirmed: state only shows correctly after a fresh navigation),
    and the click itself occasionally doesn't register at all (confirmed: some
    clicks leave the job in unchanged 'Apply' state even after a reload). So
    this reloads to check ground truth, and retries the click a couple of
    times before giving up -- real duplicate-apply risk is negligible since
    Naukri itself blocks/no-ops a second click once #already-applied exists.
    """
    for attempt in range(1, 4):
        btn = detail_page.query_selector("#apply-button")
        if not btn or not btn.is_visible():
            return "error", f"apply button not found/visible at click time (attempt {attempt})"

        btn.click()

        drawer = wait_for_modal(detail_page, timeout_ms=4000)
        if drawer:
            result, detail = handle_chatbot_modal(detail_page, drawer, job_url)
            if result == "answered_all":
                return "applied", detail
            return "modal_skipped", detail

        # Re-navigate fresh to get ground-truth state (same-page state lags/misses)
        try:
            detail_page.goto(job_url, wait_until="domcontentloaded", timeout=20000)
            time.sleep(1.5)
        except Exception:
            pass

        state = get_button_state(detail_page)
        if state == "applied":
            return "applied", f"instant apply, no modal (attempt {attempt})"

        # Click didn't register -- retry from a fresh Apply button
        time.sleep(1.0)

    return "error", f"click didn't register after {attempt} attempts, still in '{state}' state"


# ── HTML Report ───────────────────────────────────────────────────────────────

DECISION_STYLE = {
    "applied":            ("#0f5132", "#d1e7dd", "Applied"),
    "would_apply":        ("#0f5132", "#d1e7dd", "Would apply (dry run)"),
    "already_applied":    ("#41464b", "#e2e3e5", "Already applied"),
    "manual_needed":      ("#055160", "#cff4fc", "Needs manual apply (company site)"),
    "rejected_experience":("#842029", "#f8d7da", "Rejected: experience"),
    "rejected_salary":    ("#842029", "#f8d7da", "Rejected: CTC below floor"),
    "rejected_score":     ("#842029", "#f8d7da", "Rejected: low relevance"),
    "modal_skipped":      ("#664d03", "#fff3cd", "Modal appeared, skipped"),
    "capped":             ("#664d03", "#fff3cd", "Deferred (per-run cap hit)"),
    "error":              ("#664d03", "#fff3cd", "Error"),
}

def build_html(jobs: list[dict], live: bool) -> str:
    counts = {}
    for j in jobs:
        counts[j["decision"]] = counts.get(j["decision"], 0) + 1

    rows = ""
    for j in jobs:
        fg, bg, label = DECISION_STYLE.get(j["decision"], ("#842029", "#f8d7da", j["decision"]))
        skill_tags = "".join(
            f'<span class="tag">{s.strip()}</span>' for s in j["skills"].split(",") if s.strip()
        )
        rows += f"""
        <tr>
          <td><span class="status-badge" style="background:{bg};color:{fg}">{label}</span></td>
          <td><span class="score-badge">{j['score']}</span></td>
          <td>
            <a class="job-title" href="{j['url']}" target="_blank">{j['title']}</a>
          </td>
          <td><strong>{j['company']}</strong></td>
          <td>{j['location']}</td>
          <td>{j['experience']}</td>
          <td>{j['salary']}</td>
          <td class="skills-cell">{skill_tags}</td>
          <td class="reason-cell">{j['reason']}</td>
        </tr>"""

    run_dt = datetime.now().strftime("%d %b %Y, %H:%M")
    mode = "LIVE (applies submitted)" if live else "DRY RUN (nothing applied)"

    stat_html = "".join(
        f'<div class="stat"><div class="n">{counts.get(k,0)}</div><div class="l">{label}</div></div>'
        for k, (_, _, label) in DECISION_STYLE.items() if counts.get(k, 0) > 0
    )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Naukri Auto-Apply Report — {run_dt}</title>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
          font-size: 13px; background: #f5f7fa; color: #1a1a2e; }}
  .header {{ background: #0e2d5e; color: white; padding: 20px 32px; }}
  .header h1 {{ font-size: 20px; font-weight: 700; }}
  .header p  {{ margin-top: 4px; opacity: .8; font-size: 12px; }}
  .stats {{ display: flex; gap: 20px; padding: 16px 32px; background: white;
            border-bottom: 1px solid #e2e8f0; flex-wrap: wrap; }}
  .stat  {{ text-align: center; }}
  .stat .n {{ font-size: 22px; font-weight: 800; color: #0e2d5e; }}
  .stat .l {{ font-size: 10px; color: #718096; text-transform: uppercase; letter-spacing: .04em; }}
  .table-wrap {{ padding: 20px 32px; overflow-x: auto; }}
  table {{ width: 100%; border-collapse: collapse; background: white;
           border-radius: 8px; overflow: hidden; box-shadow: 0 1px 4px rgba(0,0,0,.08); }}
  th {{ background: #0e2d5e; color: white; text-align: left; padding: 10px 12px;
        font-size: 11px; text-transform: uppercase; letter-spacing: .05em; white-space: nowrap; }}
  td {{ padding: 10px 12px; border-bottom: 1px solid #f0f4f8; vertical-align: top; }}
  tr:hover td {{ background: #f7faff; }}
  .status-badge {{ display: inline-block; padding: 3px 9px; border-radius: 12px;
                   font-weight: 700; font-size: 11px; white-space: nowrap; }}
  .score-badge {{ font-weight: 700; }}
  .job-title   {{ font-weight: 600; color: #0e2d5e; text-decoration: none; }}
  .job-title:hover {{ text-decoration: underline; }}
  .tag  {{ display: inline-block; background: #edf2ff; color: #3730a3;
           padding: 1px 7px; border-radius: 10px; font-size: 10px; margin: 1px 2px 1px 0; }}
  .skills-cell {{ max-width: 180px; }}
  .reason-cell {{ max-width: 280px; font-size: 11px; color: #4a5568; }}
</style>
</head>
<body>
<div class="header">
  <h1>Naukri Auto-Apply Report</h1>
  <p>{run_dt} &nbsp;|&nbsp; Mode: {mode} &nbsp;|&nbsp; Exp {EXPERIENCE_MIN}-{EXPERIENCE_MAX} yrs, CTC floor {CTC_MIN_LPA} LPA, score threshold {APPLY_SCORE_THRESHOLD}</p>
</div>
<div class="stats">{stat_html}</div>
<div class="table-wrap">
<table>
  <thead>
    <tr>
      <th>Status</th><th>Score</th><th>Role</th><th>Company</th><th>Location</th>
      <th>Exp</th><th>Salary</th><th>Skills</th><th>Reason</th>
    </tr>
  </thead>
  <tbody>
{rows}
  </tbody>
</table>
</div>
</body>
</html>"""


def save_csv(jobs: list[dict]):
    with open(OUTPUT_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        writer.writerows({k: j.get(k, "") for k in CSV_COLUMNS} for j in jobs)
    print(f"CSV  -> {OUTPUT_CSV}")

def save_html(jobs: list[dict], live: bool):
    html = build_html(jobs, live)
    with open(OUTPUT_HTML, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"HTML -> {OUTPUT_HTML}")

def save_manual_list(jobs: list[dict]):
    """Company-site redirects Adhiraj needs to apply to himself -- accumulates
    across runs (append + dedup by URL), sorted by score."""
    existing = {}
    if MANUAL_LIST_CSV.exists():
        with open(MANUAL_LIST_CSV, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                existing[row["url"]] = row

    for j in jobs:
        if j["decision"] == "manual_needed":
            existing[j["url"]] = {
                "score": j["score"], "title": j["title"], "company": j["company"],
                "location": j["location"], "experience": j["experience"],
                "salary": j["salary"], "url": j["url"],
                "first_seen": existing.get(j["url"], {}).get("first_seen",
                              datetime.now().strftime("%Y-%m-%d")),
            }

    rows = sorted(existing.values(), key=lambda r: -int(r["score"]))
    with open(MANUAL_LIST_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["score","title","company","location","experience","salary","url","first_seen"])
        writer.writeheader()
        writer.writerows(rows)
    print(f"Manual apply list -> {MANUAL_LIST_CSV} ({len(rows)} total)")
    save_manual_dashboard(rows)


def save_manual_dashboard(rows: list[dict]):
    """Standalone dashboard for company-site-redirect jobs Adhiraj needs to apply
    to himself. 'Mark done' persists in the browser's localStorage (keyed by job
    URL) so checked-off rows survive across daily regenerations of this file."""
    run_dt = datetime.now().strftime("%d %b %Y, %H:%M")
    trs = ""
    for r in rows:
        url = r["url"]
        trs += f"""
        <tr data-url="{url}">
          <td><input type="checkbox" class="done-box" onchange="toggleDone(this)"></td>
          <td><span class="score-badge">{r['score']}</span></td>
          <td><a class="job-title" href="{url}" target="_blank">{r['title']}</a></td>
          <td><strong>{r['company']}</strong></td>
          <td>{r['location']}</td>
          <td>{r['experience']}</td>
          <td>{r['salary']}</td>
          <td class="muted">{r['first_seen']}</td>
        </tr>"""

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Naukri Company-Site Applications — {run_dt}</title>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
          font-size: 13px; background: #f5f7fa; color: #1a1a2e; }}
  .header {{ background: #0e2d5e; color: white; padding: 20px 32px; }}
  .header h1 {{ font-size: 20px; font-weight: 700; }}
  .header p  {{ margin-top: 4px; opacity: .8; font-size: 12px; }}
  .stats {{ display: flex; gap: 20px; padding: 16px 32px; background: white;
            border-bottom: 1px solid #e2e8f0; }}
  .stat  {{ text-align: center; }}
  .stat .n {{ font-size: 22px; font-weight: 800; color: #0e2d5e; }}
  .stat .l {{ font-size: 10px; color: #718096; text-transform: uppercase; letter-spacing: .04em; }}
  .filters {{ padding: 12px 32px; background: white; border-bottom: 1px solid #e2e8f0; }}
  .filter-btn {{ padding: 5px 14px; border-radius: 20px; border: 1.5px solid #cbd5e0;
                 background: white; cursor: pointer; font-size: 12px; margin-right: 8px; }}
  .filter-btn.active {{ background: #0e2d5e; color: white; border-color: #0e2d5e; }}
  .table-wrap {{ padding: 20px 32px; overflow-x: auto; }}
  table {{ width: 100%; border-collapse: collapse; background: white;
           border-radius: 8px; overflow: hidden; box-shadow: 0 1px 4px rgba(0,0,0,.08); }}
  th {{ background: #0e2d5e; color: white; text-align: left; padding: 10px 12px;
        font-size: 11px; text-transform: uppercase; letter-spacing: .05em; white-space: nowrap; }}
  td {{ padding: 10px 12px; border-bottom: 1px solid #f0f4f8; vertical-align: top; }}
  tr:hover td {{ background: #f7faff; }}
  tr.done td {{ opacity: .4; text-decoration: line-through; }}
  tr.done td:first-child {{ text-decoration: none; }}
  .score-badge {{ font-weight: 700; }}
  .job-title   {{ font-weight: 600; color: #0e2d5e; text-decoration: none; }}
  .job-title:hover {{ text-decoration: underline; }}
  .muted {{ color: #a0aec0; font-size: 11px; }}
  .done-box {{ width: 16px; height: 16px; }}
</style>
</head>
<body>
<div class="header">
  <h1>Naukri — Company-Site Applications To Do</h1>
  <p>{run_dt} &nbsp;|&nbsp; These went to an external ATS on click, so Naukri Apply Agent doesn't auto-apply here &mdash; apply yourself, then check off.</p>
</div>
<div class="stats" id="stats">
  <div class="stat"><div class="n" id="stat-total">{len(rows)}</div><div class="l">Total</div></div>
  <div class="stat"><div class="n" id="stat-done">0</div><div class="l">Done</div></div>
  <div class="stat"><div class="n" id="stat-remaining">{len(rows)}</div><div class="l">Remaining</div></div>
</div>
<div class="filters">
  <button class="filter-btn active" onclick="filterRows('all', this)">All</button>
  <button class="filter-btn" onclick="filterRows('remaining', this)">Remaining only</button>
  <button class="filter-btn" onclick="filterRows('done', this)">Done only</button>
</div>
<div class="table-wrap">
<table id="jobs-table">
  <thead>
    <tr><th></th><th>Score</th><th>Role</th><th>Company</th><th>Location</th><th>Exp</th><th>Salary</th><th>First seen</th></tr>
  </thead>
  <tbody>
{trs}
  </tbody>
</table>
</div>
<script>
const STORE_KEY = 'naukri_manual_done_urls';
function getDone() {{ try {{ return new Set(JSON.parse(localStorage.getItem(STORE_KEY) || '[]')); }} catch(e) {{ return new Set(); }} }}
function setDone(s) {{ localStorage.setItem(STORE_KEY, JSON.stringify([...s])); }}

function updateStats() {{
  const total = document.querySelectorAll('#jobs-table tbody tr').length;
  const done = document.querySelectorAll('#jobs-table tbody tr.done').length;
  document.getElementById('stat-total').textContent = total;
  document.getElementById('stat-done').textContent = done;
  document.getElementById('stat-remaining').textContent = total - done;
}}

function toggleDone(box) {{
  const row = box.closest('tr');
  const url = row.dataset.url;
  const done = getDone();
  if (box.checked) {{ done.add(url); row.classList.add('done'); }}
  else {{ done.delete(url); row.classList.remove('done'); }}
  setDone(done);
  updateStats();
}}

function filterRows(type, btn) {{
  document.querySelectorAll('.filter-btn').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
  document.querySelectorAll('#jobs-table tbody tr').forEach(row => {{
    const isDone = row.classList.contains('done');
    row.style.display = (type === 'all' || (type === 'done') === isDone) ? '' : 'none';
  }});
}}

(function init() {{
  const done = getDone();
  document.querySelectorAll('#jobs-table tbody tr').forEach(row => {{
    if (done.has(row.dataset.url)) {{
      row.classList.add('done');
      row.querySelector('.done-box').checked = true;
    }}
  }});
  updateStats();
}})();
</script>
</body>
</html>"""

    with open(MANUAL_DASHBOARD, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"Manual dashboard -> {MANUAL_DASHBOARD}")


def open_in_chrome(path: Path):
    subprocess.run(["open", "-a", "Google Chrome", str(path)])


# ── Main ──────────────────────────────────────────────────────────────────────

def process_job(detail_page, job: dict, already_applied_urls: set, live: bool, applies_so_far: int) -> dict:
    job["score"], score_reasons = score_job(job)

    if job["url"] in already_applied_urls:
        job["decision"] = "already_applied"
        job["reason"] = "in local applied log from a previous run"
        job["naukri_button_text"] = ""
        return job

    exp_pass, exp_reason = experience_ok(job["experience"])
    ctc_pass, ctc_reason = ctc_ok(job["salary"])

    try:
        detail_page.goto(job["url"], wait_until="domcontentloaded", timeout=25000)
        time.sleep(1.3)
        state = get_button_state(detail_page)
    except Exception as e:
        job["decision"] = "error"
        job["reason"] = f"couldn't load job page: {e}"
        job["naukri_button_text"] = ""
        return job

    job["naukri_button_text"] = state

    if state == "applied":
        job["decision"] = "already_applied"
        job["reason"] = "Naukri already shows this as Applied"
        return job

    if state == "company_site":
        job["decision"] = "manual_needed"
        job["reason"] = "external ATS redirect -- apply manually, not automated"
        return job

    if not exp_pass:
        job["decision"] = "rejected_experience"
        job["reason"] = exp_reason
        return job

    if not ctc_pass:
        job["decision"] = "rejected_salary"
        job["reason"] = ctc_reason
        return job

    if job["score"] < APPLY_SCORE_THRESHOLD:
        job["decision"] = "rejected_score"
        job["reason"] = f"score {job['score']} < threshold {APPLY_SCORE_THRESHOLD}. " + "; ".join(score_reasons)
        return job

    # Qualifies
    if not live:
        job["decision"] = "would_apply"
        job["reason"] = f"score {job['score']}, {exp_reason}, {ctc_reason}"
        return job

    if applies_so_far >= MAX_APPLIES_PER_RUN:
        job["decision"] = "capped"
        job["reason"] = f"per-run cap of {MAX_APPLIES_PER_RUN} applies reached -- will retry next run"
        return job

    result, detail = click_apply(detail_page, job["url"])
    if result == "applied":
        job["decision"] = "applied"
        job["reason"] = detail
        append_applied_log(job)
    elif result == "modal_skipped":
        job["decision"] = "modal_skipped"
        job["reason"] = detail
    else:
        job["decision"] = "error"
        job["reason"] = detail
    return job


def run(keywords: list[str], pages_per_keyword: int, live: bool, headless: bool):
    already_applied_urls = load_applied_log()
    target = MIN_APPLIES_TARGET if live else 0

    all_jobs = []
    processed_urls = set()
    applies_so_far = 0
    keyword_state = {kw: {"next_page": 1, "exhausted": False} for kw in keywords}
    round_pages = pages_per_keyword
    unique = []

    with sync_playwright() as pw:
        context = pw.chromium.launch_persistent_context(
            user_data_dir=PROFILE_DIR,
            headless=headless,
            args=["--disable-blink-features=AutomationControlled"],
            viewport={"width": 1440, "height": 900},
            locale="en-IN",
        )
        page = context.pages[0] if context.pages else context.new_page()
        detail_page = context.new_page()

        # An uncaught exception here must never crash the whole run before reaching
        # the save/report code below -- that would silently lose every result.
        try:
            while True:
                for keyword in keywords:
                    st = keyword_state[keyword]
                    if st["exhausted"]:
                        continue
                    print(f"\n[{keyword}] (pages {st['next_page']}-{round_pages})")
                    for pg in range(st["next_page"], round_pages + 1):
                        url = build_url(keyword, pg)
                        print(f"  p{pg} -> {url}")
                        jobs = scrape_page(page, url, keyword)
                        all_jobs.extend(jobs)
                        if not jobs:
                            st["exhausted"] = True
                            break
                        wait(2.0, 3.5)
                    st["next_page"] = round_pages + 1
                    wait(2.0, 3.5)

                unique = deduplicate(all_jobs)
                new_jobs = [j for j in unique if j["url"] not in processed_urls]
                print(f"\n{len(new_jobs)} new unique job(s) to process this round...\n")

                for j in new_jobs:
                    try:
                        jac.run_with_timeout(150, process_job, detail_page, j, already_applied_urls, live, applies_so_far)
                    except jac.JobTimeout as e:
                        j["decision"] = "error"
                        j["reason"] = str(e)
                        try:  # clear whatever mid-navigation/dialog state the interrupt left behind
                            detail_page.goto("about:blank", timeout=10000)
                        except Exception:
                            pass
                    processed_urls.add(j["url"])
                    if j["decision"] == "applied":
                        applies_so_far += 1
                    print(f"  [{j['decision']:20s}] {j['title'][:40]:40s} | {j['company'][:25]:25s} | score={j['score']}")
                    wait(1.0, 2.0)

                all_exhausted = all(st["exhausted"] for st in keyword_state.values())
                if not live or applies_so_far >= target or round_pages >= MAX_ESCALATION_PAGES or all_exhausted or not new_jobs:
                    if live and applies_so_far < target:
                        reason = "all keywords exhausted" if all_exhausted else f"hit page ceiling ({MAX_ESCALATION_PAGES})"
                        print(f"\n--- Stopping short of {target}-apply target ({applies_so_far} applied): {reason} ---\n")
                    break

                round_pages = min(round_pages + ESCALATION_STEP_PAGES, MAX_ESCALATION_PAGES)
                print(f"\n--- Only {applies_so_far}/{target} applied so far -- escalating to {round_pages} pages/keyword ---\n")
        except Exception as e:
            print(f"\n--- Run interrupted by an unexpected error, saving what was collected: {e} ---\n")
            unique = deduplicate(all_jobs)

        context.close()

    # Defensive: jobs that never reached process_job() (e.g. the run was interrupted
    # mid-scrape by an exception) won't have a "decision"/"reason" key yet. Without
    # this, the sort below raises KeyError and the whole save/report path below is
    # skipped -- silently losing every row, which contradicts "never drop rows from
    # the report." Backfill instead of crashing.
    for j in unique:
        j.setdefault("score", 0)
        j.setdefault("decision", "not_processed")
        j.setdefault("reason", "run was interrupted before this job could be scored/applied")

    unique.sort(key=lambda j: (j["decision"] != "applied", j["decision"] != "would_apply", -j["score"]))
    save_csv(unique)
    save_html(unique, live)
    save_manual_list(unique)  # also regenerates naukri_manual_apply_dashboard.html
    open_in_chrome(OUTPUT_HTML)
    open_in_chrome(MANUAL_DASHBOARD)

    applied_count = sum(1 for j in unique if j["decision"] == "applied")
    print(f"\n{'LIVE' if live else 'DRY RUN'} complete. {applied_count} application(s) submitted.")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--keyword", "-k", help="Single keyword (overrides default list)")
    parser.add_argument("--pages",   "-p", type=int, default=5, help="Pages per keyword (default 5)")
    parser.add_argument("--live", action="store_true", help="Actually click Apply. Default is dry-run.")
    parser.add_argument("--headless", action="store_true", help="Run browser headless (for scheduled runs)")
    args = parser.parse_args()

    keywords = [args.keyword] if args.keyword else TARGET_KEYWORDS

    print(f"Naukri Auto-Apply  —  {datetime.now().strftime('%d %b %Y %H:%M')}")
    print(f"Mode      : {'LIVE' if args.live else 'DRY RUN'}")
    print(f"Keywords  : {', '.join(keywords)}")
    print(f"Filters   : {EXPERIENCE_MIN}-{EXPERIENCE_MAX} yrs, CTC floor {CTC_MIN_LPA} LPA, score>={APPLY_SCORE_THRESHOLD}")
    if args.live:
        print(f"Target    : {MIN_APPLIES_TARGET} applies/run minimum (escalates pages up to {MAX_ESCALATION_PAGES} to hit it)")
    print(f"Safety cap: {MAX_APPLIES_PER_RUN} applies/run\n")

    run(keywords, args.pages, args.live, args.headless)


if __name__ == "__main__":
    main()
