# naukri-agent/

Bulk auto-apply agent for Naukri.com: searches a configurable list of role
keywords, scores/filters results, and applies to qualifying jobs, walking
Naukri's own screening chatbot when one appears.

See `NOTES.md` for the full design rationale, the three confirmed apply paths,
and the incident history behind the current safety behaviors -- read it before
changing scoring, filtering, or apply logic.

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
python3 naukri_login.py                       # one-time manual login, saves session
python3 naukri_auto_apply.py                  # dry run: scrapes, scores, shows what WOULD happen
python3 naukri_auto_apply.py --live           # actually applies to qualifying jobs
python3 naukri_auto_apply.py --keyword "growth marketing manager"
python3 naukri_auto_apply.py --pages 2
```

Dry-run is the default. `--live` is required to actually click Apply.

## Config

Edit the constants directly at the top of `naukri_auto_apply.py`
(`TARGET_KEYWORDS`, `EXPERIENCE_MIN`/`MAX`, `CTC_MIN_LPA`,
`APPLY_SCORE_THRESHOLD`, `MIN_APPLIES_TARGET`) for your own target roles and
thresholds -- these are plain constants by design, not pulled from a config
file, so they're easy to read at a glance in one place.

`.env.example` documents the one thing that's genuinely environment-specific:
where the persistent logged-in browser profile is stored.

## Verification

`python3 -m py_compile naukri_auto_apply.py naukri_login.py naukri_search.py`
all pass. The scraping/login/apply flows themselves can only be exercised
against a real, logged-in Naukri session and weren't run live during
sanitization -- this is documented as a limitation in the repo-root
`SANITIZATION_REPORT.md`.

`naukri_search.py` is an older, read-only, no-apply scraper kept only for
reference (see `NOTES.md`) -- `naukri_auto_apply.py` is the actively
maintained tool.
