"""Send a newsletter-style HTML email via Gmail SMTP, embedding local images
as inline CID attachments -- no external image hosting required.

The HTML file references images with tokens like:
    <img src="{{IMAGE_URL: headshot.jpg}}">

This script finds every such token, looks for a same-named file in
--images-dir, rewrites the token to a `cid:` reference, and attaches the
file inline. Anything that isn't found raises a clear error instead of
silently sending a broken image.

Usage:
    python3 send_newsletter_email.py \\
        --html email-template.html \\
        --images-dir ./images \\
        --to someone@example.com \\
        --subject "Your subject line"

    # subject can be omitted if the HTML has a <title>; that's used instead.

Auth: reads GMAIL_SENDER and GMAIL_APP_PASSWORD from the environment (or a
local .env file next to this script -- see .env.example). Gmail requires an
App Password (not your normal password): enable 2-Step Verification, then
generate one at myaccount.google.com/apppasswords.
"""
import argparse
import mimetypes
import os
import re
import smtplib
import sys
from email.mime.image import MIMEImage
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

TOKEN_RE = re.compile(r"\{\{IMAGE_URL:\s*([^}]+?)\s*\}\}")
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))


def load_env(path):
    """Minimal .env loader (KEY=VALUE per line) -- no external dependency."""
    env = {}
    if not os.path.isfile(path):
        return env
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip()
    return env


def extract_subject(html):
    match = re.search(r"<title>(.*?)</title>", html, re.IGNORECASE | re.DOTALL)
    return match.group(1).strip() if match else None


def build_message(html_path, images_dir, to_addr, sender, subject):
    with open(html_path, encoding="utf-8") as f:
        html = f.read()

    subject = subject or extract_subject(html) or "Untitled"

    tokens = TOKEN_RE.findall(html)
    cid_map = {}
    for filename in tokens:
        cid = re.sub(r"[^a-zA-Z0-9]", "_", filename)
        cid_map[filename] = cid
        html = html.replace("{{IMAGE_URL: " + filename + "}}", f"cid:{cid}")
        # tolerate the token appearing without the internal space too
        html = html.replace("{{IMAGE_URL:" + filename + "}}", f"cid:{cid}")

    msg = MIMEMultipart("related")
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = to_addr
    msg.attach(MIMEText(html, "html", "utf-8"))

    for filename, cid in cid_map.items():
        path = os.path.join(images_dir, filename)
        if not os.path.isfile(path):
            raise FileNotFoundError(
                f"HTML references '{{{{IMAGE_URL: {filename}}}}}' but no file "
                f"named '{filename}' exists in {images_dir}"
            )
        mime_type, _ = mimetypes.guess_type(path)
        subtype = (mime_type or "image/png").split("/")[-1]
        with open(path, "rb") as img_f:
            img = MIMEImage(img_f.read(), _subtype=subtype)
        img.add_header("Content-ID", f"<{cid}>")
        img.add_header("Content-Disposition", "inline", filename=filename)
        msg.attach(img)

    return msg


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--html", required=True, help="Path to the HTML email template")
    parser.add_argument("--images-dir", required=True, help="Folder containing the images referenced by {{IMAGE_URL: ...}} tokens")
    parser.add_argument("--to", required=True, help="Recipient email address")
    parser.add_argument("--subject", default=None, help="Subject line (defaults to the HTML <title>)")
    args = parser.parse_args()

    env = {**os.environ, **load_env(os.path.join(SCRIPT_DIR, ".env"))}
    sender = env.get("GMAIL_SENDER")
    app_password = env.get("GMAIL_APP_PASSWORD")
    if not sender or not app_password:
        sys.exit("Missing GMAIL_SENDER / GMAIL_APP_PASSWORD. Copy .env.example to .env and fill it in.")

    msg = build_message(args.html, args.images_dir, args.to, sender, args.subject)

    with smtplib.SMTP("smtp.gmail.com", 587) as server:
        server.starttls()
        server.login(sender, app_password)
        server.sendmail(sender, [args.to], msg.as_string())

    print(f"Sent '{msg['Subject']}' to {args.to} from {sender}")


if __name__ == "__main__":
    main()
