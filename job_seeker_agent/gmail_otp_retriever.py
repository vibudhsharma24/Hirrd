"""
gmail_otp_retriever.py — IMAP-based OTP / verification-code retriever.

Connects to Gmail via IMAP, polls for recent verification emails,
and extracts OTP codes using regex patterns.

Usage (standalone test):
    python gmail_otp_retriever.py --email user@gmail.com --password app_password

Requirements:
    Gmail "App Password" (not the normal account password).
    Enable IMAP in Gmail settings.
"""

import email
import imaplib
import os
import re
import sys
import time
from datetime import datetime, timezone, timedelta
from email.header import decode_header

# ── Config ────────────────────────────────────────────────────────────────────

IMAP_HOST = "imap.gmail.com"
IMAP_PORT = 993

# Keywords that identify a verification / OTP email
VERIFICATION_SUBJECTS = [
    "verification",
    "verify",
    "code",
    "otp",
    "passcode",
    "confirm",
    "one-time",
    "security code",
    "login code",
    "sign in",
    "access code",
    "authentication",
]

# Regex patterns for 4–8 digit/alpha OTP codes
OTP_PATTERNS = [
    r"\b(\d{4,8})\b",                    # pure digit codes  (e.g. 123456)
    r"(?:code|otp|passcode|pin)[:\s]+(\w{4,8})",  # labelled codes
    r"\b([A-Z0-9]{6})\b",                # 6-char alphanumeric (e.g. A3K9D2)
]

# ── Public API ────────────────────────────────────────────────────────────────


def fetch_latest_otp(
    email_user: str,
    email_pass: str,
    since_time: datetime | None = None,
    timeout_seconds: int = 120,
    poll_interval: int = 10,
) -> str | None:
    """Poll Gmail IMAP for the latest verification email and return the OTP code.

    Args:
        email_user:      Gmail address (e.g. user@gmail.com)
        email_pass:      Gmail App Password
        since_time:      Only consider emails received after this time.
                         Defaults to 2 minutes ago.
        timeout_seconds: How long to keep polling before giving up.
        poll_interval:   Seconds between poll attempts.

    Returns:
        The OTP/verification code string, or None if not found within timeout.
    """
    if since_time is None:
        since_time = datetime.now(timezone.utc) - timedelta(minutes=2)

    deadline = time.time() + timeout_seconds
    attempt = 0

    while time.time() < deadline:
        attempt += 1
        print(f"  [Gmail OTP] Poll attempt {attempt} ...")

        try:
            code = _scan_inbox(email_user, email_pass, since_time)
            if code:
                print(f"  [Gmail OTP] Found code: {code}")
                return code
        except Exception as e:
            print(f"  [Gmail OTP] Error scanning inbox: {e}")

        if time.time() + poll_interval < deadline:
            time.sleep(poll_interval)
        else:
            break

    print("  [Gmail OTP] Timeout — no verification code found")
    return None


async def handle_email_verification(session, gmail_user: str, gmail_pass: str) -> bool:
    """Detect and handle an email-verification wall on the current page.

    Args:
        session:    BrowserSession instance (from browser_manager.py)
        gmail_user: Gmail address
        gmail_pass: Gmail App Password

    Returns:
        True if verification was completed successfully, False otherwise.
    """
    if not gmail_user or not gmail_pass:
        print("  [Gmail OTP] No Gmail credentials provided — cannot handle verification")
        return False

    # Check if a verification input is visible on the page
    verification_selectors = [
        'input[name*="code"]',
        'input[name*="otp"]',
        'input[name*="verification"]',
        'input[name*="token"]',
        'input[aria-label*="verification"]',
        'input[aria-label*="code"]',
        'input[placeholder*="code"]',
        'input[placeholder*="verification"]',
        'input[placeholder*="OTP"]',
        'input[id*="code"]',
        'input[id*="otp"]',
        'input[id*="verify"]',
    ]

    code_input_sel = None
    for sel in verification_selectors:
        if await session.element_exists(sel):
            code_input_sel = sel
            break

    if not code_input_sel:
        return False  # No verification field detected

    print(f"  [Gmail OTP] Verification input detected: {code_input_sel}")

    # Record the time before we fetch, so we only look at emails received now
    since = datetime.now(timezone.utc) - timedelta(seconds=30)

    # Fetch the OTP
    code = fetch_latest_otp(gmail_user, gmail_pass, since_time=since, timeout_seconds=90)
    if not code:
        return False

    # Fill the code into the input
    try:
        await session.fill(code_input_sel, code)
        await session.wait(1000)

        # Click verify / submit / next button
        verify_buttons = [
            'button:has-text("Verify")',
            'button:has-text("Submit")',
            'button:has-text("Continue")',
            'button:has-text("Next")',
            'button:has-text("Confirm")',
            'button[type="submit"]',
            'input[type="submit"]',
        ]
        for btn_sel in verify_buttons:
            if await session.element_exists(btn_sel):
                await session.click(btn_sel)
                await session.wait(3000)
                print("  [Gmail OTP] Verification code submitted")
                return True

        # Fallback: press Enter
        page = await session.get_page()
        await page.keyboard.press("Enter")
        await session.wait(3000)
        print("  [Gmail OTP] Pressed Enter to submit verification code")
        return True

    except Exception as e:
        print(f"  [Gmail OTP] Error submitting verification code: {e}")
        return False


# ── Internal helpers ──────────────────────────────────────────────────────────


def _scan_inbox(email_user: str, email_pass: str, since: datetime) -> str | None:
    """Connect to Gmail IMAP and scan for recent verification emails."""
    mail = imaplib.IMAP4_SSL(IMAP_HOST, IMAP_PORT)
    try:
        mail.login(email_user, email_pass)
        mail.select("INBOX")

        # Search for recent unseen emails
        imap_date = since.strftime("%d-%b-%Y")
        status, msg_ids = mail.search(None, f'(SINCE "{imap_date}" UNSEEN)')

        if status != "OK" or not msg_ids[0]:
            # Also check ALL recent emails (some may be auto-read)
            status, msg_ids = mail.search(None, f'(SINCE "{imap_date}")')

        if status != "OK" or not msg_ids[0]:
            return None

        ids = msg_ids[0].split()
        # Process most recent first
        for msg_id in reversed(ids[-20:]):
            status, data = mail.fetch(msg_id, "(RFC822)")
            if status != "OK":
                continue

            msg = email.message_from_bytes(data[0][1])

            # Check date
            msg_date = _parse_email_date(msg)
            if msg_date and msg_date < since:
                continue

            # Check subject for verification keywords
            subject = _decode_subject(msg.get("Subject", ""))
            if not any(kw in subject.lower() for kw in VERIFICATION_SUBJECTS):
                continue

            # Extract body and search for OTP
            body = _get_email_body(msg)
            code = _extract_otp(body)
            if code:
                return code

        return None

    finally:
        try:
            mail.close()
            mail.logout()
        except Exception:
            pass


def _decode_subject(raw_subject: str) -> str:
    """Decode an email subject header."""
    if not raw_subject:
        return ""
    decoded_parts = decode_header(raw_subject)
    parts = []
    for part, charset in decoded_parts:
        if isinstance(part, bytes):
            parts.append(part.decode(charset or "utf-8", errors="replace"))
        else:
            parts.append(part)
    return " ".join(parts)


def _parse_email_date(msg) -> datetime | None:
    """Parse the Date header from an email message."""
    date_str = msg.get("Date", "")
    if not date_str:
        return None
    try:
        from email.utils import parsedate_to_datetime
        return parsedate_to_datetime(date_str)
    except Exception:
        return None


def _get_email_body(msg) -> str:
    """Extract the text body from an email message."""
    body_parts = []

    if msg.is_multipart():
        for part in msg.walk():
            content_type = part.get_content_type()
            if content_type == "text/plain":
                payload = part.get_payload(decode=True)
                if payload:
                    charset = part.get_content_charset() or "utf-8"
                    body_parts.append(payload.decode(charset, errors="replace"))
            elif content_type == "text/html" and not body_parts:
                payload = part.get_payload(decode=True)
                if payload:
                    charset = part.get_content_charset() or "utf-8"
                    html = payload.decode(charset, errors="replace")
                    # Strip HTML tags for simple extraction
                    body_parts.append(re.sub(r"<[^>]+>", " ", html))
    else:
        payload = msg.get_payload(decode=True)
        if payload:
            charset = msg.get_content_charset() or "utf-8"
            body_parts.append(payload.decode(charset, errors="replace"))

    return "\n".join(body_parts)


def _extract_otp(text: str) -> str | None:
    """Extract an OTP / verification code from email body text."""
    if not text:
        return None

    for pattern in OTP_PATTERNS:
        matches = re.findall(pattern, text, re.IGNORECASE)
        for m in matches:
            # Filter out common false positives
            if m.lower() in ("2024", "2025", "2026", "2027", "0000", "1234", "1111"):
                continue
            if len(m) >= 4:
                return m

    return None


# ── CLI test ──────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    p = argparse.ArgumentParser(description="Test Gmail OTP retrieval")
    p.add_argument("--email", required=True, help="Gmail address")
    p.add_argument("--password", required=True, help="Gmail App Password")
    p.add_argument("--timeout", type=int, default=60, help="Timeout in seconds")
    args = p.parse_args()

    code = fetch_latest_otp(
        email_user=args.email,
        email_pass=args.password,
        timeout_seconds=args.timeout,
    )
    if code:
        print(f"\n✅ Found OTP: {code}")
    else:
        print("\n❌ No OTP found")
