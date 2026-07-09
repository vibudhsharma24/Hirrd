import os
import sys
import asyncio
from datetime import datetime, timezone
from playwright.async_api import async_playwright

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from core import database as db
from naukri_agent.session_manager import load_session, is_session_valid
from naukri_agent.answer_bank import get_or_propose_answer

async def run_naukri_auto_apply(user_id: int, max_daily_apps: int = 5) -> dict:
    """
    Automated Naukri Apply Agent:
    - Loads surfaced applications for the user.
    - Enforces daily throttling limits.
    - Logs into Naukri using decrypted session cookies.
    - Auto-fills screening questions using the Answer Bank (flags new questions for review).
    - Uploads tailored resumes.
    - Submits applications and updates statuses in the database.
    """
    print(f"\n[Naukri Applier] Starting auto-apply pipeline for User ID: {user_id}")
    
    # 1. Enforce throttling limit
    apps = db.get_naukri_applications(user_id)
    today_str = datetime.now().strftime("%Y-%m-%d")
    
    today_applied = [
        a for a in apps 
        if a.get("status") == "applied" and a.get("applied_at", "").startswith(today_str)
    ]
    
    print(f"[Naukri Applier] Daily stats: {len(today_applied)} / {max_daily_apps} applied today.")
    if len(today_applied) >= max_daily_apps:
        print("[Naukri Applier] Throttling limit reached. Skipping execution for today.")
        return {
            "success": True, 
            "message": "Daily throttling limit reached. No applications submitted today.", 
            "applied_count": 0,
            "flagged_count": 0
        }
        
    remaining_capacity = max_daily_apps - len(today_applied)
    
    # 2. Get surfaced or retrying jobs
    surfaced_apps = [a for a in apps if a.get("status") in ("surfaced", "retrying")]
    if not surfaced_apps:
        print("[Naukri Applier] No surfaced or retrying applications ready to apply.")
        return {
            "success": True, 
            "message": "No surfaced or retrying applications found in database.", 
            "applied_count": 0,
            "flagged_count": 0
        }
        
    print(f"[Naukri Applier] Found {len(surfaced_apps)} surfaced/retrying applications. Processing up to {remaining_capacity}...")
    
    # 3. Load cookies
    cookies = load_session(user_id)
    if not cookies:
        print("[Naukri Applier] Error: No valid session cookies found. Please run login re-auth tool first.")
        return {
            "success": False, 
            "message": "Session cookies missing or expired. Run credential login first.", 
            "applied_count": 0,
            "flagged_count": 0
        }

    applied_count = 0
    flagged_count = 0
    
    async with async_playwright() as p:
        # Launch headed chromium with bot evasion
        browser = await p.chromium.launch(
            headless=False,
            args=["--disable-blink-features=AutomationControlled"]
        )
        
        # Set context details
        context = await browser.new_context(
            viewport={"width": 1280, "height": 800},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        
        # Evasion init script
        await context.add_init_script("Object.defineProperty(navigator, 'webdriver', { get: () => undefined })")
        
        # Load cookies
        await context.add_cookies(cookies)
        
        page = await context.new_page()
        
        # Validate session
        valid = await is_session_valid(page)
        if not valid:
            print("[Naukri Applier] Expiration check failed. Aborting.")
            await browser.close()
            return {
                "success": False, 
                "message": "Session expired or invalid. Please re-authenticate.", 
                "applied_count": 0,
                "flagged_count": 0
            }
            
        for app in surfaced_apps[:remaining_capacity]:
            job_id = app.get("job_id")
            tailored_resume = app.get("tailored_resume_path")
            
            # Fetch job details for URL
            job_details = db.get_naukri_job_details(job_id)
            if not job_details:
                print(f"[Naukri Applier] Job details not found for ID: {job_id}. Skipping.")
                continue
                
            job_url = job_details.get("url")
            print(f"\n[Naukri Applier] Navigating to job: '{job_details.get('title')}' ({job_url})")
            
            attempt_num = app.get("retry_count", 0) + 1
            os.makedirs("screenshots", exist_ok=True)
            safe_job_id = job_id.replace(':', '_').replace('/', '_').replace('.', '_')
            
            try:
                await page.goto(job_url, timeout=30000, wait_until="domcontentloaded")
                await page.wait_for_timeout(3000)
                
                # Check if already applied
                already_applied = False
                applied_locators = [
                    "button.applied", ".already-applied", 
                    "span:has-text('Already Applied')", 
                    "button:has-text('Applied')"
                ]
                for locator in applied_locators:
                    if await page.locator(locator).first.count() > 0:
                        already_applied = True
                        break
                        
                if already_applied:
                    print(f"  [Naukri Applier] Already applied previously on Naukri UI. Updating status to 'applied'.")
                    db.add_naukri_application(user_id, job_id, status="applied", tailored_resume_path=tailored_resume)
                    db.update_naukri_application_retry(user_id, job_id, "applied", 0, None)
                    ss_path = os.path.abspath(f"screenshots/naukri_success_{user_id}_{safe_job_id}.png")
                    await page.screenshot(path=ss_path)
                    db.add_naukri_application_attempt(user_id, job_id, attempt_num, "applied", None, ss_path)
                    applied_count += 1
                    continue
                    
                # Locate Apply button
                apply_button = page.locator("button.apply-button, button.blue-btn, button#apply-button, button:has-text('Apply')").first
                if await apply_button.count() == 0:
                    raise Exception("Apply button not found on job page")
                    
                btn_text = await apply_button.inner_text()
                if "company site" in btn_text.lower() or "external" in btn_text.lower():
                    print("  [Naukri Applier] Job redirects to external company website. Marking as 'external_redirect'.")
                    db.add_naukri_application(user_id, job_id, status="external_redirect", tailored_resume_path=tailored_resume)
                    db.update_naukri_application_retry(user_id, job_id, "external_redirect", 0, None)
                    ss_path = os.path.abspath(f"screenshots/naukri_external_{user_id}_{safe_job_id}.png")
                    await page.screenshot(path=ss_path)
                    db.add_naukri_application_attempt(user_id, job_id, attempt_num, "external_redirect", None, ss_path)
                    continue
                    
                # Click Apply
                print("  [Naukri Applier] Clicking Apply button...")
                await apply_button.click()
                await page.wait_for_timeout(4000)
                
                # Check for dialogs, modals, or screening questions
                question_blocks = page.locator(".chatbot-message, div.question, div.form-row, div.form-group, label.question-label")
                count = await question_blocks.count()
                
                needs_review = False
                if count > 0:
                    print(f"  [Naukri Applier] Detected {count} potential screening questions. Processing...")
                    
                    for i in range(count):
                        block = question_blocks.nth(i)
                        question_text = (await block.inner_text()).strip()
                        if not question_text:
                            continue
                            
                        # Clean and query Answer Bank
                        answer, status = get_or_propose_answer(user_id, question_text)
                        
                        if status == 'pending_review':
                            print(f"  [Answer Bank] Question needs review: '{question_text}' -> Proposed: '{answer}'")
                            needs_review = True
                            
                    if needs_review:
                        print("  [Naukri Applier] Flagging application as 'pending_review' for manual verification.")
                        ss_path = os.path.abspath(f"screenshots/naukri_review_{user_id}_{safe_job_id}.png")
                        await page.screenshot(path=ss_path)
                        
                        db.add_naukri_application(user_id, job_id, status="pending_review", tailored_resume_path=tailored_resume)
                        db.update_naukri_application_retry(user_id, job_id, "pending_review", app.get("retry_count", 0), "Screening questions pending review")
                        db.add_naukri_application_attempt(user_id, job_id, attempt_num, "pending_review", "Screening questions pending review", ss_path)
                        flagged_count += 1
                        continue
                    else:
                        print("  [Naukri Applier] Filling in approved answers...")
                        for i in range(count):
                            block = question_blocks.nth(i)
                            question_text = (await block.inner_text()).strip()
                            if not question_text:
                                continue
                            answer, _ = get_or_propose_answer(user_id, question_text)
                            
                            input_text = block.locator("input[type='text'], input[type='number'], textarea").first
                            if await input_text.count() > 0:
                                await input_text.fill(answer)
                                continue
                                
                            select = block.locator("select").first
                            if await select.count() > 0:
                                await select.select_option(label=answer)
                                continue
                                
                            radio = block.locator(f"input[type='radio'][value='{answer}'], label:has-text('{answer}')").first
                            if await radio.count() > 0:
                                await radio.click()
                                continue
                                
                # Check for file upload / CV update field
                cv_input = page.locator("input[type='file'][name*='resume'], input[type='file'][id*='resume'], input[type='file']").first
                if await cv_input.count() > 0 and tailored_resume and os.path.exists(tailored_resume):
                    print(f"  [Naukri Applier] Uploading tailored resume: {tailored_resume}")
                    await cv_input.set_input_files(tailored_resume)
                    await page.wait_for_timeout(2000)
                    
                # Submit final form if modal is open
                submit_modal = page.locator("button.submit-button, button:has-text('Submit'), button:has-text('Save & Continue'), button:has-text('Apply Now')").first
                if await submit_modal.count() > 0:
                    print("  [Naukri Applier] Submitting screening form...")
                    await submit_modal.click()
                    await page.wait_for_timeout(3000)
                    
                print("  [Naukri Applier] Application completed successfully.")
                db.add_naukri_application(user_id, job_id, status="applied", tailored_resume_path=tailored_resume)
                db.update_naukri_application_retry(user_id, job_id, "applied", 0, None)
                
                ss_path = os.path.abspath(f"screenshots/naukri_success_{user_id}_{safe_job_id}.png")
                await page.screenshot(path=ss_path)
                db.add_naukri_application_attempt(user_id, job_id, attempt_num, "applied", None, ss_path)
                applied_count += 1
                
            except Exception as ex:
                err_msg = str(ex)
                print(f"  [Naukri Applier] Error applying to job {job_id} (Attempt {attempt_num}): {err_msg}")
                
                ss_path = os.path.abspath(f"screenshots/naukri_failed_{user_id}_{safe_job_id}_attempt_{attempt_num}.png")
                try:
                    await page.screenshot(path=ss_path)
                except Exception as ss_ex:
                    print(f"  [Naukri Applier] Failed to capture screenshot: {ss_ex}")
                    ss_path = None
                    
                new_retry_count = app.get("retry_count", 0) + 1
                if new_retry_count >= 3:
                    print(f"  [Naukri Applier] Job {job_id} reached terminal failure.")
                    db.add_naukri_application(user_id, job_id, status="failed", tailored_resume_path=tailored_resume)
                    db.update_naukri_application_retry(user_id, job_id, "failed", new_retry_count, err_msg)
                    db.add_naukri_application_attempt(user_id, job_id, attempt_num, "failed", err_msg, ss_path)
                else:
                    print(f"  [Naukri Applier] Job {job_id} will be retried later. Current retries: {new_retry_count}")
                    db.add_naukri_application(user_id, job_id, status="retrying", tailored_resume_path=tailored_resume)
                    db.update_naukri_application_retry(user_id, job_id, "retrying", new_retry_count, err_msg)
                    db.add_naukri_application_attempt(user_id, job_id, attempt_num, "retrying", err_msg, ss_path)
                    
        await browser.close()
        
    return {
        "success": True,
        "message": f"Auto-apply complete. Submitted {applied_count} application(s), flagged {flagged_count} for review.",
        "applied_count": applied_count,
        "flagged_count": flagged_count
    }
