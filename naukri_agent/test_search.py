"""
test_search.py
──────────────
Executable verification script to test Naukri job search and filtering.
"""

import asyncio
import os
import sys

# Ensure project root is in sys.path
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from core import database as db
from naukri_agent.search import run_naukri_job_search, resolve_search_filters


async def main():
    print("=" * 60)
    print(" Naukri Job Search and Filtering Test Harness")
    print("=" * 60)
    
    # Initialize DB (executes column additions automatically)
    db.init_db()
    
    TEST_USER_ID = 9999
    
    # ── Step 1: Test Database Preference Storage ────────────────────────────
    print("\n[Test 1] Saving custom job search preferences to DB...")
    custom_prefs = {
        "roles": ["Python Developer", "React Engineer"],
        "locations": ["Bangalore", "Mumbai"],
        "experience": 3
    }
    
    # We must first ensure a user with ID 9999 exists in the DB so get_user doesn't return None
    # Let's seed a mock user if not present
    with db._connect() as conn:
        conn.execute(
            """INSERT OR IGNORE INTO users (id, name, last_name, email, password_hash, submitted_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (TEST_USER_ID, "Test", "Candidate", "candidate9999@test.com", "hash", "2026-07-07T00:00:00")
        )
        conn.commit()

    success = db.update_user_naukri_preferences(TEST_USER_ID, custom_prefs)
    if success:
        print("[OK] Preferences successfully saved.")
    else:
        print("[ERROR] Failed to save preferences.")
        return
        
    print("Retrieving saved user details from DB...")
    user_data = db.get_user(TEST_USER_ID)
    retrieved_prefs = user_data.get("naukri_preferences") or {}
    print(f"Retrieved Preferences: {retrieved_prefs}")
    
    if retrieved_prefs.get("experience") == 3 and "React Engineer" in retrieved_prefs.get("roles"):
        print("[OK] DB preference round-trip successful.")
    else:
        print("[ERROR] DB preference round-trip failed.")
        return

    # ── Step 2: Test Profile-Based Fallback parsing ─────────────────────────
    print("\n[Test 2] Testing master_cv profile fallback parsing...")
    # Inject a mock master_cv
    mock_cv = {
        "personal": {
            "name": "Test",
            "last_name": "Candidate",
            "headline": "Lead Backend Developer | Python Specialist | API Architect"
        },
        "experience": [
            {
                "company": "Tech Corp",
                "role": "Senior Software Engineer",
                "start_date": "2022-01",
                "end_date": "2024-01"  # 2 years
            },
            {
                "company": "Startup Inc",
                "role": "Python Developer",
                "start_date": "Jan 2020",
                "end_date": "Dec 2021"  # 2 years
            }
        ]
    }
    
    db.save_master_cv(TEST_USER_ID, mock_cv)
    print("Mock Master CV saved.")
    
    # Temporarily clear preferences to force fallback resolution
    db.update_user_naukri_preferences(TEST_USER_ID, {})
    resolved = resolve_search_filters(TEST_USER_ID)
    print(f"Resolved Fallback Filters: {resolved}")
    
    # Total experience should be around 4 years (2020-2024)
    if resolved.get("experience") >= 3 and len(resolved.get("roles")) > 0:
        print("[OK] Profile fallback resolution successful.")
    else:
        print("[ERROR] Profile fallback resolution failed.")
        
    # Restore custom preferences for the search run
    db.update_user_naukri_preferences(TEST_USER_ID, custom_prefs)

    # ── Step 3: Run the Job Search Scraper ──────────────────────────────────
    print("\n[Test 3] Launching Playwright to query job postings...")
    print("This will run headless search for: roles=['Python Developer', 'React Engineer'] in Bangalore/Mumbai.")
    
    # We will search with a limit of 1 page per combination for testing
    results = await run_naukri_job_search(TEST_USER_ID, max_pages_per_query=1, headed=True)
    
    print("\n" + "=" * 60)
    print(f" RESULTS SUMMARY: Found {len(results)} jobs")
    print("=" * 60)
    
    if len(results) > 0:
        print("[OK] Scraped listings parsed successfully!")
        print("\nShowing first 3 normalized postings:")
        for idx, job in enumerate(results[:3], 1):
            print(f"\n[{idx}] {job['title']}")
            print(f"    Company:     {job['company']}")
            print(f"    Location:    {job['location']}")
            print(f"    Experience:  {job['experience']}")
            print(f"    Posted:      {job['posted_date']}")
            print(f"    Skills:      {', '.join(job['skills'][:5])}")
            print(f"    URL:         {job['url']}")
    else:
        print("[ERROR] Search returned 0 results. Check network connectivity or selector updates.")
        
    print("\nVerification test complete.")


if __name__ == "__main__":
    asyncio.run(main())
