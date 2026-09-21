# Sanitization Report — personal-automation-toolkit

Generated as part of preparing this toolkit for a public GitHub portfolio
repo. Source directories (`/Users/anchalpuri/Downloads/work/` and
`~/Downloads/park-quiz/`) were only read from, never modified. Method followed
per file: copy in, grep (case-insensitive) for every pattern in
`SECRETS_CHECKLIST.md`, redact with a named placeholder + `.env.example`/
`*.example.*` config, re-grep to confirm zero hits, `py_compile`/`node --check`
the result, note what still needs live credentials to run for real.

## Files copied, and what was done to each

### naukri-agent/
- `naukri_auto_apply.py` — copied, no secrets found. Added `NAUKRI_PROFILE_DIR`
  env-var override (was already a portable relative path, just made it
  configurable) and a `sys.path` shim so `import job_apply_common` resolves
  to the new `../shared/` location.
- `naukri_login.py` — same `NAUKRI_PROFILE_DIR` env-var treatment.
- `naukri_search.py` — copied unchanged (already fully portable, no secrets).
- `NOTES.md` — from `.claude/agents/naukri-apply-agent.md`. Redacted: the
  absolute path header `/Users/anchalpuri/Downloads/work/` → generic
  "this repo's naukri-agent/ directory" description. Genericized: the specific
  company name in the fake-offer incident → "a real submitted application,
  2026-08-12". `PROFILE_FACTS` reference updated to point at
  `../shared/profile.json`/`profile.example.json` instead of describing the
  real CV facts inline.
- `.env.example` — new, documents `NAUKRI_PROFILE_DIR`.
- `README.md` — new, setup/usage/verification notes.

### iimjobs-agent/
- `iimjobs_auto_apply.py` — copied. Added `import os`/`import sys`,
  `IIMJOBS_PROFILE_DIR` env-var override, and the same `sys.path` shim for
  `../shared/`. **Update**: real employer names that appeared in code comments
  (an external-ATS redirect bug, and a volume-run results note) were initially
  left in place as documented bug examples, but were genericized on the user's
  explicit instruction — replaced with generic descriptors ("a large-enterprise
  listing", "large consulting/professional-services and enterprise firms")
  that preserve the technical narrative without naming real employers.
- `iimjobs_login.py` — same env-var treatment.
- `iimjobs_search.py` — **fixed a real stale-path bug**, not just redacted:
  `PROFILE_DIR = str(Path.home() / "Desktop/work/.iimjobs-profile")`
  (a machine-specific pattern matching the checklist's flagged old-machine
  path style) → `os.environ.get("IIMJOBS_PROFILE_DIR", str(Path(__file__).parent / ".iimjobs-profile"))`,
  matching the portable pattern already used everywhere else in the codebase
  (this exact bug is independently documented as already-identified-but-
  unfixed in `iimjobs-apply-agent.md`'s own text).
- `NOTES.md` — from `.claude/agents/iimjobs-apply-agent.md`. Same absolute-path
  header redaction as naukri's NOTES.md. Same company-name genericization as
  `iimjobs_auto_apply.py` above, applied here too.
- `.env.example` — new, documents `IIMJOBS_PROFILE_DIR`.
- `README.md` — new.

### shared/
- `job_apply_common.py` — the file with the most real personal data. Moved out
  of hardcoded constants into `profile.json`/`profile.example.json`, loaded at
  runtime via a new `_load_profile_config()`:
  - `PROFILE_FACTS` (the full real CV block: name, CARS24 employment history
    and metrics, education, current/expected CTC in Rs, notice period,
    Gurugram location) — moved out entirely, replaced with a placeholder
    "Jordan Example / Example Corp" version in `profile.example.json` with
    the same structure/fields.
  - `KNOWN_TOTAL_EXPERIENCE_YEARS` (real: 7) — moved to config (placeholder: 5).
  - `CURRENT_LOCATION_KEYWORDS` (real: gurugram/gurgaon/delhi/ncr/haryana) —
    moved to config (placeholder: generic city/metro/state strings).
  - Added `CANDIDATE_NAME` (from config) and replaced three hardcoded
    "Adhiraj Sharma" mentions inside the LLM system prompts with it.
  - `OLLAMA_URL` / `OLLAMA_MODEL` — made overridable via env vars (were
    hardcoded to localhost defaults, which aren't secrets, but now
    configurable per the task's ask).
  - A comment referencing the specific real "PGDM Great Lakes" fact was
    genericized to point at the config file instead.
  - **Verified functionally**: imported the module directly and ran
    `score_job()`, `experience_ok()`, `ctc_ok()`, `deterministic_override_answer()`,
    and `currently_based_in_answer()` against the placeholder config — all
    behave correctly (see Verification section).
- `profile.example.json` — new placeholder profile config.
- `.env.example` — new, documents `OLLAMA_URL`/`OLLAMA_MODEL`.
- `README.md` — new, setup steps, design notes, Ollama prerequisite note
  (per instructions, documented as a prerequisite, not built out as its own
  tool).

### linkedin-scraper/
- `linkedin_post_scraper.py` — copied unchanged. Grepped fully per the
  checklist: zero hits. Already written in generic second-person language
  with a management-consultant example config (not tied to the user's real
  CRM background) — confirmed publish-ready as claimed.
- `requirements.txt`, `SETUP.md`, `SKILL.md` — copied unchanged, no secrets.
- `gen_linkedin_messages.py` — real personal CV facts were hardcoded directly
  into the `PITCHES` message-template bank (CARS24, BajajFinserv, specific
  real metrics like "13Cr monthly touchpoints", "5Cr+ users", "30K → 1.5L/month").
  Extracted the entire `PITCHES` dict out to `pitches.json`/`pitches.example.json`
  (same load-with-fallback pattern as the shared profile config), replacing
  real employer names and metrics with "Example Corp"/"Prior Co" placeholders
  of the same shape.
- `pitches.example.json` — new placeholder pitch bank.
- `README.md` — new. Also documents a **pre-existing, not-introduced-by-this-
  pass schema mismatch**: the scraper's post JSON field names
  (`authorName`/`headline`/`authorLink`) don't match what
  `gen_linkedin_messages.py` expects (`authorHeadline`/`authorType`/
  `authorProfileUrl`) — flagged rather than silently "fixed" since that would
  be a functional change beyond sanitization scope.
- Excluded per instructions: `linkedin_job_scraper.py`,
  `linkedin_playwright_scraper.py` (superseded earlier versions) — noted in
  the README.

### whatsapp-summary/
- `daily_whatsapp_summary.py` — hardcoded personal phone number → `WHATSAPP_PHONE`
  env var (script now refuses to send, rather than silently using an empty
  string, if it's unset). Added `WA_SEND_SCRIPT` env var for the cross-repo
  `wa_send.py` dependency (documented, not duplicated, per instructions).
  **Also fixed a path bug this refactor would otherwise have introduced**:
  the original script assumed the Naukri/IIMJobs CSV logs lived next to it in
  the same flat folder; since this toolkit now splits those into
  `naukri-agent/`/`iimjobs-agent/` sibling folders, updated `FILES` to point
  at `../naukri-agent/...` / `../iimjobs-agent/...` so the tool still actually
  works against this repo's own layout.
- `.env.example` — new, documents `WHATSAPP_PHONE` and `WA_SEND_SCRIPT`.
- `README.md` — new, explains the cross-repo dependency clearly per
  instructions.

### park-quiz-show/
This folder needed the most substantive content sanitization (not just
credential redaction) — see Judgment Calls below for the full reasoning.
- `quiz_data.example.js` — new. 7 obviously-placeholder sample questions
  (capital-of-Mars-tier general knowledge, no real unaired content) in the
  exact same object shape as the real `quiz_data.js` (`q`/`a`/`bonus`/
  `bonusA`/`reveal`/`diff`/`live`). Real `quiz_data.js` was **not** copied.
- `episode.example.json` — new. Same shape as the real `episode.json`
  (number/title/prize/audience/location/format/shuffleSeed) but with a
  placeholder title ("Sample Episode") and location instead of the real
  episode's identifying details.
- `scripts/build_rounds.js` — the real file's `roundPlan` hardcoded ~40 text
  snippets identifying real, unaired Episode 1 questions across 3 groups + a
  grand final. Replaced with a small placeholder plan (1 group, 2 stages +
  a final) wired to `quiz_data.example.js`'s sample questions instead — code
  logic (the `pick()` snippet-matching, the loud-failure-on-mismatch
  behavior, all the docx-rendering code) is untouched.
- `scripts/build_master.js` — the real file's "§2 Suggested Running Order"
  (`runOrder`) hardcoded the full real running order **including answers**
  for all 3 groups + grand final (e.g. real trivia Q&A pairs with bonus
  facts). Replaced with a matching placeholder running order referencing the
  same example questions as `build_rounds.js`. All rendering/build code
  (title page, TOC, format-rules section, full category bank section)
  untouched.
- `scripts/build_flow.js`, `build_recheck.js`, `episode.js`, `new_episode.js`,
  `build_all.js` — copied unchanged. These are pure functions of whatever
  `quiz_data.js`/`episode.json` contain at build time — no real content
  hardcoded in the scripts themselves.
- `SKILL.md` — the most heavily rewritten file in this repo. The original
  weaves specific real Episode-1 questions and answers through its "house
  style" examples, guardrail illustrations, and lessons-log as teaching
  material — genuinely useful documentation, but also a direct spoiler
  channel for unaired content (confirmed by the file's own closing line:
  *"episode 1 is written but not yet filmed... leave it in place until after
  the shoot"*). Rewrote every section that cited a specific real fact/answer
  (§3's "template he loved" examples, the Gukesh/Kasparov and
  Aradhana/Pataudi "hidden thread" examples, the Netaji slogan's specific
  guardrail framing example, §6's 1971-surrender/Asim-Munir example, §7's
  entire lessons log: the WB-CM/Suvendu-Adhikari fact, the Chicken-Tikka-
  Masala/Glasgow fact, the Yuvraj-2007/Lewis-Hamilton facts, the "rizz"/
  "delulu" specific slang words, §5's actor-CM roundPlan-swap example, and
  §9's real-time "episode 1 is written but not yet filmed" status line) —
  replaced each with an abstracted description of the *pattern/lesson*
  (e.g. "a state's Chief Minister had changed shortly before the shoot")
  with zero real answer content, while leaving 100% of the actual
  methodology, golden rules, format rules, and guardrails intact. One
  low-risk mention ("these legends don't know what 'rizz' means" as a
  *tone* example under golden rule 4) was left as-is — it illustrates
  comedic framing, not a quiz answer.
- `package.json` — copied unchanged, no secrets (just `docx` dependency + npm
  scripts).
- `README.md` — adapted from the real toolkit's own README, with the
  Infosys-founder walkthrough example (which is itself a real, confirmed
  final-bank question — see Judgment Calls) replaced with the placeholder
  Mars question, and setup steps updated to `cp *.example.* → real filenames`.
- **Excluded per instructions**: the real `quiz_data.js`, `episode.json`,
  `episodes/` (archived past episodes), and `output/` (generated real
  episode docs) were never copied.
- **Verified functionally, not just compiled**: ran the full pipeline
  (`cp quiz_data.example.js quiz_data.js && cp episode.example.json
  episode.json && npm install && node scripts/build_all.js`) in an isolated
  scratch copy — all 4 documents built successfully and LibreOffice
  (present on this machine) converted all 4 to PDF with no errors. This
  confirms the placeholder data isn't just syntactically valid but produces
  a working, complete demo end-to-end. The test copy was deleted afterward;
  no `quiz_data.js`/`episode.json`/`output/` were left in the staged repo.

### newsletter-outreach/
Added 2026-09-09, built fresh for this repo rather than copied-and-redacted
from an existing script (the real working version lives in the CARS24
CleverTap toolkit's `about-me/` folder, not in any source directory this
report otherwise draws from).
- `send_newsletter_email.py` — written generic from the start: no hardcoded
  Desktop paths, no hardcoded recipient/sender, no hardcoded image filenames.
  Images are resolved by looking for a file matching each `{{IMAGE_URL: ...}}`
  token's literal filename inside a `--images-dir` the caller passes in.
  Auth (`GMAIL_SENDER`/`GMAIL_APP_PASSWORD`) comes from the environment or a
  local `.env` (gitignored).
- `email-template.example.html` — the real, personal, filled-in version (with
  the actual name, phone number, employer metrics, and photos) was **not**
  copied here. This is a from-scratch genericized version of the same design
  system (masthead, sticker badges, quick-facts list, unboxed stat strip,
  bordered pull-quote, per-role story sections, categorized toolkit) with
  every fact replaced by a bracketed placeholder (`[Your Name]`, `[XX%]`,
  `company-1-screenshot.png`, etc.).
- `.env.example`, `README.md` — new.
- Grepped the finished folder (case-insensitive) for the real name, real
  phone number, real email address, `Desktop`/`scratchpad` path fragments,
  and the Gmail App Password string — zero hits.
- **Update 2026-09-21:** added `SKILL.md` (a generic overview of the
  four-agent pipeline: find leads, verify emails, create the newsletter, send
  and monitor the inbox), rewrote the pipeline section of `README.md`, and
  updated this folder's row in the root `README.md`. Documentation only: no
  new code, and the lead-finding, verification and inbox-check code stays
  unpublished. Written generic from the start, describing each capacity by
  role. Swept the three edited files (case-insensitive) for the real name,
  personal email, phone number, employer names, machine paths, mail domains
  and company names from real incidents, and third-party newsletter names.
  The only hit is the pre-existing `someone@example.com` placeholder in the
  usage example. The sweep was validated with a positive control against a
  private file that does contain such data.

## Secret/PII patterns checked and redacted

| Pattern | Found in | Replaced with |
|---|---|---|
| Hardcoded personal phone number | `daily_whatsapp_summary.py` | `WHATSAPP_PHONE` env var |
| Real CV facts (name, CARS24 metrics, CTC, notice period, Gurugram location) | `job_apply_common.py` (`PROFILE_FACTS`, `KNOWN_TOTAL_EXPERIENCE_YEARS`, `CURRENT_LOCATION_KEYWORDS`) | `shared/profile.json` (gitignored) / `profile.example.json` (placeholder) |
| Same, in message-pitch form (CARS24, BajajFinserv, specific metrics) | `gen_linkedin_messages.py` (`PITCHES`) | `pitches.json` / `pitches.example.json` |
| Absolute machine path `/Users/anchalpuri/Downloads/work/` | both `NOTES.md` files | relative, repo-structure-based description |
| Stale old-machine-style absolute path (`~/Desktop/work/...`) | `iimjobs_search.py` | `Path(__file__).parent`-relative + env override |
| Real unaired quiz Q&A content (~40 snippets + running order with answers) | `build_rounds.js`, `build_master.js`, `SKILL.md` | placeholder examples matching `quiz_data.example.js` |
| Real episode title/location | `episode.json` | `episode.example.json` with placeholder title/location |
| Specific real applied-job company name in an incident anecdote | `naukri-apply-agent.md` (→ `NOTES.md`) | genericized to "a real submitted application" |
| Real name, phone number, employer metrics, and photos in the filled-in outreach email | (real version lives outside this repo, in the CleverTap toolkit's `about-me/`) | `newsletter-outreach/email-template.example.html` — bracketed placeholders throughout, written fresh rather than redacted from the real file |

No hits for any of the CleverTap/Gupshup/Snowflake account IDs, passcodes,
API keys, session-token patterns, or the colleague name from
`SECRETS_CHECKLIST.md` — none of those appear anywhere in this toolkit's
source files (they belong to the separate CARS24 CleverTap CRM toolkit, not
this one). No previously-unlisted secret-shaped strings (API-key patterns,
long tokens, credential pairs) were found during the final broad grep sweep.

## Verification results

- **Python**: `python3 -m py_compile` passed on all 10 `.py` files (see file
  list above) — zero syntax errors.
- **`shared/job_apply_common.py`**: also runtime-smoke-tested (not just
  compiled) by importing it directly and exercising `score_job()`,
  `experience_ok()`, `ctc_ok()`, `deterministic_override_answer()`, and
  `currently_based_in_answer()` against the placeholder `profile.example.json`
  — all returned correct results.
- **Cross-folder imports**: verified `naukri-agent/` and `iimjobs-agent/` can
  both resolve `import job_apply_common` via the new `sys.path` shim pointing
  at `../shared/`.
- **`daily_whatsapp_summary.py --dry-run`**: ran successfully against empty
  (non-existent) CSVs, printed a correctly-formatted zero-activity summary.
- **JavaScript**: `node --check` passed on all 8 `.js` files.
- **JSON**: all 4 `.json` files (`profile.example.json`, `pitches.example.json`,
  `episode.example.json`, `package.json`) parse successfully.
- **newsletter-outreach/send_newsletter_email.py**: `py_compile` passed;
  also runtime-smoke-tested by calling `build_message()` directly against
  `email-template.example.html` with 4 tiny placeholder images matching its
  `{{IMAGE_URL: ...}}` tokens — confirmed all tokens resolved to `cid:`
  references with no leftover unresolved tokens, all 4 images attached, and
  the subject correctly extracted from the HTML `<title>`. Did not exercise
  the actual SMTP send (`--to` path), since that requires live Gmail
  credentials.
- **park-quiz-show full pipeline**: `npm install && node scripts/build_all.js`
  ran end-to-end in an isolated scratch copy against the placeholder data —
  produced all 4 `.docx` files and (LibreOffice being available) all 4 `.pdf`
  conversions with no errors.

### Documented limitations (can't be verified without a live session/server)

- **naukri-agent/**, **iimjobs-agent/**: the actual scrape → score → apply →
  screening-question flow requires a real, logged-in Playwright browser
  session against the live site. Not exercised. The pure-Python logic
  (scoring, filters, LLM prompt construction) was verified in isolation via
  `shared/job_apply_common.py`'s smoke test above.
- **`shared/job_apply_common.py`**'s `llm_pick_option()` / `llm_number_answer()`
  / `llm_free_text_answer()`: require a real, running local Ollama server.
  Not exercised.
- **linkedin-scraper/**: both scripts require a real, logged-in Chrome/
  LinkedIn session via CDP. Not exercised.
- **whatsapp-summary/**: the actual send path requires the external
  `wa_send.py` dependency (in a different toolkit in this portfolio) and a
  live WhatsApp session. Only `--dry-run` (fully self-contained) was
  exercised.

## Judgment calls / ambiguous spots flagged for review

1. **Resolved**: all real employer names found across this repo (in the
   fake-competing-offer incident story, the external-ATS-redirect bug
   examples, and the volume-run results note) have been genericized on the
   user's explicit instruction, regardless of whether they were independently
   corroborated in the user's own memory files as previously-externalized
   examples. No real employer names remain in this repo's code or docs.
2. **`CARS24` in `naukri-agent/NOTES.md`'s YAML `description` field** — one
   remaining mention, in the sentence "Not for LinkedIn/IIMJobs... or for the
   CARS24 CleverTap CRM work (different project)." Left as-is: this is a
   scope-boundary reference to the user's *other* real portfolio repo (also
   being published, under its own name), not a leaked secret or PII. Flagging
   only because it's the one remaining literal "CARS24" string in this repo
   after the CV-facts extraction elsewhere.
3. **`episode.json`'s format numbers (9 players / 3 groups / ₹500 prize)** —
   kept these as realistic-looking placeholder values in
   `episode.example.json` rather than inventing different numbers, since
   they're show-format logistics, not quiz answers, and match what the
   (sanitized) README/SKILL.md already describe as the format. Only the
   title and location strings were changed to avoid tying the example file to
   the real unaired episode's identity.
4. **`park-quiz-show/scripts/build_rounds.js` and `build_master.js`** were
   *rewritten*, not just redacted-in-place, since the real content there was
   woven throughout (full running order with answers) rather than isolated to
   one clearly-removable block. I chose to make the replacement data actually
   match `quiz_data.example.js` and produce a genuinely working `npm run
   build` demo, rather than leaving inert/broken placeholder arrays — this
   was a design choice beyond the minimum redaction ask, flagging in case a
   lighter-touch placeholder (e.g. an empty `roundPlan` with a comment) was
   preferred instead.
5. **`gen_linkedin_messages.py`'s schema mismatch** with
   `linkedin_post_scraper.py`'s actual JSON output (see linkedin-scraper/
   section above) is a pre-existing bug in the source repo, documented but
   not fixed, since fixing it would be a functional change beyond this
   sanitization pass's scope.
6. **No `.gitignore` was added** anywhere in this staging tree (for
   `profile.json`, `pitches.json`, real `quiz_data.js`/`episode.json`, etc.) —
   each README tells the user to keep the real, filled-in versions out of
   version control, but no `.gitignore` file itself was created, since this
   is a staging copy rather than an initialized git repo (per the task's
   explicit "do NOT run git init" instruction). Worth adding when this repo
   is actually initialized for publishing.
