"""
test_harness.py
───────────────
Interactive CLI tool to verify LinkedIn login and session persistence.
"""

import asyncio
import os
import sys
from datetime import datetime
from playwright.async_api import async_playwright

# Force UTF-8 encoding on Windows consoles to prevent UnicodeEncodeError with emojis/non-ASCII characters
if sys.platform.startswith("win"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

# Ensure project root is in sys.path
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from linkedin_jobs_agent.session_manager import (
    load_session,
    save_session,
    is_session_valid,
    login_linkedin,
    _get_cookies_path
)


def print_banner(text):
    print("=" * 60)
    print(f" {text}")
    print("=" * 60)


async def run_harness():
    print_banner("LinkedIn AI Agent - Session Handling Test Harness")
    
    # Ask for credentials with pre-filled defaults provided by the user
    print("Please enter your LinkedIn credentials to begin.")
    default_email = "mkixtech@gmail.com"
    username = input(f"LinkedIn Email/Username [{default_email}]: ").strip()
    if not username:
        username = default_email
        
    default_password = "@Mkix123#"
    password = input("LinkedIn Password [Press Enter to use default test password]: ").strip()
    if not password:
        password = default_password
        
    print("\n[System] Credentials received. Initializing browser...")
    
    TEST_USER_ID = 9999  # Mock user ID for testing
    cookies_path = _get_cookies_path(TEST_USER_ID)
    
    async with async_playwright() as p:
        # Launch headed browser so user can see it and solve captcha/checkpoint if needed
        browser = await p.chromium.launch(
            headless=False,
            args=[
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-blink-features=AutomationControlled",
            ]
        )
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 800},
            locale="en-US"
        )
        # Stealth helper
        await context.add_init_script("Object.defineProperty(navigator, 'webdriver', { get: () => undefined });")
        page = await context.new_page()
        
        # Check if encrypted session cookies exist
        session_exists = os.path.exists(cookies_path)
        session_loaded_and_valid = False
        
        if session_exists:
            print("\n[System] Found existing encrypted session on disk. Attempting to restore...")
            cookies = load_session(TEST_USER_ID)
            if cookies:
                await context.add_cookies(cookies)
                # Verify validity
                valid = await is_session_valid(page)
                if valid:
                    print("[OK] Session successfully restored and is VALID. Already logged in!")
                    session_loaded_and_valid = True
                else:
                    print("\n" + "!" * 50)
                    print("[WARNING] ALERT: LinkedIn Session has EXPIRED or been INVALIDATED!")
                    print("!" * 50 + "\n")
                    print("Prompting for re-authentication...")
            else:
                print("[WARNING] Failed to decrypt or load existing session.")
        else:
            print("\n[System] No existing session found on disk. Proceeding with fresh login...")
            
        if not session_loaded_and_valid:
            print("\n[System] Attempting login with credentials provided...")
            res = await login_linkedin(page, username, password)
            
            if res["success"]:
                print("[OK] Logged in successfully!")
            else:
                print(f"[WARNING] Automated login did not complete: {res['reason']} ({res['message']})")
                if res["reason"] in ("challenge_required", "unknown_state"):
                    print("\n" + "=" * 60)
                    print("[ACTION] REQUIRED: Solve any CAPTCHA or enter the verification code in the browser window.")
                    print("The harness will monitor the browser window and automatically save your session once done.")
                    print("=" * 60 + "\n")
                    
                    # Wait loop monitoring for successful redirect
                    login_detected = False
                    for seconds in range(120):
                        url = page.url
                        # If we have reached feed or successfully logged in
                        if "feed" in url:
                            # Let's also make sure we are not stuck on the verification page
                            if "checkpoint" not in url and "challenge" not in url:
                                print(f"\n[OK] Logged in successfully! (Detected page redirect after {seconds}s)")
                                login_detected = True
                                break
                        
                        # Print dot every second to show waiting
                        print(".", end="", flush=True)
                        await page.wait_for_timeout(1000)
                        
                    if not login_detected:
                        print("\n[ERROR] Login timeout reached or failed. Exiting.")
                        await browser.close()
                        return
                else:
                    print("[ERROR] Login failed. Please check credentials. Exiting.")
                    await browser.close()
                    return
            
            # Save the new cookies securely
            print("\n[System] Exporting cookies and encrypting session at rest...")
            fresh_cookies = await context.cookies()
            save_session(TEST_USER_ID, fresh_cookies)
            
        # Close the current session browser
        await browser.close()
        print("\n[System] Browser closed. Encrypted session saved successfully.")

    # Verify session persistence in a fresh context
    print("\n" + "=" * 60)
    print(" VERIFYING PERSISTENCE IN A FRESH BROWSER WINDOW")
    print("=" * 60)
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=False,
            args=[
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-blink-features=AutomationControlled",
            ]
        )
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 800}
        )
        page = await context.new_page()
        
        print("[Verify] Loading encrypted session cookies from file...")
        saved_cookies = load_session(TEST_USER_ID)
        if not saved_cookies:
            print("[ERROR] Failure: Encrypted cookies could not be loaded or decrypted!")
            await browser.close()
            return
            
        await context.add_cookies(saved_cookies)
        print("[Verify] Restored cookies into context. Navigating to feed to check validity...")
        
        valid = await is_session_valid(page)
        if valid:
            print("\n[OK] SUCCESS: Persistent session is VALID in a fresh browser session without entering passwords!")
            print("[SECURE] Rested cookies file is encrypted. Verify this by viewing the raw file contents.")
            print(f"   Path: {cookies_path}\n")
            
            # Close the current verification page and browser to let the search query run cleanly
            await browser.close()
            
            # --- START OF JOB SEARCH VERIFICATION ---
            print("\n" + "=" * 60)
            print(" TESTING LINKEDIN JOB SEARCH COMPONENT")
            print("=" * 60)
            
            # Let's save mock data to DB for the test user
            from core import database as db
            db.init_db()
            
            # Ensure CV and preferences exist for user 9999
            mock_cv = {
                "personal": {
                    "name": "Test User",
                    "email": "mkixtech@gmail.com",
                    "headline": "Python Developer | Software Engineer"
                },
                "experience": [
                    {
                        "role": "Python Developer",
                        "company": "Tech Corp",
                        "start_date": "2023-01",
                        "end_date": "present",
                        "description": "Developing web services with Python and Flask."
                    }
                ],
                "skills": ["Python", "Flask", "SQL", "Playwright"]
            }
            db.save_master_cv(TEST_USER_ID, mock_cv)
            
            mock_prefs = {
                "roles": ["Software Engineer", "Software Developer"],
                "locations": ["India"],
                "experience": 2
            }
            db.update_user_linkedin_preferences(TEST_USER_ID, mock_prefs)
            print("[Verify] Injected mock CV and preferences for user 9999 (Software Engineer / Developer in India).")
            
            # Direct unit test of outreach resolver
            print("\n[Verify] Running direct unit test of Outreach Resolver...")
            from linkedin_jobs_agent.outreach_resolver import resolve_outreach_status
            mock_job_recruiter = {
                "poster_name": "Jane Doe",
                "poster_url": "https://www.linkedin.com/in/janedoe/",
                "poster_info": "Talent Acquisition Specialist at Tech Corp"
            }
            mock_job_generic = {
                "poster_name": "LinkedIn Member",
                "poster_url": "",
                "poster_info": "Hiring Manager"
            }
            res_recruiter = resolve_outreach_status(mock_job_recruiter)
            res_generic = resolve_outreach_status(mock_job_generic)
            print(f"  Mock Job (with Recruiter) -> Outreach: {res_recruiter.get('outreach_status')} (Expected: available)")
            print(f"  Mock Job (generic)        -> Outreach: {res_generic.get('outreach_status')} (Expected: unavailable)")
            
            # Direct unit test of OpenAI connection request note generator
            print("\n[Verify] Running direct unit test of OpenAI Connection Note & Message generator...")
            from linkedin_jobs_agent.outreach import generate_connection_note, generate_follow_up_message
            sample_job = {
                "title": "Python Developer",
                "company": "FastTech Solutions",
                "poster_name": "Sarah Miller",
                "job_id": "123456789"
            }
            note_content = generate_connection_note(mock_cv, sample_job)
            dm_content = generate_follow_up_message(mock_cv, sample_job)
            print(f"  Generated Connect Note ({len(note_content)} chars): \"{note_content}\"")
            print(f"  Generated Follow-up Message: \n\"\"\"\n{dm_content}\n\"\"\"")
            if len(note_content) <= 200:
                print("  [OK] Success: Note is within the strict 200 characters limit.")
            else:
                print(f"  [WARNING] Note exceeded 200 characters limit! Length: {note_content}")
            
            # Direct unit test of Recruiter Reply Handling (Auto-Reply & Escalation classification)
            print("\n[Verify] Running direct unit test of Recruiter Reply Handling...")
            from linkedin_jobs_agent.outreach import classify_recruiter_reply, generate_auto_reply
            
            reply_high_intent = "Hi Test, thanks for reaching out. Let's schedule a Zoom call to discuss this further. Are you available this Friday at 3 PM? Here is my calendly link: calendly.com/jane-doe/interview"
            reply_low_intent = "Thanks for connecting, Test! Happy to have you in my network."
            
            class_high = classify_recruiter_reply(reply_high_intent)
            class_low = classify_recruiter_reply(reply_low_intent)
            
            print(f"  Recruiter Message 1: \"{reply_high_intent}\"")
            print(f"    -> Classified: high_intent={class_high.get('high_intent')} (Expected: True)")
            print(f"    -> Explanation: \"{class_high.get('explanation')}\"")
            
            print(f"  Recruiter Message 2: \"{reply_low_intent}\"")
            print(f"    -> Classified: high_intent={class_low.get('high_intent')} (Expected: False)")
            print(f"    -> Explanation: \"{class_low.get('explanation')}\"")
            
            # Test auto-reply generation
            mock_history = f"Jane Doe: {reply_low_intent}"
            auto_reply_content = generate_auto_reply(mock_cv, sample_job, mock_history)
            print(f"  Generated Auto-Reply Content: \"{auto_reply_content}\"")
            
            # Direct unit test of Pacing Guardrails and Kill Switch
            print("\n[Verify] Running direct unit test of Pacing Guardrails & Kill Switch...")
            from linkedin_jobs_agent.outreach import check_kill_switch_triggered, sleep_with_kill_switch
            
            # 1. Verify kill switch trigger file behavior
            trigger_file = os.path.join(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")), "outreach_kill_switch.trigger")
            if os.path.exists(trigger_file):
                try:
                    os.remove(trigger_file)
                except Exception:
                    pass
                    
            print("  Checking kill-switch (No trigger file):", check_kill_switch_triggered(TEST_USER_ID))
            
            # Create trigger file
            with open(trigger_file, "w") as f:
                f.write("kill")
            print("  Checking kill-switch (With trigger file):", check_kill_switch_triggered(TEST_USER_ID))
            
            # Clean up trigger file
            try:
                os.remove(trigger_file)
            except Exception:
                pass
                
            # 2. Verify DB user preference kill switch
            db_prefs = {
                "roles": ["Software Engineer"],
                "locations": ["India"],
                "experience": 2,
                "kill_switch": True
            }
            db.update_user_linkedin_preferences(TEST_USER_ID, db_prefs)
            print("  Checking kill-switch (With DB kill_switch preference):", check_kill_switch_triggered(TEST_USER_ID))
            
            # Reset preferences
            db.update_user_linkedin_preferences(TEST_USER_ID, mock_prefs)
            print("  Checking kill-switch (After DB preference reset):", check_kill_switch_triggered(TEST_USER_ID))
            
            # 3. Test sleep_with_kill_switch short-circuiting
            async def trigger_switch_after_delay():
                await asyncio.sleep(1.5)
                with open(trigger_file, "w") as f:
                    f.write("kill")
                print("    [Test Helper] Created kill-switch trigger file after 1.5 seconds.")
                
            print("  Testing sleep_with_kill_switch for 5 seconds (Should halt within ~2s)...")
            start_t = datetime.now()
            # Start background task to trigger kill switch
            bg_task = asyncio.create_task(trigger_switch_after_delay())
            halted = await sleep_with_kill_switch(5.0, TEST_USER_ID)
            end_t = datetime.now()
            duration = (end_t - start_t).total_seconds()
            print(f"    -> Sleep completed. Halted={halted}, Duration={duration:.2f} seconds (Expected: ~2.0s).")
            if halted and duration < 3.0:
                print("    [OK] Success: Kill-switch successfully halted wait loop within 30-second budget!")
            else:
                print("    [WARNING] Kill-switch did not halt wait loop as expected.")
                
            # Clean up trigger file
            try:
                os.remove(trigger_file)
            except Exception:
                pass
            
            # Direct unit test of Outreach Tracking Funnel Component
            print("\n[Verify] Running direct unit test of Outreach Tracking Funnel...")
            
            # Setup clean mock data for funnel testing
            with db._connect_jobs() as conn:
                conn.execute("DELETE FROM linkedin_jobs_tracking WHERE user_id = ?", (TEST_USER_ID,))
                conn.execute("DELETE FROM linkedin_outreach WHERE user_id = ?", (TEST_USER_ID,))
                conn.execute("DELETE FROM linkedin_jobs WHERE job_id IN ('funnel_a', 'funnel_b', 'funnel_c', 'funnel_d', 'funnel_e')")
                conn.commit()
                
            # Insert Job A: Found only
            db.save_linkedin_jobs([{
                "job_id": "funnel_a",
                "title": "Funnel Developer A",
                "company": "Company A",
                "location": "India",
                "description": "Job description A",
                "url": "https://linkedin.com/jobs/view/funnel_a",
                "scraped_at": datetime.now().isoformat(),
                "relevance_percent": 80
            }])
            db.track_linkedin_job(TEST_USER_ID, "funnel_a")
            
            # Insert Job B: Recruiter identified
            db.save_linkedin_jobs([{
                "job_id": "funnel_b",
                "title": "Funnel Developer B",
                "company": "Company B",
                "location": "India",
                "description": "Job description B",
                "url": "https://linkedin.com/jobs/view/funnel_b",
                "scraped_at": datetime.now().isoformat(),
                "relevance_percent": 85,
                "poster_name": "Jane Funnel",
                "poster_url": "https://linkedin.com/in/janefunnel"
            }])
            db.track_linkedin_job(TEST_USER_ID, "funnel_b")
            
            # Insert Job C: Connection sent
            db.save_linkedin_jobs([{
                "job_id": "funnel_c",
                "title": "Funnel Developer C",
                "company": "Company C",
                "location": "India",
                "description": "Job description C",
                "url": "https://linkedin.com/jobs/view/funnel_c",
                "scraped_at": datetime.now().isoformat(),
                "relevance_percent": 90,
                "poster_name": "John Connect",
                "poster_url": "https://linkedin.com/in/johnconnect"
            }])
            db.track_linkedin_job(TEST_USER_ID, "funnel_c")
            db.add_linkedin_outreach(TEST_USER_ID, "funnel_c", "https://linkedin.com/in/johnconnect", "sent", "note c", "dm c")
            
            # Insert Job D: Message sent
            db.save_linkedin_jobs([{
                "job_id": "funnel_d",
                "title": "Funnel Developer D",
                "company": "Company D",
                "location": "India",
                "description": "Job description D",
                "url": "https://linkedin.com/jobs/view/funnel_d",
                "scraped_at": datetime.now().isoformat(),
                "relevance_percent": 95,
                "poster_name": "Alice Message",
                "poster_url": "https://linkedin.com/in/alicemessage"
            }])
            db.track_linkedin_job(TEST_USER_ID, "funnel_d")
            db.add_linkedin_outreach(TEST_USER_ID, "funnel_d", "https://linkedin.com/in/alicemessage", "sent", "note d", "dm d")
            db.update_linkedin_outreach_status(TEST_USER_ID, "funnel_d", "accepted", follow_up_sent=1)
            
            # Insert Job E: Reply received
            db.save_linkedin_jobs([{
                "job_id": "funnel_e",
                "title": "Funnel Developer E",
                "company": "Company E",
                "location": "India",
                "description": "Job description E",
                "url": "https://linkedin.com/jobs/view/funnel_e",
                "scraped_at": datetime.now().isoformat(),
                "relevance_percent": 75,
                "poster_name": "Bob Reply",
                "poster_url": "https://linkedin.com/in/bobreply"
            }])
            db.track_linkedin_job(TEST_USER_ID, "funnel_e")
            db.add_linkedin_outreach(TEST_USER_ID, "funnel_e", "https://linkedin.com/in/bobreply", "replied_auto", "note e", "dm e")
            db.update_linkedin_outreach_status(TEST_USER_ID, "funnel_e", "replied_auto", follow_up_sent=1)
            
            # Fetch the funnel data
            funnel_results = db.get_linkedin_outreach_funnel(TEST_USER_ID)
            print(f"  Retrieved {len(funnel_results)} funnel items from database.")
            
            stages = {item["job_id"]: item["funnel_stage"] for item in funnel_results if item["job_id"] in ('funnel_a', 'funnel_b', 'funnel_c', 'funnel_d', 'funnel_e')}
            print("  Calculated Funnel Stages:")
            for jid, stage in stages.items():
                print(f"    - Job {jid[-1].upper()}: {stage}")
                
            expected = {
                "funnel_a": "job_found",
                "funnel_b": "recruiter_identified",
                "funnel_c": "connection_sent",
                "funnel_d": "message_sent",
                "funnel_e": "reply_received"
            }
            
            all_correct = True
            for k, v in expected.items():
                actual = stages.get(k)
                if actual != v:
                    print(f"    [FAIL] Expected {k} to be in stage {v}, but got {actual}")
                    all_correct = False
                    
            if all_correct:
                print("  [OK] Success: Outreach Tracking Funnel successfully tracked all stages correctly!")
            else:
                print("  [FAIL] Funnel stage validation failed.")
            
            # Run LinkedIn job search
            from linkedin_jobs_agent.search import run_linkedin_job_search
            print("\n[Verify] Running LinkedIn job search (max 3 jobs, headed browser)...")
            
            jobs = await run_linkedin_job_search(TEST_USER_ID, max_jobs_per_run=3, headed=True)
            
            print(f"\n[OK] Search execution complete. Discovered {len(jobs)} new jobs.")
            for idx, j in enumerate(jobs):
                print(f"\n--- Job #{idx+1} ---")
                print(f"Title: {j.get('title')}")
                print(f"Company: {j.get('company')}")
                print(f"Location: {j.get('location')}")
                print(f"Relevance: {j.get('relevance_percent', 0)}%")
                print(f"Recruiter Outreach: {j.get('outreach_status', 'unavailable').upper()}")
                if j.get("poster_name"):
                    print(f"  Poster Name: {j.get('poster_name')}")
                if j.get("poster_url"):
                    print(f"  Poster Profile: {j.get('poster_url')}")
                print(f"Posted: {j.get('posted_date')}")
                print(f"URL: {j.get('url')}")
                print(f"Description (Snippet): {j.get('description', '')[:150]}...")
            
            # Verify de-duplication guard
            if jobs:
                print("\n[Verify] Re-running search to verify de-duplication guard...")
                re_jobs = await run_linkedin_job_search(TEST_USER_ID, max_jobs_per_run=3, headed=True)
                print(f"[Verify] Second run returned {len(re_jobs)} new jobs (Expected: 0).")
                if len(re_jobs) == 0:
                    print("[OK] De-duplication guard successfully prevented already tracked jobs from resurfacing!")
                else:
                    print("[WARNING] De-duplication guard did not filter out all jobs.")
            # --- END OF JOB SEARCH VERIFICATION ---
            
            # Re-open a headless/headed browser instance for the remaining cleanup/simulation options
            browser = await p.chromium.launch(
                headless=False,
                args=["--no-sandbox", "--disable-setuid-sandbox", "--disable-blink-features=AutomationControlled"]
            )
        else:
            print("\n[ERROR] FAILURE: Session was not restored correctly or is invalid.\n")
            
        # Ask user if they want to simulate session expiration / invalidation
        sim_exp = input("Do you want to simulate session invalidation/deletion? (y/n): ").strip().lower()
        if sim_exp == "y":
            try:
                os.remove(cookies_path)
                print(f"[DELETE] Deleted {cookies_path} to invalidate session.")
                print("[Verify] Running validity check again in same context...")
                
                # Check validity with a new context/page
                new_context = await browser.new_context()
                new_page = await new_context.new_page()
                valid = await is_session_valid(new_page)
                if not valid:
                    print("[OK] Expiration/Invalidation correctly detected! Session is reported as invalid.")
                else:
                    print("[ERROR] Error: Cleared session was somehow reported as valid!")
            except Exception as e:
                print(f"Error deleting file: {e}")
                
        await browser.close()
        print("\nTest harness complete.")


if __name__ == "__main__":
    try:
        asyncio.run(run_harness())
    except KeyboardInterrupt:
        print("\nTest interrupted. Exiting.")
