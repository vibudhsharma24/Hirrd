"""
connector.py — LinkedIn connection request automation.

Uses Playwright to send connection requests to target profiles.
This module is part of the LinkedIn interaction layer (NOT job discovery).
"""

import os
import sys

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)


async def send_connection_requests(
    linkedin_username: str,
    linkedin_password: str,
    target_urls: list[str],
    message_template: str = "",
    limit: int = 5,
    dry_run: bool = False,
) -> list[dict]:
    """Send LinkedIn connection requests to a list of profile URLs.

    Args:
        linkedin_username: LinkedIn login email
        linkedin_password: LinkedIn login password (decrypted)
        target_urls: List of LinkedIn profile URLs to connect with
        message_template: Optional connection note (max 300 chars)
        limit: Max connections to send per run
        dry_run: If True, simulate without actually sending

    Returns:
        List of result dicts: [{url, status: 'sent'|'already_connected'|'error', message}]
    """
    results = []

    if dry_run:
        for url in target_urls[:limit]:
            results.append({"url": url, "status": "dry_run", "message": "Simulated"})
        return results

    try:
        from playwright.async_api import async_playwright

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context()
            page = await context.new_page()

            # Login to LinkedIn
            await page.goto("https://www.linkedin.com/login")
            await page.fill("#username", linkedin_username)
            await page.fill("#password", linkedin_password)
            await page.click("button[type='submit']")
            await page.wait_for_timeout(3000)

            # Check if login was successful
            if "feed" not in page.url and "mynetwork" not in page.url:
                print("[Connector] LinkedIn login failed")
                await browser.close()
                return [{"url": "", "status": "error", "message": "Login failed"}]

            # Send connection requests
            for url in target_urls[:limit]:
                try:
                    result = await _send_single_request(page, url, message_template)
                    results.append(result)
                    await page.wait_for_timeout(2000)  # Rate limiting
                except Exception as e:
                    results.append({"url": url, "status": "error", "message": str(e)})

            await browser.close()

    except ImportError:
        print("[Connector] Playwright not installed")
        results.append({"url": "", "status": "error", "message": "Playwright not installed"})
    except Exception as e:
        print(f"[Connector] Error: {e}")
        results.append({"url": "", "status": "error", "message": str(e)})

    return results


async def _send_single_request(page, profile_url: str, message: str = "") -> dict:
    """Send a connection request to a single profile."""
    await page.goto(profile_url)
    await page.wait_for_timeout(1500)

    # Look for Connect button
    connect_btn = page.locator("button:has-text('Connect')").first
    if not await connect_btn.is_visible():
        # Check if already connected
        msg_btn = page.locator("button:has-text('Message')").first
        if await msg_btn.is_visible():
            return {"url": profile_url, "status": "already_connected", "message": ""}
        return {"url": profile_url, "status": "error", "message": "Connect button not found"}

    await connect_btn.click()
    await page.wait_for_timeout(1000)

    # Add note if provided
    if message:
        add_note = page.locator("button:has-text('Add a note')").first
        if await add_note.is_visible():
            await add_note.click()
            await page.wait_for_timeout(500)
            textarea = page.locator("textarea[name='message']").first
            if await textarea.is_visible():
                await textarea.fill(message[:300])

    # Send
    send_btn = page.locator("button:has-text('Send')").first
    if await send_btn.is_visible():
        await send_btn.click()
        await page.wait_for_timeout(1000)
        return {"url": profile_url, "status": "sent", "message": message[:50] if message else ""}

    return {"url": profile_url, "status": "error", "message": "Could not find Send button"}


async def verify_linkedin_login_and_get_name(username, password) -> str:
    """Logs in to LinkedIn and returns the profile's full name, or raises on failure."""
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-blink-features=AutomationControlled",
            ]
        )
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        page = await context.new_page()
        try:
            await page.goto("https://www.linkedin.com/login", timeout=20000)
            await page.fill("#username", username)
            await page.fill("#password", password)
            await page.click("button[type='submit']")
            await page.wait_for_timeout(3000)

            # Check for OTP or login wall
            if "checkpoint" in page.url:
                raise ValueError("LinkedIn login triggered security verification.")
            if "login" in page.url or "login-submit" in page.url:
                raise ValueError("Invalid credentials or login blocked.")

            # Navigate to feed to fetch actor name
            await page.goto("https://www.linkedin.com/feed/", timeout=20000)
            await page.wait_for_timeout(2000)

            # Find the user's name
            name = await page.evaluate("""() => {
                // Try feed sidebar actor link
                let el = document.querySelector('.feed-identity-module__actor-meta a');
                if (el && el.innerText.trim()) return el.innerText.trim();

                // Try me photo alt attribute
                let img = document.querySelector('img.global-nav__me-photo');
                if (img && img.alt) {
                    return img.alt.replace('Photo of', '').trim();
                }
                return '';
            }""")

            if name:
                return name
            return "LinkedIn User"
        finally:
            await browser.close()

