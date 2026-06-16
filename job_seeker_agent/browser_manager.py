"""
browser_manager.py
──────────────────
Unified browser session interface for the auto-apply engine.

Two modes:
  1. HyperbrowserSession — Cloud browser via Hyperbrowser API
     (stealth, proxies, CAPTCHA solving built in)
  2. LocalPlaywrightSession — Local headless browser via Playwright
     (fallback when no HYPERBROWSER_API_KEY is set)

Both expose the same BrowserSession interface so adapters
don't need to know which backend is active.
"""

import asyncio
import os
import json
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from pathlib import Path

# Try loading .env
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

SCREENSHOTS_DIR = os.path.join(os.path.dirname(__file__), "screenshots")
os.makedirs(SCREENSHOTS_DIR, exist_ok=True)

HYPERBROWSER_API_KEY = os.environ.get("HYPERBROWSER_API_KEY", "")


class BrowserSession(ABC):
    """Abstract interface for browser automation."""

    @abstractmethod
    async def goto(self, url: str, wait_until: str = "domcontentloaded", timeout: int = 30000) -> None:
        """Navigate to a URL."""
        ...

    @abstractmethod
    async def fill(self, selector: str, value: str) -> None:
        """Fill a form field identified by CSS selector."""
        ...

    @abstractmethod
    async def click(self, selector: str, timeout: int = 5000) -> None:
        """Click an element identified by CSS selector."""
        ...

    @abstractmethod
    async def upload_file(self, selector: str, file_path: str) -> None:
        """Upload a file to a file input element."""
        ...

    @abstractmethod
    async def screenshot(self, name: str = "") -> str:
        """Take a screenshot and save it. Returns the file path."""
        ...

    @abstractmethod
    async def get_dom_snapshot(self) -> str:
        """Get the current page's HTML content."""
        ...

    @abstractmethod
    async def get_page_text(self) -> str:
        """Get visible text content of the page."""
        ...

    @abstractmethod
    async def get_page_url(self) -> str:
        """Get the current page URL."""
        ...

    @abstractmethod
    async def wait_for_selector(self, selector: str, timeout: int = 10000) -> bool:
        """Wait for an element to appear. Returns True if found, False if timed out."""
        ...

    @abstractmethod
    async def wait(self, ms: int) -> None:
        """Wait for a specified number of milliseconds."""
        ...

    @abstractmethod
    async def type_text(self, selector: str, text: str, delay: int = 50) -> None:
        """Type text character by character (more human-like than fill)."""
        ...

    @abstractmethod
    async def select_option(self, selector: str, value: str) -> None:
        """Select an option from a dropdown."""
        ...

    @abstractmethod
    async def get_element_text(self, selector: str) -> str:
        """Get the text content of an element."""
        ...

    @abstractmethod
    async def element_exists(self, selector: str) -> bool:
        """Check if an element exists on the page."""
        ...

    @abstractmethod
    async def get_page(self):
        """Get the underlying Playwright page object (for advanced use)."""
        ...

    @abstractmethod
    async def close(self) -> None:
        """Close the browser session and clean up resources."""
        ...

    def _screenshot_path(self, name: str = "") -> str:
        """Generate a screenshot file path."""
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        filename = f"{name}_{ts}.png" if name else f"screenshot_{ts}.png"
        return os.path.join(SCREENSHOTS_DIR, filename)


class HyperbrowserSession(BrowserSession):
    """Cloud browser via Hyperbrowser API.

    Provides stealth mode, proxy rotation, and CAPTCHA solving.
    """

    def __init__(self):
        self._client = None
        self._session = None
        self._browser = None
        self._context = None
        self._page = None

    async def start(self, headed: bool = False):
        """Initialize a Hyperbrowser cloud session."""
        try:
            from hyperbrowser import AsyncHyperbrowser
            from playwright.async_api import async_playwright

            self._client = AsyncHyperbrowser(api_key=HYPERBROWSER_API_KEY)

            # Create a session with stealth + CAPTCHA solving enabled
            self._session = await self._client.sessions.create(
                solveCaptchas=True,
                useStealthMode=True,
            )
            print(f"  [HB] Cloud session created: {self._session.id}")

            # Connect Playwright to the cloud browser via CDP
            self._pw = await async_playwright().start()
            self._browser = await self._pw.chromium.connect_over_cdp(
                self._session.wsEndpoint
            )
            self._context = self._browser.contexts[0]
            self._page = self._context.pages[0]

        except ImportError:
            raise RuntimeError(
                "Hyperbrowser SDK not installed. Run: pip install hyperbrowser"
            )
        except Exception as e:
            raise RuntimeError(f"Failed to create Hyperbrowser session: {e}")

    async def goto(self, url, wait_until="domcontentloaded", timeout=30000):
        await self._page.goto(url, wait_until=wait_until, timeout=timeout)

    async def fill(self, selector, value):
        await self._page.fill(selector, value)

    async def click(self, selector, timeout=5000):
        await self._page.click(selector, timeout=timeout)

    async def upload_file(self, selector, file_path):
        await self._page.set_input_files(selector, file_path)

    async def screenshot(self, name=""):
        path = self._screenshot_path(name)
        await self._page.screenshot(path=path, full_page=False)
        return path

    async def get_dom_snapshot(self):
        return await self._page.content()

    async def get_page_text(self):
        return await self._page.inner_text("body")

    async def get_page_url(self):
        return self._page.url

    async def wait_for_selector(self, selector, timeout=10000):
        try:
            await self._page.wait_for_selector(selector, timeout=timeout)
            return True
        except Exception:
            return False

    async def wait(self, ms):
        await self._page.wait_for_timeout(ms)

    async def type_text(self, selector, text, delay=50):
        await self._page.type(selector, text, delay=delay)

    async def select_option(self, selector, value):
        await self._page.select_option(selector, value)

    async def get_element_text(self, selector):
        try:
            elem = self._page.locator(selector).first
            if await elem.count() > 0:
                return await elem.inner_text()
        except Exception:
            pass
        return ""

    async def element_exists(self, selector):
        try:
            count = await self._page.locator(selector).count()
            return count > 0
        except Exception:
            return False

    async def get_page(self):
        return self._page

    async def close(self):
        try:
            if self._browser:
                await self._browser.close()
            if self._pw:
                await self._pw.stop()
            if self._client and self._session:
                await self._client.sessions.stop(self._session.id)
                print(f"  [HB] Session {self._session.id} stopped")
        except Exception as e:
            print(f"  [HB] Cleanup warning: {e}")


class LocalPlaywrightSession(BrowserSession):
    """Local headless browser via Playwright.

    Fallback when no HYPERBROWSER_API_KEY is set.
    Uses stealth-like settings (user agent, viewport, etc.)
    """

    def __init__(self):
        self._pw = None
        self._browser = None
        self._context = None
        self._page = None

    async def start(self, headed: bool = False):
        """Initialize a local Playwright browser session."""
        from playwright.async_api import async_playwright

        self._pw = await async_playwright().start()
        self._browser = await self._pw.chromium.launch(
            headless=not headed,
            args=[
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-blink-features=AutomationControlled",
                "--disable-infobars",
            ],
        )
        self._context = await self._browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1366, "height": 768},
            locale="en-US",
        )
        # Stealth: hide webdriver property
        await self._context.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
        """)
        self._page = await self._context.new_page()
        print("  [PW] Local browser session started" + (" (headed)" if headed else ""))

    async def goto(self, url, wait_until="domcontentloaded", timeout=30000):
        await self._page.goto(url, wait_until=wait_until, timeout=timeout)

    async def fill(self, selector, value):
        await self._page.fill(selector, value)

    async def click(self, selector, timeout=5000):
        await self._page.click(selector, timeout=timeout)

    async def upload_file(self, selector, file_path):
        await self._page.set_input_files(selector, file_path)

    async def screenshot(self, name=""):
        path = self._screenshot_path(name)
        await self._page.screenshot(path=path, full_page=False)
        return path

    async def get_dom_snapshot(self):
        return await self._page.content()

    async def get_page_text(self):
        return await self._page.inner_text("body")

    async def get_page_url(self):
        return self._page.url

    async def wait_for_selector(self, selector, timeout=10000):
        try:
            await self._page.wait_for_selector(selector, timeout=timeout)
            return True
        except Exception:
            return False

    async def wait(self, ms):
        await self._page.wait_for_timeout(ms)

    async def type_text(self, selector, text, delay=50):
        await self._page.type(selector, text, delay=delay)

    async def select_option(self, selector, value):
        await self._page.select_option(selector, value)

    async def get_element_text(self, selector):
        try:
            elem = self._page.locator(selector).first
            if await elem.count() > 0:
                return await elem.inner_text()
        except Exception:
            pass
        return ""

    async def element_exists(self, selector):
        try:
            count = await self._page.locator(selector).count()
            return count > 0
        except Exception:
            return False

    async def get_page(self):
        return self._page

    async def close(self):
        try:
            if self._browser:
                await self._browser.close()
            if self._pw:
                await self._pw.stop()
            print("  [PW] Local session closed")
        except Exception as e:
            print(f"  [PW] Cleanup warning: {e}")


# ── Session Factory ────────────────────────────────────────────────────────────

async def create_session(headed: bool = False) -> BrowserSession:
    """Factory: returns Hyperbrowser session if API key is set, else local Playwright.

    Args:
        headed: Show browser window (only applies to local Playwright mode).

    Returns:
        A ready-to-use BrowserSession instance.
    """
    if HYPERBROWSER_API_KEY:
        print("  [Browser] Using Hyperbrowser cloud session")
        session = HyperbrowserSession()
        await session.start(headed=headed)
        return session
    else:
        print("  [Browser] Using local Playwright (no HYPERBROWSER_API_KEY set)")
        session = LocalPlaywrightSession()
        await session.start(headed=headed)
        return session


def get_browser_mode() -> str:
    """Return which browser mode will be used."""
    return "hyperbrowser" if HYPERBROWSER_API_KEY else "playwright"
