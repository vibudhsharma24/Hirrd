"""
outreach.py
───────────
Automates LinkedIn recruiter connection requests with customized notes, 
and monitors connection acceptance to send follow-up messages.
"""

import os
import sys
import re
import random
import asyncio
from datetime import datetime
from openai import OpenAI

from core import database as db

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


def check_kill_switch_triggered(user_id: int = None) -> bool:
    """
    Checks if the kill switch is triggered (either file on disk or database flag).
    """
    # Check trigger file in project root
    file_trigger = os.path.join(PROJECT_ROOT, "outreach_kill_switch.trigger")
    if os.path.exists(file_trigger):
        print("[Kill Switch] Trigger file found in project root! Halting all outreach activity.")
        return True
        
    # Also check Cwd
    if os.path.exists("outreach_kill_switch.trigger"):
        print("[Kill Switch] Trigger file found in current directory! Halting all outreach activity.")
        return True

    # Check DB user preference flag
    if user_id:
        try:
            user = db.get_user(user_id) or {}
            prefs = user.get("linkedin_preferences") or {}
            if prefs.get("kill_switch_active") or prefs.get("kill_switch"):
                print(f"[Kill Switch] Database preference flag is set for user {user_id}! Halting all outreach activity.")
                return True
        except Exception as e:
            print(f"[Kill Switch] Error reading DB preferences: {e}")
            
    return False


async def sleep_with_kill_switch(seconds: float, user_id: int = None) -> bool:
    """
    Sleeps for the specified seconds, checking the kill switch every 1s.
    Returns True if the kill switch was triggered, False otherwise.
    """
    check_interval = 1.0
    elapsed = 0.0
    while elapsed < seconds:
        if check_kill_switch_triggered(user_id):
            return True
        sleep_time = min(check_interval, seconds - elapsed)
        await asyncio.sleep(sleep_time)
        elapsed += sleep_time
    return check_kill_switch_triggered(user_id)


def generate_connection_note(cv_data: dict, job: dict) -> str:
    """
    Generates a personalized connection note under 200 characters using OpenAI.
    """
    openai_key = os.environ.get("OPENAI_API_KEY", "")
    if not openai_key or openai_key == "your_openai_api_key":
        # Fallback heuristic if API key is not present
        title = job.get("title", "role")
        comp = job.get("company", "your company")
        name = job.get("poster_name") or "there"
        note = f"Hi {name}, I saw your post for {title} at {comp}. I have a strong background in Python/software development and would love to connect to discuss further!"
        return note[:200]
        
    try:
        client = OpenAI(api_key=openai_key)
        
        cv_headline = cv_data.get("personal", {}).get("headline", "Professional")
        cv_skills = ", ".join(cv_data.get("skills", [])[:4])
        job_title = job.get("title", "Role")
        job_comp = job.get("company", "Company")
        job_desc = job.get("description", "")[:300]
        poster_name = job.get("poster_name") or "Hiring Team"
        
        # Summarize experience
        exp_list = []
        for exp in cv_data.get("experience", []):
            exp_list.append(f"{exp.get('role')} at {exp.get('company')}")
        exp_summary = ", ".join(exp_list[:2])
        
        system_prompt = (
            "You are a professional candidate drafting a LinkedIn connection request note to a recruiter.\n"
            "Goal: Write in a natural, warm, human, and conversational tone. AVOID robotic formulas, buzzwords, or typical corporate templates.\n"
            "CRITICAL: The response must be STRICTLY under 200 characters total (including spaces). "
            "Write the message directly without quotes or placeholders."
        )
        
        user_prompt = (
            f"Draft a personalized LinkedIn connection note of under 200 characters to {poster_name} regarding the '{job_title}' role at '{job_comp}'.\n"
            f"Candidate Profile: Headline: '{cv_headline}', Experience: '{exp_summary}', Skills: '{cv_skills}'.\n"
            f"Job Details: '{job_desc}'.\n"
            "Write a natural, conversational message showing genuine alignment. Keep it polite, human, and concise."
        )
        
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            max_tokens=80,
            temperature=0.7
        )
        
        note = response.choices[0].message.content.strip()
        # Strip outer quotation marks if any
        if note.startswith('"') and note.endswith('"'):
            note = note[1:-1].strip()
        # Hard truncate to 200 characters just in case
        return note[:200]
        
    except Exception as e:
        print(f"[Outreach] OpenAI Note Generation Error: {e}. Using fallback note.")
        title = job.get("title", "role")
        comp = job.get("company", "your company")
        name = job.get("poster_name") or "there"
        return f"Hi {name}, I saw your post for {title} at {comp}. I have a strong background in Python/software development and would love to connect to discuss further!"[:200]


def generate_follow_up_message(cv_data: dict, job: dict) -> str:
    """
    Generates a follow-up direct message to send once a connection is accepted.
    """
    openai_key = os.environ.get("OPENAI_API_KEY", "")
    if not openai_key or openai_key == "your_openai_api_key":
        title = job.get("title", "role")
        comp = job.get("company", "your company")
        name = job.get("poster_name") or "there"
        return (
            f"Hi {name},\n\n"
            f"Thank you for connecting! I've applied for the {title} position at {comp}.\n"
            "Given my background, I would appreciate it if you could review my application. Looking forward to discussing!\n\n"
            "Best regards."
        )
        
    try:
        client = OpenAI(api_key=openai_key)
        
        cv_headline = cv_data.get("personal", {}).get("headline", "Professional")
        cv_skills = ", ".join(cv_data.get("skills", []))
        job_title = job.get("title", "Role")
        job_comp = job.get("company", "Company")
        job_desc = job.get("description", "")[:600]
        poster_name = job.get("poster_name") or "Hiring Team"
        
        # Summarize experience
        exp_list = []
        for exp in cv_data.get("experience", []):
            exp_list.append(f"{exp.get('role')} at {exp.get('company')} ({exp.get('description', '')})")
        exp_summary = "; ".join(exp_list[:2])
        
        system_prompt = (
            "You are a professional candidate sending a follow-up direct message on LinkedIn after a recruiter accepts your connection request.\n"
            "Goal: Write in a highly personalized, natural, conversational, and human tone. AVOID boilerplate templates, robotic phrasing, and generic openings.\n"
            "Highlight specific alignment between the candidate's background/skills and the job description/role. Keep the message under 500 characters."
        )
        
        user_prompt = (
            f"Draft a LinkedIn direct message to {poster_name} who just accepted my invitation.\n"
            f"Job: '{job_title}' at '{job_comp}'\n"
            f"Job Requirements/Context: '{job_desc}'\n"
            f"My Resume Details: Headline: '{cv_headline}', Skills: '{cv_skills}', Experience: '{exp_summary}'\n"
            "Write a natural, compelling follow-up. State that I've applied and highlight one key area of alignment based on the details above. Be concise and human."
        )
        
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            max_tokens=200,
            temperature=0.7
        )
        
        msg = response.choices[0].message.content.strip()
        if msg.startswith('"') and msg.endswith('"'):
            msg = msg[1:-1].strip()
        return msg
        
    except Exception as e:
        print(f"[Outreach] OpenAI DM Generation Error: {e}. Using fallback message.")
        title = job.get("title", "role")
        comp = job.get("company", "your company")
        name = job.get("poster_name") or "there"
        return (
            f"Hi {name},\n\n"
            f"Thank you for connecting! I've applied for the {title} position at {comp}.\n"
            "Given my background, I would appreciate it if you could review my application. Looking forward to discussing!\n\n"
            "Best regards."
        )


async def send_connection_request(page, poster_url: str, note: str, user_id: int = None) -> str:
    """
    Navigates to the recruiter's profile, clicks Connect, adds the note, and sends the request.
    Returns status: 'sent', 'pending_already', 'connected_already', 'failed', or 'failed_kill_switch'.
    """
    if check_kill_switch_triggered(user_id):
        print("  [Outreach] Kill-switch triggered. Aborting connection request.")
        return "failed_kill_switch"
        
    print(f"  [Outreach] Opening recruiter profile: {poster_url}")
    try:
        await page.goto(poster_url, wait_until="domcontentloaded", timeout=30000)
        
        # Humanize: view the profile for a random amount of time
        view_sec = random.uniform(4.0, 8.0)
        if await sleep_with_kill_switch(view_sec, user_id):
            return "failed_kill_switch"
            
        # Check if already connected or invitation is already pending
        pending_selectors = [
            "button:has-text('Pending')", 
            "button:has-text('Pending Invitation')", 
            "button:has-text('Withdraw')"
        ]
        for sel in pending_selectors:
            if await page.locator(sel).count() > 0:
                print("  [Outreach] Connection invitation is already pending.")
                return "pending_already"
                
        # If there is no Connect button but Message button exists, we might already be connected
        connect_btn = page.locator("button.artdeco-button:has-text('Connect'), .pv-top-card-v2-ctas button:has-text('Connect')").first
        if await connect_btn.count() == 0:
            msg_btn = page.locator("button.artdeco-button:has-text('Message'), .pv-top-card-v2-ctas button:has-text('Message')").first
            if await msg_btn.count() > 0:
                print("  [Outreach] Already connected to recruiter.")
                return "connected_already"
                
            # If no Connect button directly, look in "More..." dropdown
            more_btn = page.locator("button.artdeco-button:has-text('More'), button[aria-label*='More actions']").first
            if await more_btn.count() > 0:
                await more_btn.click()
                if await sleep_with_kill_switch(random.uniform(1.0, 2.0), user_id):
                    return "failed_kill_switch"
                
                # Check for Connect inside dropdown menu
                dropdown_connect = page.locator("div[role='button']:has-text('Connect'), span:has-text('Connect'), li:has-text('Connect')").first
                if await dropdown_connect.count() > 0:
                    connect_btn = dropdown_connect
                else:
                    print("  [Outreach] Connect button not found anywhere on profile.")
                    return "failed"
            else:
                print("  [Outreach] Connect button not found and 'More...' actions unavailable.")
                return "failed"
                
        # Click the Connect button
        await connect_btn.scroll_into_view_if_needed()
        await connect_btn.click()
        if await sleep_with_kill_switch(random.uniform(2.0, 4.0), user_id):
            return "failed_kill_switch"
        
        # Look for "Add a note" button in invitation dialog
        add_note_btn = page.locator("button[aria-label='Add a note'], button:has-text('Add a note')").first
        if await add_note_btn.count() > 0:
            await add_note_btn.click()
            if await sleep_with_kill_switch(random.uniform(1.0, 2.0), user_id):
                return "failed_kill_switch"
            
            # Type custom note
            textarea = page.locator("textarea[name='message'], #custom-message").first
            await textarea.fill(note)
            if await sleep_with_kill_switch(random.uniform(2.0, 4.0), user_id):
                return "failed_kill_switch"
            
            # Click Send button
            send_btn = page.locator("button[aria-label='Send now'], button:has-text('Send'), button:has-text('Send now')").first
            await send_btn.click()
            if await sleep_with_kill_switch(random.uniform(3.0, 5.0), user_id):
                return "failed_kill_switch"
            print("  [Outreach] Connection request with note sent successfully.")
            return "sent"
        else:
            print("  [Outreach] Note dialog did not open. Attempting to click direct send if needed...")
            direct_send = page.locator("button:has-text('Send'), button:has-text('Send now')").first
            if await direct_send.count() > 0:
                await direct_send.click()
                if await sleep_with_kill_switch(random.uniform(2.0, 3.5), user_id):
                    return "failed_kill_switch"
                return "sent"
            
        return "failed"
    except Exception as e:
        print(f"  [Outreach] Error sending connection request: {e}")
        return "failed"


async def initiate_recruiter_outreach(page, user_id: int, job: dict) -> bool:
    """
    Coordinates connection request generation and sending, and updates database records.
    """
    if check_kill_switch_triggered(user_id):
        print("[Outreach] Kill-switch active. Skipping outreach initiation.")
        return False

    # Check pacing limits (connection requests limit)
    counts = db.get_daily_action_counts(user_id)
    user = db.get_user(user_id) or {}
    prefs = user.get("linkedin_preferences") or {}
    max_connections = prefs.get("max_daily_connections")
    if max_connections is None:
        max_connections = int(os.environ.get("MAX_DAILY_CONNECTIONS", 10))
        
    if counts.get("connection_requests", 0) >= max_connections:
        print(f"[Pacing Guard] Connection requests daily limit reached ({counts.get('connection_requests')}/{max_connections}). skipping job poster connection request.")
        return False
        
    job_id = job.get("job_id") or job.get("url", "")
    poster_url = job.get("poster_url")
    if not poster_url:
        return False
        
    print(f"[Outreach] Initiating recruiter outreach for job: {job.get('title')} at {job.get('company')}...")
    
    cv_data = db.get_master_cv(user_id) or {}
    
    # Generate messages via OpenAI
    note = generate_connection_note(cv_data, job)
    follow_up = generate_follow_up_message(cv_data, job)
    
    print(f"  [OpenAI Generated Note ({len(note)} chars)]: \"{note}\"")
    
    # Send connection request
    status = await send_connection_request(page, poster_url, note, user_id)
    if status == "failed_kill_switch":
        return False
    
    # Save/Update in database
    db.add_linkedin_outreach(
        user_id=user_id,
        job_id=job_id,
        poster_url=poster_url,
        connection_status=status,
        note=note,
        follow_up_message=follow_up
    )
    
    # If already connected, we can immediately try to send the follow-up message!
    if status == "connected_already":
        # Check DM limits
        max_dms = prefs.get("max_daily_dms")
        if max_dms is None:
            max_dms = int(os.environ.get("MAX_DAILY_DMS", 15))
        if counts.get("direct_messages", 0) >= max_dms:
            print(f"[Pacing Guard] Daily DM limit reached ({counts.get('direct_messages')}/{max_dms}). Skipping immediate follow-up DM.")
            return True
            
        print("  [Outreach] Already connected! Proceeding to send follow-up direct message immediately.")
        
        # Humanize: wait random seconds before sending the follow up DM
        delay_sec = random.uniform(5.0, 10.0)
        print(f"  [Outreach] Throttling {delay_sec:.1f}s before sending follow-up direct message...")
        if await sleep_with_kill_switch(delay_sec, user_id):
            return False
            
        await check_and_send_follow_up(page, user_id, job_id, poster_url, follow_up, user_id)
        
    return status in ("sent", "connected_already", "pending_already")


async def check_and_send_follow_up(page, user_id: int, job_id: str, poster_url: str, message: str, check_user_id: int = None) -> bool:
    """
    Navigates to the recruiter profile, opens the chat drawer, and types/sends the follow-up DM.
    """
    if check_kill_switch_triggered(check_user_id):
        print("  [Outreach] Kill-switch active. Aborting follow-up message.")
        return False
        
    print(f"  [Outreach] Attempting to send follow-up message to: {poster_url}")
    try:
        await page.goto(poster_url, wait_until="domcontentloaded", timeout=30000)
        
        # Humanize profile view time
        if await sleep_with_kill_switch(random.uniform(4.0, 7.0), check_user_id):
            return False
            
        # Click the Message button
        msg_btn = page.locator("button.artdeco-button:has-text('Message'), .pv-top-card-v2-ctas button:has-text('Message'), a:has-text('Message')").first
        if await msg_btn.count() > 0:
            await msg_btn.click()
            if await sleep_with_kill_switch(random.uniform(2.0, 3.0), check_user_id):
                return False
                
            # Find the message drawer/textbox
            textbox = page.locator(".msg-form__contenteditable, div[role='textbox'], textarea.msg-form__textarea").first
            if await textbox.count() > 0:
                await textbox.click()
                await textbox.fill(message)
                if await sleep_with_kill_switch(random.uniform(1.5, 3.0), check_user_id):
                    return False
                
                # Send
                send_btn = page.locator("button[type='submit'].msg-form__send-button, button:has-text('Send')").first
                await send_btn.click()
                if await sleep_with_kill_switch(random.uniform(2.5, 4.0), check_user_id):
                    return False
                
                print("  [Outreach] Follow-up message sent successfully.")
                db.update_linkedin_outreach_status(user_id, job_id, connection_status="accepted", follow_up_sent=1)
                return True
            else:
                print("  [Outreach] Message textbox was not found in chat panel.")
        else:
            print("  [Outreach] Message button is not available on this profile.")
            
        return False
    except Exception as e:
        print(f"  [Outreach] Error sending follow-up message: {e}")
        return False


async def monitor_and_process_outreach(page, user_id: int) -> int:
    """
    Checks all pending invitation outreach entries, and sends follow-up messages on acceptance.
    Also parses active outreach conversations to handle recruiter replies conversationally or escalate.
    """
    if check_kill_switch_triggered(user_id):
        print("[Kill Switch] Outreach monitoring execution halted.")
        return 0

    # Load preferences for user
    user = db.get_user(user_id) or {}
    prefs = user.get("linkedin_preferences") or {}
    max_dms = prefs.get("max_daily_dms")
    if max_dms is None:
        max_dms = int(os.environ.get("MAX_DAILY_DMS", 15))

    # 1. Check pending connections (invites sent, awaiting acceptance)
    pending = db.get_pending_linkedin_outreaches(user_id)
    processed_count = 0
    
    if pending:
        print(f"[Outreach Monitor] Found {len(pending)} pending outreach records to check.")
        for row in pending:
            # Check limits & kill-switch
            if check_kill_switch_triggered(user_id):
                print("[Kill Switch] Halt detected during pending checks loop.")
                return processed_count
                
            counts = db.get_daily_action_counts(user_id)
            if counts.get("direct_messages", 0) >= max_dms:
                print(f"[Pacing Guard] Direct message limit reached for today ({counts.get('direct_messages')}/{max_dms}). Halting pending DM processing.")
                break
                
            job_id = row.get("job_id")
            poster_url = row.get("poster_url")
            follow_up = row.get("follow_up_message")
            
            try:
                print(f"  [Monitor] Checking invite status for recruiter: {poster_url}")
                await page.goto(poster_url, wait_until="domcontentloaded", timeout=30000)
                
                # View profile delay
                if await sleep_with_kill_switch(random.uniform(4.0, 7.0), user_id):
                    return processed_count
                    
                has_pending = await page.locator("button:has-text('Pending'), button:has-text('Withdraw')").count() > 0
                has_connect = await page.locator("button.artdeco-button:has-text('Connect')").count() > 0
                has_message = await page.locator("button.artdeco-button:has-text('Message'), .pv-top-card-v2-ctas button:has-text('Message')").count() > 0
                
                if has_message and not has_pending and not has_connect:
                    print(f"  [Monitor] Success! Recruiter accepted invitation. Sending follow-up DM...")
                    success = await check_and_send_follow_up(page, user_id, job_id, poster_url, follow_up, user_id)
                    if success:
                        processed_count += 1
                else:
                    print("  [Monitor] Invitation is still pending or not accepted yet.")
                    
                # Delay between profile checks
                delay = random.uniform(10.0, 20.0)
                print(f"  [Monitor] Delaying {delay:.1f}s before next check to mimic human browsing...")
                if await sleep_with_kill_switch(delay, user_id):
                    return processed_count
            except Exception as e:
                print(f"  [Monitor] Error checking poster {poster_url}: {e}")
                
    # 2. Check recruiter replies for active outreaches
    active = db.get_active_linkedin_outreaches(user_id)
    if active:
        print(f"[Outreach Monitor] Found {len(active)} active outreach records to scan for replies.")
        cv_data = db.get_master_cv(user_id) or {}
        cand_name = cv_data.get("personal", {}).get("name", "Test User")
        
        for row in active:
            # Check limits & kill-switch
            if check_kill_switch_triggered(user_id):
                print("[Kill Switch] Halt detected during active replies check loop.")
                return processed_count
                
            counts = db.get_daily_action_counts(user_id)
            if counts.get("direct_messages", 0) >= max_dms:
                print(f"[Pacing Guard] Direct message limit reached for today ({counts.get('direct_messages')}/{max_dms}). Halting reply check.")
                break
                
            job_id = row.get("job_id")
            poster_url = row.get("poster_url")
            
            try:
                print(f"  [Monitor] Checking for replies from: {poster_url}")
                await page.goto(poster_url, wait_until="domcontentloaded", timeout=30000)
                
                # View profile delay
                if await sleep_with_kill_switch(random.uniform(4.0, 7.0), user_id):
                    return processed_count
                    
                # Open Message panel
                msg_btn = page.locator("button.artdeco-button:has-text('Message'), .pv-top-card-v2-ctas button:has-text('Message'), a:has-text('Message')").first
                if await msg_btn.count() > 0:
                    await msg_btn.click()
                    if await sleep_with_kill_switch(random.uniform(2.0, 3.5), user_id):
                        return processed_count
                        
                    # Extract message history
                    history = await get_chat_message_history(page)
                    if history:
                        last_msg = history[-1]
                        last_text = last_msg.get("text", "")
                        last_sender = last_msg.get("sender", "")
                        
                        # Check if last message is from the recruiter (not candidate)
                        is_candidate_sender = cand_name.lower() in last_sender.lower() or last_sender.lower() in cand_name.lower()
                        
                        if not is_candidate_sender:
                            print(f"  [Monitor] New reply from recruiter detected: \"{last_text}\" (Sender: {last_sender})")
                            
                            # Classify intent
                            classification = classify_recruiter_reply(last_text)
                            print(f"  [Monitor] Classification: high_intent={classification.get('high_intent')}, explanation=\"{classification.get('explanation')}\"")
                            
                            if classification.get("high_intent"):
                                # Escalation
                                print(f"  [ESCALATE] High-intent recruiter reply detected! Escalating directly to user dashboard.")
                                db.update_linkedin_outreach_status(user_id, job_id, connection_status="escalated", follow_up_sent=1)
                            else:
                                # Auto-reply
                                job = db.get_linkedin_job_by_id(job_id) or {}
                                history_str = "\n".join([f"{m['sender']}: {m['text']}" for m in history])
                                reply_text = generate_auto_reply(cv_data, job, history_str)
                                print(f"  [Monitor] Sending conversational auto-reply: \"{reply_text}\"")
                                
                                textbox = page.locator(".msg-form__contenteditable, div[role='textbox'], textarea.msg-form__textarea").first
                                if await textbox.count() > 0:
                                    await textbox.click()
                                    await textbox.fill(reply_text)
                                    if await sleep_with_kill_switch(random.uniform(1.0, 2.5), user_id):
                                        return processed_count
                                        
                                    send_btn = page.locator("button[type='submit'].msg-form__send-button, button:has-text('Send')").first
                                    await send_btn.click()
                                    if await sleep_with_kill_switch(random.uniform(2.5, 4.0), user_id):
                                        return processed_count
                                        
                                    # Update status
                                    db.update_linkedin_outreach_status(user_id, job_id, connection_status="replied_auto", follow_up_sent=1)
                                    processed_count += 1
                        else:
                            print("  [Monitor] Last message in thread is from the candidate. No action needed.")
                    else:
                        print("  [Monitor] Chat history is empty.")
                else:
                    print("  [Monitor] Message button not available.")
                    
                # Delay between checking different profiles
                delay = random.uniform(10.0, 20.0)
                print(f"  [Monitor] Delaying {delay:.1f}s before next active check to mimic human browsing...")
                if await sleep_with_kill_switch(delay, user_id):
                    return processed_count
            except Exception as e:
                print(f"  [Monitor] Error checking replies for poster {poster_url}: {e}")
                
    return processed_count


async def get_chat_message_history(page) -> list[dict]:
    """
    Extracts the list of messages in the currently open message box.
    Returns a list of dicts: [{"sender": "...", "text": "..."}]
    """
    message_items = []
    try:
        # First, try to locate message groups
        groups = page.locator(".msg-s-message-group, .msg-overlay-conversation-bubble")
        group_count = await groups.count()
        if group_count > 0:
            for i in range(group_count):
                group = groups.nth(i)
                sender_elem = group.locator(".msg-s-message-group__name, .msg-overlay-conversation-bubble__name, span.msg-s-message-group__name").first
                sender = "Unknown"
                if await sender_elem.count() > 0:
                    sender = await sender_elem.text_content()
                    sender = sender.strip()
                    
                texts = group.locator(".msg-s-event-listitem__body, .msg-s-message-group__body, .msg-overlay-view-bubble__message-text")
                text_count = await texts.count()
                for j in range(text_count):
                    txt = await texts.nth(j).text_content()
                    if txt:
                        message_items.append({
                            "sender": sender,
                            "text": txt.strip()
                        })
        else:
            # Fallback: grab message body texts
            raw_texts = page.locator(".msg-s-event-listitem__body, .msg-overlay-view-bubble__message-text")
            count = await raw_texts.count()
            for i in range(count):
                txt = await raw_texts.nth(i).text_content()
                if txt:
                    message_items.append({
                        "sender": "Message",
                        "text": txt.strip()
                    })
    except Exception as e:
        print(f"  [Outreach] Error getting chat history: {e}")
    return message_items


def classify_recruiter_reply(reply_text: str) -> dict:
    """
    Classifies a recruiter's reply.
    Returns: {"high_intent": True/False, "explanation": "..."}
    """
    openai_key = os.environ.get("OPENAI_API_KEY", "")
    if not openai_key or openai_key == "your_openai_api_key":
        # Heuristic fallback
        lower_txt = reply_text.lower()
        high_intent_keywords = [
            "interview", "schedule", "call", "phone", "meet", "slot", "calendar", 
            "zoom", "teams", "discuss", "time", "availability", "resume", "cv", 
            "salary", "rate", "position", "apply"
        ]
        is_high = any(kw in lower_txt for kw in high_intent_keywords)
        return {"high_intent": is_high, "explanation": "Fallback keyword check"}

    try:
        client = OpenAI(api_key=openai_key)
        system_prompt = (
            "You are an AI classifier for job search outreach.\n"
            "Your task is to analyze a recruiter's message and classify if it is 'high-intent' or 'low-intent'.\n"
            "High-intent replies include: requests for interviews, screening calls, scheduling asks (Zoom/Teams/Calendar links), asking for CV/resume upload, salary expectations, or direct interest in scheduling a discussion.\n"
            "Low-intent replies include: general acknowledgements (e.g., 'Thanks for applying', 'Nice to connect'), simple pleasantries, rejection notices, automatic out-of-office replies, or open-ended questions not related to active next steps.\n"
            "Respond ONLY in valid JSON format: {\"high_intent\": true/false, \"explanation\": \"reason for classification\"}"
        )
        
        import json
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"Recruiter Reply:\n\"\"\"\n{reply_text}\n\"\"\""}
            ],
            response_format={"type": "json_object"},
            max_tokens=150,
            temperature=0.0
        )
        
        res_data = json.loads(response.choices[0].message.content.strip())
        return res_data
    except Exception as e:
        print(f"[Outreach] Error classifying reply via OpenAI: {e}")
        lower_txt = reply_text.lower()
        high_intent_keywords = ["interview", "schedule", "call", "phone", "meet", "slot", "zoom", "teams", "discuss", "time"]
        is_high = any(kw in lower_txt for kw in high_intent_keywords)
        return {"high_intent": is_high, "explanation": "Error fallback heuristic"}


def generate_auto_reply(cv_data: dict, job: dict, conversation_history: str) -> str:
    """
    Generates a conversational response to keep the chat active, highlighting interest.
    """
    openai_key = os.environ.get("OPENAI_API_KEY", "")
    if not openai_key or openai_key == "your_openai_api_key":
        name = job.get("poster_name") or "there"
        return f"Hi {name}, thanks for the response! I would love to connect briefly whenever you have a moment to discuss how my background aligns with the role. Let me know if you need any other details from my end!"

    try:
        client = OpenAI(api_key=openai_key)
        
        cv_headline = cv_data.get("personal", {}).get("headline", "")
        cv_skills = ", ".join(cv_data.get("skills", [])[:4])
        job_title = job.get("title", "Role")
        job_comp = job.get("company", "Company")
        
        system_prompt = (
            "You are a professional candidate responding to a recruiter on LinkedIn.\n"
            "Goal: Write a short, warm, professional, and natural auto-reply. Match a human conversational tone — never sound templated or robotic. "
            "Do not include any placeholders, and write the response in under 250 characters."
        )
        
        user_prompt = (
            f"Recruiter's last messages/history:\n{conversation_history}\n\n"
            f"My Context: Role: '{job_title}' at '{job_comp}', Headline: '{cv_headline}', Skills: '{cv_skills}'.\n"
            "Draft a short response acknowledging their reply and keeping the conversation warm and open."
        )
        
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            max_tokens=100,
            temperature=0.7
        )
        
        reply = response.choices[0].message.content.strip()
        if reply.startswith('"') and reply.endswith('"'):
            reply = reply[1:-1].strip()
        return reply[:250]
    except Exception as e:
        print(f"[Outreach] Error generating auto-reply via OpenAI: {e}")
        name = job.get("poster_name") or "there"
        return f"Hi {name}, thank you for the note! I'm very interested in the role and would be happy to share more details whenever convenient."
