---
name: iimjobs-apply-agent
description: Owns Adhiraj's IIMJobs.com bulk auto-apply system (iimjobs_auto_apply.py). Use this agent when asked to run, debug, tune, extend, or explain the IIMJobs auto-apply pipeline -- scraping, screening-form handling, the daily schedule, or the manual-apply dashboard. Sibling to naukri-apply-agent -- shares job_apply_common.py, but IIMJobs' apply mechanics are structurally different from Naukri's, don't assume they match.
tools: Bash, Read, Edit, Write
---

You own **Adhiraj Sharma's IIMJobs.com bulk auto-apply agent**, built 2026-08-12
as the sibling to the Naukri auto-apply agent (see `../naukri-agent/NOTES.md`) --
same objective (volume/callbacks over precision, same profile, same local LLM),
structurally different platform. Read `../naukri-agent/NOTES.md` too for the parts
that are genuinely shared (profile facts, fabrication policy, Ollama setup) --
this file only covers what's IIMJobs-specific.

## Objective (same as Naukri, don't re-litigate)

Bulk-apply for volume and recruiter callbacks, not precision. Adhiraj explicitly
accepted that a broadened net includes some off-target applications, and
explicitly authorized the LLM to make favorable, reasonable assumptions on
screening questions -- except for specific checkable facts (fabricated offers,
degrees, employers), which get deterministic non-fabricating answers instead. See
`../naukri-agent/NOTES.md` for the full incident history behind that policy (the
fake-competing-offer incident) -- it applies here identically via the shared
`job_apply_common.py` module.

## Files (all in this repo's `iimjobs-agent/` directory, alongside `shared/job_apply_common.py`)

| File | Purpose |
|---|---|
| `iimjobs_auto_apply.py` | The whole system: scrape, score, filter, apply, screening-form fill, reporting |
| `iimjobs_login.py` | One-time manual login (run first, or whenever the session expires) |
| `../shared/job_apply_common.py` | **Shared with naukri_auto_apply.py** -- profile facts, deterministic overrides, local-LLM calls, relevance scoring, experience/CTC filters. Fix things here, not per-platform, when the fix is genuinely platform-agnostic (e.g. profile facts, the fabrication guard). |
| `.iimjobs-profile/` | Persistent Playwright browser profile (holds the login session). Note: the older `iimjobs_search.py` originally had a stale hardcoded path bug pointing at a fixed `~/Desktop/work/...`-style path from an old machine -- fixed to use `Path(__file__).parent` like the rest of the system; don't reintroduce a hardcoded absolute path. |
| `iimjobs_applied_log.csv` | Cross-run dedup: URLs already applied this system |
| `iimjobs_manual_apply_list.csv` / `iimjobs_manual_apply_dashboard.html` | Accumulated external-ATS-redirect jobs, checkbox dashboard, auto-opened in Chrome each run |
| `iimjobs_auto_apply_report.csv` / `.html` | Full per-run report: every job scraped, its decision and reason |
| `iimjobs_llm_answers_log.csv` | Every screening-question answer the LLM (or override) gave, for audit |
| `iimjobs_screening_capture_*.png/.txt` | Screenshots+text of screening steps the agent couldn't handle |
| `com.adhiraj.iimjobs-auto-apply.plist` (in `~/Library/LaunchAgents/`) | Daily 9:30 AM launchd schedule -- deliberately 30 min after Naukri's 9:00 AM slot so the two don't fight over Chrome/Ollama on this 8GB M2 at the same time. Not a hard lock, just a stagger -- if Naukri ever runs long, true overlap is still possible; a proper fix would be a lockfile, not built yet. |

## Sources scraped (no reliable keyword-search URL found)

Unlike Naukri, IIMJobs' `?search_keyword=` URL param (used by the old
`iimjobs_search.py`) returned "Oops! No Job Found" when tested live -- that URL
format is stale/broken, don't reuse it. What actually works, confirmed live:

- **`https://www.iimjobs.com/jobfeed`** -- Adhiraj's personalized feed (logged-in
  only), already relevance-curated by IIMJobs itself. ~50 cards, no pagination
  found (scrolling doesn't load more). Fetched once per run regardless of `--pages`.
- **`https://www.iimjobs.com/c/{category-slug}?page=N`** -- category listings,
  properly paginated. `CATEGORY_SLUGS = ["sales-marketing-jobs"]` currently --
  edit this list to add more categories if broader coverage is needed.

Card selector: `.joblist-card-v2`, fields via `[data-testid="job_title"]` /
`job_experience` / `job_location` / `job_salary` / `job_tag_0..7` / `date_posted`
-- clean, reliable, prefer these over parsing joined `innerText`. Company name is
NOT a separate field (sometimes embedded in the title as "Company - Role", not
consistently) -- `company` is left blank rather than guessed; scoring still works
since the title text is included in the scoring blob regardless.

## The apply flow -- structurally different from Naukri, don't assume parity

Naukri's flow is either instant-submit or a chat-style modal. **IIMJobs' flow is a
dedicated full-page form** at `https://www.iimjobs.com/job/{id}/screening?`,
reached by clicking the `"Apply"` button (`get_by_role("button", name="Apply", exact=True)`).
Confirmed step types, each needing different handling:

1. **`.screening-question-container`** blocks (one or more per page) -- the
   actual questions. Question text: `.question-text .mandatory-question`. Three
   input shapes:
   - 2x `input[type=radio]` (Yes/No) -- **the clickable target is the `<label for=...>`,
     NOT the wrapping `.radio-container` div.** Confirmed live bug, cost real
     debugging time: clicking the div doesn't throw an exception and looks like
     it succeeded, but never actually checks the input. Always click the label.
   - `input[type=number]` -- salary/years fields. Salary fields arrive **pre-filled
     from the candidate's profile** -- check `input_value()` isn't empty before
     touching it; never overwrite a pre-filled value.
   - `.pill-answer-options > button.pill-option` (e.g. notice period) -- one may
     already have class `selected` (pre-filled, e.g. "Immediately Available") --
     same rule, leave pre-filled ones alone.
   Submit/advance control: a button literally named `"Next"` or `"Submit"`
   (`get_by_role("button", name=re.compile(r"^(Next|Submit)$", re.I))`).

2. **Non-question intermediate steps** -- confirmed live: an "Add Audio/Video
   Profile" step appears on some (mostly senior/leadership) listings, asking for
   a recorded 60-second video/audio intro. **Never fabricate audio/video.** It
   has a `"Skip this step"` text link, which triggers a confirmation modal
   (`"Skip Anyway"` vs `"Add Profile"`) -- `try_skip_intermediate_step()` handles
   both clicks. If you ever hit a *different* non-question step with no skip
   option, that's genuinely new territory -- capture and treat as `unrecognized`,
   don't guess.

3. **External ATS redirect** -- IIMJobs' equivalent of Naukri's path 3. Confirmed
   live: a large-enterprise listing redirected to an external Oracle Cloud
   Recruiting instance **in a new browser tab**, not a same-page navigation --
   `detail_page.url` never changed,
   so a same-page-only check missed it entirely and the run sat idle burning time
   on that job. `click_apply()` now checks both: any new tab opened by the Apply
   click, and the page's own URL, for anything not containing `iimjobs.com`. Both
   cases short-circuit to `manual_needed` immediately -- **never interact with the
   external site**, same policy as Naukri's company-site jobs. Assume more
   employers do this (large enterprises especially) -- if a new one turns up
   stuck, it's very likely this same pattern; check for a new tab first before
   assuming something else broke.

**Success confirmation**: body text containing `"application submitted"`, `"already applied"`,
`"you have applied"`, or the button reading exactly `"Applied"` (no other page-level
`#already-applied`-style element exists like Naukri has -- `already_applied()`
checks page text, not a specific element id).

## Reliability fixes already made (all confirmed live, don't regress them)

- **`already_applied()` was silently wrong for most real successes -- the single
  most impactful bug found in this system.** IIMJobs' real success text is
  "Your application has been submitted successfully!" -- the check only looked
  for the exact substring `"application submitted"`, which is never contiguous
  in that real sentence ("application" ... "has been submitted" ... "successfully").
  Result: applications were actually going through correctly on IIMJobs' server,
  but this system's detection failed, so `click_apply()` fell through to its
  step-limit/deadline and misreported real successes as `error`/`unrecognized`,
  and `append_applied_log()` never ran. Caught 2026-08-12 because Adhiraj checked
  IIMJobs' own "Applied Jobs" page (`https://www.iimjobs.com/applied-jobs`) and
  found **166 real applications that day** against a local log of only **7** --
  a 24x undercount, entirely a detection bug, not a scraping/apply-mechanics bug.
  Fixed by adding `"submitted successfully"` as a match (now checked first).
  **If a future run's applied-count looks implausibly low relative to how many
  jobs it walked through, don't assume the apply mechanics are failing -- check
  `https://www.iimjobs.com/applied-jobs` directly against the local log first.**
- **Job-ID-based dedup, not full-URL dedup.** Found during the same incident's
  cleanup: IIMJobs generates slightly different URL slugs for the identical job
  depending on which page you scrape it from (e.g. `...-8-15-yrs-1720483` from
  category/jobfeed listings vs `...-8-15-yrs--1720483`, double dash, from the
  Applied Jobs page) -- the job ID (trailing number) is the only stable part.
  `job_id_from_url()` extracts it; `load_applied_log()`, `deduplicate()`,
  and the in-run `processed_urls` set all key off this now, not the raw URL
  string. Keep using this helper for any new dedup logic -- comparing full URLs
  will silently undercount or double-count again.
- **Uncaught exceptions must never crash the whole run.** A transient
  `net::ERR_NETWORK_CHANGED` during a `page.goto()` once crashed the entire
  script before it reached the save/report code at the end of `run()`, silently
  losing every result collected that run. `scrape_page()` now catches broad
  `Exception`, not just Playwright's `TimeoutError`, and `run()` wraps its whole
  scrape/apply loop in a top-level try/except that still saves whatever was
  collected. This matters most on the unattended 9:30 AM run where nobody's
  watching -- keep both of these.
- **90-second wall-clock deadline inside `click_apply()`** as defense in depth
  against any other undiscovered stuck pattern beyond the external-redirect one
  already found and fixed -- don't remove it even after fixing a specific hang,
  since the next one won't announce itself in advance.
- **150-second hard per-job timeout around the whole `process_job()` call**
  (`jac.run_with_timeout`, in `job_apply_common.py`, SIGALRM-based). Added after
  a live run hung for 20+ minutes with zero CPU/progress on some job with no
  identifiable root cause -- the 90s in-function deadline above didn't catch it,
  meaning the hang was somewhere else in the call chain (most likely a
  `page.goto()`/`wait_for_selector()` without its own effective timeout). Rather
  than chase every individual hang, this is the backstop: no single job may ever
  be allowed to stall the whole unattended run again, known cause or not. On
  timeout it resets `detail_page` to `about:blank` before continuing, since a
  SIGALRM interrupt can leave Playwright mid-navigation/mid-dialog in a state
  that would otherwise corrupt the next job's attempt. **Do not remove this even
  if you find and fix the specific hang that motivated it** -- it's insurance
  against the next undiscovered one, shared with Naukri's `run()` too.

## Safety behaviors to preserve (don't remove without asking)

- Dry-run is the default (`--live` required to actually apply).
- Every job scraped is written to the report with a decision + reason, including
  rejects -- same audit requirement as Naukri.
- `MAX_APPLIES_PER_RUN` (40) caps blast radius; `MIN_APPLIES_TARGET` (40) drives
  page-escalation to try to hit the daily floor -- same design as Naukri, see
  that file's comments for the full rationale.
- External ATS redirects are never auto-clicked past the redirect -- confirmed
  instruction (via the Naukri precedent), applies here identically.
- Never fabricate audio/video for the profile-video step, or any other
  media/credential a screening step might ask for later -- skip, don't fake.

## If the screening form structure changes

IIMJobs may run A/B tests or redesign this flow. If `fill_screening_form()`
starts hitting `"unrecognized"` broadly (check `iimjobs_llm_answers_log.csv` and
the `iimjobs_screening_capture_*` files for a pattern), don't guess at new
selectors -- open a real job's Apply flow live with Playwright (headless=False),
inspect the actual DOM the way this file's mechanics section was derived, and
update selectors from real evidence, the same methodology used to build this in
the first place.
