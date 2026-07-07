"""
search.py
─────────
Queries Naukri job postings based on user search preferences and profile.
"""

import asyncio
import os
import sys
import re
from datetime import datetime
from urllib.parse import quote
from playwright.async_api import async_playwright

# Ensure project root is in sys.path
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from core import database as db
from naukri_agent.session_manager import load_session


def parse_experience_years(cv_data: dict) -> int:
    """Calculate total years of experience from master CV experience entries."""
    if not cv_data or "experience" not in cv_data:
        return 0
        
    total_months = 0
    for exp in cv_data["experience"]:
        start_str = exp.get("start_date") or ""
        end_str = exp.get("end_date") or ""
        if not start_str:
            continue
            
        # Parse dates (formats like 'YYYY-MM', 'Jan YYYY', 'Month YYYY')
        try:
            # Simple extractor for Year and Month
            start_date = None
            end_date = None
            
            # Helper to parse string to date
            def parse_date(d_str, default_now=False):
                if not d_str or "present" in d_str.lower() or "current" in d_str.lower():
                    return datetime.now() if default_now else None
                # Try YYYY-MM
                match = re.search(r"(\d{4})[-/](\d{1,2})", d_str)
                if match:
                    return datetime(int(match.group(1)), int(match.group(2)), 1)
                # Try Month Year or abbreviation
                match = re.search(r"([a-zA-Z]+)\s*(\d{4})", d_str)
                if match:
                    # Very simple month mapper
                    months = {"jan":1,"feb":2,"mar":3,"apr":4,"may":5,"jun":6,"jul":7,"aug":8,"sep":9,"oct":10,"nov":11,"dec":12}
                    mon_str = match.group(1).lower()[:3]
                    m = months.get(mon_str, 1)
                    return datetime(int(match.group(2)), m, 1)
                # Just year
                match = re.search(r"\b(\d{4})\b", d_str)
                if match:
                    return datetime(int(match.group(1)), 1, 1)
                return None

            start_date = parse_date(start_str)
            end_date = parse_date(end_str, default_now=True)
            
            if start_date and end_date:
                months = (end_date.year - start_date.year) * 12 + (end_date.month - start_date.month)
                if months > 0:
                    total_months += months
        except Exception:
            pass
            
    return max(0, round(total_months / 12))


def get_profile_fallback_filters(user_id: int) -> dict:
    """
    Extract fallback search filters (roles, locations, experience) from the master CV.
    """
    filters = {
        "roles": [],
        "locations": ["Bangalore", "Remote"],
        "experience": 0
    }
    
    cv_data = db.get_master_cv(user_id)
    if not cv_data:
        return filters
        
    # 1. Experience years
    filters["experience"] = parse_experience_years(cv_data)
    
    # 2. Target Roles from experience designations or personal headline
    roles = []
    personal = cv_data.get("personal") or {}
    headline = personal.get("headline") or ""
    if headline:
        # Split by dividers
        for part in re.split(r"[|,\-/]", headline):
            clean_part = part.strip()
            if len(clean_part) > 3 and len(clean_part) < 40:
                roles.append(clean_part)
                
    # Also collect designation titles
    for exp in cv_data.get("experience", []):
        role_title = exp.get("role") or exp.get("designation") or ""
        if role_title:
            clean_title = role_title.strip()
            if clean_title not in roles:
                roles.append(clean_title)
                
    filters["roles"] = list(set(roles))[:3]  # Limit to top 3 roles
    return filters


def resolve_search_filters(user_id: int) -> dict:
    """
    Resolve job search filters for a user.
    Prioritizes DB naukri_preferences, falling back to master_cv data if empty.
    """
    user = db.get_user(user_id)
    if not user:
        return {"roles": ["Software Engineer"], "locations": ["Bangalore"], "experience": 0}
        
    prefs = user.get("naukri_preferences") or {}
    fallback = get_profile_fallback_filters(user_id)
    
    resolved = {
        "roles": prefs.get("roles") or fallback.get("roles") or ["Software Engineer"],
        "locations": prefs.get("locations") or fallback.get("locations") or ["Bangalore"],
        "experience": prefs.get("experience") if prefs.get("experience") is not None else fallback.get("experience") or 0
    }
    
    # Ensure lists are clean
    resolved["roles"] = [r.strip() for r in resolved["roles"] if r and r.strip()]
    resolved["locations"] = [l.strip() for l in resolved["locations"] if l and l.strip()]
    
    return resolved


async def search_naukri_jobs(page, role: str, location: str, experience: int, max_pages: int = 1) -> list[dict]:
    """
    Navigate to Naukri search results for a specific role/location/experience and parse listings.
    """
    jobs = []
    # Clean location/role for standard query parameter searching
    # Naukri search pattern: https://www.naukri.com/jobs-in-india?k=keyword&l=location&experience=experience
    # OR slug format: https://www.naukri.com/role-jobs-in-location
    
    search_url = f"https://www.naukri.com/jobs-in-india?k={quote(role)}&l={quote(location)}&experience={experience}"
    print(f"  [Naukri Search] Querying: '{role}' in '{location}' with {experience} yrs exp...")
    
    for page_num in range(1, max_pages + 1):
        url = search_url if page_num == 1 else f"{search_url}&pageNo={page_num}"
        try:
            print(f"  [Naukri Search] Loading page {page_num}...")
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            await page.wait_for_timeout(3000)
            
            # Wait for job tuple elements
            card_selector = ".srp-jobtuple-wrapper"
            try:
                await page.wait_for_selector(card_selector, timeout=10000)
            except Exception:
                print(f"  [Naukri Search] No listings found or timed out on page {page_num}.")
                break
                
            # Extract cards
            cards = await page.locator(card_selector).all()
            print(f"  [Naukri Search] Found {len(cards)} listings on page {page_num}")
            
            for card in cards:
                try:
                    title_elem = card.locator("a.title")
                    title = await title_elem.inner_text()
                    url = await title_elem.get_attribute("href")
                    
                    company = await card.locator("a.comp-name").first.inner_text()
                    
                    # Experience
                    exp = ""
                    if await card.locator(".exp-wrap .expwdth").count() > 0:
                        exp = await card.locator(".exp-wrap .expwdth").first.inner_text()
                        
                    # Location
                    loc = ""
                    if await card.locator(".loc-wrap .locWdth").count() > 0:
                        loc = await card.locator(".loc-wrap .locWdth").first.inner_text()
                        
                    # Description/Summary
                    desc = ""
                    desc_container = card.locator(".ni-job-tuple-icon-srp-description .job-desc")
                    if await desc_container.count() > 0:
                        desc = await desc_container.first.inner_text()
                        
                    # Key Skills
                    skills = []
                    skill_tags = card.locator(".tags-gt .tag-li")
                    count = await skill_tags.count()
                    for idx in range(count):
                        skills.append(await skill_tags.nth(idx).inner_text())
                        
                    # Posted Date
                    posted = ""
                    if await card.locator(".job-post-day").count() > 0:
                        posted = await card.locator(".job-post-day").first.inner_text()
                        
                    # Clean URN/Job ID from URL
                    job_id = ""
                    if url:
                        # Extract number pattern from url like -120224001234
                        match = re.search(r"-(\d{10,15})\b", url)
                        if match:
                            job_id = match.group(1)
                            
                    jobs.append({
                        "job_id": job_id,
                        "title": title.strip() if title else "",
                        "company": company.strip() if company else "",
                        "location": loc.strip() if loc else "",
                        "experience": exp.strip() if exp else "",
                        "description": desc.strip() if desc else "",
                        "skills": skills,
                        "posted_date": posted.strip() if posted else "",
                        "url": url.strip() if url else "",
                        "portal": "naukri.com",
                        "scraped_at": datetime.now().isoformat()
                    })
                except Exception as e:
                    # Gracefully skip malformed card
                    continue
                    
        except Exception as e:
            print(f"  [Naukri Search] Error loading page {page_num}: {e}")
            break
            
    return jobs


async def run_naukri_job_search(user_id: int, max_pages_per_query: int = 1, headed: bool = False) -> list[dict]:
    """
    Run automated search for all resolved roles/locations of a user and return unified listings.
    """
    filters = resolve_search_filters(user_id)
    print(f"[Naukri Search] Resolved filters for user {user_id}:")
    print(f"   Roles: {filters['roles']}")
    print(f"   Locations: {filters['locations']}")
    print(f"   Experience: {filters['experience']} years")
    
    cookies = load_session(user_id)
    if not cookies:
        print("[Naukri Search] Warning: No active Naukri session cookies found. Running search logged out.")
        
    all_jobs = []
    seen_urls = set()
    
    async with async_playwright() as p:
        # Run headless for scanning unless debug requested
        browser = await p.chromium.launch(
            headless=not headed,
            args=[
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-blink-features=AutomationControlled",
            ]
        )
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 800}
        )
        
        if cookies:
            await context.add_cookies(cookies)
            
        page = await context.new_page()
        # Stealth
        await page.add_init_script("Object.defineProperty(navigator, 'webdriver', { get: () => undefined });")
        
        # Iterate combinations of roles and locations
        for role in filters["roles"]:
            for loc in filters["locations"]:
                try:
                    jobs = await search_naukri_jobs(
                        page, 
                        role=role, 
                        location=loc, 
                        experience=filters["experience"], 
                        max_pages=max_pages_per_query
                    )
                    
                    # Deduplicate
                    for j in jobs:
                        if j["url"] not in seen_urls:
                            seen_urls.add(j["url"])
                            all_jobs.append(j)
                except Exception as e:
                    print(f"  [Naukri Search] Search failed for role='{role}', loc='{loc}': {e}")
                    
        await browser.close()
        
    print(f"[Naukri Search] Search complete. Total unique jobs found: {len(all_jobs)}")
    
    # Fetch master CV data for scoring
    cv_data = db.get_master_cv(user_id) or {}
    
    # Score and sort jobs by relevance
    try:
        from naukri_agent.relevance_scorer import score_jobs
        all_jobs = score_jobs(all_jobs, cv_data, filters)
        # Sort in descending order of relevance score
        all_jobs.sort(key=lambda x: x.get("relevance_percent", 0), reverse=True)
        print("[Naukri Search] Successfully ranked scraped jobs by relevance.")
    except Exception as e:
        print(f"[Naukri Search] Error ranking jobs: {e}")
        
    # Duplicate-application guard: filter out already processed/surfaced jobs
    new_jobs = []
    for job in all_jobs:
        jid = job.get("job_id")
        if not jid:
            jid = job.get("url", "")
        if jid:
            if db.is_naukri_job_processed(user_id, jid):
                continue
            new_jobs.append(job)
            db.add_naukri_application(user_id, jid, status="surfaced")
        else:
            new_jobs.append(job)
            
    print(f"[Naukri Search] Duplicate guard: filtered out {len(all_jobs) - len(new_jobs)} already processed/surfaced jobs. {len(new_jobs)} new jobs remaining.")
    all_jobs = new_jobs
        
    # Save the scraped jobs to database
    try:
        db.save_naukri_jobs(all_jobs)
    except Exception as e:
        print(f"[Naukri Search] Database save failed: {e}")
        
    return all_jobs


if __name__ == "__main__":
    # Test script with mock user ID 9999
    # If database users table is empty, we print a mock search execution
    import sys
    user_id = 9999
    if len(sys.argv) > 1:
        try:
            user_id = int(sys.argv[1])
        except ValueError:
            pass
            
    print(f"Running standalone search test for User ID: {user_id}...")
    # Initialize DB (creates column if not exists)
    db.init_db()
    
    # Save a default mock preferences object for the mock user so it searches successfully
    mock_prefs = {
        "roles": ["Python Developer", "Software Engineer"],
        "locations": ["Bangalore", "Pune"],
        "experience": 2
    }
    db.update_user_naukri_preferences(user_id, mock_prefs)
    print("Mock preferences saved to DB.")
    
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    results = loop.run_until_complete(run_naukri_job_search(user_id))
    
    # Print sample outputs
    print("\n--- SAMPLE SEARCH RESULTS ---")
    for j in results[:5]:
        print(f"Title: {j['title']}")
        print(f"Company: {j['company']}")
        print(f"Location: {j['location']}")
        print(f"Experience: {j['experience']}")
        print(f"Posted: {j['posted_date']}")
        print(f"URL: {j['url']}")
        print("-" * 30)
