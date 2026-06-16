"""
portal_memory.py
────────────────
Manages the apply_history/<hostname>.md knowledge base.

When the auto-apply engine successfully interacts with a portal, this module
records the page structure, CSS selectors, and application flow into a
markdown file.  On subsequent visits to the same portal the file is loaded
and fed as context so the agent can skip re-exploration and save credits.

Directory layout:
    apply_history/
      lever.co.md
      workday.com.md
      google-forms.md
      <hostname>.md
"""

import os
import re
import json
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

HISTORY_DIR = os.path.join(os.path.dirname(__file__), "apply_history")

# Hostname normalisation map — collapse many subdomains into one canonical key
_HOSTNAME_ALIASES: dict[str, str] = {
    "jobs.lever.co": "lever.co",
    "jobs.eu.lever.co": "lever.co",
    "boards.greenhouse.io": "greenhouse.io",
    "job-boards.greenhouse.io": "greenhouse.io",
    "jobs.ashbyhq.com": "ashby.com",
    "jobs.smartrecruiters.com": "smartrecruiters.com",
}

# Patterns that collapse an entire family of subdomains
_HOSTNAME_PATTERNS: list[tuple[str, str]] = [
    (r".*\.lever\.co$", "lever.co"),
    (r".*\.greenhouse\.io$", "greenhouse.io"),
    (r".*\.myworkdayjobs\.com$", "workday.com"),
    (r".*\.wd\d+\.myworkdayjobs\.com$", "workday.com"),
    (r".*\.ashbyhq\.com$", "ashby.com"),
    (r".*\.smartrecruiters\.com$", "smartrecruiters.com"),
]


# ── Hostname helpers ───────────────────────────────────────────────────────────

def normalize_hostname(url: str) -> str:
    """Extract and normalise the hostname from a URL.

    Examples:
        https://jobs.lever.co/stripe/abc        → lever.co
        https://msft.wd1.myworkdayjobs.com/x    → workday.com
        https://docs.google.com/forms/d/e/xxx    → google-forms
        https://careers.microsoft.com/job/123    → careers.microsoft.com
    """
    if not url:
        return ""

    # Google Forms special case
    if "docs.google.com/forms" in url or "forms.gle/" in url:
        return "google-forms"

    try:
        parsed = urlparse(url)
        hostname = (parsed.hostname or "").lower().strip(".")
    except Exception:
        return ""

    if not hostname:
        return ""

    # 1. Exact alias match
    if hostname in _HOSTNAME_ALIASES:
        return _HOSTNAME_ALIASES[hostname]

    # 2. Pattern match
    for pattern, canonical in _HOSTNAME_PATTERNS:
        if re.match(pattern, hostname):
            return canonical

    # 3. Return as-is
    return hostname


def _memory_path(hostname: str) -> str:
    """Return the absolute path to the memory file for a hostname."""
    safe = hostname.replace("/", "_").replace("\\", "_")
    return os.path.join(HISTORY_DIR, f"{safe}.md")


# ── Read / Write / Update ─────────────────────────────────────────────────────

def get_portal_memory(hostname: str) -> str | None:
    """Load the portal memory file for a hostname.

    Args:
        hostname: Normalised hostname (e.g. "lever.co", "workday.com").

    Returns:
        The full markdown content, or None if no file exists.
    """
    path = _memory_path(hostname)
    if os.path.isfile(path):
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    return None


def get_portal_memory_for_url(url: str) -> tuple[str, str | None]:
    """Convenience: normalise a URL and return (hostname, memory_content).

    Returns:
        (hostname, memory_content_or_None)
    """
    hostname = normalize_hostname(url)
    if not hostname:
        return ("", None)
    return (hostname, get_portal_memory(hostname))


def save_portal_memory(hostname: str, content: str) -> str:
    """Write (or overwrite) the memory file for a hostname.

    Returns:
        The absolute path of the saved file.
    """
    os.makedirs(HISTORY_DIR, exist_ok=True)
    path = _memory_path(hostname)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    print(f"  [Memory] Saved portal memory → {os.path.basename(path)}")
    return path


def append_changelog(hostname: str, change_description: str) -> bool:
    """Append an entry to the ## Changelog section of a memory file.

    Returns True if the file was updated, False if no file exists.
    """
    content = get_portal_memory(hostname)
    if content is None:
        return False

    now = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    entry = f"| {now} | {change_description} |"

    if "## Changelog" in content:
        # Insert after the last table row in the changelog section
        content = content.rstrip() + "\n" + entry + "\n"
    else:
        # Add a new changelog section
        content = content.rstrip() + f"\n\n## Changelog\n| Date | Change |\n|------|--------|\n{entry}\n"

    save_portal_memory(hostname, content)
    return True


def append_applied_job(hostname: str, job_id: int, title: str, company: str, url: str) -> bool:
    """Track an applied job under ## Applied Jobs in the memory file."""
    content = get_portal_memory(hostname)
    if content is None:
        return False

    now = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    entry = f"| {now} | {job_id} | {title} | {company} | [link]({url}) |"

    if "## Applied Jobs" in content:
        content = content.rstrip() + "\n" + entry + "\n"
    else:
        content = content.rstrip() + (
            f"\n\n## Applied Jobs\n"
            f"| Date | Job ID | Title | Company | Link |\n"
            f"|------|--------|-------|---------|------|\n"
            f"{entry}\n"
        )

    save_portal_memory(hostname, content)
    return True


# ── Memory Generation ─────────────────────────────────────────────────────────

def build_memory_from_steps(
    hostname: str,
    ats_type: str,
    login_required: bool = False,
    resume_upload: str = "Yes (PDF)",
    cover_letter: str = "Optional",
    steps: list[dict] | None = None,
    known_quirks: list[str] | None = None,
    fields_needing_human: list[str] | None = None,
) -> str:
    """Generate a portal memory markdown string from recorded step data.

    Args:
        hostname: Normalised portal hostname.
        ats_type: ATS type string (lever, workday, google_forms, custom, etc.)
        login_required: Whether the portal requires account creation.
        resume_upload: Description of resume upload support.
        cover_letter: "Mandatory" / "Optional" / "Not present"
        steps: List of dicts with keys: step_num, action, selector, description
        known_quirks: List of quirk descriptions.
        fields_needing_human: List of fields the agent cannot auto-fill.

    Returns:
        The markdown string ready to be saved.
    """
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    type_label = {
        "lever": "ATS (Lever)",
        "workday": "Enterprise ATS (Workday)",
        "greenhouse": "ATS (Greenhouse)",
        "ashby": "ATS (Ashby)",
        "smartrecruiters": "ATS (SmartRecruiters)",
        "google_forms": "Google Form",
        "custom": "Custom / Company Careers",
    }.get(ats_type, "Custom")

    lines = [
        f"# Portal: {hostname}",
        f"> First seen: {now}  |  Last updated: {now}",
        "",
        "## Overview",
        f"- **Type:** {type_label}",
        f"- **Login required:** {'Yes' if login_required else 'No'}",
        f"- **Resume upload:** {resume_upload}",
        f"- **Cover letter field:** {cover_letter}",
        f"- **Easy Apply available:** No",
        "",
        "## Step-by-step Flow",
        "",
    ]

    if steps:
        for step in steps:
            num = step.get("step_num", "?")
            desc = step.get("description", "")
            selector = step.get("selector", "")
            action = step.get("action", "")
            if selector:
                lines.append(f"{num}. {desc} → `{selector}` ({action})")
            else:
                lines.append(f"{num}. {desc}")
    else:
        lines.append("1. Navigate to the apply URL.")
        lines.append("2. (Steps to be recorded on first successful application)")

    lines.append("")
    lines.append("## Known Quirks")
    if known_quirks:
        for q in known_quirks:
            lines.append(f"- {q}")
    else:
        lines.append("- None recorded yet.")

    lines.append("")
    lines.append("## Fields Requiring Human Input")
    if fields_needing_human:
        for f in fields_needing_human:
            lines.append(f"- {f}")
    else:
        lines.append("- None so far.")

    lines.append("")
    lines.append("## Changelog")
    lines.append("| Date | Change |")
    lines.append("|------|--------|")
    lines.append(f"| {now} | Initial capture |")
    lines.append("")

    return "\n".join(lines)


def list_all_memories() -> list[dict]:
    """Return a summary of all portal memory files.

    Returns:
        List of dicts with keys: hostname, path, size_bytes, modified_at
    """
    if not os.path.isdir(HISTORY_DIR):
        return []

    result = []
    for fname in sorted(os.listdir(HISTORY_DIR)):
        if not fname.endswith(".md"):
            continue
        fpath = os.path.join(HISTORY_DIR, fname)
        stat = os.stat(fpath)
        result.append({
            "hostname": fname[:-3],  # strip .md
            "path": fpath,
            "size_bytes": stat.st_size,
            "modified_at": datetime.fromtimestamp(
                stat.st_mtime, tz=timezone.utc
            ).isoformat(),
        })
    return result
