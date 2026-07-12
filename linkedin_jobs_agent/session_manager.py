"""
session_manager.py
──────────────────
Handles secure session loading, saving, encryption at rest, and automated login/validation
for LinkedIn Jobs AI Agent.
"""

import os
import json
import sys
from pathlib import Path
from core.auth import encrypt_credential, decrypt_credential

# Ensure project root is in sys.path
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

SESSIONS_DIR = os.path.join(os.path.dirname(__file__), "sessions")
os.makedirs(SESSIONS_DIR, exist_ok=True)


def _get_cookies_path(user_id: int) -> str:
    """Get the path to the encrypted cookies file for a specific user."""
    return os.path.join(SESSIONS_DIR, f"linkedin_cookies_{user_id}.enc")


def save_session(user_id: int, cookies: list[dict]) -> bool:
    """
    Encrypt the session cookies using AES-256-GCM and save to disk.
    
    Args:
        user_id: The database ID of the user.
        cookies: List of Playwright cookie dictionaries.
        
    Returns:
        True if successfully saved, False otherwise.
    """
    try:
        path = _get_cookies_path(user_id)
        # Convert list of cookies to JSON string
        cookies_json = json.dumps(cookies, indent=2)
        # Encrypt JSON string using the app's master key
        encrypted_data = encrypt_credential(cookies_json)
        
        with open(path, "w", encoding="utf-8") as f:
            f.write(encrypted_data)
        print(f"  [LinkedIn Session] Encrypted cookies saved -> {path}")
        return True
    except Exception as e:
        print(f"  [LinkedIn Session] Error saving encrypted session: {e}")
        return False


def load_session(user_id: int) -> list[dict] | None:
    """
    Load the encrypted session cookies from disk and decrypt them.
    
    Args:
        user_id: The database ID of the user.
        
    Returns:
        List of decrypted cookie dicts if successful, None otherwise.
    """
    try:
        path = _get_cookies_path(user_id)
        if not os.path.exists(path):
            return None
            
        with open(path, "r", encoding="utf-8") as f:
            encrypted_data = f.read().strip()
            
        if not encrypted_data:
            return None
            
        # Decrypt cookies JSON string
        cookies_json = decrypt_credential(encrypted_data)
        
        # Parse JSON
        cookies = json.loads(cookies_json)
        return cookies
    except Exception as e:
        print(f"  [LinkedIn Session] Error loading/decrypting session: {e}")
        return None


async def is_session_valid(page) -> bool:
    """
    Navigate to the LinkedIn feed page and check if the session is authenticated.
    
    Args:
        page: Playwright page object.
        
    Returns:
        True if authenticated, False if redirected/logged out.
    """
    try:
        print("  [LinkedIn Session] Testing session validity...")
        # Navigate to LinkedIn feed page (requires authentication)
        await page.goto("https://www.linkedin.com/feed/", wait_until="domcontentloaded", timeout=20000)
        await page.wait_for_timeout(2000)
        
        url = page.url
        # If redirected to login, signup, or checkpoint, it's invalid
        if "login" in url or "signup" in url or "checkpoint" in url:
            print(f"  [LinkedIn Session] Session invalid (Redirected to: {url})")
            return False
            
        # Check for profile identity module, global navigation bar, or feed presence
        profile_loaded = await page.locator("#global-nav, .feed-identity-module, [data-global-nav-container]").first.count() > 0
        if not profile_loaded:
            # Fallback: check if url contains feed and body is present
            profile_loaded = "feed" in url and await page.locator("body").count() > 0
            
        if profile_loaded:
            print("  [LinkedIn Session] Session is VALID")
            return True
            
        print("  [LinkedIn Session] Session is INVALID (Missing logged-in elements)")
        return False
    except Exception as e:
        print(f"  [LinkedIn Session] Expiration check failed: {e}")
        return False


async def login_linkedin(page, username, password) -> dict:
    """
    Automate the login flow on LinkedIn.com.
    
    Args:
        page: Playwright page object.
        username: User's LinkedIn email/username.
        password: User's decrypted password.
        
    Returns:
        dict: {"success": bool, "reason": str, "message": str}
    """
    print("  [LinkedIn Session] Navigating to LinkedIn login page...")
    try:
        await page.goto("https://www.linkedin.com/login", wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(2000)
        
        # Verify if already auto-logged in
        if "feed" in page.url:
            print("  [LinkedIn Session] Already logged in (auto-redirected)")
            return {"success": True}
            
        # Selectors for username/password supporting obfuscated input names/IDs
        username_sel = "input#username, input[name='session_key'], input[type='email'], input[type='text']"
        password_sel = "input#password, input[name='session_password'], input[type='password']"
        submit_sel = "button[type='submit']"
        
        # Wait for input tags to exist in DOM
        await page.wait_for_selector("input", state="attached", timeout=15000)
        
        # Find the visible username input
        username_input = None
        for el in await page.locator(username_sel).all():
            if await el.is_visible():
                username_input = el
                break
                
        # Find the visible password input
        password_input = None
        for el in await page.locator(password_sel).all():
            if await el.is_visible():
                password_input = el
                break
                
        if not username_input or not password_input:
            # Fallback if visibility check fails
            username_input = page.locator(username_sel).first
            password_input = page.locator(password_sel).first
            
        print("  [LinkedIn Session] Submitting credentials...")
        await username_input.fill(username)
        await password_input.fill(password)
        
        # Find the visible submit button
        submit_btn = None
        for el in await page.locator("button").all():
            text = (await el.inner_text()).strip().lower()
            if text == "sign in" and await el.is_visible():
                submit_btn = el
                break
                
        if not submit_btn:
            # Fallback to selector
            submit_sel = "button[type='submit'], input[type='submit']"
            for el in await page.locator(submit_sel).all():
                if await el.is_visible():
                    submit_btn = el
                    break
        if not submit_btn:
            submit_btn = page.locator("button[type='submit']").first
            
        await submit_btn.click()
        
        # Wait to check result
        await page.wait_for_timeout(3000)
        
        # Check for credential error
        # Common elements: #error-for-username, #error-for-password, or alert dialogs
        error_visible = await page.locator("#error-for-username, #error-for-password, .artdeco-inline-feedback--error").first.is_visible()
        if error_visible:
            err_text = ""
            for locator in [page.locator("#error-for-username"), page.locator("#error-for-password"), page.locator(".artdeco-inline-feedback--error")]:
                if await locator.first.is_visible():
                    err_text = await locator.first.inner_text()
                    break
            print(f"  [LinkedIn Session] Login error displayed: {err_text}")
            try:
                os.makedirs("scratch", exist_ok=True)
                await page.screenshot(path="scratch/linkedin_login_failure.png")
                print("  [LinkedIn Session] Saved failure screenshot to scratch/linkedin_login_failure.png")
            except Exception as se:
                print(f"  [LinkedIn Session] Screenshot failed: {se}")
            return {"success": False, "reason": "invalid_credentials", "message": err_text or "Invalid credentials"}
            
        # Check for Captcha / Bot protection / Checkpoint Challenge
        # LinkedIn often uses checkpoint / challenge
        if "checkpoint" in page.url or "challenge" in page.url:
            print("  [LinkedIn Session] Security checkpoint/challenge detected")
            return {"success": False, "reason": "challenge_required", "message": "Verification challenge / OTP required."}
            
        # Wait for redirects
        for _ in range(5):
            url = page.url
            if "feed" in url:
                print("  [LinkedIn Session] Login successful!")
                return {"success": True}
            await page.wait_for_timeout(1000)
            
        # Final URL check
        if "feed" in page.url:
            print("  [LinkedIn Session] Login successful!")
            return {"success": True}
        else:
            # If we're still stuck, check if there's any challenge or captcha
            if "checkpoint" in page.url or "challenge" in page.url:
                print("  [LinkedIn Session] Security checkpoint/challenge detected (delayed)")
                return {"success": False, "reason": "challenge_required", "message": "Verification challenge / OTP required."}
            print(f"  [LinkedIn Session] Login flow stuck on page: {page.url}")
            return {"success": False, "reason": "unknown_state", "message": f"Stuck on page: {page.url}"}
            
    except Exception as e:
        print(f"  [LinkedIn Session] Login automation error: {e}")
        return {"success": False, "reason": "exception", "message": str(e)}
