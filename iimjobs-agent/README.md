# iimjobs-agent/

Bulk auto-apply agent for IIMJobs.com -- sibling to `naukri-agent/`, sharing the
same profile/scoring/LLM logic via `../shared/job_apply_common.py`, but with a
structurally different apply flow (a full-page screening form, not a chat
modal). See `NOTES.md` for the full mechanics, the reliability bugs found and
fixed, and why they matter.

## Setup

```bash
pip install playwright
playwright install chromium
```

This agent depends on `../shared/job_apply_common.py` -- see `../shared/README.md`
for the local-Ollama and `profile.json` setup that must be done first (screening
answers won't work without it; the CLI scraping/scoring/filtering parts do).

## Usage

```bash
python3 iimjobs_login.py                      # one-time manual login, saves session
python3 iimjobs_auto_apply.py                 # dry run: scrapes, scores, shows what WOULD happen
python3 iimjobs_auto_apply.py --live          # actually applies to qualifying jobs
python3 iimjobs_auto_apply.py --pages 3
```

Dry-run is the default. `--live` is required to actually click Apply.

## Config

Edit the constants directly at the top of `iimjobs_auto_apply.py`
(`CATEGORY_SLUGS`, `EXPERIENCE_MIN`/`MAX`, `CTC_MIN_LPA`,
`APPLY_SCORE_THRESHOLD`, `MIN_APPLIES_TARGET`) for your own target roles and
thresholds. `.env.example` documents where the persistent logged-in browser
profile is stored.

## Verification

`python3 -m py_compile iimjobs_auto_apply.py iimjobs_login.py iimjobs_search.py`
all pass. The scraping/login/apply flows themselves can only be exercised
against a real, logged-in IIMJobs session and weren't run live during
sanitization -- this is documented as a limitation in the repo-root
`SANITIZATION_REPORT.md`.

`iimjobs_search.py` is an older, read-only, no-apply scraper kept only for
reference (its keyword-search URL is confirmed stale/broken -- see `NOTES.md`)
-- `iimjobs_auto_apply.py` is the actively maintained tool. Its originally
hardcoded, machine-specific browser-profile path has been fixed here to a
relative path.
