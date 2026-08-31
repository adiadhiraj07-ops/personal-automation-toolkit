"""
LinkedIn Hiring Post Scraper
============================
Searches LinkedIn posts for hiring signals matching your target role, domain,
and location. Works by connecting to your own Chrome browser via CDP (Chrome
DevTools Protocol) so no API keys or special auth is needed — just a logged-in
LinkedIn session.

Quick start:
  1. pip install -r requirements.txt
  2. Edit SECTIONS 1-5 below (queries, role keywords, domain, location)
  3. python linkedin_post_scraper.py

Output files:
  linkedin_hiring_posts.html  (open in browser to browse results as cards)
  linkedin_hiring_posts.json  (raw data, useful for further processing)

Requirements: Python 3.10+, Google Chrome installed, LinkedIn account
"""

import json, html, re, sys, os, subprocess, time as _t, socket, asyncio, platform
from datetime import datetime, timezone, timedelta
from typing import Optional
from urllib.parse import quote
import websockets as _ws
import requests as _req


# ==============================================================================
# SECTION 1 — SEARCH QUERIES
# LinkedIn search queries the script will run. Mix role-title queries and
# behaviour-signal queries (phrases people actually write in hiring posts).
# ==============================================================================

SEARCH_QUERIES = [
    # Examples for a management / strategy consultant.
    # Replace all of these with queries relevant to your target role.
    "management consultant hiring India",
    "strategy consultant hiring India",
    "consulting manager hiring India",
    "engagement manager hiring India",
    "associate consultant hiring India",
    "digital transformation consultant hiring",
    "operations consultant hiring India startup",
    "looking for strategy consultant India",
    "hiring management consultant MBA India",
    "principal consultant associate partner hiring",
    "chief of staff hiring India startup",
    "business analyst strategy hiring India",
]


# ==============================================================================
# SECTION 2 — ROLE KEYWORDS
# Phrases that identify a post as targeting your role. Case-insensitive substring
# match against the post text. Add every variant of your job title.
# ==============================================================================

ROLE_SIGNALS = [
    "management consultant", "strategy consultant", "business consultant",
    "management consulting", "strategy consulting",
    "associate consultant", "senior consultant", "principal consultant",
    "consulting manager", "consulting partner", "associate partner",
    "engagement manager", "client partner",
    "business analyst", "strategy analyst",
    "director of strategy", "head of strategy",
    "vp strategy", "chief of staff",
    "transformation lead", "transformation manager",
    "operations consultant", "digital transformation",
    "strategy lead", "strategy manager",
]


# ==============================================================================
# SECTION 3 — DOMAIN KEYWORDS
# Words that confirm the post is in your target domain. A post must match at
# least one of these (or have an embedded job card) to pass the filter.
# ==============================================================================

DOMAIN_KEYWORDS = [
    "consulting", "strategy", "transformation", "advisory",
    "management consulting", "operations", "business analysis",
    "due diligence", "growth strategy", "market entry",
    "go-to-market", "profitability", "cost reduction",
]


# ==============================================================================
# SECTION 4 — PROFILE MATCH KEYWORDS (scoring boost)
# Keywords that indicate a strong personal fit. These earn extra score points
# but do NOT filter posts out. Add tools, sectors, frameworks, institutions.
# ==============================================================================

PROFILE_MATCH_KEYWORDS = [
    # Top-tier firm/pedigree signal -- add your own target employers' names
    # here (e.g. specific consulting firms, Big 4, etc.); left as generic
    # category placeholders in this public copy rather than naming real firms
    "top_tier_consulting_firm_1", "top_tier_consulting_firm_2",
    "top_tier_consulting_firm_3", "big_4_firm_1", "big_4_firm_2",
    "mba", "iim", "iit", "iim ahmedabad", "iim bangalore", "iim calcutta",
    # Finance context
    "private equity", "venture capital", "investment banking",
    # Skills
    "stakeholder management", "project management", "program management",
    "excel", "powerpoint", "tableau", "sql",
    # Sectors
    "consumer", "retail", "fmcg", "healthcare", "fintech", "edtech",
    "d2c", "ecommerce", "marketplace",
    # Company stage
    "funded", "series a", "series b", "series c", "startup", "hypergrowth",
    # Seniority descriptors worth a bonus
    "leadership", "cross-functional",
]

SENIORITY_SIGNALS = [
    "7+", "8+", "6+", "5+", "4+",
    "senior", "lead", "vp", "avp", "gm",
    "general manager", "director", "partner",
    "head of", "c-level", "chief",
    "associate director", "associate partner", "principal",
    "ex-founder", "ex founder", "founder",
]


# ==============================================================================
# SECTION 5 — LOCATION FILTER
# Set TARGET_LOCATION to your target country/region, or set it to "" to disable
# location filtering entirely. Add city names in lowercase to TARGET_CITIES.
# ==============================================================================

TARGET_LOCATION = "India"   # set to "" to disable location filtering

TARGET_CITIES = [
    # India (default) — replace with your target region
    "india", "bangalore", "bengaluru", "delhi", "gurgaon", "gurugram",
    "mumbai", "noida", "hyderabad", "pune", "chennai", "kolkata", "indian",

    # Uncomment for US:
    # "united states", "new york", "san francisco", "chicago", "boston",
    # "los angeles", "seattle", "austin", "washington", "remote us",

    # Uncomment for UK:
    # "united kingdom", "london", "manchester", "edinburgh", "birmingham",
]


# ==============================================================================
# SECTION 6 — CHROME PROFILE DIRECTORY
# A dedicated Chrome profile that holds your LinkedIn session.
# On first run Chrome will open LinkedIn for you to log in, then close it.
# Subsequent runs use the saved cookies automatically.
# Default path: ~/linkedin-scraper-profile (created automatically on first run).
# ==============================================================================

CHROME_PROFILE_DIR = os.path.expanduser("~/linkedin-scraper-profile")


# ==============================================================================
# SECTION 7 — TIMING (usually fine to leave as-is)
# ==============================================================================

MAX_AGE_DAYS = 90     # ignore posts older than this many days
MAX_SCROLL   = 6      # scroll iterations per query (more = more posts, slower)
SCROLL_PAUSE = 2500   # milliseconds between scrolls
QUERY_PAUSE  = 5      # seconds between queries (be gentle with LinkedIn)

OUTPUT_HTML = "linkedin_hiring_posts.html"
OUTPUT_JSON = "linkedin_hiring_posts.json"
DEBUG_PORT  = 9222


# ==============================================================================
# Internal setup (no need to edit below this line)
# ==============================================================================

def _find_chrome():
    """Auto-detect Chrome binary path for macOS, Windows, and Linux."""
    env_override = os.environ.get("CHROME_BIN")
    if env_override:
        return env_override
    system = platform.system()
    if system == "Darwin":
        candidates = [
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
            "/Applications/Chromium.app/Contents/MacOS/Chromium",
        ]
    elif system == "Windows":
        candidates = [
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
            os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
        ]
    else:
        candidates = [
            "/usr/bin/google-chrome",
            "/usr/bin/google-chrome-stable",
            "/usr/bin/chromium-browser",
            "/usr/bin/chromium",
        ]
    for c in candidates:
        if os.path.exists(c):
            return c
    raise RuntimeError(
        "Google Chrome not found.\n"
        "Install Chrome or set the CHROME_BIN environment variable to its path."
    )

CHROME_BIN = _find_chrome()

_msg_id = 0


# ── Time parsing ──────────────────────────────────────────────────────────────

def _parse_relative_time(s: str) -> Optional[datetime]:
    s = s.lower().strip()
    m = re.search(r"(\d+)\s*(h|d|w|mo)", s)
    if not m:
        return None
    n, unit = int(m.group(1)), m.group(2)
    now = datetime.now(timezone.utc)
    if unit == "h":  return now - timedelta(hours=n)
    if unit == "d":  return now - timedelta(days=n)
    if unit == "w":  return now - timedelta(weeks=n)
    if unit == "mo": return now - timedelta(days=n * 30)
    return None


def _is_recent(post: dict) -> bool:
    ts = post.get("postedAtISO", "")
    if ts:
        try:
            posted = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            return posted >= datetime.now(timezone.utc) - timedelta(days=MAX_AGE_DAYS)
        except Exception:
            pass
    time_str = post.get("timeSincePosted", "")
    if time_str:
        posted = _parse_relative_time(time_str)
        if posted:
            return posted >= datetime.now(timezone.utc) - timedelta(days=MAX_AGE_DAYS)
    return True   # no date info: LinkedIn sorts by recency so assume in range


# ── Filtering ─────────────────────────────────────────────────────────────────

def is_relevant(post: dict) -> bool:
    if not _is_recent(post):
        return False
    text = post.get("text", "").lower()
    if not text:
        return False

    # Hiring intent
    hiring_signals = [
        "hiring", "looking for", "we need", "join us", "open role",
        "open position", "we're hiring", "we are hiring", "apply", "dm me",
        "we want", "you will own", "you'll own", "this role",
        "reach out", "reach me", "send your cv", "send cv",
        "drop your cv", "drop a dm", "connect with me",
    ]
    if not any(w in text for w in hiring_signals):
        # Posts with an embedded job card are hiring posts by definition
        if not post.get("jobTitle"):
            return False

    # Domain relevance
    if not any(w in text for w in DOMAIN_KEYWORDS):
        job = (post.get("jobTitle", "") + " " + post.get("jobCompany", "")).lower()
        if not any(w in job for w in DOMAIN_KEYWORDS + ROLE_SIGNALS):
            return False

    # Skip internship/fresher posts
    if any(e in text for e in ["intern", "fresher", "0-2 year", "0 to 2 year", "trainee",
                                "entry level", "junior", "graduate trainee"]):
        return False

    # Skip appointment/promotion announcements (not open roles)
    if any(e in text for e in [
        "congratulations", "congratulating",
        "on his appointment", "on her appointment",
        "pleased to announce", "happy to announce",
        "proud to announce", "delighted to announce",
    ]):
        return False

    # Skip person-seeking-job posts
    if any(e in text for e in [
        "open to work", "open to opportunities", "looking for opportunities",
        "seeking new opportunities", "actively looking",
        "i am looking for", "i'm looking for",
        "please refer", "available for",
    ]):
        if not any(h in text for h in ["we are hiring", "we're hiring", "join our team", "open role"]):
            return False

    # Location filter (skip if TARGET_LOCATION is set but no match found)
    if TARGET_LOCATION and TARGET_CITIES:
        if not any(sig in text for sig in TARGET_CITIES):
            job_loc = post.get("jobLocation", "").lower()
            if not any(sig in job_loc for sig in TARGET_CITIES):
                return False

    return True


# ── Scoring ───────────────────────────────────────────────────────────────────

def score_post(post: dict) -> int:
    text = post.get("text", "").lower()
    score  = sum(3 for s in ROLE_SIGNALS           if s in text)
    score += sum(2 for k in PROFILE_MATCH_KEYWORDS if k in text)
    score += sum(1 for s in SENIORITY_SIGNALS       if s in text)
    score += min(post.get("numLikes", 0) // 15, 4)
    if post.get("jobTitle"):
        score += 5   # embedded job card is a strong signal
    return score


# ── Tags (for HTML display) ───────────────────────────────────────────────────

def get_tags(post: dict) -> list[str]:
    text = post.get("text", "").lower()
    tags = []
    if post.get("jobTitle"):
        tags.append("Job Card")
    if any(k in text for k in ROLE_SIGNALS):
        tags.append("Role Match")
    if any(k in text for k in DOMAIN_KEYWORDS):
        tags.append("Domain")
    if TARGET_CITIES and any(k in text for k in TARGET_CITIES):
        tags.append(TARGET_LOCATION or "Location Match")
    if any(k in text for k in ["series a", "series b", "series c", "funded", "startup"]):
        tags.append("Startup")
    if any(k in text for k in SENIORITY_SIGNALS):
        tags.append("Senior+")
    return tags


# ── LinkedIn DOM extraction (injected into the page via CDP) ──────────────────

EXTRACT_JS = """() => {
    const results = [];
    const seenUrns = new Set();

    const menuBtns = document.querySelectorAll('[aria-label^="Open control menu for post by"]');

    for (const btn of menuBtns) {
        let container = btn;
        for (let i = 0; i < 15; i++) {
            if (!container.parentElement) break;
            container = container.parentElement;
            if (container.dataset && container.dataset.testid === 'lazy-column') break;
            const menus = container.querySelectorAll('[aria-label^="Open control menu for post by"]');
            if (menus.length === 1 && (container.innerText || '').length > 100) break;
        }

        let authorName = '', authorLink = '';
        const inLinks = container.querySelectorAll('a[href*="/in/"]');
        let nameLink = null;
        for (const link of inLinks) {
            if (!link.querySelector('img') && (link.innerText || '').trim()) {
                authorName = (link.innerText || '').trim().split('\\n')[0].trim();
                authorLink = link.href.split('?')[0];
                nameLink = link;
                break;
            }
        }
        if (!authorName) continue;

        let headline = '', timeSincePosted = '';
        if (nameLink) {
            let el = nameLink;
            for (let i = 0; i < 3; i++) { if (el.parentElement) el = el.parentElement; }
            const lines = (el.innerText || '').split('\\n')
                .map(l => l.trim())
                .filter(l => l && l !== ' ' && !/^[•·]\\s*(1st|2nd|3rd|4th|5th|\\d+)/.test(l) && l !== '•');
            for (const line of lines) {
                if (line === authorName) continue;
                if (/^\\d+(m|h|d|w|mo)\\s*•?$/.test(line) || /^Just now$/i.test(line)) {
                    timeSincePosted = line.replace(/\\s*•\\s*$/, '');
                } else if (!headline && line.length > 5 && !/^\\d+$/.test(line)) {
                    headline = line;
                }
            }
        }

        const textBox = container.querySelector('[data-testid="expandable-text-box"]');
        const text = (textBox ? (textBox.innerText || '').trim() : '');
        if (text.length < 50) continue;

        let url = '';
        for (const link of container.querySelectorAll('a')) {
            if (link.href.includes('/feed/update/') || link.href.includes('/posts/')) {
                url = link.href.split('?')[0];
                break;
            }
        }
        if (!url) url = authorLink;

        let pic = '';
        const img = container.querySelector('img[src*="licdn"]');
        if (img) pic = img.src;

        let numLikes = 0;
        const engSelectors = [
            '[aria-label*=" reaction"]', '[aria-label*=" like"]',
            'button[aria-label*="reaction"]', '[data-testid*="reaction"]',
            'span[class*="reactions-count"]',
        ];
        outer: for (const sel of engSelectors) {
            for (const el of container.querySelectorAll(sel)) {
                const raw = (el.getAttribute('aria-label') || el.innerText || '').replace(/[^0-9]/g, '');
                const n = parseInt(raw) || 0;
                if (n > 0) { numLikes = n; break outer; }
            }
        }

        // Embedded job card extraction
        const UI_LABELS = new Set(['feed post', 'view job', 'apply', 'following', 'connect',
            '1st', '2nd', '3rd', 'promoted', 'author', 'like', 'comment', 'repost', 'send']);
        let jobTitle = '', jobCompany = '', jobLocation = '';
        const jobViewLink = container.querySelector('a[href*="/jobs/view/"]');
        if (jobViewLink) {
            let jc = jobViewLink;
            for (let i = 0; i < 6; i++) {
                if (!jc.parentElement) break;
                jc = jc.parentElement;
                const lines = (jc.innerText || '').split('\\n')
                    .map(l => l.trim())
                    .filter(l => l.length > 3 && !UI_LABELS.has(l.toLowerCase())
                              && !/^\\d+$/.test(l) && l !== 'school alumni works here'
                              && !l.startsWith('1 school'));
                if (lines.length >= 2) {
                    jobTitle    = lines[0];
                    jobCompany  = lines[1];
                    jobLocation = lines[2] || '';
                    break;
                }
            }
        }
        if (UI_LABELS.has((jobTitle || '').toLowerCase()) || (jobTitle || '').length < 4) {
            jobTitle = jobCompany = jobLocation = '';
        }

        const urn = authorLink + '::' + text.substring(0, 60);
        if (seenUrns.has(urn)) continue;
        seenUrns.add(urn);

        results.push({urn, authorName, authorLink, headline, timeSincePosted, text,
                      numLikes, numComments: 0, pic, url, jobTitle, jobCompany, jobLocation});
    }
    return results;
}"""


# ── HTML output ───────────────────────────────────────────────────────────────

HTML_PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>LinkedIn Hiring Posts</title>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>
*, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
body {{ font-family: 'Inter', sans-serif; background: #F0F4FA; color: #1A1A2E; padding: 32px 16px; }}
.header {{ max-width: 800px; margin: 0 auto 24px; display: flex; justify-content: space-between; align-items: flex-end; }}
.header h1 {{ font-size: 20px; font-weight: 700; color: #0E2D5E; }}
.header p  {{ font-size: 12px; color: #9CA3AF; margin-top: 3px; }}
.meta-right {{ font-size: 12px; color: #6B7280; text-align: right; }}
.grid {{ max-width: 800px; margin: 0 auto; display: flex; flex-direction: column; gap: 14px; }}
.card {{
  background: white; border-radius: 10px; padding: 18px 22px;
  border-left: 4px solid #0E2D5E;
  box-shadow: 0 1px 3px rgba(0,0,0,.07);
}}
.card-head {{ display: flex; align-items: center; gap: 12px; margin-bottom: 12px; }}
.avatar {{
  width: 40px; height: 40px; border-radius: 50%;
  object-fit: cover; flex-shrink: 0; background: #EBF0F8;
}}
.author-name {{ font-weight: 600; font-size: 13.5px; color: #0E2D5E; }}
.author-title {{ font-size: 11.5px; color: #6B7280; margin-top: 1px; }}
.post-meta {{ margin-left: auto; text-align: right; }}
.time {{ font-size: 11px; color: #9CA3AF; }}
.engagement {{ font-size: 11px; color: #6B7280; margin-top: 2px; }}
.text {{
  font-size: 13px; line-height: 1.7; color: #374151;
  white-space: pre-wrap; word-break: break-word;
  max-height: 220px; overflow: hidden;
  mask-image: linear-gradient(to bottom, black 70%, transparent 100%);
  -webkit-mask-image: linear-gradient(to bottom, black 70%, transparent 100%);
}}
.tags {{ display: flex; gap: 6px; flex-wrap: wrap; margin-top: 12px; }}
.tag {{
  font-size: 10px; font-weight: 600; letter-spacing: .05em;
  padding: 2px 8px; border-radius: 20px;
  background: #EBF0F8; color: #0E2D5E;
}}
.link {{
  display: inline-block; margin-top: 10px;
  font-size: 12px; font-weight: 500; color: #2563EB;
  text-decoration: none;
}}
.link:hover {{ text-decoration: underline; }}
.empty {{ text-align: center; padding: 80px; color: #9CA3AF; font-size: 14px; }}
.job-card-inline {{
  display: flex; align-items: center; gap: 8px; flex-wrap: wrap;
  background: #F0F4FA; border-radius: 6px; padding: 7px 12px;
  margin-bottom: 10px; font-size: 12px;
}}
.job-card-title {{ font-weight: 700; color: #0E2D5E; }}
.job-card-company {{ color: #374151; }}
.job-card-company::before {{ content: "·"; margin-right: 8px; color: #9CA3AF; }}
.job-card-loc {{ color: #6B7280; font-size: 11px; }}
.job-card-loc::before {{ content: "·"; margin-right: 8px; color: #9CA3AF; }}
</style>
</head>
<body>
<div class="header">
  <div>
    <h1>LinkedIn Hiring Posts</h1>
    <p>{subtitle}</p>
  </div>
  <div class="meta-right">{count} posts &nbsp;&middot;&nbsp; {date}</div>
</div>
<div class="grid">
{cards}
</div>
</body>
</html>"""

CARD = """<div class="card">
  <div class="card-head">
    <img class="avatar" src="{pic}" onerror="this.style.display='none'" />
    <div>
      <div class="author-name">{name}</div>
      <div class="author-title">{headline}</div>
    </div>
    <div class="post-meta">
      <div class="time">{time}</div>
      <div class="engagement">&#128077; {likes} &nbsp; &#128172; {comments}</div>
    </div>
  </div>
  {job_card_html}
  <div class="text">{text}</div>
  <div class="tags">{tags}</div>
  <a class="link" href="{url}" target="_blank">View on LinkedIn &#8594;</a>
</div>"""

JOB_CARD_HTML = """<div class="job-card-inline">
  <span class="job-card-title">{title}</span>
  <span class="job-card-company">{company}</span>
  <span class="job-card-loc">{location}</span>
</div>"""


def build_html(posts: list[dict]) -> str:
    subtitle_parts = []
    if ROLE_SIGNALS:
        subtitle_parts.append(ROLE_SIGNALS[0].title())
    if TARGET_LOCATION:
        subtitle_parts.append(TARGET_LOCATION)
    subtitle = " &middot; ".join(subtitle_parts) if subtitle_parts else "Hiring Posts"

    if not posts:
        return HTML_PAGE.format(
            subtitle=subtitle,
            count=0,
            date=datetime.now().strftime("%d %b %Y, %H:%M"),
            cards='<div class="empty">No relevant posts found. Try running again or adjust your queries.</div>',
        )
    cards = []
    for p in posts:
        tag_html = "".join(f'<span class="tag">{t}</span>' for t in get_tags(p))
        job_title = p.get("jobTitle", "").strip()
        if job_title and job_title.lower() == p.get("authorName", "").lower():
            job_title = ""
        job_card_html = ""
        if job_title:
            job_card_html = JOB_CARD_HTML.format(
                title    = html.escape(job_title),
                company  = html.escape(p.get("jobCompany", "")),
                location = html.escape(p.get("jobLocation", "")),
            )
        cards.append(CARD.format(
            pic          = p.get("pic", ""),
            name         = html.escape(p.get("authorName", "Unknown")),
            headline     = html.escape(p.get("headline", "")),
            time         = html.escape(p.get("timeSincePosted", "")),
            likes        = p.get("numLikes", 0),
            comments     = p.get("numComments", 0),
            text         = html.escape(p.get("text", "")[:600]),
            tags         = tag_html,
            url          = p.get("url", "#"),
            job_card_html = job_card_html,
        ))
    return HTML_PAGE.format(
        subtitle=subtitle,
        count=len(posts),
        date=datetime.now().strftime("%d %b %Y, %H:%M"),
        cards="\n".join(cards),
    )


# ── Chrome / CDP helpers ──────────────────────────────────────────────────────

def _port_open(port: int) -> bool:
    with socket.socket() as s:
        return s.connect_ex(("localhost", port)) == 0


def ensure_chrome():
    """Start Chrome with the debug profile if not already running."""
    if _port_open(DEBUG_PORT):
        return
    print("Opening Chrome on LinkedIn...")
    os.makedirs(CHROME_PROFILE_DIR, exist_ok=True)
    args = [
        CHROME_BIN,
        f"--remote-debugging-port={DEBUG_PORT}",
        f"--user-data-dir={CHROME_PROFILE_DIR}",
        "--profile-directory=Default",
        "--no-first-run",
        "https://www.linkedin.com/feed/",
    ]
    if platform.system() == "Windows":
        subprocess.Popen(args, creationflags=subprocess.CREATE_NO_WINDOW)
    else:
        subprocess.Popen(args)
    for _ in range(20):
        if _port_open(DEBUG_PORT):
            break
        _t.sleep(1)
    _t.sleep(3)


def _get_linkedin_tab_ws():
    pages = _req.get(f"http://localhost:{DEBUG_PORT}/json").json()
    tab = next(
        (p for p in pages
         if "linkedin.com" in p.get("url", "")
         and "merchantpool" not in p.get("url", "")
         and "demdex" not in p.get("url", "")),
        None
    )
    if not tab:
        raise RuntimeError(
            "No LinkedIn tab found in Chrome.\n"
            "Make sure Chrome opened LinkedIn and you are logged in."
        )
    return tab["webSocketDebuggerUrl"]


async def _open_tab(url: str):
    resp = _req.put(f"http://localhost:{DEBUG_PORT}/json/new")
    data = resp.json()
    return data["webSocketDebuggerUrl"], data["id"]


async def _close_tab(tab_id: str):
    _req.get(f"http://localhost:{DEBUG_PORT}/json/close/{tab_id}")


async def scrape_via_cdp(search_url: str) -> list:
    global _msg_id
    ws_url, tab_id = await _open_tab(search_url)

    async with _ws.connect(ws_url, max_size=50_000_000) as ws:
        for domain in ["Page", "Runtime", "Network"]:
            _msg_id += 1
            await ws.send(json.dumps({"id": _msg_id, "method": f"{domain}.enable", "params": {}}))
            await ws.recv()

        _msg_id += 1
        await ws.send(json.dumps({"id": _msg_id, "method": "Page.navigate",
                                   "params": {"url": search_url}}))
        deadline = _t.time() + 20
        while _t.time() < deadline:
            msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
            if msg.get("method") == "Page.loadEventFired":
                break

        await asyncio.sleep(4)

        all_posts, seen = [], set()

        for scroll in range(MAX_SCROLL):
            _msg_id += 1
            await ws.send(json.dumps({
                "id": _msg_id,
                "method": "Runtime.evaluate",
                "params": {
                    "expression": "(" + EXTRACT_JS + ")()",
                    "returnByValue": True,
                    "awaitPromise": False,
                }
            }))
            while True:
                msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=10))
                if msg.get("id") == _msg_id:
                    posts = msg.get("result", {}).get("result", {}).get("value", []) or []
                    break

            new = 0
            for p in posts:
                if p.get("urn") and p["urn"] not in seen and p.get("text"):
                    seen.add(p["urn"])
                    all_posts.append(p)
                    new += 1

            print(f"  Scroll {scroll+1}/{MAX_SCROLL}: +{new} new  (total {len(all_posts)})")

            # Scroll the LinkedIn results container (not the window)
            scroll_js = """
                (function() {
                    const selectors = [
                        '.search-results-container',
                        '[data-finite-scroll-hotkey-context]',
                        '.scaffold-layout__main',
                        'main',
                    ];
                    for (const sel of selectors) {
                        const el = document.querySelector(sel);
                        if (el && el.scrollHeight > el.clientHeight) {
                            el.scrollTop = el.scrollHeight;
                            return 'container:' + sel;
                        }
                    }
                    window.scrollTo(0, document.body.scrollHeight);
                    return 'window';
                })()
            """
            _msg_id += 1
            await ws.send(json.dumps({
                "id": _msg_id,
                "method": "Runtime.evaluate",
                "params": {"expression": scroll_js, "returnByValue": True},
            }))
            await asyncio.wait_for(ws.recv(), timeout=5)
            await asyncio.sleep(SCROLL_PAUSE / 1000)

    await _close_tab(tab_id)
    return all_posts


def _open_in_browser(path: str):
    system = platform.system()
    if system == "Darwin":
        subprocess.run(["open", path])
    elif system == "Windows":
        os.startfile(path)
    else:
        subprocess.run(["xdg-open", path])


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    print("LinkedIn Hiring Post Scraper")
    print("=" * 56)

    ensure_chrome()

    try:
        _get_linkedin_tab_ws()
        print("Chrome: LinkedIn tab found. Session active.")
    except RuntimeError as e:
        print(f"ERROR: {e}")
        sys.exit(1)

    all_posts, seen_urns = [], set()
    loop = asyncio.get_event_loop()

    for i, query in enumerate(SEARCH_QUERIES, 1):
        print(f"\n[{i}/{len(SEARCH_QUERIES)}] \"{query}\"")
        search_url = (
            f"https://www.linkedin.com/search/results/content/"
            f"?keywords={quote(query)}&sortBy=date_posted"
        )
        try:
            raw = loop.run_until_complete(scrape_via_cdp(search_url))
            new = 0
            for p in raw:
                if p["urn"] not in seen_urns:
                    if is_relevant(p):
                        p["_score"] = score_post(p)
                        all_posts.append(p)
                        new += 1
                    seen_urns.add(p["urn"])
            print(f"  Relevant: {new}  (running total: {len(all_posts)})")
        except Exception as e:
            print(f"  ERROR on query: {e}")

        if i < len(SEARCH_QUERIES):
            print(f"  Waiting {QUERY_PAUSE}s...")
            _t.sleep(QUERY_PAUSE)

    all_posts.sort(key=lambda p: p["_score"], reverse=True)

    print(f"\n{'='*56}")
    print(f"Total relevant posts: {len(all_posts)}")

    with open(OUTPUT_JSON, "w") as f:
        json.dump(all_posts, f, indent=2)

    with open(OUTPUT_HTML, "w") as f:
        f.write(build_html(all_posts))

    print(f"Saved: {OUTPUT_JSON}")
    print(f"Saved: {OUTPUT_HTML}")

    _open_in_browser(os.path.abspath(OUTPUT_HTML))
    print("Opened in browser.")


if __name__ == "__main__":
    main()
