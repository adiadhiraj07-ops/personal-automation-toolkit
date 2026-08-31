#!/usr/bin/env python3
"""
IIMJobs Auto-Apply — searches for target roles, filters by experience/CTC/relevance,
and applies automatically to qualifying jobs. Sibling to naukri_auto_apply.py --
shares scoring/LLM/profile logic via job_apply_common.py. Runs daily via launchd
(com.adhiraj.iimjobs-auto-apply.plist, 9:15 AM).

Every job found is written to the report with a status and a reason -- nothing is
silently dropped -- so the filtering logic can be audited before trusting it to run
unattended.

FIRST RUN:
    python3 iimjobs_login.py         # one-time manual login, saves session

DRY RUN (default -- scrapes, scores, shows what WOULD happen, applies to nothing):
    python3 iimjobs_auto_apply.py

LIVE RUN (actually clicks Apply on qualifying jobs):
    python3 iimjobs_auto_apply.py --live

OPTIONS:
    python3 iimjobs_auto_apply.py --pages 3
    python3 iimjobs_auto_apply.py --live --headless
"""

import csv, os, sys, time, random, argparse, re, subprocess
from datetime import datetime
from pathlib import Path
from playwright.sync_api import sync_playwright, TimeoutError as PwTimeout

# job_apply_common.py lives in the sibling shared/ directory (split out of a
# single flat folder for this repo) -- add it to the import path.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "shared"))
import job_apply_common as jac

# ── Config ────────────────────────────────────────────────────────────────────

BASE_DIR     = Path(__file__).parent
PROFILE_DIR  = os.environ.get("IIMJOBS_PROFILE_DIR", str(BASE_DIR / ".iimjobs-profile"))
APPLIED_LOG  = BASE_DIR / "iimjobs_applied_log.csv"
OUTPUT_HTML  = BASE_DIR / "iimjobs_auto_apply_report.html"
OUTPUT_CSV   = BASE_DIR / "iimjobs_auto_apply_report.csv"
MANUAL_LIST_CSV  = BASE_DIR / "iimjobs_manual_apply_list.csv"
MANUAL_DASHBOARD = BASE_DIR / "iimjobs_manual_apply_dashboard.html"
LLM_LOG      = BASE_DIR / "iimjobs_llm_answers_log.csv"
PLATFORM_NAME = "IIMJobs.com"

# IIMJobs' own personalized feed (already relevance-curated, capped ~50, no
# pagination found) plus category listings (paginated via ?page=N) for volume.
# Edit CATEGORY_SLUGS freely -- these are IIMJobs' own category URL slugs.
INCLUDE_JOBFEED = True
CATEGORY_SLUGS = ["sales-marketing-jobs"]
# NOTE 2026-08-24: temporarily broadened to add "consulting-general-mgmt-jobs" for a
# one-off 100-apply target run at Adhiraj's explicit request (reverted back here after
# that run completed). It scored/applied well against roles at several large
# consulting/professional-services and enterprise firms -- worth considering as a
# permanent addition, but that's Adhiraj's call, not made unilaterally for the daily
# unattended schedule.

EXPERIENCE_MIN = 5
EXPERIENCE_MAX = 15
CTC_MIN_LPA    = 30

# Same broadened-net philosophy as naukri_auto_apply.py (see that file's comments
# for the full rationale) -- Adhiraj wants volume/callbacks, not just top matches.
APPLY_SCORE_THRESHOLD = 35
MAX_APPLIES_PER_RUN   = 40

MIN_APPLIES_TARGET    = 40
ESCALATION_STEP_PAGES = 5
MAX_ESCALATION_PAGES  = 20
# NOTE 2026-08-24: MAX_APPLIES_PER_RUN/MIN_APPLIES_TARGET/MAX_ESCALATION_PAGES were
# temporarily raised to 100/100/40 for a one-off elevated-target run at Adhiraj's
# explicit request (reverted back to the 40/40/20 daily defaults here once that run
# completed) -- see iimjobs_auto_apply_report.csv dated 2026-08-24 for that run's results.

CSV_COLUMNS = [
    "decision", "reason", "score", "title", "company", "location", "experience",
    "salary", "skills", "posted", "url", "source", "button_state",
]

# ── Thin wrappers around job_apply_common ────────────────────────────────────

def score_job(job: dict) -> tuple[int, list[str]]:
    return jac.score_job(job)

def experience_ok(exp_text: str) -> tuple[bool, str]:
    return jac.experience_ok(exp_text, EXPERIENCE_MIN, EXPERIENCE_MAX)

def ctc_ok(salary_text: str) -> tuple[bool, str]:
    return jac.ctc_ok(salary_text, CTC_MIN_LPA)

def llm_pick_option(job_url: str, question: str, options: list[str]) -> str:
    return jac.llm_pick_option(LLM_LOG, PLATFORM_NAME, job_url, question, options)

def llm_number_answer(job_url: str, question: str) -> str:
    return jac.llm_number_answer(LLM_LOG, PLATFORM_NAME, job_url, question, fallback=2)

def llm_free_text_answer(job_url: str, question: str) -> str:
    return jac.llm_free_text_answer(LLM_LOG, PLATFORM_NAME, job_url, question)


# ── Applied log (cross-run dedup) ────────────────────────────────────────────

def job_id_from_url(url: str) -> str:
    """
    IIMJobs generates slightly different URL slugs for the SAME job depending on
    context -- confirmed live 2026-08-12: the same job (id 1720483) appeared as
    both '...-8-15-yrs-1720483' (from category/jobfeed scraping) and
    '...-8-15-yrs--1720483' (double dash, from the Applied Jobs page) -- exact-
    URL dedup missed the match and double counted. The trailing numeric ID is
    the only stable part; dedup on that, never on the full URL string.
    """
    m = re.search(r'-(\d+)/?(?:\?.*)?$', url)
    return m.group(1) if m else url

def load_applied_log() -> set:
    if not APPLIED_LOG.exists():
        return set()
    with open(APPLIED_LOG, newline="", encoding="utf-8") as f:
        return {job_id_from_url(row["url"]) for row in csv.DictReader(f)}

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


# ── Scraper ───────────────────────────────────────────────────────────────────

def wait(lo=1.5, hi=3.0):
    time.sleep(random.uniform(lo, hi))

def card_field(card, testid: str) -> str:
    el = card.query_selector(f"[data-testid='{testid}']")
    return jac.safe_text(el)

def build_source_urls(pages_per_category: int) -> list[tuple[str, str]]:
    urls = []
    if INCLUDE_JOBFEED:
        urls.append(("jobfeed", "https://www.iimjobs.com/jobfeed"))
    for slug in CATEGORY_SLUGS:
        for pg in range(1, pages_per_category + 1):
            url = f"https://www.iimjobs.com/c/{slug}" + (f"?page={pg}" if pg > 1 else "")
            urls.append((slug, url))
    return urls

def scrape_page(page, url: str, source: str) -> list[dict]:
    jobs = []
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=30000)
    except PwTimeout:
        print(f"  [timeout] {url}")
        return jobs
    except Exception as e:
        # Confirmed live 2026-08-12: a transient net::ERR_NETWORK_CHANGED crashed
        # the whole run uncaught, losing every result from that run (report only
        # saves at the very end). One bad page must never kill the run.
        print(f"  [nav error, skipping page] {url}: {e}")
        return jobs
    try:
        page.wait_for_selector(".joblist-card-v2", timeout=12000)
    except PwTimeout:
        print(f"  [no results] {url}")
        return jobs

    wait(1.0, 1.5)
    cards = page.query_selector_all(".joblist-card-v2")
    print(f"  {len(cards)} cards.")

    for card in cards:
        try:
            title = card_field(card, "job_title")
            if not title:
                continue
            link_el = card.query_selector("a[href*='/j/']")
            href = (link_el.get_attribute("href") or "") if link_el else ""
            job_url = f"https://www.iimjobs.com{href.split('?')[0]}" if href.startswith("/") else href.split("?")[0]
            if not job_url:
                continue

            exp = card_field(card, "job_experience")
            location = card_field(card, "job_location")
            salary = card_field(card, "job_salary") or "Not disclosed"
            posted = card_field(card, "date_posted")
            tags = [card_field(card, f"job_tag_{i}") for i in range(8)]
            skills = ", ".join(t for t in tags if t)

            jobs.append({
                "title": title, "company": "", "location": location,
                "experience": exp, "salary": salary, "skills": skills,
                "posted": posted, "url": job_url, "source": source,
            })
        except Exception as e:
            print(f"  [card error] {e}")
    return jobs

def deduplicate(jobs: list[dict]) -> list[dict]:
    seen, unique = set(), []
    for j in jobs:
        jid = job_id_from_url(j["url"])
        if jid not in seen:
            seen.add(jid)
            unique.append(j)
    return unique


# ── Apply flow ────────────────────────────────────────────────────────────────
# Confirmed live 2026-08-12: clicking "Apply" navigates to
# https://www.iimjobs.com/job/{id}/screening -- a full-page form (NOT a chat like
# Naukri), one or more .screening-question-container blocks, then a "Next" button
# that either shows more questions or finalizes. Question types seen:
#   - 2x input[type=radio] (Yes/No)                              -> .radio-container per option
#   - input[type=number], sometimes pre-filled from profile       -> leave pre-filled values alone
#   - .pill-answer-options > button.pill-option (e.g. notice period), one may
#     already have class "selected" (pre-filled)                  -> leave selected alone
# No company-site-redirect pattern found yet on IIMJobs (all postings go through
# this internal flow) -- if one turns up, treat it exactly like Naukri's path 3:
# log to the manual dashboard, never auto-click through.

def already_applied(detail_page) -> bool:
    """
    CRITICAL BUG, confirmed live 2026-08-12 and found by Adhiraj catching the
    discrepancy (IIMJobs' own "Applied Jobs" page showed 166 real applications
    submitted today; this system's local log only had 7): IIMJobs' real success
    message is "Your application has been submitted successfully!" -- the exact
    substring "application submitted" checked below is NEVER contiguous in that
    real text ("application" ... "has been submitted" ... "successfully"), so
    this check silently failed on almost every real success. The application
    still went through for real on IIMJobs' server (confirmed via their Applied
    Jobs page) -- only the LOCAL detection/logging was wrong, meaning
    click_apply() fell through to its step-limit/deadline and misreported a real
    success as 'error' or 'unrecognized', and append_applied_log() never ran for
    it. Net effect: ~159 real applications went out that this system has no
    record of and never told Adhiraj about. Use substring matches that actually
    occur in the real confirmation text -- don't require adjacency of words that
    aren't adjacent in the source.
    """
    body = detail_page.inner_text("body").lower()
    return (
        "submitted successfully" in body
        or "application submitted" in body
        or "already applied" in body
        or "you have applied" in body
        or "applied\nsave" in body  # button reads exactly "Applied" alone on the job page
    )

def try_skip_intermediate_step(detail_page) -> bool:
    """Handles non-question steps in the apply flow that show a 'Skip this step'
    link -- confirmed live 2026-08-12: 'Add Audio/Video Profile' is one such step
    (some listings, mostly senior roles). Never fabricate audio/video -- always
    skip. Returns True if it found and skipped a step, False if none was present."""
    skip = detail_page.get_by_text("Skip this step", exact=True).first
    try:
        if skip.count() == 0:
            return False
    except Exception:
        return False
    skip.click()
    time.sleep(1.2)
    confirm = detail_page.get_by_text("Skip Anyway", exact=True).first
    try:
        if confirm.count() > 0:
            confirm.click()
            time.sleep(1.5)
    except Exception:
        pass
    return True

def get_apply_button(detail_page):
    btn = detail_page.get_by_role("button", name="Apply", exact=True).first
    try:
        if btn.count() > 0:
            return btn
    except Exception:
        pass
    return None

def click_radio_by_label(container, target_label: str) -> bool:
    """Clicks the <label for=...> sibling of the matching radio input -- NOT the
    wrapping .radio-container div. Confirmed live 2026-08-12: clicking the div
    silently 'succeeds' (no exception) but doesn't actually check the input, since
    the label isn't a descendant of the div's clickable path for this MUI pattern;
    only clicking the label itself (native for= semantics) reliably checks it."""
    radios = container.query_selector_all("input[type='radio']")
    for r in radios:
        rid = r.get_attribute("id") or ""
        label = container.query_selector(f"label[for='{rid}']")
        if label and jac.safe_text(label).strip().lower() == target_label.strip().lower():
            label.click()
            return True
    return False

def fill_screening_form(detail_page, job_url: str) -> tuple[str, str]:
    """
    Answers every question in the currently-visible screening form. Returns
    (result, detail): result = 'filled' | 'unrecognized' | 'error'
    """
    containers = detail_page.query_selector_all(".screening-question-container")
    if not containers:
        return "filled", "no questions on this page"

    for c in containers:
        qtext_el = c.query_selector(".question-text .mandatory-question")
        question = jac.safe_text(qtext_el) or jac.safe_text(c)[:150]

        radios = c.query_selector_all("input[type='radio']")
        number_input = c.query_selector("input[type='number']")
        pills = c.query_selector_all(".pill-option")

        if radios:
            if c.query_selector("input[type='radio']:checked"):
                continue  # already answered/pre-filled
            override = jac.deterministic_override_answer(question)
            if override is None:
                override = jac.currently_based_in_answer(question)
            answer = override if override is not None else llm_pick_option(job_url, question, ["Yes", "No"])
            if not click_radio_by_label(c, answer):
                click_radio_by_label(c, "Yes")  # last-resort default, never leave unanswered

        elif number_input:
            if (number_input.input_value() or "").strip():
                continue  # pre-filled (e.g. current/expected salary), leave alone
            ql = question.lower()
            core_skill = any(k in ql for k in [
                "retention", "crm", "lifecycle", "e-commerce", "ecommerce",
                "internet", "online", "customer", "marketing", "growth",
                "whatsapp", "automation", "performance",
            ])
            answer = str(jac.KNOWN_TOTAL_EXPERIENCE_YEARS) if core_skill else llm_number_answer(job_url, question)
            number_input.fill(str(answer))

        elif pills:
            if c.query_selector(".pill-option.selected"):
                continue  # pre-filled (e.g. notice period)
            option_texts = [jac.safe_text(p) for p in pills]
            ql = question.lower()
            if "notice period" in ql:
                answer = next((o for o in option_texts if "immediat" in o.lower()), option_texts[0])
            else:
                answer = llm_pick_option(job_url, question, option_texts)
            for p in pills:
                if jac.safe_text(p).strip().lower() == answer.strip().lower():
                    p.click()
                    break

        else:
            note = capture_screen(detail_page, f"unknown question control type: {question!r}")
            return "unrecognized", f"unknown question type -- captured to {note}.png"

        time.sleep(0.3)

    return "filled", f"answered {len(containers)} question(s) on this page"

def capture_screen(detail_page, note: str) -> str:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    dump_path = BASE_DIR / f"iimjobs_screening_capture_{ts}"
    try:
        detail_page.screenshot(path=str(dump_path) + ".png")
        dump_path.with_suffix(".txt").write_text(note, encoding="utf-8")
    except Exception:
        pass
    return dump_path.name

def is_external_redirect(page) -> bool:
    try:
        return "iimjobs.com" not in page.url
    except Exception:
        return False

def click_apply(detail_page, job_url: str) -> tuple[str, str]:
    """
    Clicks Apply and walks the screening form (if any) to completion.
    Returns (result, detail): result = 'applied' | 'modal_skipped' | 'error'

    Confirmed live 2026-08-12: some listings (e.g. JP Morgan via Oracle Cloud
    recruiting) redirect to an external ATS on click, same as Naukri's path 3.
    That external page opened in a NEW TAB, leaving detail_page itself unchanged
    on iimjobs.com -- checking detail_page.url alone missed it and the run sat
    idle. Must check both: did detail_page itself navigate off iimjobs.com, AND
    did the click spawn a new tab that did. Never interact with either -- log to
    the manual dashboard exactly like Naukri's company-site jobs.
    """
    existing_pages = set(detail_page.context.pages)
    btn = get_apply_button(detail_page)
    if not btn:
        return "error", "apply button not found"
    btn.click()
    time.sleep(2.5)

    new_pages = [p for p in detail_page.context.pages if p not in existing_pages]
    for p in new_pages:
        try:
            p.wait_for_load_state("domcontentloaded", timeout=8000)
        except Exception:
            pass
        if is_external_redirect(p):
            url = p.url
            try:
                p.close()
            except Exception:
                pass
            return "manual_needed", f"external ATS redirect opened in new tab ({url}) -- apply manually, not automated"
        try:
            p.close()
        except Exception:
            pass

    if is_external_redirect(detail_page):
        return "manual_needed", f"external ATS redirect ({detail_page.url}) -- apply manually, not automated"

    if "/screening" not in detail_page.url:
        # No screening form -- either applied instantly or something unexpected.
        if already_applied(detail_page):
            return "applied", "instant apply, no screening form"
        return "error", f"unexpected state after clicking Apply, URL={detail_page.url}"

    deadline = time.time() + 90  # defense in depth against any other undiscovered stuck pattern
    for step in range(1, 8):
        if time.time() > deadline:
            note = capture_screen(detail_page, "apply flow exceeded 90s safety deadline")
            return "error", f"apply flow taking too long, aborting -- captured to {note}.png"
        if is_external_redirect(detail_page):
            return "manual_needed", f"external ATS redirect ({detail_page.url}) -- apply manually, not automated"
        if already_applied(detail_page):
            return "applied", f"submitted after {step - 1} step(s)"
        if "/screening" not in detail_page.url:
            note = capture_screen(detail_page, "left the screening flow without a confirmation")
            return "error", f"unexpected navigation away from screening flow -- captured to {note}.png"

        if not detail_page.query_selector(".screening-question-container"):
            # Non-question step (confirmed: 'Add Audio/Video Profile' on some
            # senior roles). Never fabricate audio/video -- always skip it.
            if try_skip_intermediate_step(detail_page):
                time.sleep(1.0)
                continue
            note = capture_screen(detail_page, "no screening questions and no 'Skip this step' option found")
            return "unrecognized", f"unhandled intermediate step -- captured to {note}.png"

        result, detail = fill_screening_form(detail_page, job_url)
        if result != "filled":
            return "modal_skipped", detail

        next_btn = detail_page.get_by_role("button", name=re.compile(r"^(Next|Submit)$", re.I)).first
        try:
            next_btn.click(timeout=5000)
        except Exception as e:
            if already_applied(detail_page):
                return "applied", f"submitted after {step} page(s) of questions"
            note = capture_screen(detail_page, f"couldn't click Next/Submit: {e}")
            return "error", f"no Next/Submit control -- captured to {note}.png"
        time.sleep(2.0)

    return "unrecognized", "more than 7 steps in the apply flow, aborting rather than looping indefinitely"


# ── HTML Report (same visual system as naukri_auto_apply_report.html) ────────

DECISION_STYLE = {
    "applied":            ("#0f5132", "#d1e7dd", "Applied"),
    "would_apply":        ("#0f5132", "#d1e7dd", "Would apply (dry run)"),
    "already_applied":    ("#41464b", "#e2e3e5", "Already applied"),
    "manual_needed":      ("#055160", "#cff4fc", "Needs manual apply (external)"),
    "rejected_experience":("#842029", "#f8d7da", "Rejected: experience"),
    "rejected_salary":    ("#842029", "#f8d7da", "Rejected: CTC below floor"),
    "rejected_score":     ("#842029", "#f8d7da", "Rejected: low relevance"),
    "modal_skipped":      ("#664d03", "#fff3cd", "Screening form: unrecognized question"),
    "capped":             ("#664d03", "#fff3cd", "Deferred (per-run cap hit)"),
    "error":              ("#664d03", "#fff3cd", "Error"),
}

def build_html(jobs: list[dict], live: bool) -> str:
    # .get() throughout this function, not direct indexing -- a job dict that never
    # reached process_job() (run interrupted mid-sweep) has no "decision"/"score"/
    # "reason" key even after the run()-level backfill; that backfill is the primary
    # fix, this is the second layer so one malformed row can never crash the report
    # for every other job that WAS processed.
    counts = {}
    for j in jobs:
        counts[j.get("decision", "unknown")] = counts.get(j.get("decision", "unknown"), 0) + 1

    rows = ""
    for j in jobs:
        decision = j.get("decision", "unknown")
        fg, bg, label = DECISION_STYLE.get(decision, ("#842029", "#f8d7da", decision))
        skill_tags = "".join(
            f'<span class="tag">{s.strip()}</span>' for s in j.get("skills", "").split(",") if s.strip()
        )
        rows += f"""
        <tr>
          <td><span class="status-badge" style="background:{bg};color:{fg}">{label}</span></td>
          <td><span class="score-badge">{j.get('score', 0)}</span></td>
          <td><a class="job-title" href="{j.get('url','')}" target="_blank">{j.get('title','')}</a></td>
          <td>{j.get('location','')}</td>
          <td>{j.get('experience','')}</td>
          <td>{j.get('salary','')}</td>
          <td class="skills-cell">{skill_tags}</td>
          <td class="reason-cell">{j.get('reason','')}</td>
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
<title>IIMJobs Auto-Apply Report — {run_dt}</title>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
          font-size: 13px; background: #f5f7fa; color: #1a1a2e; }}
  .header {{ background: #1a4d2e; color: white; padding: 20px 32px; }}
  .header h1 {{ font-size: 20px; font-weight: 700; }}
  .header p  {{ margin-top: 4px; opacity: .8; font-size: 12px; }}
  .stats {{ display: flex; gap: 20px; padding: 16px 32px; background: white;
            border-bottom: 1px solid #e2e8f0; flex-wrap: wrap; }}
  .stat  {{ text-align: center; }}
  .stat .n {{ font-size: 22px; font-weight: 800; color: #1a4d2e; }}
  .stat .l {{ font-size: 10px; color: #718096; text-transform: uppercase; letter-spacing: .04em; }}
  .table-wrap {{ padding: 20px 32px; overflow-x: auto; }}
  table {{ width: 100%; border-collapse: collapse; background: white;
           border-radius: 8px; overflow: hidden; box-shadow: 0 1px 4px rgba(0,0,0,.08); }}
  th {{ background: #1a4d2e; color: white; text-align: left; padding: 10px 12px;
        font-size: 11px; text-transform: uppercase; letter-spacing: .05em; white-space: nowrap; }}
  td {{ padding: 10px 12px; border-bottom: 1px solid #f0f4f8; vertical-align: top; }}
  tr:hover td {{ background: #f7faff; }}
  .status-badge {{ display: inline-block; padding: 3px 9px; border-radius: 12px;
                   font-weight: 700; font-size: 11px; white-space: nowrap; }}
  .score-badge {{ font-weight: 700; }}
  .job-title   {{ font-weight: 600; color: #1a4d2e; text-decoration: none; }}
  .job-title:hover {{ text-decoration: underline; }}
  .tag  {{ display: inline-block; background: #e7f3ec; color: #1a4d2e;
           padding: 1px 7px; border-radius: 10px; font-size: 10px; margin: 1px 2px 1px 0; }}
  .skills-cell {{ max-width: 180px; }}
  .reason-cell {{ max-width: 280px; font-size: 11px; color: #4a5568; }}
</style>
</head>
<body>
<div class="header">
  <h1>IIMJobs Auto-Apply Report</h1>
  <p>{run_dt} &nbsp;|&nbsp; Mode: {mode} &nbsp;|&nbsp; Exp {EXPERIENCE_MIN}-{EXPERIENCE_MAX} yrs, CTC floor {CTC_MIN_LPA} LPA, score threshold {APPLY_SCORE_THRESHOLD}</p>
</div>
<div class="stats">{stat_html}</div>
<div class="table-wrap">
<table>
  <thead>
    <tr><th>Status</th><th>Score</th><th>Role</th><th>Location</th><th>Exp</th><th>Salary</th><th>Skills</th><th>Reason</th></tr>
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
    with open(OUTPUT_HTML, "w", encoding="utf-8") as f:
        f.write(build_html(jobs, live))
    print(f"HTML -> {OUTPUT_HTML}")

def save_manual_list(jobs: list[dict]):
    existing = {}
    if MANUAL_LIST_CSV.exists():
        with open(MANUAL_LIST_CSV, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                existing[row["url"]] = row
    for j in jobs:
        if j["decision"] == "manual_needed":
            existing[j["url"]] = {
                "score": j["score"], "title": j["title"], "location": j["location"],
                "experience": j["experience"], "salary": j["salary"], "url": j["url"],
                "first_seen": existing.get(j["url"], {}).get("first_seen", datetime.now().strftime("%Y-%m-%d")),
            }
    rows = sorted(existing.values(), key=lambda r: -int(r["score"]))
    with open(MANUAL_LIST_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["score", "title", "location", "experience", "salary", "url", "first_seen"])
        writer.writeheader()
        writer.writerows(rows)
    print(f"Manual apply list -> {MANUAL_LIST_CSV} ({len(rows)} total)")
    save_manual_dashboard(rows)

def save_manual_dashboard(rows: list[dict]):
    run_dt = datetime.now().strftime("%d %b %Y, %H:%M")
    trs = ""
    for r in rows:
        url = r["url"]
        trs += f"""
        <tr data-url="{url}">
          <td><input type="checkbox" class="done-box" onchange="toggleDone(this)"></td>
          <td><span class="score-badge">{r['score']}</span></td>
          <td><a class="job-title" href="{url}" target="_blank">{r['title']}</a></td>
          <td>{r['location']}</td>
          <td>{r['experience']}</td>
          <td>{r['salary']}</td>
          <td class="muted">{r['first_seen']}</td>
        </tr>"""
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>IIMJobs Manual Applications — {run_dt}</title>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
          font-size: 13px; background: #f5f7fa; color: #1a1a2e; }}
  .header {{ background: #1a4d2e; color: white; padding: 20px 32px; }}
  .header h1 {{ font-size: 20px; font-weight: 700; }}
  .header p  {{ margin-top: 4px; opacity: .8; font-size: 12px; }}
  .stats {{ display: flex; gap: 20px; padding: 16px 32px; background: white; border-bottom: 1px solid #e2e8f0; }}
  .stat {{ text-align: center; }}
  .stat .n {{ font-size: 22px; font-weight: 800; color: #1a4d2e; }}
  .stat .l {{ font-size: 10px; color: #718096; text-transform: uppercase; letter-spacing: .04em; }}
  .filters {{ padding: 12px 32px; background: white; border-bottom: 1px solid #e2e8f0; }}
  .filter-btn {{ padding: 5px 14px; border-radius: 20px; border: 1.5px solid #cbd5e0; background: white; cursor: pointer; font-size: 12px; margin-right: 8px; }}
  .filter-btn.active {{ background: #1a4d2e; color: white; border-color: #1a4d2e; }}
  .table-wrap {{ padding: 20px 32px; overflow-x: auto; }}
  table {{ width: 100%; border-collapse: collapse; background: white; border-radius: 8px; overflow: hidden; box-shadow: 0 1px 4px rgba(0,0,0,.08); }}
  th {{ background: #1a4d2e; color: white; text-align: left; padding: 10px 12px; font-size: 11px; text-transform: uppercase; letter-spacing: .05em; white-space: nowrap; }}
  td {{ padding: 10px 12px; border-bottom: 1px solid #f0f4f8; vertical-align: top; }}
  tr:hover td {{ background: #f7faff; }}
  tr.done td {{ opacity: .4; text-decoration: line-through; }}
  tr.done td:first-child {{ text-decoration: none; }}
  .score-badge {{ font-weight: 700; }}
  .job-title {{ font-weight: 600; color: #1a4d2e; text-decoration: none; }}
  .job-title:hover {{ text-decoration: underline; }}
  .muted {{ color: #a0aec0; font-size: 11px; }}
  .done-box {{ width: 16px; height: 16px; }}
</style>
</head>
<body>
<div class="header">
  <h1>IIMJobs — Manual Applications To Do</h1>
  <p>{run_dt} &nbsp;|&nbsp; External/non-standard applications the agent didn't auto-submit &mdash; apply yourself, then check off.</p>
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
  <thead><tr><th></th><th>Score</th><th>Role</th><th>Location</th><th>Exp</th><th>Salary</th><th>First seen</th></tr></thead>
  <tbody>
{trs}
  </tbody>
</table>
</div>
<script>
const STORE_KEY = 'iimjobs_manual_done_urls';
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
  const row = box.closest('tr'); const url = row.dataset.url; const done = getDone();
  if (box.checked) {{ done.add(url); row.classList.add('done'); }} else {{ done.delete(url); row.classList.remove('done'); }}
  setDone(done); updateStats();
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
    if (done.has(row.dataset.url)) {{ row.classList.add('done'); row.querySelector('.done-box').checked = true; }}
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

    if job_id_from_url(job["url"]) in already_applied_urls:
        job["decision"] = "already_applied"
        job["reason"] = "in local applied log from a previous run"
        job["button_state"] = ""
        return job

    exp_pass, exp_reason = experience_ok(job["experience"])
    ctc_pass, ctc_reason = ctc_ok(job["salary"])

    try:
        detail_page.goto(job["url"], wait_until="domcontentloaded", timeout=25000)
        time.sleep(1.3)
    except Exception as e:
        job["decision"] = "error"
        job["reason"] = f"couldn't load job page: {e}"
        job["button_state"] = ""
        return job

    if already_applied(detail_page):
        job["decision"] = "already_applied"
        job["reason"] = "IIMJobs already shows this as applied"
        job["button_state"] = "applied"
        return job

    if not get_apply_button(detail_page):
        job["decision"] = "manual_needed"
        job["reason"] = "no internal Apply button found -- needs manual review"
        job["button_state"] = "unknown"
        return job
    job["button_state"] = "apply"

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
    elif result == "manual_needed":
        # BUG found 2026-08-24: this branch was previously missing, so a
        # manual_needed returned by click_apply() (external ATS redirect
        # discovered AFTER clicking Apply -- same pattern as the large-enterprise
        # ATS redirect case click_apply() already documents)
        # fell into the else->"error" branch below. That meant it never
        # reached save_manual_list()/the manual dashboard (which filters on
        # decision == "manual_needed"), silently dropping it from the list
        # Adhiraj actually checks -- even though the reason text correctly
        # said "apply manually, not automated". The pre-click manual_needed
        # check earlier in this function (no Apply button found) was never
        # affected; only this post-click path was broken. Confirmed live via
        # 2026-08-24's 100-apply run: 2 of 22 "error" rows were actually
        # external-redirect jobs with the right detail text but wrong decision.
        job["decision"] = "manual_needed"
        job["reason"] = detail
    else:
        job["decision"] = "error"
        job["reason"] = detail
    return job


def run(pages_per_category: int, live: bool, headless: bool):
    already_applied_urls = load_applied_log()
    target = MIN_APPLIES_TARGET if live else 0

    all_jobs = []
    processed_urls = set()
    applies_so_far = 0
    round_pages = pages_per_category
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

        # Confirmed live 2026-08-12: an uncaught exception here (e.g. a transient
        # net::ERR_NETWORK_CHANGED) used to crash the whole run before reaching the
        # save/report code below, silently losing every result. This must never
        # happen on an unattended daily run -- catch anything, keep whatever was
        # collected, and still produce a report.
        try:
            fetched_jobfeed = False
            while True:
                sources = build_source_urls(round_pages)
                for source, url in sources:
                    if source == "jobfeed":
                        if fetched_jobfeed:
                            continue
                        fetched_jobfeed = True
                    print(f"\n[{source}] -> {url}")
                    jobs = scrape_page(page, url, source)
                    all_jobs.extend(jobs)
                    wait(2.0, 3.5)

                unique = deduplicate(all_jobs)
                new_jobs = [j for j in unique if job_id_from_url(j["url"]) not in processed_urls]
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
                    processed_urls.add(job_id_from_url(j["url"]))
                    if j["decision"] == "applied":
                        applies_so_far += 1
                    print(f"  [{j['decision']:20s}] {j['title'][:45]:45s} | score={j['score']}")
                    wait(1.0, 2.0)

                if not live or applies_so_far >= target or round_pages >= MAX_ESCALATION_PAGES or not new_jobs:
                    if live and applies_so_far < target:
                        print(f"\n--- Stopping short of {target}-apply target ({applies_so_far} applied): out of fresh results ---\n")
                    break
                round_pages = min(round_pages + ESCALATION_STEP_PAGES, MAX_ESCALATION_PAGES)
                print(f"\n--- Only {applies_so_far}/{target} applied so far -- escalating to {round_pages} pages/category ---\n")
        except Exception as e:
            print(f"\n--- Run interrupted by an unexpected error, saving what was collected: {e} ---\n")
            unique = deduplicate(all_jobs)
            # Confirmed live 2026-08-14: jobs that were scraped into all_jobs but never
            # reached process_job() (the loop was mid-way through new_jobs when the
            # exception hit) have no "decision"/"reason"/"button_state"/"score" key at
            # all -- score_job() only runs inside process_job(), scrape_page() never
            # sets it. The final sort()/save_csv()/build_html() below index those keys
            # unconditionally, so without this backfill the KeyError there kills the
            # process a second time -- AFTER already reaching the "recovered" print
            # above -- and still wipes out save_csv/save_html/save_manual_list for the
            # whole run, defeating the entire point of this except block. Give every
            # unprocessed job an honest decision instead of guessing an outcome for it.
            for j in unique:
                j.setdefault("decision", "not_processed")
                j.setdefault("reason", f"run interrupted before this job could be checked: {e}")
                j.setdefault("button_state", "")
                j.setdefault("score", 0)

        context.close()

    # Defensive .get() as a second layer even though the backfill above should
    # already guarantee the key -- never let a missing field on one job crash the
    # sort/save for every job that WAS processed successfully.
    unique.sort(key=lambda j: (j.get("decision") != "applied", j.get("decision") != "would_apply", -j.get("score", 0)))
    save_csv(unique)
    save_html(unique, live)
    save_manual_list(unique)  # also regenerates iimjobs_manual_apply_dashboard.html
    open_in_chrome(OUTPUT_HTML)
    open_in_chrome(MANUAL_DASHBOARD)

    applied_count = sum(1 for j in unique if j["decision"] == "applied")
    print(f"\n{'LIVE' if live else 'DRY RUN'} complete. {applied_count} application(s) submitted.")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--pages", "-p", type=int, default=5, help="Pages per category (default 5)")
    parser.add_argument("--live", action="store_true", help="Actually click Apply. Default is dry-run.")
    parser.add_argument("--headless", action="store_true", help="Run browser headless (for scheduled runs)")
    args = parser.parse_args()

    print(f"IIMJobs Auto-Apply  —  {datetime.now().strftime('%d %b %Y %H:%M')}")
    print(f"Mode      : {'LIVE' if args.live else 'DRY RUN'}")
    print(f"Sources   : jobfeed={INCLUDE_JOBFEED}, categories={CATEGORY_SLUGS}")
    print(f"Filters   : {EXPERIENCE_MIN}-{EXPERIENCE_MAX} yrs, CTC floor {CTC_MIN_LPA} LPA, score>={APPLY_SCORE_THRESHOLD}")
    if args.live:
        print(f"Target    : {MIN_APPLIES_TARGET} applies/run minimum (escalates pages up to {MAX_ESCALATION_PAGES} to hit it)")
    print(f"Safety cap: {MAX_APPLIES_PER_RUN} applies/run\n")

    run(args.pages, args.live, args.headless)


if __name__ == "__main__":
    main()
