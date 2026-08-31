# LinkedIn Hiring Post Scraper — Setup Guide

Scrapes LinkedIn posts for hiring signals matching your target role. Works by
connecting to your own Chrome browser via CDP, so no API keys are needed.

---

## Requirements

- Python 3.10 or higher
- Google Chrome installed
- A LinkedIn account

---

## Install

```bash
pip install -r requirements.txt
```

---

## Configure

Open `linkedin_post_scraper.py` and edit the sections at the top:

| Section | What to change |
|---|---|
| SECTION 1 | Your search queries |
| SECTION 2 | Role titles and domain keywords for your field |
| SECTION 3 | Domain/profile match keywords (for scoring) |
| SECTION 4 | Target location (or set to "" to disable) |
| SECTION 5 | Chrome profile directory path |

---

## First run (Chrome setup)

The script opens Chrome with a separate browser profile stored at
`~/linkedin-scraper-profile` (created automatically). The first time:

1. Chrome will open `linkedin.com`
2. Log in to your LinkedIn account
3. Close Chrome
4. Run the script again

From the second run onward, Chrome will use your saved session automatically.

---

## Run

```bash
python linkedin_post_scraper.py
```

Results are saved as:
- `linkedin_hiring_posts.html` (open this in your browser to browse results)
- `linkedin_hiring_posts.json` (raw data)

---

## Troubleshooting

**"No LinkedIn tab found"**: Chrome opened but you are not logged in. Open
`https://www.linkedin.com/feed/` in the Chrome window that the script launched,
log in, then rerun the script.

**"Google Chrome not found"**: Set the `CHROME_BIN` environment variable to the
full path of your Chrome executable, e.g.:
```bash
export CHROME_BIN="/path/to/chrome"
python linkedin_post_scraper.py
```

**Port 9222 in use**: Another Chrome instance may already be using that port.
Close all Chrome windows and try again.

**Very few results**: Try broadening your SEARCH_QUERIES or removing the
location filter (`TARGET_LOCATION = ""`).
