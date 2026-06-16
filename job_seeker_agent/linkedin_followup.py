#!/usr/bin/env python3
"""
linkedin_followup.py — AI-Powered LinkedIn DM Outreach Agent

Flow:
  1. Reads `posts` table from jobs.db where connected_at IS NOT NULL
     (meaning a connection request was already sent by linkedin-connect.mjs)
     and followup_sent_at IS NULL (not yet followed up)
  2. Visits each poster's LinkedIn profile via Playwright
  3. Checks if "Message" button is visible → connection was accepted
  4. If accepted → calls Claude API to generate a personalised DM
  5. Sends the DM through LinkedIn's message modal
  6. Updates followup_sent_at and followup_status in the DB

Usage:
  python linkedin_followup.py                  # run normally
  python linkedin_followup.py --dry-run        # preview messages, no DMs sent
  python linkedin_followup.py --headed         # visible browser
  python linkedin_followup.py --limit 10       # cap how many DMs to send per run

Requirements:
  pip install playwright anthropic
  python -m playwright install chromium

Config:
  Edit the CONFIG section below with your credentials.
"""

import argparse
import json
import os
import sqlite3
import sys
import time
import random
from datetime import datetime
from pathlib import Path

import anthropic
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout

# Try loading from .env if python-dotenv is installed
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

def load_config_credentials() -> tuple[str, str]:
    """Parse linkedin-config.yml manually using regex to avoid external yaml dependency."""
    yml_path = Path(__file__).parent / "linkedin-config.yml"
    email, password = "", ""
    if not yml_path.exists():
        return email, password
    
    try:
        content = yml_path.read_text(encoding="utf-8")
        import re
        credentials_match = re.search(r"credentials:\s*\n(.*?)(?=\n\S|$)", content, re.DOTALL)
        if credentials_match:
            block = credentials_match.group(1)
            email_match = re.search(r"email:\s*[\"']?([^\"'\n]+)[\"']?", block)
            password_match = re.search(r"password:\s*[\"']?([^\"'\n]+)[\"']?", block)
            if email_match:
                email = email_match.group(1).strip()
            if password_match:
                password = password_match.group(1).strip()
    except Exception:
        pass
    return email, password

_yml_email, _yml_password = load_config_credentials()

# ─────────────────────────────────────────────────────────────────────────────
# CONFIG — edit these before running
# ─────────────────────────────────────────────────────────────────────────────

CONFIG = {
    # LinkedIn credentials (automatically reads from linkedin-config.yml with manual fallback)
    "li_email":    _yml_email or "your_linkedin_email@example.com",
    "li_password": _yml_password or "your_linkedin_password",

    # Claude API key — or set env var ANTHROPIC_API_KEY
    "anthropic_api_key": os.environ.get("ANTHROPIC_API_KEY", "your_claude_api_key"),

    # Your own profile info — used to personalise messages
    "sender_name":    "Vibudh Sharma",
    "sender_college": "IIT Bombay",      # shown in outreach messages
    "sender_role":    "Software Engineer", # e.g. "Software Engineer", "MBA Candidate"

    # Paths
    "db_path":      Path(__file__).parent / "jobs.db",
    "cookies_path": Path(__file__).parent / "linkedin-cookies.json",

    # Behaviour
    "delay_min_sec": 5,    # min delay between profiles
    "delay_max_sec": 10,   # max delay between profiles
    "max_msg_chars": 300,  # LinkedIn DM character limit
}

# ─────────────────────────────────────────────────────────────────────────────
# DATABASE
# ─────────────────────────────────────────────────────────────────────────────

def open_db(db_path: Path) -> sqlite3.Connection:
    """Open jobs.db and add followup tracking columns if they don't exist."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA foreign_keys = ON")

    # Add followup columns — silently ignored if already present
    for col, definition in [
        ("followup_sent_at",  "TEXT DEFAULT NULL"),
        ("followup_status",   "TEXT DEFAULT NULL"),
        ("followup_msg",      "TEXT DEFAULT NULL"),
    ]:
        try:
            conn.execute(f"ALTER TABLE posts ADD COLUMN {col} {definition}")
            conn.commit()
        except sqlite3.OperationalError:
            pass  # column already exists

    return conn


def load_pending(conn: sqlite3.Connection, limit: int) -> list[sqlite3.Row]:
    """
    Load posts where:
      - A connection request was sent (connected_at IS NOT NULL)
      - The connection was not already known to have failed
      - No follow-up has been sent yet
    Also fetches apply_url, apply_link, and status to determine message type.
    """
    return conn.execute("""
        SELECT id, poster_name, poster_url, title, company, location, post_text,
               COALESCE(apply_url, '') AS apply_url,
               COALESCE(apply_link, '') AS apply_link,
               status
        FROM   posts
        WHERE  connected_at     IS NOT NULL
        AND    connected_at     NOT LIKE '%:already_connected%'
        AND    connected_at     NOT LIKE '%:no_button%'
        AND    followup_sent_at IS NULL
        ORDER  BY connected_at ASC
        LIMIT  ?
    """, (limit,)).fetchall()


def mark_followup(conn: sqlite3.Connection, post_id: int, status: str, message: str = ""):
    """Record the followup result in the DB."""
    conn.execute("""
        UPDATE posts
        SET followup_sent_at = ?,
            followup_status  = ?,
            followup_msg     = ?
        WHERE id = ?
    """, (datetime.utcnow().isoformat(), status, message, post_id))
    conn.commit()


# ─────────────────────────────────────────────────────────────────────────────
# AI MESSAGE GENERATION
# ─────────────────────────────────────────────────────────────────────────────

def generate_message_template(
    poster_name: str, title: str, company: str,
    sender_name: str, sender_college: str, sender_role: str,
    has_apply_link: bool = False, is_applied: bool = False,
) -> str:
    """Fallback generator to build a high-quality human-like outreach message when no API key is set.

    Two conditions:
      1. has_apply_link=True  → message says "I saw your post and have applied / am applying"
      2. has_apply_link=False → message says "I saw your post and want to apply as I'm interested"
    """
    name_parts = (poster_name or "").split()
    first_name = name_parts[0].strip() if name_parts else "there"
    safe_title = (title or "").strip()
    safe_company = (company or "").strip()

    # ── Build the role mention fragment ─────────────────────────────────
    if safe_title and safe_company:
        role_fragment = f"the {safe_title} role at {safe_company}"
    elif safe_title:
        role_fragment = f"the {safe_title} role"
    elif safe_company:
        role_fragment = f"the role at {safe_company}"
    else:
        role_fragment = "the role"

    # ── Build the intent fragment based on condition ───────────────────
    if has_apply_link and is_applied:
        intent = (
            f"I saw your post about {role_fragment} and have already applied for it. "
            f"As a {sender_role} from {sender_college}, I'm very excited about this opportunity "
            f"and wanted to connect directly. Would love to briefly share my background or hear any advice you might have."
        )
    elif has_apply_link:
        intent = (
            f"I saw your post about {role_fragment} and am applying for it right away. "
            f"As a {sender_role} from {sender_college}, I'm genuinely interested and wanted to connect. "
            f"Would you be open to a quick chat about the role?"
        )
    else:
        # No apply link — ask how to apply
        intent = (
            f"I saw your post about {role_fragment} and I'm very interested in applying for it. "
            f"As a {sender_role} from {sender_college}, this role strongly aligns with my background. "
            f"Could you share the best way to apply or would it be okay if I send you my resume directly?"
        )

    return f"Hi {first_name},\n\nThanks for accepting my connection! {intent}\n\nBest regards,\n{sender_name}"

def generate_message(
    client: anthropic.Anthropic,
    poster_name: str,
    title: str,
    company: str,
    post_text: str,
    sender_name: str,
    sender_college: str,
    sender_role: str,
    max_chars: int,
    has_apply_link: bool = False,
    is_applied: bool = False,
) -> str:
    """Call Claude to generate a personalised LinkedIn DM.

    Two conditions drive the tone:
      1. has_apply_link=True  → mention that the sender has applied / is applying
      2. has_apply_link=False → express interest and ask how to apply
    """
    if client is None:
        # Fallback to templated message if Claude API client is not initialized
        return generate_message_template(
            poster_name, title, company,
            sender_name, sender_college, sender_role,
            has_apply_link=has_apply_link, is_applied=is_applied,
        )

    name_parts = (poster_name or "").split()
    first_name = name_parts[0].strip() if name_parts else "there"
    safe_title  = (title   or "the role")[:60]
    safe_company = (company or "your company")[:50]
    snippet = (post_text or "")[:400]

    # ── Condition-specific prompt instructions ─────────────────────────
    if has_apply_link and is_applied:
        condition_instructions = (
            f"- Mention that the sender has already applied for the {safe_title} role at {safe_company} "
            f"through the application link and wanted to connect directly as well\n"
            f"- Express genuine excitement about the opportunity\n"
            f"- End with a soft ask — e.g. any update on the process / a quick call / sharing more about their fit"
        )
    elif has_apply_link:
        condition_instructions = (
            f"- Mention that the sender is applying for the {safe_title} role at {safe_company} "
            f"and wanted to connect to express genuine interest\n"
            f"- End with a soft ask — e.g. any advice / a quick chat about the role"
        )
    else:
        condition_instructions = (
            f"- Mention that the sender saw their post about the {safe_title} role at {safe_company} "
            f"and wants to apply for it because they are very interested in the role\n"
            f"- Since there was no application link in the post, ask if they could share "
            f"the best way to apply or if they can send their resume directly\n"
            f"- End with a polite ask — e.g. sharing the application link / accepting a resume via DM"
        )

    prompt = f"""
You are writing a short, warm LinkedIn direct message on behalf of {sender_name},
a {sender_role} from {sender_college}.

They just got connected with {poster_name} ({first_name}), who posted about a
"{safe_title}" position at {safe_company}.

Here is a snippet of the original post for context:
\"\"\"{snippet}\"\"\"

Write a follow-up DM that:
- Opens with "Hi {first_name},"
- Thanks them for accepting the connection
{condition_instructions}
- Briefly states who the sender is ({sender_name}, {sender_role} from {sender_college})
- Sounds human, warm, NOT copy-paste generic
- Is STRICTLY under {max_chars} characters (count carefully)
- Has NO hashtags, NO emojis, NO bullet points — plain conversational text only

Output ONLY the message text. Nothing else.
""".strip()

    response = client.messages.create(
        model="claude-3-5-sonnet-20241022",
        max_tokens=400,
        messages=[{"role": "user", "content": prompt}],
    )

    message = response.content[0].text.strip()

    # Hard cap — truncate at last sentence boundary under max_chars
    if len(message) > max_chars:
        truncated = message[:max_chars]
        last_period = truncated.rfind(". ")
        if last_period > max_chars * 0.6:
            message = truncated[:last_period + 1]
        else:
            message = truncated.rstrip() + "…"

    return message


# ─────────────────────────────────────────────────────────────────────────────
# LINKEDIN SESSION
# ─────────────────────────────────────────────────────────────────────────────

def restore_or_login(page, context, email: str, password: str, cookies_path: Path):
    """Use saved cookies if valid, otherwise do a fresh login."""

    # Try saved cookies first
    if cookies_path.exists():
        try:
            cookies = json.loads(cookies_path.read_text())
            context.add_cookies(cookies)
            print("🍪 Restored saved session")

            page.goto("https://www.linkedin.com/feed/", wait_until="domcontentloaded", timeout=20000)
            page.wait_for_timeout(2000)

            if "/login" not in page.url and "/authwall" not in page.url:
                print("✅ Session still valid\n")
                return
            print("⚠️  Session expired — logging in fresh...")
        except Exception:
            pass

    # Fresh login
    print("🔐 Logging in to LinkedIn...")
    page.goto("https://www.linkedin.com/login", wait_until="domcontentloaded", timeout=30000)
    page.wait_for_timeout(1500)
    page.fill("#username", email)
    page.fill("#password", password)
    page.click('[data-litms-control-urn="login-submit"], button[type="submit"]')

    try:
        page.wait_for_url(
            lambda url: "/login" not in url and "/checkpoint/lg" not in url,
            timeout=20000,
        )
    except PlaywrightTimeout:
        pass  # 2FA — user must handle in headed mode

    page.wait_for_timeout(2000)

    if "/login" in page.url or "/checkpoint" in page.url:
        raise RuntimeError(
            "Login failed or 2FA required.\n"
            "  → Run with --headed so you can complete 2FA manually."
        )

    # Save cookies for next run
    fresh_cookies = context.cookies()
    cookies_path.write_text(json.dumps(fresh_cookies, indent=2))
    print("✅ Logged in — cookies saved\n")


# ─────────────────────────────────────────────────────────────────────────────
# SEND DM
# ─────────────────────────────────────────────────────────────────────────────

def send_dm(page, profile_url: str, message: str, dry_run: bool) -> str:
    """
    Visit a LinkedIn profile and send a DM if the Message button is visible.

    Returns one of:
      'sent'              — DM sent successfully
      'not_accepted'      — no Message button (connection not yet accepted)
      'already_messaged'  — conversation already exists (LinkedIn shows badge)
      'auth_wall'         — got redirected to login
      'error:<msg>'       — unexpected error
    """
    try:
        page.goto(profile_url, wait_until="domcontentloaded", timeout=25000)
        page.wait_for_timeout(3000)

        # Auth wall check
        if "/login" in page.url or "/authwall" in page.url:
            return "auth_wall"

        # ── Look for the Message button ──
        # LinkedIn shows this only when you're connected (1st degree)
        msg_selectors = [
            'button[aria-label*="Message"]',
            'button:has-text("Message")',
            'a[aria-label*="Message"]',
        ]

        msg_btn = None
        for sel in msg_selectors:
            candidate = page.locator(sel).first
            if candidate.count() > 0 and candidate.is_visible():
                label = candidate.get_attribute("aria-label") or ""
                text = candidate.text_content() or ""
                if "InMail" in label or "InMail" in text:
                    continue
                msg_btn = candidate
                break

        if not msg_btn or not msg_btn.is_visible():
            # Double-check — sometimes it's inside a More menu
            more_btn = page.locator('button[aria-label="More actions"]').first
            if more_btn.count() > 0 and more_btn.is_visible():
                try:
                    more_btn.click(timeout=2500)
                    page.wait_for_timeout(800)
                    candidate = page.locator('[role="menuitem"]:has-text("Message")').first
                    if candidate.count() > 0 and candidate.is_visible():
                        label = candidate.get_attribute("aria-label") or ""
                        text = candidate.text_content() or ""
                        if "InMail" not in label and "InMail" not in text:
                            msg_btn = candidate
                except Exception:
                    pass

        if not msg_btn or not msg_btn.is_visible():
            return "not_accepted"

        if dry_run:
            return "dry_run"

        # ── Click Message ──
        try:
            msg_btn.click(timeout=2500)
        except Exception as e:
            return f"error:message_button_click_failed:{str(e)[:50]}"
        page.wait_for_timeout(2000)

        # ── Find the message compose box ──
        compose_selectors = [
            'div[aria-label="Write a message…"]',
            'div[role="textbox"][aria-label*="message"]',
            '.msg-form__contenteditable',
            'div.msg-form__contenteditable',
        ]

        compose_box = None
        for sel in compose_selectors:
            candidate = page.locator(sel).first
            if candidate.count() > 0:
                compose_box = candidate
                break

        if not compose_box or compose_box.count() == 0:
            return "error:compose_box_not_found"

        # Type the message
        compose_box.click()
        page.wait_for_timeout(500)
        compose_box.fill(message)
        page.wait_for_timeout(1000)

        # ── Send ──
        send_selectors = [
            'button[aria-label="Send"]',
            'button.msg-form__send-button',
            'button:has-text("Send")',
        ]

        send_btn = None
        for sel in send_selectors:
            candidate = page.locator(sel).first
            if candidate.count() > 0:
                send_btn = candidate
                break

        if not send_btn or send_btn.count() == 0:
            return "error:send_button_not_found"

        send_btn.click()
        page.wait_for_timeout(1500)

        return "sent"

    except PlaywrightTimeout as e:
        return f"error:timeout:{str(e)[:60]}"
    except Exception as e:
        return f"error:{str(e)[:80]}"


# ─────────────────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────────────────

def parse_args():
    p = argparse.ArgumentParser(description="LinkedIn AI Follow-up DM Agent")
    p.add_argument("--dry-run", action="store_true", help="Preview messages — no DMs sent")
    p.add_argument("--headed",  action="store_true", help="Show browser window")
    p.add_argument("--limit",   type=int, default=15, help="Max DMs to send per run (default: 15)")
    return p.parse_args()


def main():
    # Force UTF-8 stdout encoding to prevent UnicodeEncodeError on Windows terminals
    if sys.stdout.encoding != 'utf-8':
        try:
            sys.stdout.reconfigure(encoding='utf-8')
        except Exception:
            pass

    args = parse_args()

    # ── Validate config ──
    if CONFIG["li_email"] == "your_linkedin_email@example.com":
        print("❌ Please set your LinkedIn credentials in the CONFIG section at the top of this file.")
        sys.exit(1)

    has_api_key = True
    if CONFIG["anthropic_api_key"] in ("your_claude_api_key", "", None):
        print("ℹ️  No Anthropic API Key provided. Follow-up messages will be generated using the built-in professional template.")
        has_api_key = False

    db_path = CONFIG["db_path"]
    if not db_path.exists():
        print(f"❌ Database not found: {db_path}")
        print("   Make sure jobs.db exists and linkedin-connect.mjs has been run first.")
        sys.exit(1)

    # ── Setup ──
    ai_client = anthropic.Anthropic(api_key=CONFIG["anthropic_api_key"]) if has_api_key else None
    conn = open_db(db_path)
    pending = load_pending(conn, args.limit)

    print("\n💬 LinkedIn DM Follow-up Agent")
    print("─" * 50)
    print(f"Pending follow-ups:  {len(pending)}")
    print(f"Limit per run:       {args.limit}")
    print(f"Mode:                {'🔍 DRY RUN (no messages sent)' if args.dry_run else '🚀 LIVE'}")
    if args.headed:
        print("Browser:             HEADED (visible)")
    print()

    if not pending:
        print("✅ No pending follow-ups — either no accepted connections yet, or all done.")
        conn.close()
        return

    # ── Stats ──
    stats = {
        "sent": 0,
        "not_accepted": 0,
        "dry_run": 0,
        "errors": 0,
        "auth_wall": 0,
    }

    # ── Launch Playwright ──
    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            headless=not args.headed,
            args=[
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-blink-features=AutomationControlled",
            ],
        )

        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1366, "height": 768},
            locale="en-US",
        )

        page = context.new_page()

        # Login
        try:
            restore_or_login(
                page, context,
                CONFIG["li_email"],
                CONFIG["li_password"],
                CONFIG["cookies_path"],
            )
        except RuntimeError as e:
            print(f"❌ {e}")
            browser.close()
            conn.close()
            sys.exit(1)

        # ── Process each person ──
        for i, post in enumerate(pending):
            name      = post["poster_name"] or "Unknown"
            short_name = name[:30].ljust(30)

            # Determine condition flags
            apply_url  = (post["apply_url"] or "").strip()
            apply_link = (post["apply_link"] or "").strip()
            has_apply_link = bool(apply_url or apply_link)
            is_applied = (post["status"] or "") == "applied"

            condition_label = (
                "applied" if has_apply_link and is_applied
                else "has_link" if has_apply_link
                else "no_link"
            )
            print(f"  [{i+1}/{len(pending)}] {short_name} [{condition_label}] → ", end="", flush=True)

            # 1. Generate AI message first (before visiting profile)
            try:
                message = generate_message(
                    client=ai_client,
                    poster_name=post["poster_name"],
                    title=post["title"],
                    company=post["company"],
                    post_text=post["post_text"],
                    sender_name=CONFIG["sender_name"],
                    sender_college=CONFIG["sender_college"],
                    sender_role=CONFIG["sender_role"],
                    max_chars=CONFIG["max_msg_chars"],
                    has_apply_link=has_apply_link,
                    is_applied=is_applied,
                )
            except Exception as e:
                print(f"❌ Claude API error: {str(e)[:60]}")
                stats["errors"] += 1
                continue

            # 2. Visit profile and send
            result = send_dm(page, post["poster_url"], message, dry_run=args.dry_run)

            if result == "sent":
                print("✅ DM sent")
                print(f"     └─ \"{message[:80]}{'...' if len(message) > 80 else ''}\"")
                mark_followup(conn, post["id"], "sent", message)
                stats["sent"] += 1

            elif result == "dry_run":
                print(f"🔍 [dry] Message preview:")
                print(f"     └─ \"{message[:120]}{'...' if len(message) > 120 else ''}\"")
                stats["dry_run"] += 1

            elif result == "not_accepted":
                print("⏳ Not accepted yet — skipping")
                stats["not_accepted"] += 1

            elif result == "auth_wall":
                print("⛔ Auth wall — session expired")
                print("\n  → Run with --headed to re-authenticate")
                browser.close()
                conn.close()
                sys.exit(1)

            else:
                print(f"❌ {result}")
                mark_followup(conn, post["id"], result)
                stats["errors"] += 1

            # Human-like delay between profiles
            if i < len(pending) - 1:
                delay = random.uniform(CONFIG["delay_min_sec"], CONFIG["delay_max_sec"])
                time.sleep(delay)

        browser.close()

    conn.close()

    # ── Summary ──
    print("\n" + "━" * 50)
    print("Follow-up Agent Summary")
    print("━" * 50)
    if args.dry_run:
        print(f"Previewed:           {stats['dry_run']} messages (nothing sent)")
    else:
        print(f"DMs sent:            {stats['sent']}")
        print(f"Not accepted yet:    {stats['not_accepted']}  (run again later)")
        print(f"Errors:              {stats['errors']}")
    print(f"Total processed:     {len(pending)}")
    print()
    if not args.dry_run and stats["sent"] > 0:
        print("✅ Done. Re-run anytime — already-messaged rows are skipped.")
    if stats["not_accepted"] > 0:
        print(f"ℹ️  {stats['not_accepted']} people haven't accepted yet. Run again in a few hours.")


if __name__ == "__main__":
    main()
