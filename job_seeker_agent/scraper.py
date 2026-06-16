"""
scraper.py — Job discovery via the Linkup API.

Replaces the old Node.js linkedin-scan.mjs approach.
Uses Linkup's search API for reliable, high-speed job discovery.
"""

import os
import sys
from datetime import datetime, timezone

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)


def discover_jobs(preferences: dict | None = None, limit: int = 10) -> list[dict]:
    """Discover jobs using the Linkup API.

    Args:
        preferences: Dict with keys like 'keywords', 'location', 'experience_level'
        limit: Max number of jobs to return

    Returns:
        List of job dicts with keys: title, company, location, url, source, keywords
    """
    api_key = os.environ.get("LINKUP_API_KEY", "")
    if not api_key:
        print("[Scraper] LINKUP_API_KEY not set — skipping discovery")
        return []

    preferences = preferences or {}
    keywords = preferences.get("keywords", "software engineer IIT IIM")
    location = preferences.get("location", "India")

    try:
        from linkup import LinkupClient
        client = LinkupClient(api_key=api_key)

        query = f"{keywords} jobs in {location}"
        results = client.search(
            query=query,
            depth="standard",
            output_type="searchResults",
        )

        jobs = []
        for result in (results.results or [])[:limit]:
            job = {
                "title": result.name or "Untitled",
                "company": _extract_company(result.name, result.url),
                "location": location,
                "url": result.url or "",
                "source": "linkup",
                "keywords": keywords,
                "scraped_at": datetime.now(timezone.utc).isoformat(),
            }
            jobs.append(job)

        # Save to database
        _save_jobs_to_db(jobs)
        return jobs

    except ImportError:
        print("[Scraper] linkup-sdk not installed. Run: pip install linkup-sdk")
        return []
    except Exception as e:
        print(f"[Scraper] Error: {e}")
        return []


def _extract_company(title: str, url: str) -> str:
    """Try to extract company name from URL domain."""
    if not url:
        return ""
    try:
        from urllib.parse import urlparse
        domain = urlparse(url).hostname or ""
        # Remove common prefixes/suffixes
        parts = domain.replace("www.", "").split(".")
        if parts:
            return parts[0].capitalize()
    except Exception:
        pass
    return ""


def _save_jobs_to_db(jobs: list[dict]):
    """Save discovered jobs to the database."""
    try:
        from core.database import get_db_connection
        conn = get_db_connection("jobs")
        for job in jobs:
            try:
                conn.execute(
                    """INSERT OR IGNORE INTO jobs
                       (title, company, location, url, source, keywords, scraped_at, status)
                       VALUES (?, ?, ?, ?, ?, ?, ?, 'new')""",
                    (job["title"], job["company"], job["location"],
                     job["url"], job["source"], job["keywords"], job["scraped_at"]),
                )
            except Exception:
                pass  # Skip duplicates
        conn.commit()
        conn.close()
        print(f"[Scraper] Saved {len(jobs)} jobs to database")
    except Exception as e:
        print(f"[Scraper] DB save error: {e}")
