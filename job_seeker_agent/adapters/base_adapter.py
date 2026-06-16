"""
base_adapter.py — Abstract base class for ATS form-filling adapters.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class ApplyResult:
    """Result of an application attempt."""
    success: bool
    status: str             # applied|failed|paused
    confirmation_id: str = ""
    screenshot_path: str = ""
    dom_snapshot: str = ""
    error_message: str = ""
    failure_type: str = ""  # captcha|auth_required|unsupported_ats|form_error|network|unknown
    page_url: str = ""
    recorded_steps: list = field(default_factory=list)  # Steps discovered during application


class ATSAdapter(ABC):
    """Base class for ATS-specific form filling."""
    ats_type: str = "unknown"

    @abstractmethod
    async def fill_and_submit(
        self,
        session,  # BrowserSession
        url: str,
        profile: dict,
        resume_path: str,
        cover_letter: str = "",
        portal_memory: str = "",
    ) -> ApplyResult:
        """Fill the application form and submit it.

        Args:
            session: BrowserSession instance (Hyperbrowser or Playwright)
            url: The application URL
            profile: User profile dict with keys like:
                name, last_name, email, phone, linkedin_url,
                current_title, years_experience, etc.
            resume_path: Path to the resume file to upload
            cover_letter: Cover letter text (empty if not mandatory)
            portal_memory: Cached portal knowledge markdown (from apply_history/)
                If provided, the adapter should follow cached steps instead of
                re-exploring.  If empty, the adapter explores and records steps.

        Returns:
            ApplyResult with the outcome (including recorded_steps if exploring)
        """
        ...

    async def _safe_fill(self, session, selector: str, value: str) -> bool:
        """Fill a field only if it exists. Returns True if filled."""
        try:
            exists = await session.element_exists(selector)
            if exists and value:
                await session.fill(selector, value)
                return True
        except Exception:
            pass
        return False

    async def _safe_click(self, session, selector: str, timeout: int = 5000) -> bool:
        """Click an element only if it exists. Returns True if clicked."""
        try:
            exists = await session.element_exists(selector)
            if exists:
                await session.click(selector, timeout=timeout)
                return True
        except Exception:
            pass
        return False

    async def _safe_upload(self, session, selector: str, file_path: str) -> bool:
        """Upload a file only if the input exists. Returns True if uploaded."""
        try:
            exists = await session.element_exists(selector)
            if exists and file_path:
                await session.upload_file(selector, file_path)
                return True
        except Exception:
            pass
        return False

    async def _check_captcha(self, session) -> bool:
        """Check if a CAPTCHA is present on the page."""
        captcha_selectors = [
            "iframe[src*='recaptcha']",
            "iframe[src*='hcaptcha']",
            ".g-recaptcha",
            ".h-captcha",
            "[data-sitekey]",
            "iframe[title*='captcha']",
        ]
        for sel in captcha_selectors:
            if await session.element_exists(sel):
                return True
        return False

    def _make_step(self, step_num: int, description: str, selector: str = "", action: str = "") -> dict:
        """Create a step record for portal memory capture."""
        return {
            "step_num": step_num,
            "description": description,
            "selector": selector,
            "action": action,
        }

    async def _check_confirmation(self, session, keywords: list[str] | None = None) -> str:
        """Check the page for confirmation text. Returns the confirmation text if found."""
        if keywords is None:
            keywords = [
                "application submitted",
                "thank you for applying",
                "application received",
                "successfully submitted",
                "your application has been submitted",
                "we have received your application",
                "thank you for your interest",
            ]
        try:
            page_text = await session.get_page_text()
            text_lower = page_text.lower()
            for kw in keywords:
                if kw.lower() in text_lower:
                    # Extract a snippet around the match
                    idx = text_lower.index(kw.lower())
                    start = max(0, idx - 20)
                    end = min(len(page_text), idx + len(kw) + 50)
                    return page_text[start:end].strip()
        except Exception:
            pass
        return ""
