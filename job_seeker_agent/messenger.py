"""
messenger.py — LinkedIn messaging automation.

Uses Playwright to send messages to existing LinkedIn connections.
"""

import os
import sys

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)


async def send_messages(
    linkedin_username: str,
    linkedin_password: str,
    messages: list[dict],
    dry_run: bool = False,
) -> list[dict]:
    """Send LinkedIn messages to existing connections.

    Args:
        linkedin_username: LinkedIn login email
        linkedin_password: LinkedIn login password (decrypted)
        messages: List of dicts: [{profile_url, message_text}]
        dry_run: If True, simulate without sending

    Returns:
        List of result dicts: [{profile_url, status, message}]
    """
    results = []

    if dry_run:
        for m in messages:
            results.append({"profile_url": m["profile_url"], "status": "dry_run", "message": "Simulated"})
        return results

    try:
        from playwright.async_api import async_playwright

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context()
            page = await context.new_page()

            # Login
            await page.goto("https://www.linkedin.com/login")
            await page.fill("#username", linkedin_username)
            await page.fill("#password", linkedin_password)
            await page.click("button[type='submit']")
            await page.wait_for_timeout(3000)

            if "feed" not in page.url and "mynetwork" not in page.url:
                await browser.close()
                return [{"profile_url": "", "status": "error", "message": "Login failed"}]

            for msg in messages:
                try:
                    result = await _send_single_message(page, msg["profile_url"], msg["message_text"])
                    results.append(result)
                    await page.wait_for_timeout(2000)
                except Exception as e:
                    results.append({"profile_url": msg["profile_url"], "status": "error", "message": str(e)})

            await browser.close()

    except ImportError:
        results.append({"profile_url": "", "status": "error", "message": "Playwright not installed"})
    except Exception as e:
        results.append({"profile_url": "", "status": "error", "message": str(e)})

    return results


async def _send_single_message(page, profile_url: str, text: str) -> dict:
    """Send a message to a single LinkedIn profile."""
    await page.goto(profile_url)
    await page.wait_for_timeout(1500)

    msg_btn = page.locator("button:has-text('Message')").first
    if not await msg_btn.is_visible():
        return {"profile_url": profile_url, "status": "error", "message": "Not connected"}

    await msg_btn.click()
    await page.wait_for_timeout(1500)

    # Type message in the chat box
    chat_box = page.locator("div[role='textbox']").first
    if await chat_box.is_visible():
        await chat_box.fill(text)
        await page.wait_for_timeout(500)

        send_btn = page.locator("button[type='submit']:has-text('Send')").first
        if not await send_btn.is_visible():
            send_btn = page.locator("button.msg-form__send-button").first

        if await send_btn.is_visible():
            await send_btn.click()
            await page.wait_for_timeout(1000)
            return {"profile_url": profile_url, "status": "sent", "message": text[:50]}

    return {"profile_url": profile_url, "status": "error", "message": "Could not send"}
