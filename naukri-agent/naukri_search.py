#!/usr/bin/env python3
"""
Naukri Job Search — Playwright scraper for CRM / Growth / Lifecycle Marketing roles.

Searches Naukri, scores each result for relevance to Adhiraj's profile,
and opens a ranked HTML report in Chrome.

USAGE:
    python3 naukri_search.py                    # full search across all target roles
    python3 naukri_search.py --keyword "head of CRM"
    python3 naukri_search.py --pages 3          # pages per keyword (default: 2)
"""

import csv, time, random, argparse, re, subprocess, os
from datetime import datetime
from playwright.sync_api import sync_playwright, TimeoutError as PwTimeout

# ── Config ────────────────────────────────────────────────────────────────────

TARGET_KEYWORDS = [
    "head of CRM",
    "CRM manager",
    "lifecycle marketing manager",
    "growth marketing manager",
    "retention marketing manager",
    "CRM analytics",
    "head of growth marketing",
]

EXPERIENCE_MIN  = 6
EXPERIENCE_MAX  = 12
OUTPUT_CSV      = "naukri_jobs.csv"
OUTPUT_HTML     = "naukri_jobs.html"

CSV_COLUMNS = [
    "score", "title", "company", "location", "experience",
    "salary", "skills", "posted", "url", "keyword_searched"
]

# ── Relevance Scoring ─────────────────────────────────────────────────────────
#
# Profile: GM-level CRM, CleverTap/MoEngage/WhatsApp, e-commerce/marketplace/fintech,
#          lifecycle automation, intent scoring, cohort segmentation, 7+ years India.

SCORE_RULES = {
    # Tool mentions (skills / description) — strong signal
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

    # Industry signals (company name / title / skills)
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

    # Title signals
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

    # Negative signals
    "real estate":      (-25, "all"),
    "property":         (-20, "all"),
    "realty":           (-20, "all"),
    "construction":     (-15, "all"),
    "developer":        (-8,  "title"),   # "real estate developer" context
    "rera":             (-15, "skills"),
    "documentation":    (-8,  "skills"),
    "allotment":        (-10, "skills"),
    "hubspot":          (-8,  "skills"),   # B2B CRM, not consumer
    "salesforce":       (-10, "skills"),
    "zoho":             (-5,  "skills"),
    "b2b":              (-8,  "all"),
}

def score_job(job: dict) -> int:
    title  = job["title"].lower()
    skills = job["skills"].lower()
    co     = job["company"].lower()
    all_text = f"{title} {skills} {co} {job['location'].lower()}"

    points = 50  # base

    for keyword, (delta, scope) in SCORE_RULES.items():
        kw = keyword.lower()
        if scope == "title"  and kw in title:    points += delta
        if scope == "skills" and kw in skills:   points += delta
        if scope == "all"    and kw in all_text: points += delta

    # Experience range bonus: jobs listing 6+ years are more senior
    exp_text = job["experience"].lower()
    exp_nums = re.findall(r'\d+', exp_text)
    if exp_nums:
        min_exp = int(exp_nums[0])
        if min_exp >= 6:
            points += 8
        elif min_exp >= 4:
            points += 2
        else:
            points -= 8

    return max(0, min(100, points))


# ── HTML Report ───────────────────────────────────────────────────────────────

SCORE_COLOR = {
    (75, 101): ("#0f5132", "#d1e7dd", "Strong fit"),
    (55,  75): ("#664d03", "#fff3cd", "Moderate fit"),
    (0,   55): ("#842029", "#f8d7da", "Weak fit"),
}

def score_badge(score: int) -> tuple[str, str, str]:
    for (lo, hi), (fg, bg, label) in SCORE_COLOR.items():
        if lo <= score < hi:
            return fg, bg, label
    return "#842029", "#f8d7da", "Weak fit"


def build_html(jobs: list[dict]) -> str:
    # Build keyword filter buttons outside f-string (no backslashes allowed inside f-string exprs)
    kw_buttons = ""
    for kw in TARGET_KEYWORDS:
        kw_buttons += f'<button class="filter-btn" onclick="filterKw(this)" data-kw="{kw}">{kw}</button>\n  '

    rows = ""
    for j in jobs:
        score = j["score"]
        fg, bg, label = score_badge(score)
        sal = j["salary"] if j["salary"] != "Not disclosed" else ""
        sal_cell = f'<span class="salary">{sal}</span>' if sal else '<span class="muted">—</span>'
        skill_tags = "".join(
            f'<span class="tag">{s.strip()}</span>'
            for s in j["skills"].split(",") if s.strip()
        )
        rows += f"""
        <tr>
          <td><span class="score-badge" style="background:{bg};color:{fg}">{score}</span></td>
          <td>
            <a class="job-title" href="{j['url']}" target="_blank">{j['title']}</a>
            <div class="fit-label" style="color:{fg}">{label}</div>
          </td>
          <td><strong>{j['company']}</strong></td>
          <td>{j['location']}</td>
          <td>{j['experience']}</td>
          <td>{sal_cell}</td>
          <td class="skills-cell">{skill_tags}</td>
          <td class="muted">{j['posted']}</td>
          <td><span class="kw-tag">{j['keyword_searched']}</span></td>
        </tr>"""

    strong  = sum(1 for j in jobs if j["score"] >= 75)
    moderate = sum(1 for j in jobs if 55 <= j["score"] < 75)
    total   = len(jobs)
    run_dt  = datetime.now().strftime("%d %b %Y, %H:%M")

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Naukri Job Search — {run_dt}</title>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
          font-size: 13px; background: #f5f7fa; color: #1a1a2e; }}

  .header {{ background: #0e2d5e; color: white; padding: 20px 32px; }}
  .header h1 {{ font-size: 20px; font-weight: 700; }}
  .header p  {{ margin-top: 4px; opacity: .75; font-size: 12px; }}

  .stats {{ display: flex; gap: 20px; padding: 16px 32px; background: white;
            border-bottom: 1px solid #e2e8f0; }}
  .stat  {{ text-align: center; }}
  .stat .n {{ font-size: 24px; font-weight: 800; color: #0e2d5e; }}
  .stat .l {{ font-size: 11px; color: #718096; text-transform: uppercase; letter-spacing: .05em; }}

  .filters {{ padding: 12px 32px; display: flex; gap: 10px; flex-wrap: wrap;
              background: white; border-bottom: 1px solid #e2e8f0; }}
  .filter-btn {{ padding: 5px 14px; border-radius: 20px; border: 1.5px solid #cbd5e0;
                 background: white; cursor: pointer; font-size: 12px; transition: all .15s; }}
  .filter-btn:hover, .filter-btn.active {{ background: #0e2d5e; color: white; border-color: #0e2d5e; }}

  .table-wrap {{ padding: 20px 32px; overflow-x: auto; }}
  table {{ width: 100%; border-collapse: collapse; background: white;
           border-radius: 8px; overflow: hidden; box-shadow: 0 1px 4px rgba(0,0,0,.08); }}
  th {{ background: #0e2d5e; color: white; text-align: left; padding: 10px 12px;
        font-size: 11px; text-transform: uppercase; letter-spacing: .06em; white-space: nowrap; }}
  td {{ padding: 10px 12px; border-bottom: 1px solid #f0f4f8; vertical-align: top; }}
  tr:last-child td {{ border-bottom: none; }}
  tr:hover td {{ background: #f7faff; }}

  .score-badge {{ display: inline-block; padding: 3px 9px; border-radius: 12px;
                  font-weight: 700; font-size: 13px; min-width: 36px; text-align: center; }}
  .fit-label   {{ font-size: 10px; margin-top: 2px; font-weight: 600; }}
  .job-title   {{ font-weight: 600; color: #0e2d5e; text-decoration: none; font-size: 13px; }}
  .job-title:hover {{ text-decoration: underline; }}
  .salary      {{ color: #2d6a4f; font-weight: 600; }}
  .muted       {{ color: #a0aec0; font-size: 11px; }}
  .tag         {{ display: inline-block; background: #edf2ff; color: #3730a3;
                  padding: 1px 7px; border-radius: 10px; font-size: 10px;
                  margin: 1px 2px 1px 0; }}
  .kw-tag      {{ background: #e2e8f0; color: #4a5568; padding: 2px 8px;
                  border-radius: 10px; font-size: 10px; white-space: nowrap; }}
  .skills-cell {{ max-width: 220px; }}
  tr.hidden    {{ display: none; }}
</style>
</head>
<body>

<div class="header">
  <h1>Naukri Job Search — Adhiraj Sharma</h1>
  <p>Scraped {run_dt} &nbsp;|&nbsp; Experience filter: {EXPERIENCE_MIN}–{EXPERIENCE_MAX} yrs &nbsp;|&nbsp; Sorted by relevance score</p>
</div>

<div class="stats">
  <div class="stat"><div class="n">{total}</div><div class="l">Total jobs</div></div>
  <div class="stat"><div class="n" style="color:#0f5132">{strong}</div><div class="l">Strong fit (75+)</div></div>
  <div class="stat"><div class="n" style="color:#664d03">{moderate}</div><div class="l">Moderate fit (55–74)</div></div>
  <div class="stat"><div class="n" style="color:#842029">{total - strong - moderate}</div><div class="l">Weak fit (&lt;55)</div></div>
</div>

<div class="filters">
  <span style="font-size:12px;color:#718096;padding-top:5px;">Filter:</span>
  <button class="filter-btn active" onclick="filterRows('all', this)">All</button>
  <button class="filter-btn" onclick="filterRows('strong', this)">Strong fit only</button>
  <button class="filter-btn" onclick="filterRows('moderate', this)">Strong + Moderate</button>
  {kw_buttons}
</div>

<div class="table-wrap">
<table id="jobs-table">
  <thead>
    <tr>
      <th style="width:56px">Score</th>
      <th>Role</th>
      <th>Company</th>
      <th>Location</th>
      <th>Exp</th>
      <th>Salary</th>
      <th>Skills</th>
      <th>Posted</th>
      <th>Keyword</th>
    </tr>
  </thead>
  <tbody>
{rows}
  </tbody>
</table>
</div>

<script>
function filterRows(type, btn) {{
  document.querySelectorAll('.filter-btn').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
  document.querySelectorAll('#jobs-table tbody tr').forEach(row => {{
    const score = parseInt(row.querySelector('.score-badge').textContent);
    if (type === 'all')      row.classList.remove('hidden');
    else if (type === 'strong')   row.classList.toggle('hidden', score < 75);
    else if (type === 'moderate') row.classList.toggle('hidden', score < 55);
  }});
}}
function filterKw(btn) {{
  document.querySelectorAll('.filter-btn').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
  const kw = btn.dataset.kw.toLowerCase();
  document.querySelectorAll('#jobs-table tbody tr').forEach(row => {{
    const kwCell = row.querySelector('.kw-tag').textContent.trim().toLowerCase();
    row.classList.toggle('hidden', kwCell !== kw);
  }});
}}
</script>
</body>
</html>"""


# ── Scraper ───────────────────────────────────────────────────────────────────

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


def save_csv(jobs: list[dict]):
    with open(OUTPUT_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        writer.writerows(jobs)
    print(f"CSV  -> {OUTPUT_CSV}")

def save_html(jobs: list[dict]):
    html = build_html(jobs)
    with open(OUTPUT_HTML, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"HTML -> {OUTPUT_HTML}")

def open_in_chrome(path: str):
    abs_path = os.path.abspath(path)
    subprocess.run(["open", "-a", "Google Chrome", abs_path])
    print(f"Opened in Chrome.")


def print_summary(jobs: list[dict]):
    print(f"\n{'='*72}")
    for i, j in enumerate(jobs, 1):
        fg, _, label = score_badge(j["score"])
        sal = f" | {j['salary']}" if j['salary'] != "Not disclosed" else ""
        print(f"{i:>3}. [{j['score']:>3}] {j['title']}")
        print(f"       {j['company']} | {j['location']} | {j['experience']}{sal}")
        if j["skills"]:
            print(f"       {j['skills'][:80]}")
        print()


# ── Main ──────────────────────────────────────────────────────────────────────

def run(keywords: list[str], pages_per_keyword: int):
    all_jobs = []

    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            headless=False,
            args=["--disable-blink-features=AutomationControlled", "--no-sandbox"],
        )
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1440, "height": 900},
            locale="en-IN",
        )
        context.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
        )
        page = context.new_page()

        for keyword in keywords:
            print(f"\n[{keyword}]")
            for pg in range(1, pages_per_keyword + 1):
                url = build_url(keyword, pg)
                print(f"  p{pg} -> {url}")
                jobs = scrape_page(page, url, keyword)
                all_jobs.extend(jobs)
                if not jobs:
                    break
                if pg < pages_per_keyword:
                    wait(2.0, 3.5)
            wait(2.5, 4.5)

        browser.close()

    unique = deduplicate(all_jobs)

    # Score and sort
    for j in unique:
        j["score"] = score_job(j)
    unique.sort(key=lambda j: j["score"], reverse=True)

    print_summary(unique)
    save_csv(unique)
    save_html(unique)
    open_in_chrome(OUTPUT_HTML)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--keyword", "-k", help="Single keyword (overrides default list)")
    parser.add_argument("--pages",   "-p", type=int, default=2, help="Pages per keyword (default 2)")
    args = parser.parse_args()

    keywords = [args.keyword] if args.keyword else TARGET_KEYWORDS

    print(f"Naukri Search  —  {datetime.now().strftime('%d %b %Y %H:%M')}")
    print(f"Keywords  : {', '.join(keywords)}")
    print(f"Experience: {EXPERIENCE_MIN}–{EXPERIENCE_MAX} yrs  |  Pages/keyword: {args.pages}")
    print("Browser window will open — don't close it until the script finishes.\n")

    run(keywords, args.pages)


if __name__ == "__main__":
    main()
