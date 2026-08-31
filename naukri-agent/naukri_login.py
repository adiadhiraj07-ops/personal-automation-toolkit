#!/usr/bin/env python3
"""
One-time Naukri login — opens a persistent browser profile and waits for
you to log in manually. Session is saved to .naukri-profile/ so
naukri_auto_apply.py doesn't need to log in again.

USAGE:
    python3 naukri_login.py
"""

import os, time
from pathlib import Path
from playwright.sync_api import sync_playwright, TimeoutError as PwTimeout

PROFILE_DIR = os.environ.get("NAUKRI_PROFILE_DIR", str(Path(__file__).parent / ".naukri-profile"))


def logged_in(page) -> bool:
    try:
        html = page.inner_html("body").lower()
        url = page.url.lower()
        return (
            "logout" in html
            or "my naukri" in html
            or "mynaukri" in url
            or "homepage" in url
        )
    except Exception:
        return False


def main():
    print(f"Profile dir: {PROFILE_DIR}\n")
    with sync_playwright() as pw:
        context = pw.chromium.launch_persistent_context(
            user_data_dir=PROFILE_DIR,
            headless=False,
            args=["--disable-blink-features=AutomationControlled"],
            viewport={"width": 1440, "height": 900},
            locale="en-IN",
        )
        page = context.pages[0] if context.pages else context.new_page()
        page.goto("https://www.naukri.com/nlogin/login", wait_until="domcontentloaded", timeout=30000)

        if logged_in(page):
            print("Already logged in (existing session in profile).")
            context.close()
            return

        print("=" * 60)
        print("  Please log in to Naukri in the browser window.")
        print("  Waiting up to 180 seconds...")
        print("=" * 60)

        deadline = time.time() + 180
        while time.time() < deadline:
            if logged_in(page):
                print("\nLogin detected. Session saved to profile.")
                time.sleep(2)
                context.close()
                return
            time.sleep(2)

        print("\nTimed out waiting for login. Re-run this script to try again.")
        context.close()


if __name__ == "__main__":
    main()
