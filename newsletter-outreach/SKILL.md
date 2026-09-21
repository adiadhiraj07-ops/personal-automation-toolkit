---
name: newsletter-outreach
description: A four-agent Claude Code pipeline for newsletter-style cold outreach. One agent finds leads, one verifies that each email address exists, one creates the newsletter in different types and designs, and one sends in small approved batches and monitors the inbox for bounces and replies. Use it to run the pipeline, or as a blueprint for splitting your own outreach workflow into agents.
---

# Newsletter Outreach Pipeline

A newsletter-style cold-outreach email (a personal, story-driven "issue" instead of a CV-attached form email) plus the whole pipeline around it: finding people, checking their addresses, building the email, and sending it safely.

The work is split across four specialized Claude Code subagents. Each owns one capacity and one set of files, so scope stays clean and each one carries its own hard-won gotchas without diluting the others.

## The four agents at a glance

| # | Capacity | What it does | What it never does |
|---|---|---|---|
| 1 | **Find leads** | Searches LinkedIn by role title, reads each person's current employer from their own headline, resolves a real mail domain, and adds candidate rows to the shared queue | Draft or send anything |
| 2 | **Verify the email exists** | Guesses address patterns and checks each one directly against the domain's mail server (SMTP `RCPT TO`), with no paid API | Send anything, or call an address "confirmed" when the evidence only supports "probably" |
| 3 | **Create the newsletter, in different types** | Builds and revises the email (shared issue, tailored one-off, alternate visual directions), previews it before any send, and researches new email-safe design ideas | Find leads or send |
| 4 | **Send and monitor the inbox** | Builds a small daily batch, gets approval, sends one recipient at a time, then reads the inbox for bounce notices and replies | Edit the content or find leads |

All four share one queue file, `recipients.csv`: who was found, whether their address checked out, who has been sent to, who bounced, who replied.

Agent files: `linkedin-lead-scraper-agent` (capacities 1 and 2), `newsletter-outreach-agent` and `newsletter-design-research-agent` (capacity 3), `outreach-sender-agent` (capacity 4).

## 1. Find leads

- Searches **role-first** ("VP Growth", "Head of CRM", talent acquisition titles), not company-first. People who chose a title for their own headline usually state their real employer right after `@` or `at`, so false positives are much lower than with company-constrained search.
- Works from any company, or from a named company list when you have one.
- Skips ex-employees, unrelated roles and agency recruiters instead of forcing them into a company.
- Resolves the company name to a mail domain and confirms it has an MX record before guessing anyone's address there.
- Every search goes through one shared guard: a hard daily cap, randomized pauses between searches, a cooldown, and a breaker that stops the run on a login or checkpoint redirect or after several empty searches in a row. Never route around it.
- Uses its own browser profile, never your everyday browser. While waiting for a login it only observes, and never navigates.
- Output: candidate rows in the queue. It does not draft or send.

## 2. Verify the email exists

- Guesses the likely patterns (`first.last@`, `first@`, `firstlast@`, ...) and probes the domain's mail server with `MAIL FROM` / `RCPT TO`. Nothing is sent; the server's answer says whether it would accept mail for that address.
- **Catch-all detection:** also probes a deliberately bogus address at the same domain. If that is accepted too, the real address is recorded as `catch-all (unverifiable)`, a best-effort guess rather than a "valid".
- **Blocked is not invalid:** some servers reject the connection outright when your IP is on a blocklist. That is a rejection of you, not proof the address is wrong, and it is reported separately.
- **Never stop at the first pattern that validates.** A naive first-valid-wins loop produced two real bounces: a transient block on the correct pattern let a worse guess win, and one server validated two different patterns so both looked fine. The fix retries the top pattern when blocked (not when rejected) and cross-checks. If two independent patterns validate, the row is marked `ambiguous` and held for manual confirmation.
- Tries alternate top-level domains and first-name-only patterns when a domain guess looks wrong.
- **A live domain can still be the wrong company.** Read the site title before trusting a catch-all row for a company whose name is a common word.
- Every row records why its address is trusted in `email_verification`.
- Also runs standalone for a quick check of one address or one name at a domain.
- **`valid` is not a delivery guarantee.** In one batch, bounces showed up at every confidence tier.

## 3. Create the newsletter, in different types

**Types of issue**

- **Shared issue** (default): one version for the whole queue. The content is the sender's own story, not recipient-specific, so no per-recipient tailoring is needed.
- **Tailored issue**: a one-off for a named priority target, with swapped screenshots and shifted emphasis.
- **Design directions**: the base look is a zine-style layout (thin hairline borders, sticker badges, a bordered pull-quote). The research agent has also explored four other directions that differ in palette, layout and type, not just a color swap: an editorial magazine, a brutalist stamp, a minimal founder letter, and a dark-mode-native poster.

**Content agent** (owns the one living template, never N copies)

- Drafts and revises the email, crops and redacts screenshots, and builds an inbox-style preview page before any send.
- Reviews real reply and bounce data every few days, and proposes a change only when there is evidence for it.
- Implements exactly the design direction you approved, and nothing more.

**Design research agent** (research only, never edits the template)

- **Concept exploration:** three or four genuinely distinct directions, compared side by side on one page.
- **Technique refinement:** a short, ranked brief of small changes, each checked against real email-client support (Gmail, Outlook, Apple Mail, mobile), because most web design does not survive an email client.
- Flags anything that depends on images, since cold-outreach recipients often have images blocked by default.

**Hard rules**

- Never fabricate a fact. Every metric, employer and date traces to a source document.
- Flag AI-generated or stock imagery before using it.
- Redact sensitive screenshots with an opaque box baked into the image, never a CSS overlay (it does not survive into the sent email).
- No filled color boxes for emphasis: Gmail's dark mode inverts solid fills into something worse than the light design. Use bold colored text or borders.
- Static only, no animated GIFs.
- Always preview before sending, every time.

## 4. Send and monitor the inbox

**Sending**

- A daily batch of 10 to 15, drawn from verified rows first. This protects the sending account's reputation.
- The batch skips anyone already sent to, bounced, replied, marked `ambiguous`, or held for later.
- **Daily digest approval:** the batch is shown, and nothing goes out until the owner says so in their own words in the live conversation.
- One recipient per send, never CC or BCC. Images are embedded inline, so no image hosting is needed.
- Optional per-recipient subject line without touching the template.
- A test copy goes to your own inbox whenever the template or subject pattern has changed since the last send.
- No automated follow-up sequence by default, and anyone who replied is never contacted again.
- Batches of about ten or more take long enough to run in the background.

**Monitoring the inbox**

- A read-only IMAP check runs before every batch. It looks for delivery-failure notices and for replies from anyone already contacted, then writes `BOUNCED` or `REPLIED` back to the queue.
- It never sends, deletes or modifies mail.
- Replies are flagged prominently. A reply is a live conversation for the owner to answer personally.

**Limits, stated plainly**

- The inbox check reads **INBOX only**, for bounces and replies. It does not look in the spam folder and does not measure inbox placement. A message that is filtered to spam or silently dropped shows up as neither a bounce nor a reply, so "no bounce, no reply" is not proof of delivery.
- The volume cap and one-recipient-per-send are the spam protection today.

## Rules that apply to every stage

1. **Sending to a real person always needs the owner's own go-ahead**, said in the live conversation. Never inferred, never relayed by another agent (an agent cannot verify a quoted approval), never a standing blanket authorization. Finding, verifying, reading the inbox and reporting need no approval, since none of it sends anything to a person.
2. **The queue is the source of truth.** Corrections are appended as new rows, so a bad guess stays as data.
3. **Stay inside the caps.** Do not raise a limit, delete its state file, or work around a refusal to get more volume.
4. **A docstring saying something was fixed is not proof it runs.** Test the failure case (for example, force two patterns to both validate and confirm `ambiguous` comes back).
5. **Keep secrets out.** Sending credentials live in a gitignored `.env`, and are never printed, logged or committed.

## What is published here

- Published: `send_newsletter_email.py`, `email-template.example.html`, `.env.example`, and this file.
- Not published yet: the lead-finding, verification and inbox-check code, and the agent definitions. They currently contain real contact data and a hardcoded sender identity. See the README.
