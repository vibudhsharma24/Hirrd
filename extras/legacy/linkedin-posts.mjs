#!/usr/bin/env node

/**
 * linkedin-posts.mjs — LinkedIn Post-Based Job Scraper
 *
 * Scrapes LinkedIn FEED POSTS (not the jobs board) for job openings.
 * Requires a LinkedIn login. Credentials are read from linkedin-config.yml.
 *
 * For each post it extracts:
 *   - title        : job position name (parsed from post text)
 *   - company      : company name (from poster's headline or post text)
 *   - location     : location mentioned in post
 *   - apply_link   : the apply URL (LinkedIn Easy Apply, careers page, Google Form, etc.)
 *   - poster_name  : name of the person who posted
 *   - poster_url   : LinkedIn profile URL of the poster
 *   - post_text    : first 500 chars of the post (for context)
 *   - source       : "linkedin-posts"
 *   - keywords     : which search term found this post
 *   - scraped_at   : ISO timestamp
 *   - status       : new | reviewed | applied | dismissed
 *
 * Saves to jobs.db  →  `posts` table (separate from the jobs-board `jobs` table).
 *
 * Usage:
 *   npm run posts              # scrape all enabled keywords
 *   npm run posts:dry          # preview, no DB writes
 *   npm run posts:headed       # visible browser (recommended for first run)
 *   npm run posts:kw "hiring data engineer india"
 *
 * Login cookies are cached in linkedin-cookies.json after the first login
 * so you don't need to enter credentials every time.
 */

import { readFileSync, writeFileSync, existsSync } from 'fs';
import { fileURLToPath } from 'url';
import { dirname, join } from 'path';
import { chromium } from 'playwright';
import yaml from 'js-yaml';
import { DatabaseSync } from 'node:sqlite';

// ── Paths ────────────────────────────────────────────────────────────────────

const __dirname     = dirname(fileURLToPath(import.meta.url));
const CONFIG_PATH   = join(__dirname, 'linkedin-config.yml');
const DB_PATH       = join(__dirname, 'jobs.db');
const COOKIES_PATH  = join(__dirname, 'linkedin-cookies.json');

// ── Database setup ────────────────────────────────────────────────────────────

function openDb() {
  const db = new DatabaseSync(DB_PATH);
  db.exec('PRAGMA journal_mode = WAL');
  db.exec('PRAGMA foreign_keys = ON');

  db.exec(`
    CREATE TABLE IF NOT EXISTS posts (
      id               INTEGER PRIMARY KEY AUTOINCREMENT,
      title            TEXT    NOT NULL DEFAULT '',
      company          TEXT    NOT NULL DEFAULT '',
      location         TEXT    NOT NULL DEFAULT '',
      apply_link       TEXT    NOT NULL DEFAULT '',
      poster_name      TEXT    NOT NULL DEFAULT '',
      poster_url       TEXT    NOT NULL DEFAULT '',
      post_text        TEXT    NOT NULL DEFAULT '',
      source           TEXT    NOT NULL DEFAULT 'linkedin-posts',
      keywords         TEXT    NOT NULL DEFAULT '',
      scraped_at       TEXT    NOT NULL,
      status           TEXT    NOT NULL DEFAULT 'new',
      post_urn         TEXT    UNIQUE DEFAULT NULL,
      post_url         TEXT    NOT NULL DEFAULT '',
      apply_url        TEXT    NOT NULL DEFAULT ''
    )
  `);

  // Idempotently add post_url if not present
  try {
    db.exec(`ALTER TABLE posts ADD COLUMN post_url TEXT NOT NULL DEFAULT ''`);
  } catch (_) {
    // Column already exists or table doesn't exist
  }

  // Idempotently add apply_url if not present
  try {
    db.exec(`ALTER TABLE posts ADD COLUMN apply_url TEXT NOT NULL DEFAULT ''`);
  } catch (_) {
    // Column already exists or table doesn't exist
  }

  return db;
}

// ── Cookie helpers ────────────────────────────────────────────────────────────

function saveCookies(cookies) {
  writeFileSync(COOKIES_PATH, JSON.stringify(cookies, null, 2), 'utf-8');
}

function loadCookies() {
  if (!existsSync(COOKIES_PATH)) return null;
  try {
    return JSON.parse(readFileSync(COOKIES_PATH, 'utf-8'));
  } catch (_) {
    return null;
  }
}

// ── LinkedIn login ────────────────────────────────────────────────────────────

async function login(page, email, password) {
  console.log('🔐 Logging in to LinkedIn...');
  await page.goto('https://www.linkedin.com/login', { waitUntil: 'domcontentloaded', timeout: 30000 });
  await page.waitForTimeout(1500);

  await page.fill('#username', email);
  await page.fill('#password', password);
  await page.click('[data-litms-control-urn="login-submit"], button[type="submit"]');

  // Wait for redirect away from /login
  try {
    await page.waitForURL(url => !url.includes('/login') && !url.includes('/checkpoint/lg'), { timeout: 20000 });
  } catch (_) {
    // May land on checkpoint / 2FA — give user time in headed mode
  }

  await page.waitForTimeout(2000);

  const url = page.url();
  if (url.includes('/login') || url.includes('/checkpoint')) {
    throw new Error(
      'Login failed or 2FA required.\n' +
      '  → Run with --headed so you can complete 2FA manually,\n' +
      '    then re-run to save cookies.'
    );
  }

  console.log('✅ Logged in successfully');
}

// ── Post search URL builder ───────────────────────────────────────────────────

/**
 * Builds a LinkedIn content/post search URL.
 * datePosted options: "past-24h" | "past-week" | "past-month"
 */
function buildPostSearchUrl(keywords, datePosted = 'past-week') {
  const params = new URLSearchParams({
    keywords,
    origin:     'SWITCH_SEARCH_VERTICAL',
    datePosted,
    sortBy:     'date_posted',
  });
  return `https://www.linkedin.com/search/results/content/?${params.toString()}`;
}

// ── Text helpers ─────────────────────────────────────────────────────────────

function cleanTitle(title) {
  if (!title) return '';

  let cleaned = title;
  try {
    cleaned = cleaned.replace(/\p{Extended_Pictographic}/gu, '');
  } catch (_) {
    cleaned = cleaned.replace(/[\u2700-\u27BF]|[\uE000-\uF8FF]|\uD83C[\uDC00-\uDFFF]|\uD83D[\uDC00-\uDFFF]|[\u2011-\u26FF]|\uD83E[\uDC00-\uDFFF]/g, '');
  }

  // Remove common noise words/phrases using word boundaries
  cleaned = cleaned.replace(/\b(we|re|we're|are|hiring|for|looking|seeking|need|join|us|our|team|is|to|a|an|role|position|opening|job|opportunity|hiring!|openings|immediate|urgently|actively|active|new|alert)\b/ig, '');

  // Clean up any remaining leading/trailing/multiple spaces and symbols/punctuation
  cleaned = cleaned.replace(/^[:\s\-–—|/•+*#@(),;[\]{}]+/g, ''); // leading punctuation and spaces
  cleaned = cleaned.replace(/[:\s\-–—|/•+*#@(),;[\]{}]+$/g, ''); // trailing punctuation and spaces
  cleaned = cleaned.replace(/\s+/g, ' ').trim();

  return cleaned;
}

/**
 * Try to extract a job title from post text.
 * Looks for common patterns first, then falls back to the first meaningful line.
 */
function extractTitle(text) {
  if (!text) return '';

  let title = '';

  // Pattern: "Role: ...", "Position: ...", "Title: ...", "Opening: ..."
  const labelMatch = text.match(
    /(?:role|position|title|opening|hiring for|looking for|seeking)[:\s–-]+([^\n.!?|]{5,80})/i
  );
  if (labelMatch) {
    title = labelMatch[1].trim();
  } else {
    // Pattern: "We are hiring a/an X" or "Looking for a/an X"
    const hiringMatch = text.match(
      /(?:hiring|looking for|seeking|need) (?:a |an )?([A-Z][^\n.!?|]{4,70})/
    );
    if (hiringMatch) {
      title = hiringMatch[1].trim();
    } else {
      // Fall back: first non-empty line under 100 chars (likely the headline)
      const lines = text.split('\n').map(l => l.trim()).filter(Boolean);
      for (const line of lines) {
        if (line.length >= 5 && line.length <= 100) {
          title = line;
          break;
        }
      }
      if (!title) {
        title = text.slice(0, 80).trim();
      }
    }
  }

  return cleanTitle(title);
}

/**
 * Try to extract a location from post text.
 * Looks for city/country patterns or explicit location labels.
 */
function extractLocation(text) {
  if (!text) return '';

  const locMatch = text.match(
    /(?:location|based in|in)\s*[:\-]?\s*([A-Z][a-zA-Z ,]+(?:India|USA|UK|Remote|Hybrid|Bangalore|Mumbai|Delhi|Hyderabad|Pune|Chennai|Gurugram|Noida)[a-zA-Z ,]*)/i
  );
  if (locMatch) return locMatch[1].trim().slice(0, 80);

  // Look for "Remote" / "Hybrid" / known cities
  const cityMatch = text.match(
    /\b(Remote|Hybrid|Bangalore|Bengaluru|Mumbai|Delhi|NCR|Hyderabad|Pune|Chennai|Gurugram|Noida|Kolkata|Ahmedabad|Jaipur|India)\b/i
  );
  if (cityMatch) return cityMatch[1];

  return '';
}

/**
 * Try to extract company name from post text or poster headline.
 */
function extractCompany(postText, posterHeadline) {
  // From post text: "at XYZ", "@ XYZ", "join XYZ"
  const atMatch = postText.match(/(?:\bat\b|@|join)\s+([A-Z][A-Za-z0-9& ,.]+?)(?:\s*[|!?.\n]|$)/);
  if (atMatch) return atMatch[1].trim().slice(0, 80);

  // From poster headline: "Recruiter at XYZ" or "HR | XYZ"
  if (posterHeadline) {
    const headlineAt = posterHeadline.match(/(?:at|@|\|)\s*([A-Z][A-Za-z0-9& ,.]+)/);
    if (headlineAt) return headlineAt[1].trim().slice(0, 80);
  }

  return '';
}

/**
 * Strip only known tracking/decorative query params from a URL,
 * preserving structural params that are needed for the link to work.
 * (e.g. Lever, Greenhouse, Workday links embed job IDs in the query string)
 */
function stripTrackingParams(rawUrl) {
  try {
    const u = new URL(rawUrl);
    const TRACKING_KEYS = [
      'utm_source', 'utm_medium', 'utm_campaign', 'utm_content', 'utm_term',
      'li_source', 'li_medium', 'refId', 'trk', 'trkInfo',
      'ref', 'src', 'source',
    ];
    for (const key of TRACKING_KEYS) {
      u.searchParams.delete(key);
    }
    // Remove trailing '?' if all params were removed
    return u.toString().replace(/\?$/, '');
  } catch (_) {
    // If URL parsing fails, strip everything after '?' as a safe fallback
    return rawUrl.split('?')[0].split('#')[0];
  }
}

/**
 * Helper to resolve redirect URLs (e.g. lnkd.in, bit.ly) to their destination URLs.
 * Uses native fetch with a User-Agent header and a timeout.
 */
async function resolveUrl(url) {
  if (!url) return '';
  const isShortener = 
    url.includes('lnkd.in') || 
    url.includes('bit.ly') || 
    url.includes('tinyurl.com') || 
    url.includes('t.co') || 
    url.includes('rebrand.ly') ||
    url.includes('shorturl.at');

  if (!isShortener) return url;

  try {
    const res = await fetch(url, {
      method: 'GET',
      headers: {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
      },
      signal: AbortSignal.timeout(5000)
    });
    return res.url || url;
  } catch (_) {
    return url;
  }
}

/**
 * Extract the best apply/job link from a list of hrefs found in the post.
 * Priority: external career links > LinkedIn job links > any http link
 */
function extractApplyLink(hrefs) {
  if (!hrefs || hrefs.length === 0) return '';

  const clean = hrefs
    .map(h => stripTrackingParams(h))
    .filter(h => h.startsWith('http'));

  // Skip purely navigational LinkedIn URLs (profiles, search, feed)
  const isLinkedInNav = h =>
    h.includes('linkedin.com/search') ||
    h.includes('linkedin.com/feed') ||
    h.includes('linkedin.com/in/') ||
    h.includes('linkedin.com/company/') ||
    h.includes('linkedin.com/home');

  // Prefer external non-LinkedIn links (actual career pages / ATS portals)
  const external = clean.filter(h => !isLinkedInNav(h) && !h.includes('linkedin.com'));
  if (external.length > 0) return external[0];

  // Fall back to LinkedIn Easy Apply / job-view links
  const liJob = clean.find(h => h.includes('linkedin.com/jobs'));
  if (liJob) return liJob;

  // Last resort: any http link that isn't pure LinkedIn navigation
  const anyNonNav = clean.find(h => !isLinkedInNav(h));
  if (anyNonNav) return anyNonNav;

  return clean[0] || '';
}

// ── Playwright: extract posts from one search page ───────────────────────────

async function extractPostsFromPage(page, url, delayMs) {
  try {
    await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 25000 });
    await page.waitForTimeout(4000);

    // Check for auth wall
    const currentUrl = page.url();
    if (currentUrl.includes('/login') || currentUrl.includes('/authwall')) {
      return { posts: [], blocked: true, reason: `Auth wall: ${currentUrl}` };
    }

    // Scroll to load more posts
    for (let i = 0; i < 3; i++) {
      await page.evaluate(() => window.scrollBy(0, 800));
      await page.waitForTimeout(1200);
    }

    // Click all "see more" buttons to expand post contents and reveal links
    try {
      const buttons = page.locator('button.feed-shared-inline-show-more-text__button, button:has-text("see more"), button[aria-label*="see more"]');
      const count = await buttons.count();
      for (let i = 0; i < count; i++) {
        const btn = buttons.nth(i);
        if (await btn.isVisible()) {
          await btn.click().catch(() => {});
        }
      }
    } catch (_) {}

    const posts = await page.evaluate(() => {
      const results = [];

      // LinkedIn post containers — try multiple selectors across versions
      const containerSelectors = [
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
        // ── Poster name ──
        const nameEl = card.querySelector(
          '.entity-result__title-text a span[aria-hidden="true"],' +
          '.update-components-actor__name span[aria-hidden="true"],' +
          '.feed-shared-actor__name,' +
          '.app-aware-link .ember-view'
        );
        const posterName = nameEl?.innerText?.trim() || '';

        // ── Poster profile URL ──
        const profileLinkEl = card.querySelector(
          '.entity-result__title-text a[href*="/in/"],' +
          '.update-components-actor__container-link,' +
          '.feed-shared-actor__container-link,' +
          'a[href*="linkedin.com/in/"]'
        );
        let posterUrl = profileLinkEl?.href || '';
        if (posterUrl) {
          try {
            const p = new URL(posterUrl);
            // Keep only /in/username part
            posterUrl = p.origin + p.pathname.split('?')[0];
          } catch (_) {}
        }

        // ── Poster headline (company/role) ──
        const headlineEl = card.querySelector(
          '.entity-result__primary-subtitle,' +
          '.update-components-actor__description,' +
          '.feed-shared-actor__description'
        );
        const posterHeadline = headlineEl?.innerText?.trim() || '';

        // ── Post text ──
        const textEl = card.querySelector(
          '.entity-result__summary,' +
          '.update-components-text,' +
          '.feed-shared-text,' +
          '.break-words'
        );
        const postText = textEl?.innerText?.trim() || '';

        // ── All links in this post card ──
        const linkEls = Array.from(card.querySelectorAll('a[href]'));
        const hrefs = linkEls
          .map(a => {
            try { return new URL(a.href).href; } catch (_) { return ''; }
          })
          .filter(Boolean);

        // ── Post URN (for dedup) ──
        const urn =
          card.getAttribute('data-chameleon-result-urn') ||
          card.getAttribute('data-urn') ||
          card.getAttribute('data-id') ||
          '';

        // ── Direct Post Link ──
        const postLinkEl = card.querySelector('a[href*="/feed/update/"]');
        const directPostUrl = postLinkEl?.href || '';

        if (postText || posterName) {
          results.push({ posterName, posterUrl, posterHeadline, postText, hrefs, urn, directPostUrl });
        }
      }

      return results;
    });

    await page.waitForTimeout(delayMs);
    return { posts, blocked: false };

  } catch (err) {
    return { posts: [], blocked: false, error: err.message };
  }
}

// ── Title filter ──────────────────────────────────────────────────────────────

function buildTitleFilter(negativeKeywords = []) {
  const negative = negativeKeywords.map(k => k.toLowerCase());
  return (title) => {
    if (!title) return true; // don't discard if we couldn't extract a title
    const lower = title.toLowerCase();
    return !negative.some(k => lower.includes(k));
  };
}

// ── DB helpers ────────────────────────────────────────────────────────────────

function loadSeenUrns(db) {
  const rows = db.prepare('SELECT post_urn FROM posts WHERE post_urn IS NOT NULL').all();
  return new Set(rows.map(r => r.post_urn).filter(Boolean));
}

function loadSeenApplyLinks(db) {
  const rows = db.prepare("SELECT apply_link FROM posts WHERE apply_link != ''").all();
  return new Set(rows.map(r => r.apply_link).filter(Boolean));
}

function insertPosts(db, records, scrapedAt) {
  const insert = db.prepare(`
    INSERT OR IGNORE INTO posts
      (title, company, location, apply_link, poster_name, poster_url,
       post_text, source, keywords, scraped_at, status, post_urn, post_url, apply_url)
    VALUES (?, ?, ?, ?, ?, ?, ?, 'linkedin-posts', ?, ?, 'new', ?, ?, ?)
  `);

  for (const r of records) {
    insert.run(
      r.title,
      r.company,
      r.location,
      r.apply_link,
      r.poster_name,
      r.poster_url,
      r.post_text.slice(0, 600),
      r.keywords,
      scrapedAt,
      r.post_urn || null,
      r.post_url || '',
      r.apply_url || '',
    );
  }
}

// ── Main ──────────────────────────────────────────────────────────────────────

async function main() {
  const args     = process.argv.slice(2);
  const dryRun   = args.includes('--dry-run');
  const headed   = args.includes('--headed');
  const relogin  = args.includes('--relogin');   // force fresh login

  const kwIdx    = args.indexOf('--kw');
  const cliKw    = kwIdx !== -1 ? args[kwIdx + 1] : null;

  const pagesIdx = args.indexOf('--max-pages');
  const cliPages = pagesIdx !== -1 ? parseInt(args[pagesIdx + 1], 10) : null;

  // ── Load config ──
  if (!existsSync(CONFIG_PATH)) {
    console.error('Error: linkedin-config.yml not found.');
    process.exit(1);
  }

  const config      = yaml.load(readFileSync(CONFIG_PATH, 'utf-8'));
  const creds       = config.credentials || {};
  const email       = creds.email || '';
  const password    = creds.password || '';
  const postSearch  = config.post_search || {};
  const maxPages    = cliPages ?? postSearch.max_pages ?? 3;
  const delayMs     = (postSearch.page_delay_sec ?? 5) * 1000;
  const datePosted  = postSearch.date_posted || 'past-week';
  const titleFilter = buildTitleFilter(config.title_filter?.negative || []);

  if (!email || !password) {
    console.error('Error: credentials.email and credentials.password must be set in linkedin-config.yml');
    process.exit(1);
  }

  // ── Determine keywords ──
  let keywords = (postSearch.keywords || []).filter(k => k.enabled !== false);
  if (cliKw) {
    keywords = [{ query: cliKw, enabled: true }];
  }
  if (keywords.length === 0) {
    console.error('No enabled post_search keywords found. Check linkedin-config.yml → post_search.keywords');
    process.exit(1);
  }

  // ── Open DB ──
  const db = dryRun ? null : openDb();

  console.log(`\n🔍 LinkedIn Post Scraper — IITIIMJobAssistant`);
  console.log(`${'─'.repeat(50)}`);
  console.log(`Keywords:          ${keywords.length}`);
  console.log(`Max pages/keyword: ${maxPages}`);
  console.log(`Date filter:       ${datePosted}`);
  console.log(`Database:          ${dryRun ? 'DRY RUN — no writes' : DB_PATH}`);
  if (headed) console.log(`Browser:           HEADED (visible window)`);
  console.log();

  // ── Load dedup state ──
  const seenUrns       = dryRun ? new Set() : loadSeenUrns(db);
  const seenApplyLinks = dryRun ? new Set() : loadSeenApplyLinks(db);
  console.log(`Already in DB:     ${seenUrns.size} posts (will skip duplicates)\n`);

  // ── Launch browser ──
  const browser = await chromium.launch({
    headless: !headed,
    args: ['--no-sandbox', '--disable-setuid-sandbox', '--disable-blink-features=AutomationControlled'],
  });

  const storedCookies = !relogin ? loadCookies() : null;

  const context = await browser.newContext({
    userAgent:
      'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 ' +
      '(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
    viewport: { width: 1366, height: 768 },
    locale:   'en-US',
  });

  if (storedCookies) {
    await context.addCookies(storedCookies);
    console.log('🍪 Restored saved session (no re-login needed)');
  }

  const page = await context.newPage();

  // ── Login if needed ──
  if (!storedCookies) {
    try {
      await login(page, email, password);
      const cookies = await context.cookies();
      saveCookies(cookies);
      console.log('🍪 Session cookies saved to linkedin-cookies.json\n');
    } catch (err) {
      console.error(`\n❌ ${err.message}`);
      await browser.close();
      process.exit(1);
    }
  } else {
    // Verify the session is still valid
    await page.goto('https://www.linkedin.com/feed/', { waitUntil: 'domcontentloaded', timeout: 20000 });
    await page.waitForTimeout(2000);
    if (page.url().includes('/login') || page.url().includes('/authwall')) {
      console.log('⚠️  Saved session expired — re-logging in...');
      await login(page, email, password);
      const cookies = await context.cookies();
      saveCookies(cookies);
      console.log('🍪 Session refreshed\n');
    }
  }

  // ── Scan each keyword ──
  const scrapedAt  = new Date().toISOString();
  const date       = scrapedAt.slice(0, 10);
  const newRecords = [];
  const errors     = [];
  let totalFound   = 0;
  let totalDupes   = 0;
  let totalFiltered = 0;

  for (const kw of keywords) {
    const query = kw.query || kw;
    console.log(`\n📋 Searching posts: "${query}"`);

    for (let p = 0; p < maxPages; p++) {
      const url = buildPostSearchUrl(query, datePosted);
      // LinkedIn post search paginates via scroll/offset — for simplicity we
      // get the first N pages by adjusting the `start` param
      const pagedUrl = `${url}&start=${p * 10}`;
      process.stdout.write(`   Page ${p + 1}/${maxPages} → `);

      const { posts, blocked, reason, error } = await extractPostsFromPage(page, pagedUrl, delayMs);

      if (blocked) {
        console.log(`⛔ Blocked — ${reason}`);
        break;
      }
      if (error) {
        console.log(`⚠️  Error — ${error}`);
        errors.push({ query, page: p + 1, error });
        break;
      }

      totalFound += posts.length;
      let pageNew = 0;

      for (const post of posts) {
        // Dedup by URN
        if (post.urn && seenUrns.has(post.urn)) {
          totalDupes++;
          continue;
        }

        // Parse structured fields
        const title      = extractTitle(post.postText);
        const company    = extractCompany(post.postText, post.posterHeadline);
        const location   = extractLocation(post.postText);
        const rawApplyLink = extractApplyLink(post.hrefs);
        let applyLink = '';
        if (rawApplyLink) {
          const resolved = await resolveUrl(rawApplyLink);
          applyLink = stripTrackingParams(resolved);
        }

        // Dedup by apply link (if we have one)
        if (applyLink && seenApplyLinks.has(applyLink)) {
          totalDupes++;
          continue;
        }

        // Title filter
        if (!titleFilter(title)) {
          totalFiltered++;
          continue;
        }

        // Construct Post URL
        let postUrl = post.directPostUrl || '';
        if (!postUrl && post.urn) {
          if (post.urn.startsWith('urn:li:')) {
            postUrl = `https://www.linkedin.com/feed/update/${post.urn}/`;
          } else if (/^\d+$/.test(post.urn)) {
            postUrl = `https://www.linkedin.com/feed/update/urn:li:activity:${post.urn}/`;
          }
        }

        if (post.urn)      seenUrns.add(post.urn);
        if (applyLink)     seenApplyLinks.add(applyLink);

        newRecords.push({
          title,
          company,
          location,
          apply_link:  applyLink,
          apply_url:   applyLink,
          poster_name: post.posterName,
          poster_url:  post.posterUrl,
          post_text:   post.postText,
          keywords:    query,
          post_urn:    post.urn || null,
          post_url:    postUrl,
        });
        pageNew++;
      }

      console.log(`${posts.length} posts found, ${pageNew} new`);
      if (posts.length === 0) break;
    }
  }

  await browser.close();

  // ── Write to DB ──
  if (!dryRun && newRecords.length > 0) {
    insertPosts(db, newRecords, scrapedAt);
  }
  if (db) db.close();

  // ── Summary ──
  console.log(`\n${'━'.repeat(50)}`);
  console.log(`LinkedIn Posts Scan — ${date}`);
  console.log(`${'━'.repeat(50)}`);
  console.log(`Keywords scanned:      ${keywords.length}`);
  console.log(`Total posts found:     ${totalFound}`);
  console.log(`Filtered by title:     ${totalFiltered} removed`);
  console.log(`Duplicates skipped:    ${totalDupes}`);
  console.log(`New records added:     ${newRecords.length}`);

  if (errors.length > 0) {
    console.log(`\nErrors (${errors.length}):`);
    for (const e of errors) console.log(`  ✗ "${e.query}" page ${e.page}: ${e.error}`);
  }

  if (newRecords.length > 0) {
    console.log('\nNew posts scraped:');
    for (const r of newRecords.slice(0, 20)) {
      console.log(`  + [${r.poster_name}] ${r.title || '(title TBD)'} @ ${r.company || '?'} | ${r.location || 'N/A'}`);
      if (r.post_url)   console.log(`    post_url:  ${r.post_url}`);
      if (r.apply_url)  console.log(`    apply_url: ${r.apply_url}`);
    }
    if (newRecords.length > 20) console.log(`  ... and ${newRecords.length - 20} more`);

    if (dryRun) {
      console.log('\n(dry run — run without :dry to save to database)');
    } else {
      console.log(`\n✅ Saved to ${DB_PATH}  →  posts table`);
      console.log(`   View via: GET http://localhost:5000/api/posts`);
    }
  } else {
    console.log('\nNo new posts found.');
  }
}

main().catch(err => {
  console.error('Fatal:', err.message);
  process.exit(1);
});
