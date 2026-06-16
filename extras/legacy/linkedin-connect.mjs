#!/usr/bin/env node

/**
 * linkedin-connect.mjs — Auto-Connect with Job Posters
 *
 * Reads scraped posts from jobs.db (poster_url column populated by
 * linkedin-posts.mjs) and sends LinkedIn connection requests to each
 * poster, attaching a short personalised note (<200 chars) where
 * LinkedIn offers the "Add a note" option.
 *
 * NO AI API KEY REQUIRED — messages are templated from DB data.
 *
 * Tracking:
 *   Adds a `connected_at` column (TEXT, nullable) to the posts table.
 *   Rows already marked are skipped so you can re-run safely.
 *
 * Usage:
 *   npm run connect               # send to all pending posters
 *   npm run connect:dry           # preview only — no requests sent
 *   npm run connect:headed        # visible browser (recommended for first run)
 *   npm run connect -- --limit 10 # cap how many requests to send per run
 *
 * ⚠️  LinkedIn caps connection requests at ~100/week.
 *     Keep --limit ≤ 20 per run and space runs out over the week.
 */

import { readFileSync, existsSync } from 'fs';
import { fileURLToPath } from 'url';
import { dirname, join } from 'path';
import { chromium } from 'playwright';
import yaml from 'js-yaml';
import { DatabaseSync } from 'node:sqlite';

// ── Paths ─────────────────────────────────────────────────────────────────────

const __dirname    = dirname(fileURLToPath(import.meta.url));
const CONFIG_PATH  = join(__dirname, 'linkedin-config.yml');
const DB_PATH      = join(__dirname, 'jobs.db');
const COOKIES_PATH = join(__dirname, 'linkedin-cookies.json');

// ── DB helpers ────────────────────────────────────────────────────────────────

function openDb() {
  const db = new DatabaseSync(DB_PATH);
  db.exec('PRAGMA journal_mode = WAL');
  db.exec('PRAGMA foreign_keys  = ON');

  // Add tracking column — silently ignored if it already exists
  try {
    db.exec('ALTER TABLE posts ADD COLUMN connected_at TEXT DEFAULT NULL');
  } catch (_) { /* column already present */ }

  return db;
}

/** Load posts that have a poster_url but haven't been connected yet. */
function loadPendingPosts(db, limit) {
  return db.prepare(`
    SELECT id, poster_name, poster_url, title, company, location
    FROM   posts
    WHERE  poster_url  != ''
    AND    connected_at IS NULL
    ORDER  BY scraped_at DESC
    LIMIT  ?
  `).all(limit);
}

/** Mark a post as connected (or failed) in the DB. */
function markConnected(db, id, status = 'sent') {
  db.prepare(
    "UPDATE posts SET connected_at = ? WHERE id = ?"
  ).run(`${new Date().toISOString()}:${status}`, id);
}

// ── Message builder ───────────────────────────────────────────────────────────

/**
 * Builds a personalised connection note < 200 chars.
 * No AI needed — uses fields already scraped into the DB.
 */
function buildNote(posterName, title, company) {
  const firstName = (posterName || '').split(' ')[0].trim() || 'there';

  // Truncate long fields so the full message stays short
  const safeTitle   = (title   || '').slice(0, 45).trim();
  const safeCompany = (company || '').slice(0, 35).trim();

  let note;

  if (safeTitle && safeCompany) {
    note = `Hi ${firstName}! I saw your post about the ${safeTitle} role at ${safeCompany} — I'm very interested and would love to connect! 🙏`;
  } else if (safeTitle) {
    note = `Hi ${firstName}! I saw your post about the ${safeTitle} role and I'm very interested. Would love to connect! 🙏`;
  } else if (safeCompany) {
    note = `Hi ${firstName}! I came across your hiring post at ${safeCompany} and I'm very interested. Would love to connect! 🙏`;
  } else {
    note = `Hi ${firstName}! I came across your hiring post and I'm very interested in the role. Would love to connect! 🙏`;
  }

  // Hard-cap at 199 chars (LinkedIn max for connection notes is 300, user wants <200)
  return note.length <= 199 ? note : note.slice(0, 196) + '...';
}

// ── LinkedIn login ────────────────────────────────────────────────────────────

async function restoreOrLogin(context, page, email, password) {
  // Try saved cookies first
  const cookiesRaw = existsSync(COOKIES_PATH)
    ? (() => { try { return JSON.parse(readFileSync(COOKIES_PATH, 'utf-8')); } catch (_) { return null; } })()
    : null;

  if (cookiesRaw) {
    await context.addCookies(cookiesRaw);
    console.log('🍪 Restored saved session');

    // Verify the session is still valid
    await page.goto('https://www.linkedin.com/feed/', { waitUntil: 'domcontentloaded', timeout: 20000 });
    await page.waitForTimeout(2000);

    if (!page.url().includes('/login') && !page.url().includes('/authwall')) {
      console.log('✅ Session valid — skipping login\n');
      return;
    }
    console.log('⚠️  Session expired — re-logging in...');
  }

  // Fresh login
  console.log('🔐 Logging in to LinkedIn...');
  await page.goto('https://www.linkedin.com/login', { waitUntil: 'domcontentloaded', timeout: 30000 });
  await page.waitForTimeout(1500);
  await page.fill('#username', email);
  await page.fill('#password', password);
  await page.click('[data-litms-control-urn="login-submit"], button[type="submit"]');

  try {
    await page.waitForURL(
      url => !url.includes('/login') && !url.includes('/checkpoint/lg'),
      { timeout: 20000 }
    );
  } catch (_) { /* 2FA or checkpoint — user handles in headed mode */ }

  await page.waitForTimeout(2000);

  if (page.url().includes('/login') || page.url().includes('/checkpoint')) {
    throw new Error(
      'Login failed or 2FA required.\n' +
      '  → Run: npm run connect:headed  and complete 2FA, then re-run.'
    );
  }
  console.log('✅ Logged in\n');
}

// ── Connect flow ──────────────────────────────────────────────────────────────

/**
 * Navigates to a LinkedIn profile and sends a connection request.
 * Returns: 'sent' | 'noted' | 'already_connected' | 'no_button' | 'error'
 *
 * 'sent'              — request sent (no note option was shown)
 * 'noted'             — request sent WITH personalised note
 * 'already_connected' — already connected / pending / Follow-only
 * 'no_button'         — Connect button not found on page
 * 'error'             — unexpected error
 */
async function sendConnectionRequest(page, profileUrl, note, dryRun, delayMs) {
  try {
    await page.goto(profileUrl, { waitUntil: 'domcontentloaded', timeout: 25000 });
    await page.waitForTimeout(3000);

    // Auth wall check
    const currentUrl = page.url();
    if (currentUrl.includes('/login') || currentUrl.includes('/authwall')) {
      return 'auth_wall';
    }

    // ── Find the Connect button ──
    // LinkedIn renders it in different places depending on profile layout
    const connectSelectors = [
      'button[aria-label*="Connect"]',
      'button:has-text("Connect")',
    ];

    let connectBtn = null;
    for (const sel of connectSelectors) {
      connectBtn = page.locator(sel).first();
      if (await connectBtn.count() > 0) break;
      connectBtn = null;
    }

    // Sometimes "Connect" is hidden inside a "More" overflow menu
    if (!connectBtn || await connectBtn.count() === 0) {
      const moreBtn = page.locator('button[aria-label="More actions"]').first();
      if (await moreBtn.count() > 0) {
        await moreBtn.click();
        await page.waitForTimeout(800);
        connectBtn = page.locator('[role="menuitem"]:has-text("Connect")').first();
      }
    }

    if (!connectBtn || await connectBtn.count() === 0) {
      // Check if already connected
      const alreadyConnected =
        await page.locator('button[aria-label*="Message"]').count() > 0 ||
        await page.locator('button[aria-label*="Following"]').count() > 0 ||
        await page.locator('span:has-text("1st")').count() > 0;

      if (alreadyConnected) return 'already_connected';
      return 'no_button';
    }

    if (dryRun) {
      await page.waitForTimeout(delayMs);
      return 'dry_run';
    }

    // ── Click Connect ──
    await connectBtn.click();
    await page.waitForTimeout(1500);

    // ── Handle the modal ──
    // Modal may ask HOW you know them — pick "Other" if shown
    const howModal = page.locator('[data-test-modal] button:has-text("Other")').first();
    if (await howModal.count() > 0) {
      await howModal.click();
      await page.waitForTimeout(800);
    }

    // ── Add a note ──
    const addNoteBtn = page.locator('button[aria-label="Add a note"]').first();
    let sentWithNote = false;

    if (await addNoteBtn.count() > 0) {
      await addNoteBtn.click();
      await page.waitForTimeout(800);

      const textarea = page.locator('textarea[name="message"]').first();
      if (await textarea.count() > 0) {
        await textarea.fill(note);
        sentWithNote = true;
      }
    }

    // ── Send ──
    const sendBtn = page.locator(
      'button[aria-label="Send now"], button[aria-label="Done"], button:has-text("Send")'
    ).first();

    if (await sendBtn.count() > 0) {
      await sendBtn.click();
      await page.waitForTimeout(1000);
    }

    await page.waitForTimeout(delayMs);
    return sentWithNote ? 'noted' : 'sent';

  } catch (err) {
    return `error:${err.message.slice(0, 80)}`;
  }
}

// ── Main ──────────────────────────────────────────────────────────────────────

async function main() {
  const args    = process.argv.slice(2);
  const dryRun  = args.includes('--dry-run');
  const headed  = args.includes('--headed');

  const limitIdx = args.indexOf('--limit');
  const limit    = limitIdx !== -1 ? parseInt(args[limitIdx + 1], 10) : 20;

  // ── Load config ──
  if (!existsSync(CONFIG_PATH)) {
    console.error('Error: linkedin-config.yml not found.');
    process.exit(1);
  }

  const config   = yaml.load(readFileSync(CONFIG_PATH, 'utf-8'));
  const email    = config.credentials?.email    || '';
  const password = config.credentials?.password || '';
  const delayMs  = ((config.post_search?.page_delay_sec ?? 5) + 2) * 1000; // a bit slower than scraping

  if (!email || !password) {
    console.error('Error: credentials.email / credentials.password not set in linkedin-config.yml');
    process.exit(1);
  }

  // ── Open DB & load pending posts ──
  const db      = openDb();
  const pending = loadPendingPosts(db, limit);

  console.log('\n🤝 LinkedIn Auto-Connect — IITIIMJobAssistant');
  console.log('─'.repeat(50));
  console.log(`Pending posters:   ${pending.length}`);
  console.log(`Limit per run:     ${limit}`);
  console.log(`Delay between:     ${delayMs / 1000}s`);
  console.log(`Database:          ${DB_PATH}`);
  console.log(`Mode:              ${dryRun ? '🔍 DRY RUN (no requests sent)' : '🚀 LIVE'}`);
  if (headed) console.log('Browser:           HEADED (visible)');
  console.log();

  if (pending.length === 0) {
    console.log('✅ No pending posters — all done or no poster_url found in DB.');
    db.close();
    return;
  }

  // ── Launch browser ──
  const browser = await chromium.launch({
    headless: !headed,
    args: ['--no-sandbox', '--disable-setuid-sandbox', '--disable-blink-features=AutomationControlled'],
  });

  const context = await browser.newContext({
    userAgent:
      'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 ' +
      '(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
    viewport: { width: 1366, height: 768 },
    locale:   'en-US',
  });

  const page = await context.newPage();

  try {
    await restoreOrLogin(context, page, email, password);
  } catch (err) {
    console.error(`\n❌ ${err.message}`);
    await browser.close();
    db.close();
    process.exit(1);
  }

  // ── Process each poster ──
  const stats = { sent: 0, noted: 0, skipped: 0, errors: 0, dryRun: 0 };

  for (let i = 0; i < pending.length; i++) {
    const post      = pending[i];
    const note      = buildNote(post.poster_name, post.title, post.company);
    const shortName = (post.poster_name || 'Unknown').slice(0, 30);

    process.stdout.write(
      `  [${i + 1}/${pending.length}] ${shortName.padEnd(30)} → `
    );

    const result = await sendConnectionRequest(page, post.poster_url, note, dryRun, delayMs);

    switch (true) {
      case result === 'noted':
        console.log('✅ Connected + note sent');
        markConnected(db, post.id, 'noted');
        stats.noted++;
        break;
      case result === 'sent':
        console.log('✅ Connected (no note option)');
        markConnected(db, post.id, 'sent');
        stats.sent++;
        break;
      case result === 'already_connected':
        console.log('⏭  Already connected / follow-only');
        markConnected(db, post.id, 'already_connected');
        stats.skipped++;
        break;
      case result === 'no_button':
        console.log('⚠️  Connect button not found');
        markConnected(db, post.id, 'no_button');
        stats.skipped++;
        break;
      case result === 'dry_run':
        console.log(`🔍 [dry] Note: "${note.slice(0, 60)}..."`);
        stats.dryRun++;
        break;
      case result === 'auth_wall':
        console.log('⛔ Auth wall — session expired');
        console.log('\n  → Run: npm run connect:headed  to re-authenticate');
        await browser.close();
        db.close();
        process.exit(1);
        break;
      default:
        console.log(`❌ ${result}`);
        stats.errors++;
        break;
    }
  }

  await browser.close();
  db.close();

  // ── Summary ──
  console.log('\n' + '━'.repeat(50));
  console.log('Auto-Connect Summary');
  console.log('━'.repeat(50));
  if (dryRun) {
    console.log(`Previewed:         ${stats.dryRun} (no requests sent)`);
  } else {
    console.log(`Connected + note:  ${stats.noted}`);
    console.log(`Connected (basic): ${stats.sent}`);
    console.log(`Skipped:           ${stats.skipped}  (already connected or no button)`);
    console.log(`Errors:            ${stats.errors}`);
    console.log(`Total processed:   ${pending.length}`);
  }
  console.log();
  if (!dryRun && (stats.noted + stats.sent) > 0) {
    console.log(`✅ Connection requests sent. Re-run anytime — already-processed rows are skipped.`);
  }
}

main().catch(err => {
  console.error('Fatal:', err.message);
  process.exit(1);
});
