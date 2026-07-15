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

async def run_naukri_auto_apply(user_id: int, max_daily_apps: int = 5, resume_path: str = None, force_apply: bool = False) -> dict:
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
    
    # 2. Get surfaced or retrying jobs, sorted by relevance score descending
    with db._connect_jobs() as conn:
        rows = conn.execute(
            """SELECT a.*, j.relevance_percent 
               FROM naukri_applications a
               JOIN naukri_jobs j ON a.job_id = j.job_id OR a.job_id = j.url
               WHERE a.user_id = ? AND a.status IN ('surfaced', 'retrying')
               ORDER BY j.relevance_percent DESC""",
            (user_id,)
        ).fetchall()
        surfaced_apps = [db._row_to_dict(r) for r in rows]
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
            
        for app in surfaced_apps:
            if applied_count >= remaining_capacity:
                print(f"[Naukri Applier] Reached target applied limit of {remaining_capacity}. Stopping.")
                break
                
            job_id = app.get("job_id")
            tailored_resume = resume_path or app.get("tailored_resume_path")
            
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
                
                # 1. Interactive Chatbot Solver
                # Check if a chatbot overlay is open (i.e. contains elements with class chatbot or similar)
                chatbot_container = page.locator(".chatbot-message, [class*='chatbot'], [class*='chat-message'], [class*='chat-bubble'], .chipsContainer").first
                if await chatbot_container.count() > 0:
                    print("  [Naukri Applier] Detected interactive chatbot popup. Answering step-by-step...")
                    for step in range(15):
                        # Wait for typing dots loader / transition
                        await page.wait_for_timeout(2000)
                        
                        # Locate the last chatbot bubble text
                        question_locator = page.locator(".chatbot_Question, .chatbot-message, [class*='chatbot-message'], [class*='chat-message']").last
                        if await question_locator.count() == 0:
                            break
                            
                        question_text = (await question_locator.inner_text()).strip()
                        if not question_text:
                            break
                            
                        # Extract options from visible chips/buttons inside the chatbot overlay
                        options = []
                        all_chips = await page.locator(".chatbot_Chip, .chipItem, button, [class*='chip']").all()
                        for chip in all_chips:
                            if await chip.is_visible():
                                text = (await chip.inner_text()).strip()
                                # Filter out generic page-level buttons
                                if text and text not in ["Save", "Apply", "Following", "Close", "X", "Cancel"]:
                                    text_clean = " ".join(text.split())
                                    if text_clean and text_clean not in options:
                                        options.append(text_clean)
                                        
                        # Extract options listed in the question text itself (split by newline)
                        lines = [line.strip() for line in question_text.split("\n") if line.strip()]
                        question_core = lines[0]
                        if len(lines) > 1:
                            for line in lines[1:]:
                                if line not in options and line not in ["Save", "Apply", "Following", "Close"]:
                                    options.append(line)
                                    
                        if not question_core or "upload" in question_core.lower() or "resume" in question_core.lower() or "unsuccessful" in question_core.lower():
                            # Break if chatbot is asking for resume upload or complaining about it
                            print(f"    [Chatbot] Step {step+1}: Encountered resume upload prompt/error: '{question_core}'. Ending chat loop.")
                            break
                            
                        print(f"    [Chatbot] Step {step+1} Question: '{question_core}'")
                        if options:
                            print(f"    [Chatbot] Available options: {options}")
                            
                        answer, status = get_or_propose_answer(user_id, question_core, options=options)
                        print(f"    [Chatbot] Step {step+1} Answer: '{answer}' (Status: {status})")
                        
                        clicked = False
                        # Try to click the matched option chip
                        if options:
                            for opt in options:
                                if clean_text(opt) == clean_text(answer) or answer.lower() in opt.lower() or opt.lower() in answer.lower():
                                    chip_selectors = [
                                        f".chatbot_Chip:has-text('{opt}')",
                                        f".chipItem:has-text('{opt}')",
                                        f"button:has-text('{opt}')",
                                        f"[class*='chip']:has-text('{opt}')",
                                        f"div:has-text('{opt}')"
                                    ]
                                    for selector in chip_selectors:
                                        loc = page.locator(selector).first
                                        if await loc.count() > 0 and await loc.is_visible():
                                            print(f"      [Chatbot] Clicking selected option chip: '{opt}' via {selector}")
                                            await loc.click()
                                            clicked = True
                                            break
                                    if clicked:
                                        break
                                        
                        if not clicked and options:
                            # Direct check of all visible chips
                            all_chips = await page.locator(".chatbot_Chip, .chipItem, button, [class*='chip']").all()
                            for chip in all_chips:
                                if await chip.is_visible():
                                    text = (await chip.inner_text()).strip()
                                    text_clean = " ".join(text.split())
                                    if text_clean and (clean_text(text_clean) == clean_text(answer) or answer.lower() in text_clean.lower() or text_clean.lower() in answer.lower()):
                                        print(f"      [Chatbot] Clicking matched chip: '{text_clean}'")
                                        await chip.click()
                                        clicked = True
                                        break
                                        
                        if clicked:
                            await page.wait_for_timeout(1000)
                            continue
                            
                        # 3. Fill in text inputs/textareas inside the chatbot
                        chat_input = page.locator("input[type='text'], input[type='number'], textarea").first
                        if await chat_input.count() > 0 and await chat_input.is_visible():
                            print(f"      [Chatbot] Filling input field: '{answer}'")
                            await chat_input.fill(answer)
                            await chat_input.press("Enter")
                            # Try to click send button if present
                            send_btn = page.locator(".send-btn, button:has-text('Send'), [class*='send']").first
                            if await send_btn.count() > 0 and await send_btn.is_visible():
                                await send_btn.click()
                            await page.wait_for_timeout(1000)
                            continue
                            
                        print("      [Chatbot] No inputs or option chips available. Chat loop finished.")
                        break

                # 2. Static Form Solver (for traditional multi-question forms/modals)
                question_blocks = page.locator("div.question, div.form-row, div.form-group, label.question-label")
                count = await question_blocks.count()
                
                needs_review = False
                if count > 0:
                    print(f"  [Naukri Applier] Detected {count} static screening questions. Processing...")
                    
                    for i in range(count):
                        block = question_blocks.nth(i)
                        question_text = (await block.inner_text()).strip()
                        if not question_text:
                            continue
                            
                        question_core = question_text.split("\n")[0].strip()
                        options = []
                        
                        select = block.locator("select").first
                        if await select.count() > 0:
                            option_elems = await select.locator("option").all()
                            for opt_el in option_elems:
                                val = await opt_el.get_attribute("value") or ""
                                txt = (await opt_el.inner_text()).strip()
                                if txt and val != "":
                                    options.append(" ".join(txt.split()))
                        else:
                            radio_labels = await block.locator("input[type='radio'] + label, label:has(input[type='radio']), input[type='checkbox'] + label, label:has(input[type='checkbox'])").all()
                            if len(radio_labels) == 0:
                                radio_labels = await block.locator("label").all()
                            for r_label in radio_labels:
                                txt = (await r_label.inner_text()).strip()
                                if txt:
                                    options.append(" ".join(txt.split()))
                                    
                        # Clean and query Answer Bank
                        answer, status = get_or_propose_answer(user_id, question_core, options=options)
                        
                        if status == 'pending_review':
                            print(f"  [Answer Bank] Question needs review: '{question_core}' -> Proposed: '{answer}'")
                            needs_review = True
                            
                    if needs_review and not force_apply:
                        print("  [Naukri Applier] Flagging application as 'pending_review' for manual verification.")
                        ss_path = os.path.abspath(f"screenshots/naukri_review_{user_id}_{safe_job_id}.png")
                        await page.screenshot(path=ss_path)
                        
                        db.add_naukri_application(user_id, job_id, status="pending_review", tailored_resume_path=tailored_resume)
                        db.update_naukri_application_retry(user_id, job_id, "pending_review", app.get("retry_count", 0), "Screening questions pending review")
                        db.add_naukri_application_attempt(user_id, job_id, attempt_num, "pending_review", "Screening questions pending review", ss_path)
                        flagged_count += 1
                        continue
                    else:
                        print("  [Naukri Applier] Filling in approved/proposed answers...")
                        for i in range(count):
                            block = question_blocks.nth(i)
                            question_text = (await block.inner_text()).strip()
                            if not question_text:
                                continue
                            
                            question_core = question_text.split("\n")[0].strip()
                            options = []
                            
                            select = block.locator("select").first
                            if await select.count() > 0:
                                option_elems = await select.locator("option").all()
                                for opt_el in option_elems:
                                    val = await opt_el.get_attribute("value") or ""
                                    txt = (await opt_el.inner_text()).strip()
                                    if txt and val != "":
                                        options.append(" ".join(txt.split()))
                                        
                                answer, _ = get_or_propose_answer(user_id, question_core, options=options)
                                print(f"    [Static Dropdown] Selected Option: '{answer}'")
                                await select.select_option(label=answer)
                                continue
                                
                            radio_labels = await block.locator("input[type='radio'] + label, label:has(input[type='radio']), input[type='checkbox'] + label, label:has(input[type='checkbox'])").all()
                            if len(radio_labels) == 0:
                                radio_labels = await block.locator("label").all()
                            for r_label in radio_labels:
                                txt = (await r_label.inner_text()).strip()
                                if txt:
                                    options.append(" ".join(txt.split()))
                                    
                            if options:
                                answer, _ = get_or_propose_answer(user_id, question_core, options=options)
                                print(f"    [Static Radio/Checkbox] Selected Option: '{answer}'")
                                clicked_radio = False
                                for opt in options:
                                    if clean_text(opt) == clean_text(answer) or answer.lower() in opt.lower() or opt.lower() in answer.lower():
                                        radio_el = block.locator(f"input[type='radio'][value='{opt}'], label:has-text('{opt}')").first
                                        if await radio_el.count() > 0 and await radio_el.is_visible():
                                            await radio_el.click()
                                            clicked_radio = True
                                            break
                                if clicked_radio:
                                    continue
                                    
                            input_text = block.locator("input[type='text'], input[type='number'], textarea").first
                            if await input_text.count() > 0:
                                answer, _ = get_or_propose_answer(user_id, question_core)
                                print(f"    [Static Text Input] Answer: '{answer}'")
                                await input_text.fill(answer)
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
