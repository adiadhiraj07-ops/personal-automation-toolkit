# Personal Automation Toolkit

A collection of personal automation tools built with Claude Code: bulk job-application
agents for two Indian job portals and a LinkedIn hiring-signal scraper.

Each subfolder is a self-contained tool with its own README. This is a
sanitized copy of real, actively-used personal tooling -- see
`SANITIZATION_REPORT.md` for exactly what was redacted/genericized and why.

## Contents

| Folder | What it does |
|---|---|
| `naukri-agent/` | Bulk auto-apply agent for Naukri.com -- scrape, score, filter, apply, handle the screening chatbot |
| `iimjobs-agent/` | Sibling auto-apply agent for IIMJobs.com -- same objective, structurally different apply flow |
| `shared/` | Common logic both agents depend on: candidate profile, local-LLM screening answers, relevance scoring |
| `linkedin-scraper/` | LinkedIn hiring-post scraper + a connection-message generator |

## A note on what's real vs. placeholder

- The **code and logic** throughout this repo is real, working automation --
  built, debugged, and run against live sites/services.
- **Personal data is not.** Candidate profile facts, pitch copy, phone
  numbers, and account credentials have all been moved to `*.example.*`
  config files with obviously-placeholder content (see each subfolder's
  README). Copy the relevant `.example` file, fill in your own facts, and the
  tools work the same way for you.
- **No real employer names appear anywhere in this repo.** Bug-report
  narratives that originally named specific companies (e.g. an external-ATS
  redirect encountered live) have been genericized to describe the technical
  pattern without identifying the employer.

## Requirements (vary by tool, see subfolder READMEs)

- Python 3.10+ with `playwright` (job-apply agents, LinkedIn scraper)
- A local Ollama server (job-apply agents' screening-question answers only --
  see `shared/README.md`)
