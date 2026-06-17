#!/usr/bin/env python3
"""
apply_orchestrator.py — Main auto-apply engine for IITIIMJobAssistant.

Processes job posts from jobs.db and auto-applies using the appropriate
ATS adapter. Logs every submission with screenshots and routes failures
to the human follow-through queue.

Usage:
  python apply_orchestrator.py                    # apply for all active buyers
  python apply_orchestrator.py --dry-run          # preview, no submissions
  python apply_orchestrator.py --id 42            # single post by ID
  python apply_orchestrator.py --headed           # visible browser (local only)
  python apply_orchestrator.py --buyer-id 1       # specific buyer
  python apply_orchestrator.py --known-only       # skip unknown ATS
  python apply_orchestrator.py --limit 5          # max applications this run

Requirements:
  pip install playwright anthropic
  python -m playwright install chromium
  Optional: pip install hyperbrowser browser-use langchain-anthropic
"""

import argparse
import asyncio
import os
import sys
import time
import random
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

# Try loading .env
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# Add project root to path
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)
if os.path.dirname(__file__) not in sys.path:
    sys.path.insert(0, os.path.dirname(__file__))

import core.database as db
from ats_detector import detect_ats, detect_ats_with_browser, extract_hostname
from browser_manager import create_session, get_browser_mode
from resume_generator import get_resume_for_application, get_cover_letter
from adapters import get_adapter
from portal_memory import (
    get_portal_memory_for_url,
    save_portal_memory,
    build_memory_from_steps,
    append_applied_job,
    append_changelog,
    normalize_hostname,
)
from gmail_otp_retriever import handle_email_verification
from linkedin_posts_scraper import scrape_linkedin_posts
from connector import send_connection_requests


# ── Config ─────────────────────────────────────────────────────────────────────

# Negative keywords: skip posts whose title contains any of these
NEGATIVE_KEYWORDS = [
    "intern", "internship", "trainee", ".net", "ios", "android", "embedded", "firmware",
    "cobol", "mainframe", "php", "ruby",
]

DAILY_APPLY_LIMIT = 5  # Default per buyer per day
DELAY_MIN_SEC = 3      # Min delay between applications
DELAY_MAX_SEC = 8      # Max delay between applications


# ── Decision Rules ─────────────────────────────────────────────────────────────

def should_skip_post(post: dict, buyer_id: int) -> tuple[bool, str]:
    """Check if a post should be skipped based on decision rules.

    Returns (should_skip, reason).
    """
    title = (post.get("title") or "").lower()
    apply_link = (post.get("apply_link") or post.get("apply_url") or "").strip()

    # Note: posts without apply_link are handled as connection requests,
    # so we do NOT skip them here anymore.

    # Negative keywords in title
    for kw in NEGATIVE_KEYWORDS:
        if kw.lower() in title:
            return True, f"Title contains negative keyword: '{kw}'"

    # Already applied to this company recently
    company = (post.get("company") or "").strip()
    if company:
        recent_apps = db.get_all_applications(buyer_id=buyer_id, status="applied")
        for app in recent_apps[:50]:  # Check last 50
            if app.get("portal_hostname", "") and company.lower() in app.get("notes", "").lower():
                return True, f"Already applied to {company} recently"

    return False, ""


def check_daily_limit(buyer_id: int, limit: int = DAILY_APPLY_LIMIT) -> bool:
    """Check if the buyer has reached their daily application limit.

    Returns True if they can still apply (under limit).
    """
    count = db.count_today_applications(buyer_id)
    return count < limit


# ── Main Application Logic ────────────────────────────────────────────────────

async def apply_to_post(
    post: dict,
    buyer: dict,
    headed: bool = False,
    dry_run: bool = False,
    known_only: bool = False,
) -> dict:
    """Apply to a single post for a specific buyer.

    Returns a result dict with status and details.
    """
    post_id = post["id"]
    title = post.get("title", "Unknown")
    company = post.get("company", "Unknown")
    apply_link = (post.get("apply_link") or post.get("apply_url") or "").strip()
    buyer_id = buyer["id"]

    result = {
        "post_id": post_id,
        "title": title,
        "company": company,
        "status": "skipped",
        "reason": "",
    }

    # Decision rules
    should_skip, skip_reason = should_skip_post(post, buyer_id)
    if should_skip:
        result["reason"] = skip_reason
        db.update_post_status(post_id, "dismissed")
        return result

    # Daily limit check
    daily_limit = buyer.get("daily_apply_limit", DAILY_APPLY_LIMIT)
    if not check_daily_limit(buyer_id, daily_limit):
        result["reason"] = f"Daily limit reached ({daily_limit}/day)"
        return result

    # ATS Detection (Phase 1: URL only)
    ats_result = detect_ats(apply_link)
    hostname = ats_result.hostname

    if known_only and ats_result.ats_type == "custom":
        result["reason"] = f"Unknown ATS ({hostname}) — skipped (--known-only)"
        return result

    # Get resume
    try:
        resume_path = get_resume_for_application(buyer, post)
    except FileNotFoundError as e:
        result["reason"] = f"Resume not found: {e}"
        result["status"] = "error"
        return result

    # Dry run: just report what would happen
    if dry_run:
        # Also report portal memory status
        mem_hostname = normalize_hostname(apply_link)
        _, mem_content = get_portal_memory_for_url(apply_link)
        mem_status = f"memory={mem_hostname}" if mem_content else "no memory"
        result["status"] = "dry_run"
        result["reason"] = (
            f"Would apply via {ats_result.ats_type} ({hostname}) "
            f"with resume: {os.path.basename(resume_path)} [{mem_status}]"
        )
        return result

    # Create application record
    app_record = db.create_application(
        buyer_id=buyer_id,
        post_id=post_id,
        portal_hostname=hostname,
        ats_type=ats_result.ats_type,
        resume_used=resume_path,
        notes=f"company={company}",
    )
    app_id = app_record["id"]

    # Generate and store portal credential (password format: {Firstname}@123$, padded if needed)
    try:
        db.get_or_create_portal_credential(
            buyer_id=buyer_id,
            portal_hostname=hostname,
            firstname=buyer.get("name", "User"),
            email=buyer.get("email", ""),
            required_length=10
        )
    except Exception as e:
        print(f"Warning: could not generate/save portal credential: {e}")

    # Create browser session
    session = None
    try:
        session = await create_session(headed=headed)

        # Navigate and do Phase 2 ATS detection if needed
        await session.goto(apply_link, timeout=30000)
        await session.wait(2000)

        # Log the page load
        ss_initial = await session.screenshot(f"app_{app_id}_initial")
        db.add_submission_log(
            application_id=app_id,
            step_name="page_loaded",
            screenshot_path=ss_initial,
            page_url=await session.get_page_url(),
        )

        # Phase 2: DOM-based ATS detection for better accuracy
        page = await session.get_page()
        ats_result = await detect_ats_with_browser(page, apply_link)

        if known_only and ats_result.ats_type == "custom":
            db.update_application_status(app_id, "dismissed", notes="Unknown ATS skipped")
            result["reason"] = f"Unknown ATS ({hostname}) — skipped after DOM check"
            return result

        # Check for expired/404 pages
        page_text = await session.get_page_text()
        page_url = await session.get_page_url()
        if any(x in page_text.lower() for x in ["page not found", "404", "expired"]):
            db.update_application_status(app_id, "dismissed", notes="Expired/404 page")
            db.update_post_status(post_id, "dismissed")
            result["status"] = "dismissed"
            result["reason"] = "Job posting expired (404)"
            return result

        # Get the adapter
        adapter = get_adapter(ats_result.ats_type)

        # ── Portal Memory: Load cached knowledge ────────────────────────
        mem_hostname, portal_memory_content = get_portal_memory_for_url(apply_link)
        if portal_memory_content:
            print(f"  [Memory] Loaded {mem_hostname}.md ({len(portal_memory_content)} chars)")
            db.add_submission_log(
                app_id, "portal_memory_loaded",
                page_url=page_url,
                dom_snapshot=f"hostname={mem_hostname}, size={len(portal_memory_content)}",
            )

        # Check portal profile for cover letter requirement
        portal = db.get_portal_profile(hostname)
        cover_letter_mandatory = False
        if portal and portal.get("cover_letter") == "mandatory":
            cover_letter_mandatory = True

        cover_letter = get_cover_letter(buyer, post, mandatory=cover_letter_mandatory)
        if cover_letter:
            db.add_submission_log(app_id, "cover_letter_generated", page_url=page_url)

        # Build profile dict for the adapter
        profile = {
            "name": buyer.get("name", ""),
            "last_name": buyer.get("last_name", ""),
            "email": buyer.get("email", ""),
            "phone": "",  # Not stored in current schema
            "linkedin_url": "",
            "github_url": "",
            "current_company": "",
        }

        # Log the adapter selection
        db.add_submission_log(
            application_id=app_id,
            step_name=f"adapter_selected:{ats_result.ats_type}",
            page_url=page_url,
        )

        # Run the adapter — pass portal memory
        apply_result = await adapter.fill_and_submit(
            session=session,
            url=apply_link,
            profile=profile,
            resume_path=resume_path,
            cover_letter=cover_letter,
            portal_memory=portal_memory_content or "",
        )

        # Log the final result
        db.add_submission_log(
            application_id=app_id,
            step_name="submission_complete" if apply_result.success else "submission_failed",
            screenshot_path=apply_result.screenshot_path,
            dom_snapshot=apply_result.dom_snapshot[:5000] if apply_result.dom_snapshot else "",
            page_url=apply_result.page_url,
        )

        # Update application status
        if apply_result.success:
            db.update_application_status(
                app_id, "applied",
                confirmation_id=apply_result.confirmation_id,
                notes=f"company={company}, ats={ats_result.ats_type}",
            )
            db.update_post_status(post_id, "applied")
            db.increment_portal_success(hostname)

            # Upsert portal profile if it's a new portal
            if not portal:
                db.upsert_portal_profile(
                    hostname=hostname,
                    ats_type=ats_result.ats_type,
                    login_required=ats_result.requires_login,
                )

            # ── Portal Memory: Save learned steps ────────────────────────
            if not portal_memory_content and apply_result.recorded_steps:
                # First successful application — generate and save memory file
                memory_md = build_memory_from_steps(
                    hostname=mem_hostname or hostname,
                    ats_type=ats_result.ats_type,
                    login_required=ats_result.requires_login,
                    steps=apply_result.recorded_steps,
                )
                save_portal_memory(mem_hostname or hostname, memory_md)
                db.add_submission_log(
                    app_id, "portal_memory_saved",
                    page_url=apply_result.page_url,
                    dom_snapshot=f"hostname={mem_hostname or hostname}, steps={len(apply_result.recorded_steps)}",
                )
            elif portal_memory_content:
                # Memory existed — log that we used it successfully
                append_changelog(mem_hostname or hostname, f"Successful apply (post_id={post_id})")

            # Track applied job in memory file
            append_applied_job(
                mem_hostname or hostname, post_id, title, company, apply_link
            )

            result["status"] = "applied"
            result["reason"] = f"Successfully applied via {ats_result.ats_type}"

        else:
            db.update_application_status(
                app_id, apply_result.status,
                notes=apply_result.error_message,
            )
            db.increment_portal_failure(hostname)

            # Add to failure queue
            db.add_to_failure_queue(
                application_id=app_id,
                apply_url=apply_link,
                failure_reason=apply_result.error_message,
                failure_type=apply_result.failure_type,
                buyer_id=buyer_id,
                post_title=title,
                company=company,
            )

            result["status"] = "failed"
            result["reason"] = apply_result.error_message

    except Exception as e:
        # Catch-all error handling
        try:
            if session:
                ss = await session.screenshot(f"app_{app_id}_crash")
                db.add_submission_log(app_id, "crash", screenshot_path=ss)
        except Exception:
            pass

        db.update_application_status(app_id, "failed", notes=str(e)[:200])
        db.add_to_failure_queue(
            application_id=app_id,
            apply_url=apply_link,
            failure_reason=f"Unexpected error: {str(e)[:200]}",
            failure_type="unknown",
            buyer_id=buyer_id,
            post_title=title,
            company=company,
        )
        result["status"] = "error"
        result["reason"] = str(e)[:200]

    finally:
        if session:
            try:
                await session.close()
            except Exception:
                pass

    return result


# ── Main Loop ──────────────────────────────────────────────────────────────────

async def run_auto_apply(
    buyer_id: int | None = None,
    post_id: int | None = None,
    dry_run: bool = False,
    headed: bool = False,
    known_only: bool = False,
    limit: int = 5,
):
    """Main entry point for the auto-apply engine."""
    print("\n" + "=" * 60)
    print("  IITIIMJobAssistant — Auto-Apply Engine")
    print("=" * 60)
    print(f"  Mode:          {'🔍 DRY RUN' if dry_run else '🚀 LIVE'}")
    print(f"  Browser:       {get_browser_mode()}")
    print(f"  Known only:    {known_only}")
    print(f"  Max this run:  {limit}")
    if headed:
        print(f"  Browser mode:  HEADED (visible)")
    print()

    # Get active buyers
    if buyer_id:
        buyer = db.get_agent_buyer(buyer_id)
        if not buyer:
            print(f"❌ Buyer ID {buyer_id} not found")
            return
        if buyer.get("subscription_status") != "active":
            print(f"❌ Buyer ID {buyer_id} has inactive subscription")
            return
        buyers = [buyer]
    else:
        buyers = db.get_active_agent_buyers()

    if not buyers:
        print("❌ No active agent buyers found. Add one via the API first.")
        return

    # Get posts to process
    if post_id:
        posts = [p for p in db.get_all_posts() if p["id"] == post_id]
        if not posts:
            print(f"❌ Post ID {post_id} not found")
            return
    else:
        posts = db.get_all_posts(status="new")

    if not posts:
        print("✅ No new posts to process.")
        return

    # Filter posts that have apply_links
    posts_with_links = [p for p in posts if (p.get("apply_link") or p.get("apply_url") or "").strip()]
    print(f"  Posts found:     {len(posts)}")
    print(f"  With apply links: {len(posts_with_links)}")
    print()

    if not posts_with_links:
        print("✅ No posts with apply links to process.")
        return

    # Stats
    stats = {"applied": 0, "failed": 0, "skipped": 0, "dry_run": 0, "errors": 0}
    applied_count = 0

    for buyer in buyers:
        buyer_name = f"{buyer.get('name', '')} {buyer.get('last_name', '')}".strip()
        print(f"━━━ Processing for: {buyer_name} (ID: {buyer['id']}) ━━━")

        daily_limit = buyer.get("daily_apply_limit", DAILY_APPLY_LIMIT)
        today_count = db.count_today_applications(buyer["id"])
        remaining = min(daily_limit - today_count, limit - applied_count)

        if remaining <= 0:
            print(f"  ⏸  Daily limit reached ({today_count}/{daily_limit})")
            continue

        print(f"  Today: {today_count}/{daily_limit} applied, {remaining} remaining\n")

        for i, post in enumerate(posts_with_links):
            if applied_count >= limit:
                print(f"\n  ⏸  Run limit reached ({limit})")
                break
            if not check_daily_limit(buyer["id"], daily_limit):
                print(f"\n  ⏸  Daily limit reached for {buyer_name}")
                break

            title = (post.get("title") or "Untitled")[:40]
            company = (post.get("company") or "Unknown")[:20]
            print(f"  [{i+1}/{len(posts_with_links)}] {title} @ {company} ... ", end="", flush=True)

            result = await apply_to_post(
                post=post,
                buyer=buyer,
                headed=headed,
                dry_run=dry_run,
                known_only=known_only,
            )

            status = result["status"]
            reason = result.get("reason", "")

            if status == "applied":
                print(f"✅ Applied")
                stats["applied"] += 1
                applied_count += 1
            elif status == "dry_run":
                print(f"🔍 {reason}")
                stats["dry_run"] += 1
            elif status == "failed":
                print(f"❌ {reason[:60]}")
                stats["failed"] += 1
            elif status == "dismissed":
                print(f"🚫 {reason}")
                stats["skipped"] += 1
            elif status == "skipped":
                print(f"⏭  {reason}")
                stats["skipped"] += 1
            else:
                print(f"⚠️  {reason[:60]}")
                stats["errors"] += 1

            # Human-like delay between applications
            if not dry_run and i < len(posts_with_links) - 1:
                delay = random.uniform(DELAY_MIN_SEC, DELAY_MAX_SEC)
                await asyncio.sleep(delay)

    # Summary
    print("\n" + "━" * 60)
    print("  Auto-Apply Summary")
    print("━" * 60)
    if dry_run:
        print(f"  Previewed:    {stats['dry_run']} applications (nothing submitted)")
    else:
        print(f"  Applied:      {stats['applied']}")
        print(f"  Failed:       {stats['failed']}")
    print(f"  Skipped:      {stats['skipped']}")
    print(f"  Errors:       {stats['errors']}")
    print(f"  Total:        {sum(stats.values())}")

    if stats["failed"] > 0:
        print(f"\n  ℹ️  {stats['failed']} failed applications added to the failure queue.")
        print(f"     View them: GET /api/failure-queue")

    print()


# ── Full Pipeline ──────────────────────────────────────────────────────────────

async def run_full_pipeline(
    user_id: int,
    dry_run: bool = False,
    headed: bool = False,
    known_only: bool = False,
    limit: int = 5,
):
    """Run the complete Job Seeker Agent pipeline for a user.

    Steps:
      1. Scrape LinkedIn feed posts for jobs matching preferences
      2. For posts WITH apply links  → auto-apply (with OTP support)
      3. For posts WITHOUT apply links → send connection request to poster
      4. Update dashboard / logs
    """
    import json
    PROJECT_ROOT_LOCAL = str(Path(__file__).parent.parent)
    if PROJECT_ROOT_LOCAL not in sys.path:
        sys.path.insert(0, PROJECT_ROOT_LOCAL)
    from core.database import get_user, get_user_detail

    print("\n" + "=" * 60)
    print("  IITIIMJobAssistant — Full Pipeline")
    print("=" * 60)

    # ── Load user & credentials ────────────────────────────────────
    user = get_user(user_id)
    if not user:
        print(f"  ❌ User {user_id} not found")
        return

    user_detail = get_user_detail(user_id)
    buyer = (user_detail or {}).get("agent_buyer")
    if not buyer:
        print(f"  ❌ No agent buyer record for user {user_id}")
        return

    li_user = user.get("linkedin_username", "")
    li_pass = user.get("linkedin_password", "")
    gmail_user = user.get("gmail_username", "")
    gmail_pass = user.get("gmail_password", "")

    prefs_str = user.get("job_preferences", "{}")
    try:
        prefs = json.loads(prefs_str) if isinstance(prefs_str, str) else prefs_str
    except Exception:
        prefs = {}

    roles = prefs.get("roles", ["Software Engineer", "Product Manager"])
    locations = prefs.get("locations", ["India"])

    # ── Step 1: Scrape LinkedIn posts ──────────────────────────────
    print("\n━━━ Step 1: Scrape LinkedIn Feed Posts ━━━")
    new_posts = []
    if li_user and li_pass:
        try:
            new_posts = await scrape_linkedin_posts(
                user_id=user_id,
                linkedin_username=li_user,
                linkedin_password=li_pass,
                roles=roles,
                locations=locations,
                headed=headed,
            )
            print(f"  Discovered {len(new_posts)} new posts")
        except Exception as e:
            print(f"  ⚠️ Scraper error: {e}")
    else:
        print("  ⚠️ No LinkedIn credentials — skipping scrape")

    # ── Step 2 & 3: Process posts ─────────────────────────────────
    all_posts = db.get_all_posts(status="new")
    posts_with_links = [p for p in all_posts if (p.get("apply_link") or p.get("apply_url") or "").strip()]
    posts_without_links = [p for p in all_posts if not (p.get("apply_link") or p.get("apply_url") or "").strip()]

    print(f"\n  Total new posts: {len(all_posts)}")
    print(f"  With apply links: {len(posts_with_links)}")
    print(f"  Without apply links (connection requests): {len(posts_without_links)}")

    # ── Step 2: Auto-apply to posts with links ────────────────────
    if posts_with_links:
        print("\n━━━ Step 2: Auto-Apply to Job Posts ━━━")
        await run_auto_apply(
            buyer_id=buyer["id"],
            dry_run=dry_run,
            headed=headed,
            known_only=known_only,
            limit=limit,
        )

    # ── Step 3: Send connection requests for posts without links ──
    if posts_without_links and li_user and li_pass and not dry_run:
        print("\n━━━ Step 3: Send Connection Requests ━━━")
        poster_urls = []
        poster_map = {}  # url → post
        for p in posts_without_links[:limit]:
            poster_url = (p.get("poster_url") or "").strip()
            if poster_url and poster_url not in poster_map:
                poster_urls.append(poster_url)
                poster_map[poster_url] = p

        if poster_urls:
            buyer_name = f"{buyer.get('name', '')} {buyer.get('last_name', '')}".strip()
            msg = f"Hi! I noticed your post about a job opportunity. I'd love to connect and learn more. – {buyer_name}"

            try:
                results = await send_connection_requests(
                    linkedin_username=li_user,
                    linkedin_password=li_pass,
                    target_urls=poster_urls,
                    message_template=msg,
                    limit=min(len(poster_urls), 5),
                )
                for r in results:
                    url = r.get("url", "")
                    post = poster_map.get(url)
                    if post and r.get("status") == "sent":
                        db.update_post_status(post["id"], "pending")
                        # Create an application record for tracking
                        db.create_application(
                            buyer_id=buyer["id"],
                            post_id=post["id"],
                            portal_hostname="linkedin.com",
                            ats_type="connection_request",
                            resume_used="",
                            notes=f"Connection request sent to {post.get('poster_name', '')}",
                        )
                        db.update_application_status(
                            db.get_all_applications(buyer_id=buyer["id"])[-1]["id"],
                            "pending",
                            notes="connection_request_sent",
                        )
                        poster_nm = post.get('poster_name', '') or url[:40]
                        print(f"  ✅ Connection request sent → {poster_nm}")
                    elif post:
                        print(f"  ⏭  {r.get('status', 'error')}: {url[:50]}")
            except Exception as e:
                print(f"  ⚠️ Connection requests error: {e}")
        else:
            print("  No poster URLs to connect with")
    elif posts_without_links and dry_run:
        print(f"\n━━━ Step 3: [DRY RUN] Would send {len(posts_without_links)} connection requests ━━━")

    print("\n━━━ Pipeline Complete ━━━\n")


# ── CLI ────────────────────────────────────────────────────────────────────────

def parse_args():
    p = argparse.ArgumentParser(description="IITIIMJobAssistant Auto-Apply Engine")
    p.add_argument("--dry-run", action="store_true", help="Preview — no submissions")
    p.add_argument("--headed", action="store_true", help="Show browser (local mode only)")
    p.add_argument("--id", type=int, default=None, help="Apply to a single post ID")
    p.add_argument("--buyer-id", type=int, default=None, help="Specific buyer ID")
    p.add_argument("--known-only", action="store_true", help="Skip unknown ATS")
    p.add_argument("--limit", type=int, default=5, help="Max applications this run (default: 5)")
    return p.parse_args()


def main():
    # Force UTF-8 stdout on Windows
    if sys.stdout.encoding != "utf-8":
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass

    args = parse_args()

    # Ensure DB is initialized
    db.init_db()
    db.init_posts_table()

    asyncio.run(
        run_auto_apply(
            buyer_id=args.buyer_id,
            post_id=args.id,
            dry_run=args.dry_run,
            headed=args.headed,
            known_only=args.known_only,
            limit=args.limit,
        )
    )


if __name__ == "__main__":
    main()
