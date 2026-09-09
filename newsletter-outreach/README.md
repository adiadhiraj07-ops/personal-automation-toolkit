# newsletter-outreach

A newsletter-style cold-outreach email: personal story, real metrics, playful
zine-like design (thin hairline borders, sticker badges, a pull-quote, no
resume bullet dumps) instead of a CV-attached form email. Built after finding
the usual CV+cover-letter cold email offputting to send repeatedly.

`send_newsletter_email.py` sends the finished HTML via Gmail SMTP, embedding
every image as an inline CID attachment -- no image hosting service needed,
no broken images if a link rots later.

## How it works

The HTML template references images with a simple token:

```html
<img src="{{IMAGE_URL: headshot.jpg}}">
```

Put a file literally named `headshot.jpg` in your images folder, and the
script finds it, embeds it inline, and rewrites the token to a `cid:`
reference automatically. Any token without a matching file fails loudly
instead of shipping a broken image.

## Setup

```bash
cp .env.example .env
# edit .env with your Gmail address + an App Password (see .env.example)
```

Gmail blocks plain-password SMTP if 2-Step Verification is on (which it
should be) -- generate an App Password at
[myaccount.google.com/apppasswords](https://myaccount.google.com/apppasswords),
not your normal login password.

## Usage

```bash
python3 send_newsletter_email.py \
  --html email-template.example.html \
  --images-dir ./images \
  --to someone@example.com
```

- `--html` — path to your filled-in HTML file (copy `email-template.example.html`
  as a starting point and replace the bracketed placeholders with your own
  story, photos, and numbers).
- `--images-dir` — folder containing every image referenced by an
  `{{IMAGE_URL: ...}}` token in the HTML.
- `--to` — recipient address.
- `--subject` — optional; defaults to the HTML `<title>`.

## Design notes

- Table-based layout, all styles inlined -- renders correctly in Gmail and
  Outlook, not just a modern browser.
- No filled color boxes for the stat numbers or pull-quote -- Gmail's dark
  mode auto-inverts solid background fills in ways that often look worse
  than the light-mode design, so those are borders/dividers with colored
  text instead of background fills. `color-scheme: light` is also set to
  discourage clients from re-theming it at all.
- A small `@media (max-width:600px)` block reflows the masthead photo and
  headline for narrow screens rather than relying on the email client to
  scale the whole table uniformly (it usually doesn't, and fixed-width
  columns fight each other when it tries).

## What's a placeholder here

`email-template.example.html` ships with bracketed placeholder copy
(`[Your Name]`, `[XX%]`, etc.) and placeholder image filenames -- it's the
design system, not a real person's actual pitch. Swap in your own facts,
photos, and numbers before sending anything.
