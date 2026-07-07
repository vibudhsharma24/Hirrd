"""
session_manager.py
──────────────────
Handles secure session loading, saving, encryption at rest, and automated login/validation
for Naukri AI Agent.
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
    return os.path.join(SESSIONS_DIR, f"naukri_cookies_{user_id}.enc")


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
        print(f"  [Naukri Session] Encrypted cookies saved -> {path}")
        return True
    except Exception as e:
        print(f"  [Naukri Session] Error saving encrypted session: {e}")
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
        print(f"  [Naukri Session] Error loading/decrypting session: {e}")
        return None


async def is_session_valid(page) -> bool:
    """
    Navigate to the Naukri profile page and check if the session is authenticated.
    
    Args:
        page: Playwright page object.
        
    Returns:
        True if authenticated, False if redirected/logged out.
    """
    try:
        # Navigate to Naukri user profile page (server-enforced authentication required)
        print("  [Naukri Session] Testing session validity...")
        await page.goto("https://www.naukri.com/mnjuser/profile", wait_until="domcontentloaded", timeout=20000)
        await page.wait_for_timeout(2000)
        
        # Check current URL
        url = page.url
        if "/nlogin/login" in url or "mnjuser" not in url:
            print(f"  [Naukri Session] Session invalid (Redirected to: {url})")
            return False
            
        # Check for profile elements to confirm full load
        profile_loaded = await page.locator("div.profile-summary, div.profile-holder, .nProfileCard").first.count() > 0
        # If selectors are not immediately matched, check if main body exists
        if not profile_loaded:
            profile_loaded = await page.locator("body").count() > 0 and "mnjuser" in url
            
        if profile_loaded:
            print("  [Naukri Session] Session is VALID")
            return True
            
        return False
    except Exception as e:
        print(f"  [Naukri Session] Expiration check failed: {e}")
        return False


async def login_naukri(page, username, password) -> dict:
    """
    Automate the login flow on Naukri.com.
    
    Args:
        page: Playwright page object.
        username: User's Naukri email/username.
        password: User's decrypted password.
        
    Returns:
        dict: {"success": bool, "reason": str, "message": str}
    """
    print("  [Naukri Session] Navigating to Naukri login page...")
    try:
        await page.goto("https://www.naukri.com/nlogin/login", wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(2000)
        
        # Verify if already auto-logged in
        if "/feed" in page.url or "mnjuser" in page.url:
            print("  [Naukri Session] Already logged in (auto-redirected)")
            return {"success": True}
            
        # Selectors
        username_sel = "input#usernameField"
        password_sel = "input#passwordField"
        submit_sel = "button.blue-btn[type='submit']"
        error_sel = ".commonErrorMsg"
        
        await page.wait_for_selector(username_sel, state="visible", timeout=10000)
        
        # Fill credentials
        print("  [Naukri Session] Submitting credentials...")
        await page.fill(username_sel, username)
        await page.fill(password_sel, password)
        await page.click(submit_sel)
        
        # Wait to check result
        await page.wait_for_timeout(3000)
        
        # Check for credential error
        if await page.locator(error_sel).first.is_visible():
            err_text = await page.locator(error_sel).first.inner_text()
            print(f"  [Naukri Session] Login error displayed: {err_text}")
            try:
                os.makedirs("scratch", exist_ok=True)
                await page.screenshot(path="scratch/naukri_login_failure.png")
                print("  [Naukri Session] Saved failure screenshot to scratch/naukri_login_failure.png")
            except Exception as se:
                print(f"  [Naukri Session] Screenshot failed: {se}")
            return {"success": False, "reason": "invalid_credentials", "message": err_text}
            
        # Check for Captcha / Bot protection
        captcha_visible = await page.locator(".g-recaptcha, iframe[src*='recaptcha'], #recaptcha-anchor").first.is_visible()
        if captcha_visible:
            print("  [Naukri Session] Captcha trigger detected")
            return {"success": False, "reason": "captcha_required", "message": "Captcha solving required."}
            
        # Check for OTP page redirect
        # Naukri sometimes redirects to verify OTP or verify mobile/email on login
        if "otp" in page.url.lower() or "verify" in page.url.lower():
            print("  [Naukri Session] OTP challenge detected")
            return {"success": False, "reason": "otp_required", "message": "OTP Verification required."}
            
        # Wait for redirects
        for _ in range(5):
            url = page.url
            if "mnjuser" in url or "homepage" in url:
                print("  [Naukri Session] Login successful!")
                return {"success": True}
            await page.wait_for_timeout(1000)
            
        # Final URL check
        if "mnjuser" in page.url or "homepage" in page.url:
            print("  [Naukri Session] Login successful!")
            return {"success": True}
        else:
            print(f"  [Naukri Session] Login flow stuck on page: {page.url}")
            return {"success": False, "reason": "unknown_state", "message": f"Stuck on page: {page.url}"}
            
    except Exception as e:
        print(f"  [Naukri Session] Login automation error: {e}")
        return {"success": False, "reason": "exception", "message": str(e)}
