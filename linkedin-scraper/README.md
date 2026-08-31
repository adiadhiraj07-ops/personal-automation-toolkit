# linkedin-scraper/

Two tools for a LinkedIn-driven job search:

- **`linkedin_post_scraper.py`** -- scrapes LinkedIn posts for hiring signals
  matching your target role/domain/location, by connecting to your own Chrome
  via CDP (no API keys needed, just a logged-in LinkedIn session). Scores and
  ranks results, outputs a browsable HTML card view and a JSON file. See
  `SETUP.md` for detailed configuration and troubleshooting, `SKILL.md` for a
  short overview.
- **`gen_linkedin_messages.py`** -- companion script that takes the JSON output
  of the scraper (`linkedin_hiring_posts.json`) and drafts a personalized,
  300-char-limit connection-request message per post, with one-click-copy
  buttons in an HTML output.

## Setup

```bash
pip install -r requirements.txt
```

`linkedin_post_scraper.py` is close to a generic, ready-to-use tool -- edit the
labeled `SECTION 1-6` config blocks at the top with your own search queries,
role keywords, domain keywords, and target location (see `SETUP.md`).

`gen_linkedin_messages.py` reads your pitch bank from `pitches.json` (copy
`pitches.example.json` to `pitches.json` and write your own one-line pitches
per topic first -- the example file ships with obviously-placeholder company
names and numbers).

**Known schema mismatch (pre-existing, not fixed here):** the scraper's post
JSON uses field names like `authorName` / `headline` / `authorLink`, while
`gen_linkedin_messages.py` was written against a slightly different shape
(`authorHeadline`, `authorType`, `authorProfileUrl`). If you wire the two
together, reconcile the field names in `build_message()`/the row builder to
match whatever your actual `linkedin_hiring_posts.json` contains.

## Excluded from this repo

`linkedin_job_scraper.py` and `linkedin_playwright_scraper.py` (earlier,
superseded versions of the same scraping approach) are intentionally not
included here -- `linkedin_post_scraper.py` is the current, maintained tool
and duplicating the older iterations wouldn't add anything.

## Verification

`python3 -m py_compile linkedin_post_scraper.py gen_linkedin_messages.py` both
pass. Neither script was run against a live LinkedIn session during
sanitization -- that requires a real logged-in Chrome profile and is
documented as a limitation in the repo-root `SANITIZATION_REPORT.md`.
