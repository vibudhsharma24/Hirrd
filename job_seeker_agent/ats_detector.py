"""
ats_detector.py
───────────────
Detects which Applicant Tracking System (ATS) is behind a given career URL.

Two-phase detection:
  Phase 1: URL pattern matching (fast, no browser needed)
  Phase 2: DOM fingerprinting (browser-based, for embedded/custom career pages)

Covers the top 6 ATS platforms:
  - Greenhouse (boards.greenhouse.io)
  - Lever (jobs.lever.co)
  - Workday (*.myworkdayjobs.com)
  - Ashby (jobs.ashbyhq.com)
  - SmartRecruiters (jobs.smartrecruiters.com)
  - Custom / Unknown (fallback)
"""

import re
from dataclasses import dataclass, field
from urllib.parse import urlparse


@dataclass
class ATSResult:
    """Result of ATS detection."""
    ats_type: str           # greenhouse|lever|workday|ashby|smartrecruiters|custom
    confidence: float       # 0.0–1.0
    hostname: str           # extracted hostname from the URL
    requires_login: bool    # whether the portal typically requires account creation
    url: str                # the original URL
    detection_method: str   # "url_pattern" or "dom_fingerprint"


# ── Phase 1: URL Pattern Matching ──────────────────────────────────────────────

ATS_URL_PATTERNS: dict[str, list[dict]] = {
    "greenhouse": [
        {"pattern": r"boards\.greenhouse\.io", "confidence": 0.95, "login": False},
        {"pattern": r"job-boards\.greenhouse\.io", "confidence": 0.95, "login": False},
        {"pattern": r"[a-z0-9-]+\.greenhouse\.io", "confidence": 0.90, "login": False},
    ],
    "lever": [
        {"pattern": r"jobs\.lever\.co", "confidence": 0.95, "login": False},
        {"pattern": r"[a-z0-9-]+\.lever\.co", "confidence": 0.90, "login": False},
    ],
    "workday": [
        {"pattern": r"[a-z0-9-]+\.myworkdayjobs\.com", "confidence": 0.95, "login": True},
        {"pattern": r"[a-z0-9-]+\.wd\d+\.myworkdayjobs\.com", "confidence": 0.95, "login": True},
        {"pattern": r"workday\.com", "confidence": 0.80, "login": True},
    ],
    "ashby": [
        {"pattern": r"jobs\.ashbyhq\.com", "confidence": 0.95, "login": False},
        {"pattern": r"[a-z0-9-]+\.ashbyhq\.com", "confidence": 0.90, "login": False},
    ],
    "smartrecruiters": [
        {"pattern": r"jobs\.smartrecruiters\.com", "confidence": 0.95, "login": False},
        {"pattern": r"[a-z0-9-]+\.smartrecruiters\.com", "confidence": 0.90, "login": False},
    ],
    "google_forms": [
        {"pattern": r"docs\.google\.com", "confidence": 0.95, "login": False},
        {"pattern": r"forms\.gle", "confidence": 0.95, "login": False},
    ],
}


def detect_from_url(url: str) -> ATSResult | None:
    """Phase 1: Detect ATS type from the URL pattern alone.

    Returns ATSResult if detected, None if no pattern matches.
    """
    if not url:
        return None

    # Special case: Google Forms detected by path, not just hostname
    if "docs.google.com/forms" in url or "forms.gle/" in url:
        return ATSResult(
            ats_type="google_forms",
            confidence=0.95,
            hostname="google-forms",
            requires_login=False,
            url=url,
            detection_method="url_pattern",
        )

    try:
        parsed = urlparse(url)
        hostname = (parsed.hostname or "").lower()
    except Exception:
        return None

    if not hostname:
        return None

    for ats_type, patterns in ATS_URL_PATTERNS.items():
        for p in patterns:
            if re.search(p["pattern"], hostname, re.IGNORECASE):
                return ATSResult(
                    ats_type=ats_type,
                    confidence=p["confidence"],
                    hostname=hostname,
                    requires_login=p["login"],
                    url=url,
                    detection_method="url_pattern",
                )

    return None


# ── Phase 2: DOM Fingerprinting ────────────────────────────────────────────────

# Signatures to search for in the page's HTML source
DOM_FINGERPRINTS: dict[str, list[dict]] = {
    "greenhouse": [
        {"selector": "#grnhse_app", "type": "id", "confidence": 0.90},
        {"selector": "script[src*='boards.greenhouse.io']", "type": "css", "confidence": 0.85},
        {"selector": "iframe[src*='boards.greenhouse.io']", "type": "css", "confidence": 0.85},
        {"text": "greenhouse", "type": "meta_content", "confidence": 0.70},
    ],
    "lever": [
        {"text": "LeverPostings", "type": "script_content", "confidence": 0.90},
        {"selector": "script[src*='lever.co']", "type": "css", "confidence": 0.85},
        {"selector": "[data-lever-origin]", "type": "css", "confidence": 0.90},
        {"selector": ".posting-apply", "type": "css", "confidence": 0.70},
    ],
    "workday": [
        {"selector": "[data-automation-id]", "type": "css", "confidence": 0.80},
        {"text": "workday", "type": "meta_content", "confidence": 0.75},
        {"selector": "script[src*='workday']", "type": "css", "confidence": 0.85},
    ],
    "ashby": [
        {"selector": "[data-ashby-job-posting-id]", "type": "css", "confidence": 0.95},
        {"selector": "script[src*='ashbyhq.com']", "type": "css", "confidence": 0.90},
        {"text": "ashby", "type": "meta_content", "confidence": 0.70},
    ],
    "smartrecruiters": [
        {"selector": ".st-apply-button", "type": "css", "confidence": 0.85},
        {"selector": "script[src*='smartrecruiters']", "type": "css", "confidence": 0.85},
        {"text": "SmartRecruiters", "type": "script_content", "confidence": 0.80},
    ],
}


async def detect_from_dom(page, url: str) -> ATSResult | None:
    """Phase 2: Detect ATS type by inspecting the page's DOM.

    Args:
        page: A Playwright page object (already navigated to the URL).
        url: The original URL.

    Returns ATSResult if detected, None if no fingerprint matches.
    """
    hostname = ""
    try:
        parsed = urlparse(url)
        hostname = (parsed.hostname or "").lower()
    except Exception:
        pass

    best_match = None
    best_confidence = 0.0

    for ats_type, fingerprints in DOM_FINGERPRINTS.items():
        for fp in fingerprints:
            try:
                detected = False

                if fp["type"] == "id":
                    # Check if an element with this ID exists
                    elem_id = fp["selector"].lstrip("#")
                    count = await page.locator(f"#{elem_id}").count()
                    detected = count > 0

                elif fp["type"] == "css":
                    count = await page.locator(fp["selector"]).count()
                    detected = count > 0

                elif fp["type"] == "script_content":
                    # Check if any script tag contains this text
                    html = await page.content()
                    detected = fp["text"].lower() in html.lower()

                elif fp["type"] == "meta_content":
                    # Check meta tags and page source for the text
                    html = await page.content()
                    detected = fp["text"].lower() in html.lower()

                if detected and fp["confidence"] > best_confidence:
                    login_required = ats_type == "workday"
                    best_match = ATSResult(
                        ats_type=ats_type,
                        confidence=fp["confidence"],
                        hostname=hostname,
                        requires_login=login_required,
                        url=url,
                        detection_method="dom_fingerprint",
                    )
                    best_confidence = fp["confidence"]

            except Exception:
                continue

    return best_match


# ── Unified Detection ──────────────────────────────────────────────────────────

def detect_ats(url: str) -> ATSResult:
    """Phase 1 detection only (no browser needed).

    Returns the detected ATS type, or 'custom' if no match found.
    Use detect_ats_with_browser() for Phase 2 DOM-based detection.
    """
    result = detect_from_url(url)
    if result:
        return result

    # Fallback: return custom/unknown
    hostname = ""
    try:
        parsed = urlparse(url)
        hostname = (parsed.hostname or "").lower()
    except Exception:
        pass

    return ATSResult(
        ats_type="custom",
        confidence=0.0,
        hostname=hostname,
        requires_login=False,
        url=url,
        detection_method="none",
    )


async def detect_ats_with_browser(page, url: str) -> ATSResult:
    """Full 2-phase detection: URL patterns first, then DOM fingerprinting.

    Args:
        page: A Playwright page object (already navigated to the URL).
        url: The original URL.

    Returns ATSResult with the best match, or 'custom' if nothing found.
    """
    # Phase 1: URL pattern
    result = detect_from_url(url)
    if result and result.confidence >= 0.90:
        return result

    # Phase 2: DOM fingerprinting
    dom_result = await detect_from_dom(page, url)
    if dom_result:
        # Use DOM result if it's better than URL result
        if not result or dom_result.confidence > result.confidence:
            return dom_result

    # Return URL result if it exists (even lower confidence)
    if result:
        return result

    # Fallback: custom
    hostname = ""
    try:
        parsed = urlparse(url)
        hostname = (parsed.hostname or "").lower()
    except Exception:
        pass

    return ATSResult(
        ats_type="custom",
        confidence=0.0,
        hostname=hostname,
        requires_login=False,
        url=url,
        detection_method="none",
    )


# ── Utility ────────────────────────────────────────────────────────────────────

def get_supported_ats_types() -> list[str]:
    """Return list of all supported ATS type identifiers."""
    return ["greenhouse", "lever", "workday", "ashby", "smartrecruiters", "google_forms", "custom"]


def extract_hostname(url: str) -> str:
    """Extract and normalize the hostname from a URL."""
    try:
        parsed = urlparse(url)
        return (parsed.hostname or "").lower()
    except Exception:
        return ""
