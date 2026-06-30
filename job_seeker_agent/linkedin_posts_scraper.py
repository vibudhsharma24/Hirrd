"""
linkedin_posts_scraper.py — Python LinkedIn Feed-Post Scraper.

Logs in to LinkedIn using Playwright, searches for content posts
matching the user's target roles, extracts job details and apply links,
and saves them to the `posts` table in jobs.db.

This replaces the legacy Node.js linkedin-posts.mjs with a native Python
implementation that shares the same cookie cache and selectors.

Usage (standalone):
    python linkedin_posts_scraper.py --user-id 1 --headed   # first run
    python linkedin_posts_scraper.py --user-id 1             # subsequent runs

Requirements:
    pip install playwright
    python -m playwright install chromium
"""

import asyncio
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse, quote_plus

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# Try loading .env
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


# ── Paths ────────────────────────────────────────────────────────────────────

SESSIONS_DIR = os.path.join(os.path.dirname(__file__), "sessions")
os.makedirs(SESSIONS_DIR, exist_ok=True)


# ── Config ───────────────────────────────────────────────────────────────────

MAX_PAGES_PER_KEYWORD = 2
PAGE_DELAY_MS = 5000
SCROLL_COUNT = 3
SCROLL_DELAY_MS = 1200

# Negative keywords — skip posts whose parsed title contains any of these
NEGATIVE_TITLE_KEYWORDS = [
    "intern", "internship", "trainee", ".net", "ios", "android",
    "embedded", "firmware", "cobol", "mainframe", "php", "ruby",
]


# ── Cookie helpers ───────────────────────────────────────────────────────────

def _cookies_path(user_id: int) -> str:
    return os.path.join(SESSIONS_DIR, f"linkedin_cookies_{user_id}.json")


def _save_cookies(user_id: int, cookies: list[dict]):
    path = _cookies_path(user_id)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(cookies, f, indent=2)
    print(f"  [LI Scraper] Cookies saved -> {path}")


def _load_cookies(user_id: int) -> list[dict] | None:
    path = _cookies_path(user_id)
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


# ── URL builder ──────────────────────────────────────────────────────────────

def build_search_url(keywords: str, date_posted: str = "past-week") -> str:
    """Build a LinkedIn content/post search URL."""
    params = (
        f"keywords={quote_plus(keywords)}"
        f"&origin=SWITCH_SEARCH_VERTICAL"
        f"&datePosted={date_posted}"
        f"&sortBy=date_posted"
    )
    return f"https://www.linkedin.com/search/results/content/?{params}"


# ── Text extraction helpers (ported from linkedin-posts.mjs) ─────────────────

def clean_title(title: str) -> str:
    if not title:
        return ""
    # Remove emoji
    try:
        title = re.sub(r"[\U00002700-\U000027BF]|[\U0000E000-\U0000F8FF]|"
                       r"\U0001F300-\U0001F9FF|[\u2011-\u26FF]", "", title)
    except Exception:
        pass
    # Remove noise words
    title = re.sub(
        r"\b(we|re|we're|are|hiring|for|looking|seeking|need|join|us|our|team|"
        r"is|to|a|an|role|position|opening|job|opportunity|openings|immediate|"
        r"urgently|actively|active|new|alert)\b",
        "",
        title,
        flags=re.IGNORECASE,
    )
    title = re.sub(r"^[:\s\-–—|/•+*#@(),;\[\]{}]+", "", title)
    title = re.sub(r"[:\s\-–—|/•+*#@(),;\[\]{}]+$", "", title)
    title = re.sub(r"\s+", " ", title).strip()
    return title


def extract_title(text: str) -> str:
    if not text:
        return ""
    # Pattern: "Role: ...", "Position: ...", etc.
    m = re.search(
        r"(?:role|position|title|opening|hiring for|looking for|seeking)"
        r"[:\s–-]+([^\n.!?|]{5,80})",
        text, re.IGNORECASE
    )
    if m:
        return clean_title(m.group(1).strip())

    # Pattern: "We are hiring a/an X"
    m = re.search(
        r"(?:hiring|looking for|seeking|need) (?:a |an )?([A-Z][^\n.!?|]{4,70})",
        text,
    )
    if m:
        return clean_title(m.group(1).strip())

    # Fallback: first non-empty line 5-100 chars
    for line in text.split("\n"):
        line = line.strip()
        if 5 <= len(line) <= 100:
            return clean_title(line)

    return clean_title(text[:80].strip())


def extract_location(text: str) -> str:
    if not text:
        return ""
    m = re.search(
        r"(?:location|based in|in)\s*[:\-]?\s*"
        r"([A-Z][a-zA-Z ,]+(?:India|USA|UK|Remote|Hybrid|Bangalore|Mumbai|Delhi|"
        r"Hyderabad|Pune|Chennai|Gurugram|Noida)[a-zA-Z ,]*)",
        text, re.IGNORECASE,
    )
    if m:
        return m.group(1).strip()[:80]

    m = re.search(
        r"\b(Remote|Hybrid|Bangalore|Bengaluru|Mumbai|Delhi|NCR|Hyderabad|Pune|"
        r"Chennai|Gurugram|Noida|Kolkata|Ahmedabad|Jaipur|India)\b",
        text, re.IGNORECASE,
    )
    if m:
        return m.group(1)
    return ""


def extract_company(post_text: str, poster_headline: str = "") -> str:
    m = re.search(r"(?:\bat\b|@|join)\s+([A-Z][A-Za-z0-9& ,.]+?)(?:\s*[|!?.\n]|$)", post_text)
    if m:
        return m.group(1).strip()[:80]
    if poster_headline:
        m = re.search(r"(?:at|@|\|)\s*([A-Z][A-Za-z0-9& ,.]+)", poster_headline)
        if m:
            return m.group(1).strip()[:80]
    return ""


def strip_tracking_params(url: str) -> str:
    try:
        from urllib.parse import urlparse, parse_qs, urlencode, urlunparse
        u = urlparse(url)
        tracking = {
            "utm_source", "utm_medium", "utm_campaign", "utm_content", "utm_term",
            "li_source", "li_medium", "refId", "trk", "trkInfo", "ref", "src", "source",
        }
        qs = parse_qs(u.query, keep_blank_values=True)
        filtered = {k: v for k, v in qs.items() if k not in tracking}
        new_query = urlencode(filtered, doseq=True)
        return urlunparse(u._replace(query=new_query)).rstrip("?")
    except Exception:
        return url.split("?")[0].split("#")[0]


def extract_apply_link(hrefs: list[str]) -> str:
    """Choose the best apply/job link from a list of URLs in the post."""
    if not hrefs:
        return ""
    clean = [strip_tracking_params(h) for h in hrefs if h.startswith("http")]

    def is_linkedin_nav(h: str) -> bool:
        return any(x in h for x in [
            "linkedin.com/search", "linkedin.com/feed",
            "linkedin.com/in/", "linkedin.com/company/",
            "linkedin.com/home",
        ])

    # Prefer external links (actual career pages / ATS portals)
    external = [h for h in clean if not is_linkedin_nav(h) and "linkedin.com" not in h]
    if external:
        return external[0]

    # LinkedIn job-view links
    li_job = next((h for h in clean if "linkedin.com/jobs" in h), None)
    if li_job:
        return li_job

    # Any non-nav link
    non_nav = next((h for h in clean if not is_linkedin_nav(h)), None)
    if non_nav:
        return non_nav

    return clean[0] if clean else ""


async def resolve_url(url: str) -> str:
    """Resolve shortened URLs (lnkd.in, bit.ly, etc.) to their final destination."""
    if not url:
        return ""
    shorteners = ["lnkd.in", "bit.ly", "tinyurl.com", "t.co", "rebrand.ly", "shorturl.at"]
    if not any(s in url for s in shorteners):
        return url

    try:
        import aiohttp
        async with aiohttp.ClientSession() as session:
            async with session.get(url, allow_redirects=True, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                return str(resp.url)
    except ImportError:
        # Fallback: use urllib
        import urllib.request
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=5) as resp:
                return resp.url
        except Exception:
            return url
    except Exception:
        return url


# ── Title filter ─────────────────────────────────────────────────────────────

def passes_title_filter(title: str) -> bool:
    if not title:
        return True  # Don't discard if we couldn't extract a title
    lower = title.lower()
    return not any(kw in lower for kw in NEGATIVE_TITLE_KEYWORDS)


# ── Claude AI Post Refinement ────────────────────────────────────────────────

CLAUDE_MODEL = "claude-sonnet-4-6"


async def refine_posts_with_claude(posts: list[dict]) -> list[dict]:
    """Use Claude AI to extract clean, structured fields from raw scraped posts.

    This prevents issues like company being saved as 'lnkd.in' or 'linkedin.com'
    by having Claude read the post text and extract the actual company name,
    job title, location, and apply method.
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        print("  [LI Scraper] WARNING: No ANTHROPIC_API_KEY -- skipping Claude refinement")
        return posts

    try:
        import anthropic
    except ImportError:
        print("  [LI Scraper] WARNING: anthropic package not installed -- skipping refinement")
        return posts

    print(f"  [LI Scraper] [AI] Refining {len(posts)} posts with Claude AI...")

    client = anthropic.AsyncAnthropic(api_key=api_key)
    semaphore = asyncio.Semaphore(5)  # Max 5 concurrent API calls

    async def refine_single(post: dict) -> dict:
        async with semaphore:
            prompt = f"""You are a professional recruitment data cleaner. Analyze the following LinkedIn post and extract accurate job details.

RAW POST DATA:
- Post Text: {post.get('post_text', '')}
- Poster Name: {post.get('poster_name', '')}
- Poster URL: {post.get('poster_url', '')}
- Current Title: {post.get('title', '')}
- Current Company: {post.get('company', '')}
- Current Location: {post.get('location', '')}
- Current Apply Link: {post.get('apply_link', '')}
- Post URL: {post.get('post_url', '')}

Extract and return these fields:

1. "title" — The clean job title (e.g. "Senior Backend Developer", "Product Manager"). Remove noise words like "hiring", "urgent", etc.
2. "company" — The ACTUAL hiring company name.
   CRITICAL: NEVER use domain names as company. Never output "linkedin.com", "linkd.in", "lnkd.in", "google.com", "docs.google.com", "forms.gle" or any URL/domain as the company name.
   Look at the post text for mentions like "at CompanyName", "join CompanyName", or the poster's headline.
   If truly unknown, return empty string.
3. "location" — Job location (e.g. "Remote", "Bangalore, India", "Hybrid - Mumbai").
4. "apply_link" — The best external application URL. Keep as-is if it's a valid external link.
5. "apply_method" — How the candidate should apply. Examples:
   - "Apply via link" (if there's a direct application URL)
   - "Message poster on LinkedIn" (if the post says to DM/message)
   - "Email resume to hr@company.com" (if email is mentioned)
   - "Apply via Google Form" (if it's a Google Forms link)
   - "Comment on post" (if that's the instruction)
   - "Send connection request" (if no other method is clear)
6. "poster_name" — Clean poster name.
7. "poster_url" — Poster's LinkedIn profile URL.

Return ONLY a JSON object with these 7 keys. No markdown, no code blocks, no explanation."""

            try:
                response = await client.messages.create(
                    model=CLAUDE_MODEL,
                    max_tokens=500,
                    messages=[{"role": "user", "content": prompt}],
                )
                raw_text = response.content[0].text.strip()

                # Strip markdown fences if Claude wraps in ```json
                if raw_text.startswith("```"):
                    parts = raw_text.split("```")
                    content = parts[1] if len(parts) >= 2 else raw_text
                    if content.startswith("json"):
                        content = content[4:]
                    raw_text = content.strip()

                data = json.loads(raw_text)

                # Merge refined fields back, keeping original as fallback
                refined = dict(post)
                refined["title"] = data.get("title") or post.get("title") or "Untitled"
                refined["company"] = data.get("company") or ""
                refined["location"] = data.get("location") or post.get("location") or ""
                refined["poster_name"] = data.get("poster_name") or post.get("poster_name") or ""
                refined["poster_url"] = data.get("poster_url") or post.get("poster_url") or ""
                refined["apply_link"] = data.get("apply_link") or post.get("apply_link") or ""
                refined["apply_url"] = refined["apply_link"]
                refined["apply_method"] = data.get("apply_method") or ""

                # Safety: reject if Claude still returned a domain as company
                bad_company = ["linkedin.com", "lnkd.in", "linkd.in", "google.com",
                               "docs.google.com", "forms.gle", "bit.ly"]
                if refined["company"].lower().strip() in bad_company:
                    refined["company"] = ""

                return refined

            except Exception as e:
                print(f"  [LI Scraper] WARNING: Claude refinement failed for one post: {e}")
                return post

    tasks = [refine_single(p) for p in posts]
    refined_posts = await asyncio.gather(*tasks)
    print(f"  [LI Scraper] Claude refinement complete")
    return list(refined_posts)


# ── Main scraper ─────────────────────────────────────────────────────────────

async def scrape_linkedin_posts(
    user_id: int,
    linkedin_username: str,
    linkedin_password: str,
    roles: list[str] | None = None,
    locations: list[str] | None = None,
    max_pages: int = MAX_PAGES_PER_KEYWORD,
    headed: bool = False,
) -> list[dict]:
    """Scrape LinkedIn feed posts for job opportunities.

    Args:
        user_id:            User ID (for cookie caching)
        linkedin_username:  LinkedIn email
        linkedin_password:  LinkedIn password (decrypted)
        roles:              List of target roles to search for
        locations:          List of target locations
        max_pages:          Max search pages per keyword
        headed:             Show browser window

    Returns:
        List of post dicts saved to the database.
    """
    from playwright.async_api import async_playwright

    roles = roles or ["Software Engineer", "Product Manager"]
    locations = locations or ["India"]

    # Build search queries
    queries = []
    for role in roles:
        queries.append(f"hiring {role}")
        for loc in locations[:2]:  # Limit location combos
            queries.append(f"hiring {role} {loc}")

    # Deduplicate
    seen_queries = set()
    unique_queries = []
    for q in queries:
        normalized = q.lower().strip()
        if normalized not in seen_queries:
            seen_queries.add(normalized)
            unique_queries.append(q)

    print(f"  [LI Scraper] Searching {len(unique_queries)} queries for user {user_id}")

    all_posts = []
    scraped_at = datetime.now(timezone.utc).isoformat()

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=not headed,
            args=[
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-blink-features=AutomationControlled",
            ],
        )
        context = await browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1366, "height": 768},
            locale="en-US",
        )

        # Stealth
        await context.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', { get: () => undefined });"
        )

        page = await context.new_page()

        # ── Login / restore cookies ──────────────────────────────────────
        cached_cookies = _load_cookies(user_id)
        if cached_cookies:
            await context.add_cookies(cached_cookies)
            await page.goto("https://www.linkedin.com/feed/", wait_until="domcontentloaded", timeout=30000)
            await page.wait_for_timeout(3000)

            if "/login" in page.url or "/authwall" in page.url:
                print("  [LI Scraper] Cookies expired — logging in fresh")
                cached_cookies = None

        if not cached_cookies:
            logged_in = await _login(page, linkedin_username, linkedin_password)
            if not logged_in:
                print("  [LI Scraper] Login failed")
                await browser.close()
                return []
            cookies = await context.cookies()
            _save_cookies(user_id, cookies)

        # ── Scrape each query ────────────────────────────────────────────
        seen_urns = set()
        seen_links = set()

        for qi, query in enumerate(unique_queries):
            print(f"  [LI Scraper] [{qi+1}/{len(unique_queries)}] Searching: \"{query}\"")

            for page_num in range(max_pages):
                url = build_search_url(query)
                if page_num > 0:
                    url += f"&page={page_num + 1}"

                posts = await _extract_posts_from_page(page, url)

                if not posts:
                    break

                for raw in posts:
                    # Dedup by URN
                    urn = raw.get("urn", "")
                    if urn and urn in seen_urns:
                        continue
                    if urn:
                        seen_urns.add(urn)

                    # Parse fields
                    post_text = raw.get("postText", "")
                    poster_headline = raw.get("posterHeadline", "")

                    title = extract_title(post_text)
                    if not passes_title_filter(title):
                        continue

                    company = extract_company(post_text, poster_headline)
                    location = extract_location(post_text)

                    # Extract and resolve apply link
                    apply_link = extract_apply_link(raw.get("hrefs", []))
                    if apply_link:
                        try:
                            apply_link = await resolve_url(apply_link)
                        except Exception:
                            pass
                        apply_link = strip_tracking_params(apply_link)

                    # Dedup by apply link
                    if apply_link and apply_link in seen_links:
                        continue
                    if apply_link:
                        seen_links.add(apply_link)

                    post_record = {
                        "title": title or "Untitled",
                        "company": company,
                        "location": location,
                        "apply_link": apply_link,
                        "poster_name": raw.get("posterName", ""),
                        "poster_url": raw.get("posterUrl", ""),
                        "post_text": post_text[:1200],
                        "source": "linkedin-posts",
                        "keywords": query,
                        "scraped_at": scraped_at,
                        "status": "new",
                        "post_urn": urn or None,
                        "post_url": raw.get("directPostUrl", ""),
                        "apply_url": apply_link,
                        "apply_method": "",
                    }
                    all_posts.append(post_record)

                await page.wait_for_timeout(PAGE_DELAY_MS)

        # Save cookies after all scraping
        try:
            cookies = await context.cookies()
            _save_cookies(user_id, cookies)
        except Exception:
            pass

        await browser.close()

    # ── Claude AI Refinement Layer ────────────────────────────────────
    # Process all scraped posts through Claude to extract clean fields:
    # proper company names, titles, locations, and apply methods.
    if all_posts:
        try:
            all_posts = await refine_posts_with_claude(all_posts)
        except Exception as e:
            print(f"  [LI Scraper] WARNING: Claude refinement layer error: {e}")
            print(f"  [LI Scraper]   -> Saving posts with regex-extracted fields")

    # Save to database
    if all_posts:
        _save_posts_to_db(all_posts)

    print(f"  [LI Scraper] Total new posts found: {len(all_posts)}")
    return all_posts


# ── Internal: LinkedIn login ─────────────────────────────────────────────────

async def _login(page, email: str, password: str) -> bool:
    """Log in to LinkedIn."""
    print("  [LI Scraper] Logging in to LinkedIn...")
    try:
        await page.goto("https://www.linkedin.com/login", wait_until="domcontentloaded", timeout=30000)
        
        # Wait dynamically for either the login inputs OR redirect to feed/search
        try:
            await page.wait_for_function(
                """() => {
                    const emailInput = document.querySelector('input[type="email"], input#username, input[name="session_key"]');
                    const isEmailVisible = emailInput && (emailInput.offsetWidth > 0 || emailInput.offsetHeight > 0);
                    const isFeedOrSearch = window.location.href.includes('/feed') || window.location.href.includes('/search');
                    return isEmailVisible || isFeedOrSearch;
                }""",
                timeout=15000
            )
        except Exception:
            pass
        
        # Check if already logged in via redirect
        if "/feed" in page.url or "/search" in page.url:
            print("  [LI Scraper] Already logged in (auto-redirected)")
            return True

        email_selector = 'input[type="email"]:visible, input#username:visible, input[name="session_key"]:visible'
        await page.wait_for_selector(email_selector, state="visible", timeout=5000)

        email_input = page.locator(email_selector).first
        password_input = page.locator('input[type="password"]:visible, input#password:visible, input[name="session_password"]:visible').first
        submit_btn = page.locator('button:has-text("Sign in"):not(:has-text("Apple")):not(:has-text("Microsoft")):visible').first

        await email_input.fill(email)
        await password_input.fill(password)
        await submit_btn.click()

        # Wait for redirect away from /login
        try:
            await page.wait_for_url(
                lambda url: "/login" not in url and "/checkpoint" not in url,
                timeout=20000,
            )
        except Exception:
            pass

        await page.wait_for_timeout(2000)

        current_url = page.url
        if "/login" in current_url or "/checkpoint" in current_url:
            print("  [LI Scraper] WARNING: Login failed or 2FA required")
            print("  [LI Scraper]   -> Run with --headed to complete 2FA manually")
            return False

        print("  [LI Scraper] Logged in successfully")
        return True

    except Exception as e:
        print(f"  [LI Scraper] Login error: {e}")
        print(f"  [LI Scraper] Page URL at error: {page.url}")
        try:
            os.makedirs("scratch", exist_ok=True)
            await page.screenshot(path="scratch/login_failure.png")
            print("  [LI Scraper] Saved failure screenshot to scratch/login_failure.png")
        except Exception as se:
            print(f"  [LI Scraper] Failed to save screenshot: {se}")
        return False


# ── Internal: extract posts from one search page ─────────────────────────────

async def _extract_posts_from_page(page, url: str) -> list[dict]:
    """Navigate to a LinkedIn search URL and extract post data."""
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=25000)
        await page.wait_for_timeout(4000)

        # Check for auth wall
        if "/login" in page.url or "/authwall" in page.url:
            return []

        # Scroll to load more posts
        for _ in range(SCROLL_COUNT):
            await page.evaluate("window.scrollBy(0, 800)")
            await page.wait_for_timeout(SCROLL_DELAY_MS)

        # Click all "see more" buttons to reveal full text and hidden links
        try:
            buttons = page.locator(
                'button.feed-shared-inline-show-more-text__button, '
                'button:has-text("see more"), '
                'button[aria-label*="see more"]'
            )
            count = await buttons.count()
            for i in range(min(count, 15)):  # Cap at 15 to avoid slowdowns
                btn = buttons.nth(i)
                if await btn.is_visible():
                    try:
                        await btn.click()
                    except Exception:
                        pass
        except Exception:
            pass

        # Extract post data using page.evaluate
        posts = await page.evaluate("""() => {
            const results = [];

            const containerSelectors = [
                'div[role="listitem"]',
                '.search-results__list .entity-result',
                '.search-results-container .entity-result',
                '[data-chameleon-result-urn]',
                '.update-components-update-v2',
                '.feed-shared-update-v2',
                '.occludable-update',
            ];

            let cards = [];
            for (const sel of containerSelectors) {
                cards = Array.from(document.querySelectorAll(sel));
                if (cards.length > 0) break;
            }

            for (const card of cards) {
                // Poster name & URL (handle both /in/ and /company/)
                const profileLinks = Array.from(card.querySelectorAll('a[href*="/in/"], a[href*="/company/"], a[href*="linkedin.com/in/"], a[href*="linkedin.com/company/"]'));
                
                let posterUrl = '';
                let posterName = '';
                
                if (profileLinks.length > 0) {
                    posterUrl = profileLinks[0].href;
                    const nameLink = profileLinks.find(a => a.innerText.trim().length > 0);
                    if (nameLink) {
                        posterName = nameLink.innerText.split('\\n')[0].trim();
                    }
                }
                
                if (posterUrl) {
                    try {
                        const p = new URL(posterUrl);
                        posterUrl = p.origin + p.pathname.split('?')[0];
                    } catch (_) {}
                }

                // Poster headline fallback
                const headlineEl = card.querySelector(
                    '.entity-result__primary-subtitle,' +
                    '.update-components-actor__description,' +
                    '.feed-shared-actor__description'
                );
                let posterHeadline = headlineEl?.innerText?.trim() || '';
                if (!posterHeadline && profileLinks.length > 0) {
                    const nameLink = profileLinks.find(a => a.innerText.trim().length > 0);
                    if (nameLink) {
                        const parts = nameLink.innerText.split('\\n').map(x => x.trim()).filter(Boolean);
                        if (parts.length > 1) {
                            posterHeadline = parts.slice(1).join(' ');
                        }
                    }
                }

                // Post text
                const textEl = card.querySelector(
                    '.entity-result__summary,' +
                    '.update-components-text,' +
                    '.feed-shared-text,' +
                    '.break-words'
                );
                let postText = textEl?.innerText?.trim() || '';
                if (!postText) {
                    // Fallback: find the span/div with longest text that doesn't contain "Follow"
                    const allTextElements = Array.from(card.querySelectorAll('span, div')).filter(el => {
                        const text = el.innerText || '';
                        return text.length > 100 && !text.includes('Follow');
                    });
                    if (allTextElements.length > 0) {
                        allTextElements.sort((a, b) => b.innerText.length - a.innerText.length);
                        postText = allTextElements[0].innerText.trim();
                    }
                }

                // All links in the card
                const linkEls = Array.from(card.querySelectorAll('a[href]'));
                const hrefs = linkEls.map(a => {
                    try { return new URL(a.href).href; } catch (_) { return ''; }
                }).filter(Boolean);

                // Post URN (for dedup)
                const urn =
                    card.getAttribute('data-chameleon-result-urn') ||
                    card.getAttribute('data-urn') ||
                    card.getAttribute('data-id') ||
                    '';

                // Direct post link
                const postLinkEl = card.querySelector('a[href*="/feed/update/"]');
                const directPostUrl = postLinkEl?.href || '';

                if (postText || posterName) {
                    results.push({ posterName, posterUrl, posterHeadline, postText, hrefs, urn, directPostUrl });
                }
            }

            return results;
        }""")

        return posts or []

    except Exception as e:
        print(f"  [LI Scraper] Error extracting posts: {e}")
        return []


# ── Database save ────────────────────────────────────────────────────────────

def _save_posts_to_db(posts: list[dict]):
    """Save discovered posts to jobs.db -> posts table."""
    try:
        from core.database import init_posts_table, _connect_jobs, _row_to_dict

        init_posts_table()

        with _connect_jobs() as conn:
            for post in posts:
                try:
                    conn.execute(
                        """INSERT OR IGNORE INTO posts
                           (title, company, location, apply_link, poster_name,
                            poster_url, post_text, source, keywords, scraped_at,
                            status, post_urn, post_url, apply_url, apply_method)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (
                            post["title"], post["company"], post["location"],
                            post["apply_link"], post["poster_name"], post["poster_url"],
                            post["post_text"], post["source"], post["keywords"],
                            post["scraped_at"], post["status"],
                            post.get("post_urn"), post.get("post_url", ""),
                            post.get("apply_url", ""),
                            post.get("apply_method", ""),
                        ),
                    )
                except Exception:
                    pass
            conn.commit()

        print(f"  [LI Scraper] Saved {len(posts)} posts to database")

    except Exception as e:
        print(f"  [LI Scraper] DB save error: {e}")


# ── CLI ──────────────────────────────────────────────────────────────────────

async def _cli_main():
    import argparse
    p = argparse.ArgumentParser(description="LinkedIn Feed Posts Scraper")
    p.add_argument("--user-id", type=int, required=True, help="User ID for cookie caching")
    p.add_argument("--headed", action="store_true", help="Show browser window")
    p.add_argument("--max-pages", type=int, default=2, help="Max pages per query")
    args = p.parse_args()

    from core.database import get_user
    user = get_user(args.user_id)
    if not user:
        print(f"ERROR: User {args.user_id} not found")
        return

    li_user = user.get("linkedin_username", "")
    li_pass = user.get("linkedin_password", "")
    if not li_user or not li_pass:
        print("ERROR: LinkedIn credentials not set for this user")
        return

    prefs_str = user.get("job_preferences", "{}")
    try:
        prefs = json.loads(prefs_str) if isinstance(prefs_str, str) else prefs_str
    except Exception:
        prefs = {}

    roles = prefs.get("roles", ["Software Engineer"])
    locations = prefs.get("locations", ["India"])

    posts = await scrape_linkedin_posts(
        user_id=args.user_id,
        linkedin_username=li_user,
        linkedin_password=li_pass,
        roles=roles,
        locations=locations,
        max_pages=args.max_pages,
        headed=args.headed,
    )
    print(f"\n[OK] Scraped {len(posts)} posts total")


if __name__ == "__main__":
    asyncio.run(_cli_main())
