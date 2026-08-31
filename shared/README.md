# shared/

Common logic used by both `naukri-agent/` and `iimjobs-agent/`, extracted so a
fix in one place (scoring, screening-answer policy, profile facts) never
silently diverges between the two platforms.

## Files

- `job_apply_common.py` -- profile facts loading, deterministic answer
  overrides, the local-LLM (Ollama) calls, relevance scoring (`score_job()`,
  the positive-relevance gate), and the experience/CTC filters.
- `profile.example.json` -- placeholder shape for your own candidate profile.
  **Copy this to `profile.json` and fill in your real facts** before running
  either agent for real. `profile.json` is read first if present; the agents
  fall back to `profile.example.json` (obviously-fake placeholder content) so
  the dry-run mode still works out of the box without any setup.
- `.env.example` -- optional Ollama endpoint overrides.

## Setup

1. **Local LLM prerequisite**: both agents answer open-ended screening
   questions via a local Ollama server running `llama3.2:3b` (or a similarly
   small/fast model) at `http://localhost:11434`. This is a general-purpose
   dependency, not something built as part of this toolkit -- install Ollama
   separately (https://ollama.com), then `ollama pull llama3.2:3b` and make
   sure `ollama serve` is running before a live run. Override the endpoint/
   model via `OLLAMA_URL` / `OLLAMA_MODEL` env vars if needed (see
   `.env.example`).
2. **Your profile**: `cp profile.example.json profile.json`, then edit
   `profile.json` with your real experience, CV bullets, current/expected
   compensation, notice period, and location. This is what grounds every
   LLM-answered screening question -- see the `PROFILE_FACTS` docstring usage
   in `job_apply_common.py`.
3. `profile.json` is real personal data -- keep it out of version control
   (add it to `.gitignore` in your own fork; it is not tracked here).

## Design notes worth knowing before editing

- **Fabrication policy**: screening answers favor "maximize callbacks" over
  precision (lean affirmative on vague fit/willingness questions), but a small
  set of high-stakes question patterns (`DETERMINISTIC_OVERRIDES` -- e.g.
  "offer in hand?") are answered with a fixed, non-fabricating answer instead
  of going to the LLM at all. This exists because, in real use, a local LLM
  left to answer freely invented a fake competing offer with a specific
  company and salary figure on a real submitted application. If you find
  another question type where the LLM fabricates a specific checkable fact
  (a named employer, certification, or discoverable number), add it here as
  an override rather than trying to prompt-engineer the model out of it.
- **Positive relevance gate** (`has_positive_relevance()` / `has_hard_exclude()`):
  a flat base score alone is not enough for a job to qualify -- it must also
  show at least one genuine signal for the kind of role you're targeting (or
  it's forced to a score of 0 regardless of other bonus points). This was
  added after a real run auto-applied to a batch of completely unrelated
  roles that had cleared the score threshold on unrelated keyword matches
  alone. Tune `SCORE_RULES`, `POSITIVE_RELEVANCE_PATTERNS`,
  `GROWTH_ROLE_WORDS` / `MARKETING_QUALIFIER_WORDS`, and `HARD_EXCLUDE_PATTERNS`
  for your own target roles -- the defaults here are tuned for CRM/growth/
  lifecycle-marketing roles.
- **`run_with_timeout()`**: a hard per-job wall-clock timeout (SIGALRM-based,
  macOS/Unix only) so one hung job page can never stall an entire unattended
  daily run. Added after a real run hung 20+ minutes on a single job with no
  identifiable root cause.

## Verification

`python3 -m py_compile job_apply_common.py` passes (see
`SANITIZATION_REPORT.md` at the repo root). The Ollama-dependent functions
(`llm_pick_option`, `llm_number_answer`, `llm_free_text_answer`) can only be
exercised against a real, running local Ollama server -- that part is not
covered by static compilation and wasn't executed live during sanitization.
