#!/usr/bin/env python3
"""
IIMJobs Search — Playwright scraper for CRM / Growth / Lifecycle Marketing roles.

Uses a persistent browser profile so you only log in once.
Results are scored for relevance to Adhiraj's profile and opened in Chrome.

FIRST RUN (one-time login):
    python3 iimjobs_search.py --login

SUBSEQUENT RUNS:
    python3 iimjobs_search.py
    python3 iimjobs_search.py --keyword "lifecycle marketing"
    python3 iimjobs_search.py --pages 3
"""

import json, time, random, argparse, re, subprocess, os, csv
from datetime import datetime
from pathlib import Path
from playwright.sync_api import sync_playwright, TimeoutError as PwTimeout

# ── Config ────────────────────────────────────────────────────────────────────

PROFILE_DIR  = os.environ.get("IIMJOBS_PROFILE_DIR", str(Path(__file__).parent / ".iimjobs-profile"))
SESSION_FILE = "iimjobs_session.json"
OUTPUT_HTML  = "iimjobs_jobs.html"
OUTPUT_CSV   = "iimjobs_jobs.csv"

TARGET_KEYWORDS = [
    "CRM marketing",
]

CSV_COLUMNS = [
    "score", "title", "company", "location", "experience",
    "salary", "posted", "url", "keyword_searched"
]

# ── Relevance Scoring (shared with naukri_search.py) ─────────────────────────

SCORE_RULES = {
    "clevertap":          (+20, "all"),
    "moengage":           (+18, "all"),
    "webengage":          (+15, "all"),
    "braze":              (+15, "all"),
    "whatsapp":           (+8,  "all"),
    "push notification":  (+6,  "all"),
    "segmentation":       (+8,  "all"),
    "cohort":             (+8,  "all"),
    "a/b test":           (+6,  "all"),
    "propensity":         (+8,  "all"),
    "personalisation":    (+5,  "all"),
    "personalization":    (+5,  "all"),
    "retention":          (+6,  "all"),
    "automation":         (+4,  "all"),
    "python":             (+5,  "all"),
    "sql":                (+5,  "all"),
    "analytics":          (+4,  "all"),
    "e-commerce":         (+12, "all"),
    "ecommerce":          (+12, "all"),
    "marketplace":        (+12, "all"),
    "fintech":            (+12, "all"),
    "consumer tech":      (+10, "all"),
    "edtech":             (+8,  "all"),
    "d2c":                (+8,  "all"),
    "insurtech":          (+8,  "all"),
    "saas":               (+6,  "all"),
    "lifecycle":          (+15, "title"),
    "growth marketing":   (+12, "title"),
    "retention marketing":(+12, "title"),
    "crm analytics":      (+10, "title"),
    "head of crm":        (+15, "title"),
    "head of growth":     (+15, "title"),
    "vp crm":             (+15, "title"),
    "director crm":       (+15, "title"),
    "real estate":        (-25, "all"),
    "property":           (-20, "all"),
    "realty":             (-20, "all"),
    "construction":       (-15, "all"),
    "rera":               (-15, "all"),
    "hubspot":            (-5,  "all"),
    "salesforce":         (-10, "all"),
    "b2b":                (-8,  "all"),
}

def score_job(job: dict) -> int:
    title    = job.get("title", "").lower()
    company  = job.get("company", "").lower()
    all_text = f"{title} {company} {job.get('location','').lower()}"
    points   = 50

    for kw, (delta, scope) in SCORE_RULES.items():
        if scope == "title" and kw in title:    points += delta
        if scope == "all"   and kw in all_text: points += delta

    exp_text = job.get("experience", "").lower()
    exp_nums = re.findall(r'\d+', exp_text)
    if exp_nums and int(exp_nums[0]) >= 6:
        points += 8
    elif exp_nums and int(exp_nums[0]) >= 4:
        points += 2

    return max(0, min(100, points))


# ── HTML Report ───────────────────────────────────────────────────────────────

SCORE_COLOR = {
    (75, 101): ("#0f5132", "#d1e7dd", "Strong fit"),
    (55,  75): ("#664d03", "#fff3cd", "Moderate fit"),
    (0,   55): ("#842029", "#f8d7da", "Weak fit"),
}

def score_badge(score):
    for (lo, hi), vals in SCORE_COLOR.items():
        if lo <= score < hi:
            return vals
    return ("#842029", "#f8d7da", "Weak fit")

def build_html(jobs: list[dict]) -> str:
    kw_buttons = ""
    for kw in TARGET_KEYWORDS:
        kw_buttons += f'<button class="filter-btn" onclick="filterKw(this)" data-kw="{kw}">{kw}</button>\n  '

    rows = ""
    for j in jobs:
        score = j["score"]
        fg, bg, label = score_badge(score)
        sal = j.get("salary", "")
        sal_cell = f'<span class="salary">{sal}</span>' if sal and sal != "Not disclosed" else '<span class="muted">—</span>'
        rows += f"""
        <tr>
          <td><span class="score-badge" style="background:{bg};color:{fg}">{score}</span>
              <div class="fit-label" style="color:{fg}">{label}</div></td>
          <td><a class="job-title" href="{j['url']}" target="_blank">{j['title']}</a></td>
          <td><strong>{j['company']}</strong></td>
          <td>{j.get('location','')}</td>
          <td>{j.get('experience','')}</td>
          <td>{sal_cell}</td>
          <td class="muted">{j.get('posted','')}</td>
          <td><span class="kw-tag">{j['keyword_searched']}</span></td>
        </tr>"""

    strong   = sum(1 for j in jobs if j["score"] >= 75)
    moderate = sum(1 for j in jobs if 55 <= j["score"] < 75)
    total    = len(jobs)
    run_dt   = datetime.now().strftime("%d %b %Y, %H:%M")

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>IIMJobs Search — {run_dt}</title>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; font-size: 13px; background: #f5f7fa; color: #1a1a2e; }}
  .header {{ background: #7c3aed; color: white; padding: 20px 32px; }}
  .header h1 {{ font-size: 20px; font-weight: 700; }}
  .header p  {{ margin-top: 4px; opacity: .75; font-size: 12px; }}
  .stats {{ display: flex; gap: 20px; padding: 16px 32px; background: white; border-bottom: 1px solid #e2e8f0; }}
  .stat .n {{ font-size: 24px; font-weight: 800; color: #7c3aed; }}
  .stat .l {{ font-size: 11px; color: #718096; text-transform: uppercase; letter-spacing: .05em; }}
  .filters {{ padding: 12px 32px; display: flex; gap: 10px; flex-wrap: wrap; background: white; border-bottom: 1px solid #e2e8f0; }}
  .filter-btn {{ padding: 5px 14px; border-radius: 20px; border: 1.5px solid #cbd5e0; background: white; cursor: pointer; font-size: 12px; transition: all .15s; }}
  .filter-btn:hover, .filter-btn.active {{ background: #7c3aed; color: white; border-color: #7c3aed; }}
  .table-wrap {{ padding: 20px 32px; overflow-x: auto; }}
  table {{ width: 100%; border-collapse: collapse; background: white; border-radius: 8px; overflow: hidden; box-shadow: 0 1px 4px rgba(0,0,0,.08); }}
  th {{ background: #7c3aed; color: white; text-align: left; padding: 10px 12px; font-size: 11px; text-transform: uppercase; letter-spacing: .06em; white-space: nowrap; }}
  td {{ padding: 10px 12px; border-bottom: 1px solid #f0f4f8; vertical-align: top; }}
  tr:last-child td {{ border-bottom: none; }}
  tr:hover td {{ background: #faf5ff; }}
  .score-badge {{ display: inline-block; padding: 3px 9px; border-radius: 12px; font-weight: 700; font-size: 13px; min-width: 36px; text-align: center; }}
  .fit-label   {{ font-size: 10px; margin-top: 2px; font-weight: 600; }}
  .job-title   {{ font-weight: 600; color: #7c3aed; text-decoration: none; font-size: 13px; }}
  .job-title:hover {{ text-decoration: underline; }}
  .salary {{ color: #2d6a4f; font-weight: 600; }}
  .muted  {{ color: #a0aec0; font-size: 11px; }}
  .kw-tag {{ background: #ede9fe; color: #6d28d9; padding: 2px 8px; border-radius: 10px; font-size: 10px; white-space: nowrap; }}
  tr.hidden {{ display: none; }}
</style>
</head>
<body>
<div class="header">
  <h1>IIMJobs Search — Adhiraj Sharma</h1>
  <p>Scraped {run_dt} &nbsp;|&nbsp; Sorted by relevance score</p>
</div>
<div class="stats">
  <div class="stat"><div class="n">{total}</div><div class="l">Total jobs</div></div>
  <div class="stat"><div class="n" style="color:#0f5132">{strong}</div><div class="l">Strong fit (75+)</div></div>
  <div class="stat"><div class="n" style="color:#664d03">{moderate}</div><div class="l">Moderate fit (55–74)</div></div>
  <div class="stat"><div class="n" style="color:#842029">{total-strong-moderate}</div><div class="l">Weak fit</div></div>
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
      <th style="width:80px">Score</th>
      <th>Role</th>
      <th>Company</th>
      <th>Location</th>
      <th>Exp</th>
      <th>Salary</th>
      <th>Posted</th>
      <th>Keyword</th>
    </tr>
  </thead>
  <tbody>{rows}</tbody>
</table>
</div>
<script>
function filterRows(type, btn) {{
  document.querySelectorAll('.filter-btn').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
  document.querySelectorAll('#jobs-table tbody tr').forEach(row => {{
    const score = parseInt(row.querySelector('.score-badge').textContent);
    if (type === 'all')           row.classList.remove('hidden');
    else if (type === 'strong')   row.classList.toggle('hidden', score < 75);
    else if (type === 'moderate') row.classList.toggle('hidden', score < 55);
  }});
}}
function filterKw(btn) {{
  document.querySelectorAll('.filter-btn').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
  const kw = btn.dataset.kw.toLowerCase();
  document.querySelectorAll('#jobs-table tbody tr').forEach(row => {{
    row.classList.toggle('hidden', row.querySelector('.kw-tag').textContent.trim().toLowerCase() !== kw);
  }});
}}
</script>
</body>
</html>"""


# ── Session helpers ───────────────────────────────────────────────────────────

def save_session(context):
    data = {
        "cookies":      context.cookies(),
        "saved_at":     datetime.now().isoformat(),
    }
    with open(SESSION_FILE, "w") as f:
        json.dump(data, f, indent=2)
    print(f"Session saved to {SESSION_FILE}")

def load_session(context):
    if not os.path.exists(SESSION_FILE):
        return False
    try:
        with open(SESSION_FILE) as f:
            data = json.load(f)
        context.add_cookies(data["cookies"])
        print(f"Session loaded (saved {data['saved_at'][:19]})")
        return True
    except Exception as e:
        print(f"Could not load session: {e}")
        return False


# ── Scraper ───────────────────────────────────────────────────────────────────

def wait(lo=1.5, hi=3.0):
    time.sleep(random.uniform(lo, hi))

def safe_text(el) -> str:
    try:
        return el.inner_text().strip()
    except Exception:
        return ""

def is_logged_in(page) -> bool:
    try:
        page.goto("https://www.iimjobs.com/", wait_until="domcontentloaded", timeout=20000)
        time.sleep(3)
        url  = page.url.lower()
        html = page.inner_html("body").lower()
        return (
            "jobfeed" in url
            or "dashboard" in url
            or "my profile" in html
            or "my account" in html
            or "logout" in html
            or "sign out" in html
            or "jobfeed" in html
            or "applied jobs" in html
        )
    except:
        return False

def login_flow(page, context):
    """Open login page and wait for user to log in manually."""
    print("\n" + "="*60)
    print("  IIMJobs LOGIN REQUIRED")
    print("  A browser window will open. Please log in with your")
    print("  IIMJobs credentials. The script continues automatically.")
    print("="*60 + "\n")

    page.goto("https://www.iimjobs.com/login", wait_until="domcontentloaded", timeout=20000)
    print("Waiting for you to log in... (up to 120 seconds)")

    try:
        page.wait_for_function(
            """() => {
                const html = document.body.innerText.toLowerCase();
                const url  = window.location.href.toLowerCase();
                return html.includes('jobfeed') || html.includes('applied jobs')
                    || html.includes('my profile') || html.includes('logout')
                    || html.includes('sign out') || html.includes('my account')
                    || url.includes('jobfeed') || url.includes('dashboard');
            }""",
            timeout=120000
        )
        print("Login detected!")
        time.sleep(2)
        save_session(context)
    except PwTimeout:
        print("Login timeout. Re-run with --login to try again.")
        return False
    return True

def extract_from_api(data, keyword: str) -> list[dict]:
    """Parse job data from an intercepted JSON API response."""
    jobs = []
    job_list = None
    if isinstance(data, list):
        job_list = data
    elif isinstance(data, dict):
        for key in ["jobs", "data", "results", "items", "jobList", "job_list", "listings", "records"]:
            if key in data and isinstance(data[key], list):
                job_list = data[key]
                break
    if not job_list:
        return jobs
    for item in job_list:
        if not isinstance(item, dict):
            continue
        title    = str(item.get("title") or item.get("job_title") or item.get("designation") or item.get("jobTitle") or "").strip()
        company  = str(item.get("company") or item.get("company_name") or item.get("companyName") or item.get("employer") or "").strip()
        location = str(item.get("location") or item.get("city") or item.get("job_location") or item.get("jobLocation") or "").strip()
        experience = str(item.get("experience") or item.get("exp") or item.get("minExp") or item.get("min_exp") or "").strip()
        salary   = str(item.get("salary") or item.get("ctc") or item.get("minSalary") or item.get("min_salary") or "").strip()
        posted   = str(item.get("posted") or item.get("postedAt") or item.get("posted_at") or item.get("createdAt") or "").strip()
        slug     = str(item.get("slug") or item.get("job_slug") or item.get("jobSlug") or "").strip()
        job_id   = str(item.get("id") or item.get("job_id") or item.get("jobId") or "").strip()
        url = item.get("url") or item.get("jobUrl") or ""
        if not url:
            if slug:
                url = f"https://www.iimjobs.com/j/{slug}"
            elif job_id:
                url = f"https://www.iimjobs.com/j/{job_id}"
        if title and (company or url):
            jobs.append({
                "title": title, "company": company, "location": location,
                "experience": experience, "salary": salary, "posted": posted,
                "url": str(url), "keyword_searched": keyword,
            })
    return jobs


def scrape_keyword(page, keyword: str, pages: int) -> list[dict]:
    jobs = []
    for pg in range(1, pages + 1):
        pg_param = f"&pg={pg}" if pg > 1 else ""
        # No experience filter -- broad search
        url = f"https://www.iimjobs.com/search?search_keyword={keyword.replace(' ', '+')}{pg_param}"
        print(f"  p{pg} -> {url}")

        # Intercept background API calls IIMJobs makes to load jobs
        captured_api: list[dict] = []

        def on_response(response):
            try:
                r_url = response.url.lower()
                if response.status != 200:
                    return
                if not ("iimjobs" in r_url or "gladiator" in r_url):
                    return
                ct = response.headers.get("content-type", "")
                if "json" not in ct:
                    return
                data = response.json()
                if data:
                    captured_api.append({"url": response.url, "data": data})
            except Exception:
                pass

        page.on("response", on_response)

        try:
            page.goto(url, wait_until="domcontentloaded", timeout=30000)
        except PwTimeout:
            print(f"  [page load timeout]")
            page.remove_listener("response", on_response)
            break

        # Wait up to 15s for actual job links to appear in the DOM
        job_links_ready = False
        try:
            page.wait_for_selector("a[href*='/j/']", timeout=15000)
            job_links_ready = True
        except PwTimeout:
            pass

        time.sleep(3)
        page.remove_listener("response", on_response)

        # Try API data first (most reliable)
        if captured_api:
            print(f"  API: {len(captured_api)} JSON response(s) captured")
            for capture in captured_api:
                extracted = extract_from_api(capture["data"], keyword)
                if extracted:
                    print(f"    {len(extracted)} jobs from {capture['url'][:80]}")
                    jobs.extend(extracted)
            if jobs:
                print(f"  API total: {len(jobs)} jobs for '{keyword}'")
                if pg < pages:
                    wait(2.0, 3.5)
                continue

        # DOM fallback: collect all /j/ links and pull parent card text
        links = page.query_selector_all("a[href*='/j/']") if job_links_ready else []
        print(f"  DOM: {len(links)} job link(s) found")

        seen_hrefs: set[str] = set()
        for link in links:
            try:
                href = link.get_attribute("href") or ""
                if not href or href in seen_hrefs:
                    continue
                seen_hrefs.add(href)
                if not href.startswith("http"):
                    href = "https://www.iimjobs.com" + href

                title = safe_text(link)
                if not title or len(title) < 5:
                    continue

                # Walk up to find a card container with more details
                parent_text: str = page.evaluate(
                    """el => {
                        let node = el;
                        for (let i = 0; i < 6; i++) {
                            node = node.parentElement;
                            if (!node) break;
                            const t = node.innerText || '';
                            if (t.split('\\n').length > 3) return t;
                        }
                        return '';
                    }""",
                    link
                )

                lines = [l.strip() for l in parent_text.split('\n') if l.strip()]
                # First line that isn't the title is usually company
                company = ""
                for ln in lines:
                    if ln.lower() != title.lower() and len(ln) > 2:
                        company = ln
                        break

                location = experience = salary = posted = ""
                for ln in lines:
                    if re.search(r'\d+\s*[-–]\s*\d+\s*(yr|year)', ln, re.I) and not experience:
                        experience = ln
                    elif re.search(r'lacs?|lakh|₹|\d+\s*lpa', ln, re.I) and not salary:
                        salary = ln
                    elif re.search(r'\d+\s*(day|week|month|hour)s?\s*ago', ln, re.I) and not posted:
                        posted = ln
                    elif re.search(r'(mumbai|delhi|bangalore|bengaluru|hyderabad|pune|chennai|gurgaon|noida|remote)', ln, re.I) and not location:
                        location = ln

                jobs.append({
                    "title": title, "company": company, "location": location,
                    "experience": experience, "salary": salary, "posted": posted,
                    "url": href, "keyword_searched": keyword,
                })
            except Exception:
                continue

        # If DOM also gave nothing, log page state for debugging
        if not links and not captured_api:
            pg_url = page.url
            pg_html_snippet = page.inner_text("body")[:300] if page.inner_text("body") else ""
            print(f"  [nothing found] current url: {pg_url}")
            print(f"  [page text preview]: {pg_html_snippet[:200]}")

        print(f"  Total for '{keyword}': {len(jobs)} so far")
        if pg < pages:
            wait(2.0, 3.5)

    return jobs




def is_within_3_months(posted: str) -> bool:
    """Return True if the posted string is within the last 90 days."""
    if not posted:
        return True   # no date = keep it (better than discarding valid jobs)
    s = posted.lower()
    m = re.search(r'(\d+)\s*(day|week|month|hour)', s)
    if not m:
        return True
    n, unit = int(m.group(1)), m.group(2)
    if unit.startswith("hour") or unit.startswith("day"):
        return True
    if unit.startswith("week"):
        return n <= 12          # 12 weeks ~ 3 months
    if unit.startswith("month"):
        return n <= 3
    return True


def deduplicate(jobs: list[dict]) -> list[dict]:
    seen, unique = set(), []
    for j in jobs:
        if not is_within_3_months(j.get("posted", "")):
            continue
        key = (j["title"].lower()[:50], j.get("company", "").lower())
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
    with open(OUTPUT_HTML, "w", encoding="utf-8") as f:
        f.write(build_html(jobs))
    print(f"HTML -> {OUTPUT_HTML}")

def open_in_chrome(path: str):
    subprocess.run(["open", "-a", "Google Chrome", os.path.abspath(path)])
    print("Opened in Chrome.")

def print_summary(jobs: list[dict]):
    print(f"\n{'='*70}")
    for i, j in enumerate(jobs, 1):
        fg, _, label = score_badge(j["score"])
        print(f"{i:>3}. [{j['score']:>3}] {j['title']}")
        print(f"       {j.get('company','')} | {j.get('location','')} | {j.get('experience','')}")
        print()


# ── Main ──────────────────────────────────────────────────────────────────────

def run(keywords: list[str], pages: int, force_login: bool):
    all_jobs = []

    with sync_playwright() as pw:
        # Use persistent profile so login survives across runs
        context = pw.chromium.launch_persistent_context(
            user_data_dir=PROFILE_DIR,
            headless=False,
            args=["--disable-blink-features=AutomationControlled", "--no-sandbox"],
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

        # Check login status
        logged_in = not force_login and is_logged_in(page)
        if not logged_in:
            ok = login_flow(page, context)
            if not ok:
                context.close()
                return

        print(f"\nLogged in. Starting search across {len(keywords)} keywords...\n")

        for keyword in keywords:
            print(f"[{keyword}]")
            jobs = scrape_keyword(page, keyword, pages)
            all_jobs.extend(jobs)
            wait(3.0, 5.0)

        context.close()

    unique = deduplicate(all_jobs)
    for j in unique:
        j["score"] = score_job(j)
    unique.sort(key=lambda j: j["score"], reverse=True)

    print_summary(unique)
    save_csv(unique)
    save_html(unique)
    open_in_chrome(OUTPUT_HTML)

    print(f"\nDone. {len(unique)} unique jobs found.")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--keyword",   "-k", help="Single keyword (overrides default list)")
    parser.add_argument("--pages",     "-p", type=int, default=2, help="Pages per keyword (default 2)")
    parser.add_argument("--login",     action="store_true", help="Force re-login")
    args = parser.parse_args()

    keywords = [args.keyword] if args.keyword else TARGET_KEYWORDS

    print(f"IIMJobs Search  --  {datetime.now().strftime('%d %b %Y %H:%M')}")
    print(f"Keywords : {', '.join(keywords)}")
    print(f"Pages/kw : {args.pages}")
    print(f"Profile  : {PROFILE_DIR}\n")

    run(keywords, args.pages, force_login=args.login)


if __name__ == "__main__":
    main()
