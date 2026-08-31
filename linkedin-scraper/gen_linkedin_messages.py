#!/usr/bin/env python3
"""
Generate personalized LinkedIn connection-request messages for hiring posts
found by linkedin_post_scraper.py.
Output: linkedin_messages.html  (one-click copy buttons, 300-char limit enforced)

Reads posts from linkedin_hiring_posts.json (produced by linkedin_post_scraper.py)
and your pitch bank from pitches.json (falls back to the placeholder
pitches.example.json if pitches.json doesn't exist yet -- copy it and fill in
your own background/pitch lines before using this for real).

NOTE: linkedin_post_scraper.py's current output schema (authorName, headline,
authorLink, ...) doesn't line up 1:1 with the fields this script reads
(authorHeadline, authorType, authorProfileUrl) -- that mismatch existed in the
original source and hasn't been fixed here; adjust build_message()/the row
builder below to match whatever field names your actual posts JSON uses.
"""
import json, re, html as html_lib
from pathlib import Path
from datetime import datetime

with open("linkedin_hiring_posts.json") as f:
    posts = json.load(f)

# ── Role signals (longest-first for greedy match) ──────────────────────────
ROLE_SIGNALS = [
    "e-commerce head", "ecommerce head",
    "head of growth", "head of crm", "head of lifecycle", "head of marketing",
    "vp of growth", "vp growth", "vp marketing",
    "chief growth officer", "chief marketing officer", "chief growth", "chief marketing",
    "growth lead", "growth head",
    "gm - growth", "gm growth",
    "director of growth", "director growth",
    "growth & marketing",
    "marketing lead", "marketing manager",
    "crm lead", "crm manager",
    "lifecycle lead", "lifecycle manager",
    "retention lead", "engagement lead",
    "growth manager",
    "performance marketing",
]

# ── Pitch bank: 3 variants per topic (rotated to avoid sameness) ───────────
# Loaded from pitches.json (your real background/pitch lines) if present,
# else pitches.example.json (obviously-placeholder content) so this script
# still runs out of the box. Copy pitches.example.json -> pitches.json and
# write your own one-line pitches per topic before using this for real.
_PITCHES_PATH = Path(__file__).parent / "pitches.json"
_PITCHES_EXAMPLE_PATH = Path(__file__).parent / "pitches.example.json"
with open(_PITCHES_PATH if _PITCHES_PATH.exists() else _PITCHES_EXAMPLE_PATH) as f:
    PITCHES = json.load(f)

_counter: dict = {}

def get_pitch(topic: str) -> str:
    idx = _counter.get(topic, 0)
    p = PITCHES.get(topic, PITCHES["default"])[idx % 3]
    _counter[topic] = idx + 1
    return p

def detect_topic(text: str) -> str:
    t = text.lower()
    if any(k in t for k in ["crm", "lifecycle", "retention", "clevertap", "moengage", "engagement marketing"]):
        return "crm"
    if any(k in t for k in ["ecommerce", "e-commerce", "d2c", "marketplace", "amazon"]):
        return "ecommerce"
    if any(k in t for k in ["head of growth", "vp growth", "gm growth", "growth lead"]):
        return "growth"
    if any(k in t for k in ["performance marketing", "digital marketing", "marketing lead", "marketing manager"]):
        return "marketing"
    return "default"

def extract_role(text: str) -> str:
    t = text.lower()
    for sig in ROLE_SIGNALS:
        if sig in t:
            return sig.title()
    # Fallback: capture text after hiring/for a/for an
    m = re.search(
        r"(?:hiring[:\s]+|we(?:'re| are) hiring[:\s]+|looking for (?:a |an )?)([A-Z][^\n\.!?]{5,50})",
        text, re.IGNORECASE
    )
    if m:
        role = re.sub(r'[^a-zA-Z &\-/].*$', '', m.group(1).strip())
        if len(role) > 4:
            return role[:45].title()
    return "Growth Role"

def first_name(name: str) -> str:
    if not name:
        return "there"
    parts = name.strip().split()
    candidate = parts[0] if parts else name
    ascii_len = len(candidate.encode("ascii", "ignore"))
    if ascii_len < 2:
        return "there"
    # Title-case all-caps names (e.g. "NIKHIL" -> "Nikhil")
    if candidate.isupper():
        candidate = candidate.capitalize()
    return candidate

def is_senior(headline: str) -> bool:
    hl = (headline or "").lower()
    return any(k in hl for k in [
        "founder", "co-founder", "ceo", "cto", "coo", "chief",
        "president", "owner", "director", "head of", "vp ", "md "
    ])

def build_message(post: dict) -> str:
    name     = post.get("authorName", "")
    headline = post.get("authorHeadline", "")
    text     = post.get("text", "")
    is_co    = post.get("authorType", "Person") == "Company"

    fn    = first_name(name)
    role  = extract_role(text)
    topic = detect_topic(text)
    pitch = get_pitch(topic)

    if is_co:
        msg = f"Hi there, noticed your {role} post. {pitch}. Would love to connect!"
    elif is_senior(headline):
        msg = f"Hi {fn}, saw your {role} post — {pitch}. Would love to connect!"
    else:
        msg = f"Hi {fn}, saw your {role} post. {pitch}. Happy to share my profile if relevant!"

    # Enforce 300-char LinkedIn limit
    while len(msg) > 295:
        if len(pitch) > 50:
            pitch = pitch.rsplit(" ", 1)[0]   # trim one word at a time
            if is_co:
                msg = f"Hi there, noticed your {role} post. {pitch}. Would love to connect!"
            elif is_senior(headline):
                msg = f"Hi {fn}, saw your {role} post — {pitch}. Would love to connect!"
            else:
                msg = f"Hi {fn}, saw your {role} post. {pitch}. Happy to connect!"
        else:
            msg = msg[:292] + "..."
            break

    return msg

# ── Build data ─────────────────────────────────────────────────────────────
rows = []
for i, post in enumerate(posts):
    msg  = build_message(post)
    role = extract_role(post.get("text", ""))
    rows.append({
        "num":      i + 1,
        "author":   post.get("authorName", "Unknown"),
        "headline": post.get("authorHeadline", ""),
        "role":     role,
        "message":  msg,
        "post_url": post.get("url", "#"),
        "author_url": post.get("authorProfileUrl", "#"),
        "chars":    len(msg),
        "score":    post.get("_score", 0),
    })

# ── HTML ───────────────────────────────────────────────────────────────────
def char_color(n: int) -> str:
    if n <= 250: return "#16a34a"   # green
    if n <= 280: return "#d97706"   # amber
    return "#dc2626"                # red

rows_html = []
for r in rows:
    esc_msg  = html_lib.escape(r["message"])
    esc_auth = html_lib.escape(r["author"])
    esc_hl   = html_lib.escape(r["headline"])
    esc_role = html_lib.escape(r["role"])
    cc       = char_color(r["chars"])

    rows_html.append(f"""
<tr>
  <td class="num">{r['num']}</td>
  <td>
    <a class="author-name" href="{r['author_url']}" target="_blank">{esc_auth}</a>
    <div class="author-hl">{esc_hl}</div>
  </td>
  <td><span class="role-tag">{esc_role}</span></td>
  <td class="msg-cell">
    <div class="msg-text" id="msg-{r['num']}">{esc_msg}</div>
    <div class="msg-footer">
      <span class="char-count" style="color:{cc}">{r['chars']} chars</span>
      <button class="copy-btn" onclick="copyMsg({r['num']})">Copy</button>
      <a class="post-link" href="{r['post_url']}" target="_blank">View post ↗</a>
    </div>
  </td>
</tr>""")

page = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>LinkedIn Connection Messages</title>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>
*, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
body {{ font-family: 'Inter', sans-serif; background: #F0F4FA; color: #1A1A2E; padding: 32px 16px; }}
.header {{ max-width: 1100px; margin: 0 auto 24px; display: flex; justify-content: space-between; align-items: flex-end; }}
.header h1 {{ font-size: 20px; font-weight: 700; color: #0E2D5E; }}
.header p  {{ font-size: 12px; color: #9CA3AF; margin-top: 3px; }}
.meta {{ font-size: 12px; color: #6B7280; text-align: right; }}
.wrapper {{ max-width: 1100px; margin: 0 auto; background: white; border-radius: 12px; box-shadow: 0 1px 6px rgba(0,0,0,.08); overflow: hidden; }}
table {{ width: 100%; border-collapse: collapse; }}
thead tr {{ background: #0E2D5E; color: white; }}
thead th {{ padding: 12px 14px; font-size: 11px; font-weight: 600; letter-spacing: .06em; text-transform: uppercase; text-align: left; }}
tbody tr {{ border-bottom: 1px solid #EBF0F8; }}
tbody tr:last-child {{ border-bottom: none; }}
tbody tr:hover {{ background: #F7F9FC; }}
td {{ padding: 14px; vertical-align: top; font-size: 13px; }}
.num {{ color: #9CA3AF; font-size: 12px; width: 34px; text-align: center; }}
.author-name {{ font-weight: 600; color: #0E2D5E; text-decoration: none; font-size: 13px; }}
.author-name:hover {{ text-decoration: underline; }}
.author-hl {{ font-size: 11px; color: #6B7280; margin-top: 3px; max-width: 200px; line-height: 1.4; }}
.role-tag {{
  display: inline-block;
  font-size: 10px; font-weight: 600; letter-spacing: .04em;
  padding: 3px 9px; border-radius: 20px;
  background: #EBF0F8; color: #0E2D5E;
  white-space: nowrap;
}}
.msg-cell {{ min-width: 420px; }}
.msg-text {{
  font-size: 13px; line-height: 1.6; color: #374151;
  background: #F9FAFB; border: 1px solid #E5E7EB;
  border-radius: 6px; padding: 10px 12px;
  margin-bottom: 8px;
  white-space: pre-wrap; word-break: break-word;
}}
.msg-footer {{ display: flex; align-items: center; gap: 10px; }}
.char-count {{ font-size: 11px; font-weight: 600; }}
.copy-btn {{
  font-size: 11px; font-weight: 600;
  padding: 4px 12px; border-radius: 5px;
  background: #0E2D5E; color: white;
  border: none; cursor: pointer;
  transition: background .15s;
}}
.copy-btn:hover {{ background: #163d80; }}
.copy-btn.copied {{ background: #16a34a; }}
.post-link {{ font-size: 11px; color: #2563EB; text-decoration: none; }}
.post-link:hover {{ text-decoration: underline; }}
</style>
</head>
<body>
<div class="header">
  <div>
    <h1>LinkedIn Connection Messages</h1>
    <p>Personalized for 40 recent hiring posts — Growth · CRM · Head of Growth · India</p>
  </div>
  <div class="meta">{len(rows)} messages &nbsp;·&nbsp; {datetime.now().strftime("%d %b %Y")}</div>
</div>
<div class="wrapper">
<table>
  <thead>
    <tr>
      <th>#</th>
      <th>Author</th>
      <th>Role</th>
      <th>Connection Message (≤300 chars)</th>
    </tr>
  </thead>
  <tbody>
    {"".join(rows_html)}
  </tbody>
</table>
</div>
<script>
function copyMsg(id) {{
  const el = document.getElementById('msg-' + id);
  navigator.clipboard.writeText(el.innerText).then(() => {{
    const btn = el.parentElement.querySelector('.copy-btn');
    btn.textContent = 'Copied!';
    btn.classList.add('copied');
    setTimeout(() => {{ btn.textContent = 'Copy'; btn.classList.remove('copied'); }}, 1800);
  }});
}}
</script>
</body>
</html>"""

with open("linkedin_messages.html", "w") as f:
    f.write(page)

print(f"Done — {len(rows)} messages written to linkedin_messages.html")
for r in rows[:5]:
    print(f"\n#{r['num']} {r['author']} | {r['chars']} chars")
    print(f"  {r['message']}")
