"""
search.py
─────────
Queries LinkedIn job postings based on user search preferences and profile.
"""

import asyncio
import os
import sys
import re
import random
from datetime import datetime
from urllib.parse import quote
from playwright.async_api import async_playwright

# Ensure project root is in sys.path
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from core import database as db
from linkedin_jobs_agent.session_manager import load_session


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
            
        try:
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
    Prioritizes DB linkedin_preferences, falling back to master_cv data if empty.
    """
    user = db.get_user(user_id)
    if not user:
        return {"roles": ["Software Engineer"], "locations": ["Bangalore"], "experience": 0}
        
    prefs = user.get("linkedin_preferences") or {}
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


async def search_linkedin_jobs(page, role: str, location: str, experience: int, max_jobs: int = 5) -> list[dict]:
    """
    Navigate to LinkedIn search results for a specific role/location and parse listings.
    """
    jobs = []
    
    # Build LinkedIn search URL
    search_url = f"https://www.linkedin.com/jobs/search/?keywords={quote(role)}&location={quote(location)}"
    print(f"  [LinkedIn Search] Querying: '{role}' in '{location}'...")
    
    try:
        await page.goto(search_url, wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(3000)
        
        # Check if login or checkpoint page loaded
        if "login" in page.url or "signup" in page.url or "checkpoint" in page.url:
            print(f"  [LinkedIn Search] Auth redirect detected: {page.url}. Aborting search.")
            return []
            
        # Scroll the left sidebar list to load lazy-loaded cards
        container_sel = ".jobs-search-results-list, div.jobs-search-results-list"
        list_exists = await page.locator(container_sel).count() > 0
        if list_exists:
            print("  [LinkedIn Search] Scroll list pane to load cards...")
            for _ in range(4):
                await page.evaluate(f"document.querySelector('{container_sel}')?.scrollBy(0, 500)")
                await page.wait_for_timeout(1000)
        else:
            print("  [LinkedIn Search] Scroll page body as fallback...")
            for _ in range(4):
                await page.evaluate("window.scrollBy(0, 500)")
                await page.wait_for_timeout(1000)
                
        # Card selector
        card_sel = "li.jobs-search-results__list-item, div.job-card-container"
        await page.wait_for_selector(card_sel, timeout=10000)
        cards = await page.locator(card_sel).all()
        print(f"  [LinkedIn Search] Found {len(cards)} listings on search page.")
        
        scraped_count = 0
        for card in cards:
            if scraped_count >= max_jobs:
                break
                
            try:
                # Title link elements
                title_elem = card.locator("a.job-card-list__title, .artdeco-entity-lockup__title a, a[href*='/jobs/view/']").first
                if await title_elem.count() == 0:
                    continue
                    
                title = await title_elem.inner_text()
                href = await title_elem.get_attribute("href")
                
                # Resolve job ID
                job_id = await card.get_attribute("data-job-id")
                if not job_id:
                    job_id = await card.get_attribute("data-occludable-job-id")
                if not job_id and href:
                    match = re.search(r"/view/(\d+)", href)
                    if match:
                        job_id = match.group(1)
                
                if not job_id:
                    continue
                    
                url = f"https://www.linkedin.com/jobs/view/{job_id}/"
                
                # Company
                comp_elem = card.locator(".job-card-container__company-name, .job-card-list__company-name, .artdeco-entity-lockup__subtitle").first
                company = await comp_elem.inner_text() if await comp_elem.count() > 0 else ""
                
                # Location
                loc_elem = card.locator(".job-card-container__metadata-item, .job-card-list__metadata-item, .artdeco-entity-lockup__caption").first
                location = await loc_elem.inner_text() if await loc_elem.count() > 0 else ""
                
                # Click to load details pane
                await title_elem.scroll_into_view_if_needed()
                await title_elem.click()
                
                # Safe pacing
                delay = random.uniform(2.5, 4.5)
                await page.wait_for_timeout(int(delay * 1000))
                
                # Detail extraction
                desc = ""
                desc_sel = "#job-details, .jobs-description__content, .jobs-description, .jobs-box__html-content"
                desc_elem = page.locator(desc_sel).first
                if await desc_elem.count() > 0:
                    desc = await desc_elem.inner_text()
                    
                # Poster details
                poster_info = ""
                poster_name = ""
                poster_url = ""
                
                poster_card = page.locator(".jobs-poster, .hirer-card, .jobs-poster__card").first
                if await poster_card.count() > 0:
                    poster_info = await poster_card.inner_text()
                    
                    # Extract poster name specifically
                    name_elem = poster_card.locator(".jobs-poster__card-name, a.jobs-poster__name-link, .jobs-poster__name").first
                    if await name_elem.count() > 0:
                        poster_name = await name_elem.inner_text()
                    else:
                        lines = [l.strip() for l in poster_info.split("\n") if l.strip()]
                        if lines:
                            poster_name = lines[0]
                            
                    # Extract poster URL link
                    link_elem = poster_card.locator("a[href*='/in/']").first
                    if await link_elem.count() > 0:
                        href = await link_elem.get_attribute("href")
                        if href:
                            if href.startswith("/"):
                                poster_url = f"https://www.linkedin.com{href}"
                            else:
                                poster_url = href
                    
                # Posted Date
                posted = ""
                posted_sel = ".jobs-unified-top-card__posted-date, .jobs-unified-top-card__subtitle-grid time"
                posted_elem = page.locator(posted_sel).first
                if await posted_elem.count() > 0:
                    posted = await posted_elem.inner_text()
                if not posted:
                    time_elem = card.locator("time").first
                    if await time_elem.count() > 0:
                        posted = await time_elem.inner_text()
                        
                jobs.append({
                    "job_id": job_id,
                    "title": title.strip() if title else "",
                    "company": company.strip() if company else "",
                    "location": location.strip() if location else "",
                    "description": desc.strip() if desc else "",
                    "poster_info": poster_info.strip(),
                    "poster_name": poster_name.strip(),
                    "poster_url": poster_url.strip(),
                    "posted_date": posted.strip() if posted else "",
                    "url": url,
                    "portal": "linkedin.com",
                    "scraped_at": datetime.now().isoformat()
                })
                
                scraped_count += 1
                print(f"    [Scraped] Title: {title.strip()} | Company: {company.strip()}")
                
            except Exception as ce:
                print(f"    [LinkedIn Search] Error scraping card: {ce}")
                continue
                
    except Exception as e:
        print(f"  [LinkedIn Search] Error searching jobs: {e}")
        
    return jobs


async def run_linkedin_job_search(user_id: int, max_jobs_per_run: int = 5, headed: bool = False) -> list[dict]:
    """
    Run automated search for all resolved roles/locations of a user and return unified listings.
    """
    filters = resolve_search_filters(user_id)
    print(f"[LinkedIn Search] Resolved filters for user {user_id}:")
    print(f"   Roles: {filters['roles']}")
    print(f"   Locations: {filters['locations']}")
    print(f"   Experience: {filters['experience']} years")
    
    cookies = load_session(user_id)
    if not cookies:
        print("[LinkedIn Search] Error: No active LinkedIn session cookies found. Authenticated session is required.")
        return []
        
    all_jobs = []
    seen_urls = set()
    
    async with async_playwright() as p:
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
        
        await context.add_cookies(cookies)
        page = await context.new_page()
        await page.add_init_script("Object.defineProperty(navigator, 'webdriver', { get: () => undefined });")
        
        # Iterate combinations of roles and locations
        for role in filters["roles"]:
            for loc in filters["locations"]:
                try:
                    jobs = await search_linkedin_jobs(
                        page, 
                        role=role, 
                        location=loc, 
                        experience=filters["experience"], 
                        max_jobs=max_jobs_per_run
                    )
                    
                    # Deduplicate
                    for j in jobs:
                        if j["url"] not in seen_urls:
                            seen_urls.add(j["url"])
                            all_jobs.append(j)
                            
                    # Pacing between queries
                    query_delay = random.uniform(5.0, 8.0)
                    await page.wait_for_timeout(int(query_delay * 1000))
                    
                except Exception as e:
                    print(f"  [LinkedIn Search] Search failed for role='{role}', loc='{loc}': {e}")
                    
        # Trigger Recruiter connection requests for the newly found jobs
        new_jobs_with_poster = [j for j in all_jobs if j.get("poster_url")]
        if new_jobs_with_poster:
            print(f"[LinkedIn Search] Initiating automated connection requests for {len(new_jobs_with_poster)} recruiters...")
            from linkedin_jobs_agent.outreach import initiate_recruiter_outreach
            for job in new_jobs_with_poster:
                try:
                    jid = job.get("job_id") or job.get("url", "")
                    # Connect and send note if not already processed
                    if not db.is_linkedin_job_processed(user_id, jid):
                        await initiate_recruiter_outreach(page, user_id, job)
                except Exception as e:
                    print(f"  [LinkedIn Search] Failed to initiate connection for job '{job.get('title')}': {e}")
                    
        # Check pending connections and send follow-up messages
        try:
            print("[LinkedIn Search] Checking pending connections for accepted invitations...")
            from linkedin_jobs_agent.outreach import monitor_and_process_outreach
            await monitor_and_process_outreach(page, user_id)
        except Exception as e:
            print(f"  [LinkedIn Search] Failed to run outreach monitoring: {e}")

        await browser.close()
        
    print(f"[LinkedIn Search] Search complete. Total unique jobs found: {len(all_jobs)}")
    
    # Resolve recruiter outreach status
    try:
        from linkedin_jobs_agent.outreach_resolver import resolve_outreach_statuses
        all_jobs = resolve_outreach_statuses(all_jobs)
        print("[LinkedIn Search] Successfully resolved recruiter outreach statuses.")
    except Exception as e:
        print(f"[LinkedIn Search] Error resolving outreach statuses: {e}")

    # Fetch master CV data for scoring
    cv_data = db.get_master_cv(user_id) or {}
    
    # Score and sort jobs by relevance using dedicated LinkedIn scorer
    try:
        from linkedin_jobs_agent.relevance_scorer import score_jobs
        all_jobs = score_jobs(all_jobs, cv_data, filters)
        # Sort in descending order of relevance score
        all_jobs.sort(key=lambda x: x.get("relevance_percent", 0), reverse=True)
        print("[LinkedIn Search] Successfully ranked scraped jobs by relevance.")
    except Exception as e:
        print(f"[LinkedIn Search] Error ranking jobs: {e}")
        
    # De-duplication guard: filter out already tracked jobs
    new_jobs = []
    for job in all_jobs:
        jid = job.get("job_id")
        if not jid:
            jid = job.get("url", "")
        if jid:
            if db.is_linkedin_job_tracked(user_id, jid):
                continue
            
            new_jobs.append(job)
            db.track_linkedin_job(user_id, jid)
        else:
            new_jobs.append(job)
            
    print(f"[LinkedIn Search] De-duplication guard: filtered out {len(all_jobs) - len(new_jobs)} already tracked/surfaced jobs. {len(new_jobs)} new jobs remaining.")
    all_jobs = new_jobs
        
    # Save the scraped jobs to database
    try:
        db.save_linkedin_jobs(all_jobs)
    except Exception as e:
        print(f"[LinkedIn Search] Database save failed: {e}")
        
    return all_jobs
