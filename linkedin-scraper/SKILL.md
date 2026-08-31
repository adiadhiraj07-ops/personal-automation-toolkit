---
name: LinkedIn Hiring Post Scraper
description: Scrapes LinkedIn posts for hiring signals matching your target role, domain, and location. Uses your existing Chrome browser via CDP — no API keys needed. Outputs a ranked HTML card view and JSON file of relevant posts.
---

# LinkedIn Hiring Post Scraper

Searches LinkedIn for hiring posts that match your target role and location. Works by connecting to your own Chrome browser (with your logged-in LinkedIn session) via Chrome DevTools Protocol (CDP).

## What it does

- Runs a configurable list of search queries on LinkedIn
- Scrolls each results page to load more posts
- Extracts post text, author info, engagement, and embedded job cards
- Filters out noise (internships, congratulations posts, open-to-work posts, wrong location)
- Scores each post by role signal strength and profile keyword match
- Outputs a sorted HTML card view and a JSON file

## Setup

1. Install dependencies: `pip install -r requirements.txt`
2. Edit the CONFIG sections at the top of `linkedin_post_scraper.py`:
   - **SECTION 1**: Your LinkedIn search queries
   - **SECTION 2**: Role title phrases you are targeting
   - **SECTION 3**: Domain/profile match keywords
   - **SECTION 4**: Target location (or set to "" to disable)
3. Run: `python linkedin_post_scraper.py`
4. First run: Chrome will open LinkedIn so you can log in. After that, your session is saved.

## Files

- `linkedin_post_scraper.py` — main script
- `requirements.txt` — pip dependencies (`websockets`, `requests`)
- `SETUP.md` — detailed setup and troubleshooting guide

## Requirements

- Python 3.10+
- Google Chrome
- LinkedIn account
