#!/usr/bin/env node

/**
 * linkedin-scan.mjs — LinkedIn Role-Based Job Scanner
 *
 * Searches LinkedIn's public job board by role keyword (e.g. "software engineer")
 * and saves discovered jobs into the project's SQLite database (users.db).
 *
 * Integrates with the IITIIMJobAssistant Flask backend:
 *   - Writes to the `jobs` table in users.db (same DB as the user system)
 *   - Deduplicates by URL — already-seen jobs are skipped on every run
 *   - Flask exposes scraped jobs via GET /api/jobs
 *
 * Usage:
 *   npm run linkedin               # scan all enabled roles
 *   npm run linkedin:dry           # preview — no DB writes
 *   npm run linkedin:headed        # visible browser (if LinkedIn blocks you)
 *   npm run linkedin:role "data analyst"  # single role override
 *   node linkedin-scan.mjs --max-pages 2 # override page limit
 *
 * Zero Claude API tokens — pure Playwright + public LinkedIn URLs.
 */

import { readFileSync, existsSync } from 'fs';
import { fileURLToPath } from 'url';
import { dirname, join } from 'path';
import { chromium } from 'playwright';
import yaml from 'js-yaml';
import { DatabaseSync } from 'node:sqlite';

// ── Paths ────────────────────────────────────────────────────────────────────

const __dirname      = dirname(fileURLToPath(import.meta.url));
const CONFIG_PATH    = join(__dirname, 'linkedin-config.yml');
const DB_PATH        = join(__dirname, 'jobs.db');

// ── Database setup ───────────────────────────────────────────────────────────

/**
 * Opens users.db and creates the `jobs` table if it doesn't already exist.
 * Returns the DatabaseSync instance (Node 22 built-in node:sqlite).
 */
function openDb() {
  const db = new DatabaseSync(DB_PATH);

  // WAL mode for safe concurrent reads alongside Flask
  db.exec('PRAGMA journal_mode = WAL');
  db.exec('PRAGMA foreign_keys = ON');

  db.exec(`
    CREATE TABLE IF NOT EXISTS jobs (
      id         INTEGER PRIMARY KEY AUTOINCREMENT,
      title      TEXT NOT NULL,
      company    TEXT NOT NULL DEFAULT '',
      location   TEXT NOT NULL DEFAULT '',
      url        TEXT UNIQUE  NOT NULL,
      apply_link TEXT NOT NULL DEFAULT '',
      source     TEXT NOT NULL DEFAULT 'linkedin',
      keywords   TEXT NOT NULL DEFAULT '',
      scraped_at TEXT NOT NULL,
      status     TEXT NOT NULL DEFAULT 'new'
    )
  `);

  // Add apply_link to existing DBs that were created before this column existed
  try {
    db.exec(`ALTER TABLE jobs ADD COLUMN apply_link TEXT NOT NULL DEFAULT ''`);
  } catch (_) { /* column already exists — ignore */ }

  return db;
}

// ── LinkedIn URL builder ──────────────────────────────────────────────────────

/**
 * Builds a LinkedIn public job search URL.
 * @param {string} keywords  - role search terms
 * @param {string} location  - location string (empty = worldwide)
 * @param {object} filters   - { work_type, date_posted, experience_level }
 * @param {number} page      - 0-indexed page number (start = page * 25)
 */
function buildLinkedInUrl(keywords, location, filters, page = 0) {
  const params = new URLSearchParams();

  params.set('keywords', keywords);
  if (location)                  params.set('location', location);
  if (filters.date_posted)       params.set('f_TPR',    filters.date_posted);
  if (filters.work_type)         params.set('f_WT',     filters.work_type);
  if (filters.experience_level)  params.set('f_E',      filters.experience_level);

  params.set('sortBy', 'DD');              // newest first
  params.set('start',  String(page * 25)); // pagination offset

  return `https://www.linkedin.com/jobs/search/?${params.toString()}`;
}

// ── Playwright: extract jobs from one page ────────────────────────────────────

/**
 * Navigates to a LinkedIn job search page and extracts all visible job cards.
 * Returns { jobs: [{title, company, location, url}], blocked, reason?, error? }
 */
async function extractJobsFromPage(page, url, delayMs) {
  try {
    await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 20000 });

    // Wait for LinkedIn SPA to hydrate job cards
    await page.waitForTimeout(3000);

    // Check for login wall or CAPTCHA redirect
    const currentUrl = page.url();
    if (
      currentUrl.includes('/login') ||
      currentUrl.includes('/authwall') ||
      currentUrl.includes('/checkpoint')
    ) {
      return { jobs: [], blocked: true, reason: `Redirected to: ${currentUrl}` };
    }

    const bodyText = await page.evaluate(() => document.body?.innerText ?? '');
    if (bodyText.includes('Sign in to view more jobs') && bodyText.length < 2000) {
      return { jobs: [], blocked: true, reason: 'Login wall detected (minimal content)' };
    }

    // Extract job cards using LinkedIn's public DOM structure
    const jobs = await page.evaluate(() => {
      const results = [];

      // LinkedIn uses these selectors on the public jobs page
      const cardSelectors = [
        '.job-search-card',
        '.jobs-search__results-list li',
        '[data-entity-urn]',
      ];

      let cards = [];
      for (const sel of cardSelectors) {
        cards = Array.from(document.querySelectorAll(sel));
        if (cards.length > 0) break;
      }

      for (const card of cards) {
        // Title
        const titleEl = card.querySelector(
          '.job-search-card__title, h3.base-search-card__title, .base-card__full-link'
        );
        const title = titleEl?.innerText?.trim() || '';

        // Company
        const companyEl = card.querySelector(
          '.job-search-card__company-name, h4.base-search-card__subtitle, .base-search-card__subtitle a'
        );
        const company = companyEl?.innerText?.trim() || '';

        // Location
        const locationEl = card.querySelector(
          '.job-search-card__location, .job-search-card__location span, .base-search-card__metadata'
        );
        const location = locationEl?.innerText?.trim() || '';

        // URL — grab the canonical job link
        const linkEl = card.querySelector(
          'a.job-search-card__title-link, a.base-card__full-link, a[href*="/jobs/view/"]'
        );
        let url = linkEl?.href || '';

        // Strip tracking params — keep only the clean /jobs/view/{id}/ path
        // But preserve the full URL as apply_link (the listing page IS the apply page)
        let applyLink = url;
        if (url) {
          try {
            const parsed = new URL(url);
            url = parsed.origin + parsed.pathname;
            applyLink = url;  // clean URL is also the apply link for LinkedIn Jobs board
          } catch (_) { /* keep as-is */ }
        }

        if (title && url) {
          results.push({ title, company, location, url, apply_link: applyLink });
        }
      }

      return results;
    });

    // Human-like delay before next navigation
    await page.waitForTimeout(delayMs);

    return { jobs, blocked: false };

  } catch (err) {
    return { jobs: [], blocked: false, error: err.message };
  }
}

// ── Title filter ──────────────────────────────────────────────────────────────

function buildTitleFilter(negativeKeywords = []) {
  const negative = negativeKeywords.map(k => k.toLowerCase());
  return (title) => {
    const lower = title.toLowerCase();
    return !negative.some(k => lower.includes(k));
  };
}

// ── Dedup helpers ─────────────────────────────────────────────────────────────

/**
 * Returns a Set of all URLs already in the jobs table.
 */
function loadSeenUrls(db) {
  const rows = db.prepare('SELECT url FROM jobs').all();
  return new Set(rows.map(r => r.url));
}

// ── DB writer ─────────────────────────────────────────────────────────────────

/**
 * Inserts new jobs into the jobs table.
 * Uses INSERT OR IGNORE so URL uniqueness is enforced at DB level too.
 */
function insertJobs(db, offers, scrapedAt) {
  const insert = db.prepare(`
    INSERT OR IGNORE INTO jobs (title, company, location, url, apply_link, source, keywords, scraped_at, status)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'new')
  `);

  for (const job of offers) {
    insert.run(
      job.title,
      job.company,
      job.location,
      job.url,
      job.apply_link || job.url || '',  // apply_link = the job page itself for LinkedIn Jobs board
      job.source || 'linkedin',
      job.keywords || '',
      scrapedAt,
    );
  }
}

// ── Main ──────────────────────────────────────────────────────────────────────

async function main() {
  // ── Parse CLI args ──
  const args     = process.argv.slice(2);
  const dryRun   = args.includes('--dry-run');
  const headed   = args.includes('--headed');

  const roleIdx  = args.indexOf('--role');
  const cliRole  = roleIdx !== -1 ? args[roleIdx + 1] : null;

  const pagesIdx = args.indexOf('--max-pages');
  const cliPages = pagesIdx !== -1 ? parseInt(args[pagesIdx + 1], 10) : null;

  // ── Load config ──
  if (!existsSync(CONFIG_PATH)) {
    console.error(`Error: ${CONFIG_PATH} not found.`);
    process.exit(1);
  }

  const config      = yaml.load(readFileSync(CONFIG_PATH, 'utf-8'));
  const location    = config.location    || '';
  const maxPages    = cliPages ?? config.max_pages ?? 3;
  const delayMs     = (config.page_delay_sec ?? 4) * 1000;
  const titleFilter = buildTitleFilter(config.title_filter?.negative || []);

  const filters = {
    date_posted:      config.date_posted      || 'r604800',
    work_type:        config.work_type        || '',
    experience_level: config.experience_level || '',
  };

  // ── Determine roles to scan ──
  let roles = (config.roles || []).filter(r => r.enabled !== false);
  if (cliRole) {
    roles = [{ keywords: cliRole, enabled: true }];
  }

  if (roles.length === 0) {
    console.error('No enabled roles found. Check linkedin-config.yml.');
    process.exit(1);
  }

  // ── Open DB ──
  const db = dryRun ? null : openDb();

  console.log(`\n🔍 LinkedIn Job Scanner — IITIIMJobAssistant`);
  console.log(`${'─'.repeat(48)}`);
  console.log(`Roles to scan:     ${roles.length}`);
  console.log(`Max pages/role:    ${maxPages}`);
  console.log(`Location:          ${location || '(worldwide)'}`);
  console.log(`Experience level:  ${filters.experience_level || '(all levels)'}`);
  console.log(`Date posted:       ${filters.date_posted}`);
  console.log(`Database:          ${dryRun ? 'DRY RUN — no writes' : DB_PATH}`);
  if (headed) console.log(`Browser:           HEADED (visible window)`);
  console.log();

  // ── Load dedup state ──
  const seenUrls = dryRun ? new Set() : loadSeenUrls(db);
  console.log(`Already in DB:     ${seenUrls.size} jobs (will skip duplicates)\n`);

  // ── Launch Playwright ──
  const browser = await chromium.launch({
    headless: !headed,
    args: [
      '--no-sandbox',
      '--disable-setuid-sandbox',
      '--disable-blink-features=AutomationControlled',
    ],
  });

  // Use a realistic user agent to reduce bot detection
  const context = await browser.newContext({
    userAgent:
      'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 ' +
      '(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
    viewport: { width: 1280, height: 800 },
    locale:   'en-US',
  });

  const page = await context.newPage();

  // ── Scan each role ──
  const scrapedAt   = new Date().toISOString();
  const date        = scrapedAt.slice(0, 10);
  const newOffers   = [];
  const errors      = [];
  let totalFound    = 0;
  let totalFiltered = 0;
  let totalDupes    = 0;
  let blockedRoles  = 0;

  for (const role of roles) {
    const { keywords } = role;
    console.log(`📋 Scanning: "${keywords}"`);

    let roleBlocked = false;

    for (let p = 0; p < maxPages; p++) {
      const url = buildLinkedInUrl(keywords, location, filters, p);
      process.stdout.write(`   Page ${p + 1}/${maxPages} → `);

      const { jobs, blocked, reason, error } = await extractJobsFromPage(page, url, delayMs);

      if (blocked) {
        console.log(`⛔ Blocked — ${reason}`);
        console.log(`   ℹ  Try: npm run linkedin:headed`);
        roleBlocked = true;
        blockedRoles++;
        break;
      }

      if (error) {
        console.log(`⚠️  Error — ${error}`);
        errors.push({ role: keywords, page: p + 1, error });
        break;
      }

      totalFound += jobs.length;
      let pageNew = 0;

      for (const job of jobs) {
        // Apply title filter
        if (!titleFilter(job.title)) {
          totalFiltered++;
          continue;
        }

        // Dedup by URL
        if (seenUrls.has(job.url)) {
          totalDupes++;
          continue;
        }

        seenUrls.add(job.url);
        newOffers.push({ ...job, source: 'linkedin', keywords });
        pageNew++;
      }

      console.log(`${jobs.length} found, ${pageNew} new`);

      // No point paginating if LinkedIn returned nothing
      if (jobs.length === 0) break;
    }

    if (roleBlocked) continue;
  }

  await browser.close();

  // ── Write results to DB ──
  if (!dryRun && newOffers.length > 0) {
    insertJobs(db, newOffers, scrapedAt);
  }
  if (db) db.close();

  // ── Summary ──
  console.log(`\n${'━'.repeat(48)}`);
  console.log(`LinkedIn Scan — ${date}`);
  console.log(`${'━'.repeat(48)}`);
  console.log(`Roles scanned:         ${roles.length}`);
  console.log(`Total jobs found:      ${totalFound}`);
  console.log(`Filtered by title:     ${totalFiltered} removed`);
  console.log(`Duplicates skipped:    ${totalDupes}`);
  console.log(`New jobs added:        ${newOffers.length}`);

  if (blockedRoles > 0) {
    console.log(`\n⛔ ${blockedRoles} role(s) blocked by LinkedIn.`);
    console.log(`   → Run: npm run linkedin:headed`);
  }

  if (errors.length > 0) {
    console.log(`\nErrors (${errors.length}):`);
    for (const e of errors) {
      console.log(`  ✗ "${e.role}" page ${e.page}: ${e.error}`);
    }
  }

  if (newOffers.length > 0) {
    console.log('\nNew jobs:');
    for (const o of newOffers) {
      console.log(`  + ${o.company || '(unknown)'} | ${o.title} | ${o.location || 'N/A'}`);
    }
    if (dryRun) {
      console.log('\n(dry run — run without :dry to save to database)');
    } else {
      console.log(`\n✅ Saved to ${DB_PATH} — view via GET /api/jobs`);
    }
  } else if (!blockedRoles) {
    console.log('\nNo new jobs found (all were duplicates or filtered).');
  }

  console.log('\n→ Start Flask server and open http://localhost:5000 to review jobs.');
}

main().catch(err => {
  console.error('Fatal:', err.message);
  process.exit(1);
});
