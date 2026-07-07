"""
test_harness.py
───────────────
Interactive CLI tool to verify Naukri.com login and session persistence.
"""

import asyncio
import os
import sys
import getpass
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

from naukri_agent.session_manager import (
    load_session,
    save_session,
    is_session_valid,
    login_naukri,
    _get_cookies_path
)


def print_banner(text):
    print("=" * 60)
    print(f" {text}")
    print("=" * 60)


async def run_harness():
    print_banner("Naukri AI Agent - Session Handling Test Harness")
    
    # ── Requirement: Ask for credentials BEFORE starting anything ───────────
    print("Please enter your Naukri.com credentials to begin.")
    default_email = "mkixtech@gmail.com"
    username = input(f"Naukri Email/Username [{default_email}]: ").strip()
    if not username:
        username = default_email
        
    default_password = "MkixTech@123$"
    password = input("Naukri Password [Press Enter to use default test password]: ").strip()
    if not password:
        password = default_password
        
    print("\n[System] Credentials received. Initializing browser...")
    
    TEST_USER_ID = 9999  # Mock user ID for testing
    cookies_path = _get_cookies_path(TEST_USER_ID)
    
    async with async_playwright() as p:
        # Launch headed browser so user can see it and solve captcha/OTP if needed
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
        # Stealth
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
                    print("[WARNING] ALERT: Naukri Session has EXPIRED or been INVALIDATED!")
                    print("!" * 50 + "\n")
                    print("Prompting for re-authentication...")
            else:
                print("[WARNING] Failed to decrypt or load existing session.")
        else:
            print("\n[System] No existing session found on disk. Proceeding with fresh login...")
            
        if not session_loaded_and_valid:
            print("\n[System] Attempting login with credentials provided...")
            res = await login_naukri(page, username, password)
            
            if res["success"]:
                print("[OK] Logged in successfully!")
            else:
                print(f"[WARNING] Automated login did not complete: {res['reason']} ({res['message']})")
                if res["reason"] in ("captcha_required", "otp_required", "unknown_state"):
                    print("\n" + "=" * 60)
                    print("[ACTION] REQUIRED: Solve any CAPTCHA or enter the OTP in the browser window.")
                    print("The harness will monitor the browser window and automatically save your session once done.")
                    print("=" * 60 + "\n")
                    
                    # Wait loop monitoring for successful redirect
                    login_detected = False
                    for seconds in range(120):
                        url = page.url
                        if "mnjuser" in url or "homepage" in url:
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

    # ── Step 7: Verify session persistence in a fresh context ────────────────
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
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, Gecko) Chrome/125.0.0.0 Safari/537.36",
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
        print("[Verify] Restored cookies into context. Navigating to profile to check validity...")
        
        valid = await is_session_valid(page)
        if valid:
            print("\n[OK] SUCCESS: Persistent session is VALID in a fresh browser session without entering passwords!")
            print("[SECURE] Rested cookies file is encrypted. Verify this by viewing the raw file contents.")
            print(f"   Path: {cookies_path}\n")
        else:
            print("\n[ERROR] FAILURE: Session was not restored correctly or is invalid.\n")
            
        # Ask user if they want to simulate session expiration / invalidation
        sim_exp = input("Do you want to simulate session invalidation/deletion? (y/n): ").strip().lower()
        if sim_exp == "y":
            try:
                os.remove(cookies_path)
                print(f"[DELETE] Deleted {cookies_path} to invalidate session.")
                print("[Verify] Running validity check again in same context...")
                # Validity check in a new page or cleared cookies
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
