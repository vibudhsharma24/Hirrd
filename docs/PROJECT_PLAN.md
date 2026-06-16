# IITIIMJobAssistant — Multi-Tenant Platform: Full Project Plan

---

## What You Have Right Now

| File | What it does |
|---|---|
| `linkedin-scan.mjs` | Scrapes LinkedIn **job board** by role/keyword → saves to `jobs` table in `jobs.db` |
| `linkedin-posts.mjs` | Scrapes LinkedIn **feed posts** (hiring posts) → saves to `posts` table in `jobs.db` |
| `linkedin-connect.mjs` | Reads `posts` table, visits each poster's profile, sends a connection request with a personalised note |
| `config.js` | Frontend config — Google OAuth, app URL |

**Current limitation:** All three scripts use a single `linkedin-config.yml` with one hardcoded email/password. There is no concept of multiple users, no web dashboard, no per-user job tracking, and no message-after-acceptance flow.

---

## What You Want to Build

A **multi-tenant SaaS platform** where:
- Each user registers/logs in via Google OAuth
- Each user connects their own LinkedIn account (credentials stored encrypted)
- The platform runs scraping + outreach **on behalf of each user individually**
- After a connection is accepted, a follow-up message is sent automatically
- Each user sees only their own dashboard: jobs found, connections sent, replies received

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────┐
│                     Frontend (React)                     │
│  Login → Dashboard → Jobs → Outreach → Settings         │
└────────────────────┬────────────────────────────────────┘
                     │ REST API
┌────────────────────▼────────────────────────────────────┐
│                  Backend (Flask / Python)                 │
│  Auth · User API · Jobs API · Outreach API · Job Queue   │
└──────┬──────────────────┬──────────────────┬────────────┘
       │                  │                  │
┌──────▼──────┐  ┌────────▼───────┐  ┌──────▼──────────┐
│  PostgreSQL  │  │  Redis + Celery │  │  Playwright     │
│  (users,     │  │  (task queue)   │  │  Workers        │
│   jobs,      │  │                 │  │  (1 browser     │
│   outreach)  │  │                 │  │   per user job) │
└─────────────┘  └────────────────┘  └─────────────────┘
```

---

## Database Schema (PostgreSQL)

### `users`
```sql
id              UUID PRIMARY KEY
email           TEXT UNIQUE NOT NULL        -- from Google OAuth
name            TEXT
google_id       TEXT UNIQUE
li_email_enc    BYTEA                       -- AES-256 encrypted
li_pass_enc     BYTEA                       -- AES-256 encrypted
li_cookies      JSONB                       -- cached session cookies
li_session_ok   BOOLEAN DEFAULT FALSE
created_at      TIMESTAMPTZ DEFAULT NOW()
plan            TEXT DEFAULT 'free'         -- free | pro
```

### `jobs`
```sql
id              UUID PRIMARY KEY
user_id         UUID REFERENCES users(id)
title           TEXT
company         TEXT
location        TEXT
url             TEXT
source          TEXT                        -- 'linkedin-board' | 'linkedin-posts'
keywords        TEXT
post_text       TEXT
poster_name     TEXT
poster_url      TEXT
post_urn        TEXT
scraped_at      TIMESTAMPTZ
status          TEXT DEFAULT 'new'          -- new | reviewed | applied | dismissed
```

### `outreach`
```sql
id              UUID PRIMARY KEY
user_id         UUID REFERENCES users(id)
job_id          UUID REFERENCES jobs(id)
poster_url      TEXT
poster_name     TEXT
connection_note TEXT
connection_sent_at   TIMESTAMPTZ
connection_status    TEXT DEFAULT 'pending'  -- pending | sent | accepted | failed
followup_msg         TEXT
followup_sent_at     TIMESTAMPTZ
followup_status      TEXT DEFAULT 'pending'  -- pending | sent | skipped | failed
```

### `scrape_runs`
```sql
id              UUID PRIMARY KEY
user_id         UUID REFERENCES users(id)
run_type        TEXT                        -- 'scan' | 'posts' | 'connect' | 'followup'
status          TEXT                        -- queued | running | done | error
started_at      TIMESTAMPTZ
finished_at     TIMESTAMPTZ
summary         JSONB                       -- { found: 12, sent: 5, errors: 1 }
```

---

## Backend Modules (Python / Flask)

### 1. Auth (`/auth`)
- `GET /auth/google` → redirect to Google OAuth
- `GET /auth/google/callback` → exchange code, create/update user, issue JWT
- `POST /auth/logout`

### 2. LinkedIn Credential Management (`/api/linkedin`)
- `POST /api/linkedin/credentials` — user submits their LI email + password
  - Encrypt with AES-256-GCM, store `li_email_enc` + `li_pass_enc`
  - Trigger a test-login job to verify and cache cookies
- `GET /api/linkedin/status` — returns `{ connected: true/false, session_ok: bool }`
- `DELETE /api/linkedin/credentials` — wipe stored credentials

### 3. Jobs API (`/api/jobs`)
- `GET /api/jobs` — paginated list of this user's scraped jobs
- `PATCH /api/jobs/:id` — update status (reviewed / applied / dismissed)
- `POST /api/jobs/scan` — queue a new scrape run for this user

### 4. Outreach API (`/api/outreach`)
- `GET /api/outreach` — list of connection requests + their statuses
- `POST /api/outreach/run` — queue a connect+followup run for this user
- `GET /api/outreach/stats` — `{ sent, accepted, followups_sent, ... }`

### 5. Task Queue (Celery + Redis)

Each task runs a Playwright browser session for one user:

| Task | What it does |
|---|---|
| `task_scan_jobs(user_id)` | Runs the equivalent of `linkedin-scan.mjs` for this user |
| `task_scrape_posts(user_id)` | Runs the equivalent of `linkedin-posts.mjs` for this user |
| `task_send_connections(user_id)` | Visits poster profiles, sends connection requests with notes |
| `task_send_followups(user_id)` | Checks accepted connections, sends follow-up message |
| `task_verify_session(user_id)` | Logs in, caches cookies, marks session ok/failed |

### 6. Credential Encryption

```python
# Using cryptography.fernet (AES-128-CBC + HMAC) or AES-256-GCM
# Master key stored in environment variable, NEVER in DB
MASTER_KEY = os.environ["CREDENTIAL_MASTER_KEY"]

def encrypt(plaintext: str) -> bytes: ...
def decrypt(ciphertext: bytes) -> str: ...
```

---

## Playwright Worker: Multi-User Pattern

Each user gets their **own isolated browser context** with their own cookies. Workers are stateless — they decrypt credentials, launch a context, do the work, save cookies back, and exit.

```python
async def run_for_user(user_id):
    user = db.get_user(user_id)
    email = decrypt(user.li_email_enc)
    password = decrypt(user.li_pass_enc)
    cookies = user.li_cookies  # cached from last login

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(user_agent=REALISTIC_UA)

        if cookies:
            await context.add_cookies(cookies)

        page = await context.new_page()
        # verify session or login fresh
        # ... do the work (scrape / connect / followup)
        # save cookies back to DB
        fresh_cookies = await context.cookies()
        db.update_cookies(user_id, fresh_cookies)

        await browser.close()
```

---

## Follow-up Message Flow

This is the piece you don't have yet. Here's how it works:

1. `task_send_connections` sends connection requests and records `connection_sent_at`
2. `task_send_followups` runs on a schedule (e.g. every 6 hours)
3. For each outreach row where `connection_status = 'sent'` and it's been >24h:
   - Visit the poster's profile
   - Check if a "Message" button is now visible (means they accepted)
   - If yes → update `connection_status = 'accepted'`, send the follow-up message
   - Mark `followup_sent_at` and `followup_status = 'sent'`

### AI-Personalised Follow-up (Claude API)
```python
def build_followup_message(user_profile, job_post):
    prompt = f"""
    Write a short, warm LinkedIn follow-up message (under 300 chars).
    The sender is: {user_profile.name}, {user_profile.role}, from {user_profile.college}
    They connected because of this job post: {job_post.title} at {job_post.company}
    The poster is: {job_post.poster_name}
    Make it personal, grateful, and professional. No fluff.
    """
    # Call Claude API here
```

---

## Frontend Dashboard (React)

### Pages
| Route | What the user sees |
|---|---|
| `/` | Landing page |
| `/dashboard` | Stats: jobs found, connections sent, accepted, followups sent |
| `/jobs` | Table of scraped jobs — filter by status, source, date |
| `/outreach` | Table of connection requests + statuses |
| `/settings` | Connect LinkedIn account, set keywords, set message templates |

### Key UI Components
- **LinkedIn Connect Widget** — user enters their LI email + password, we verify and show green checkmark
- **Keyword Editor** — add/remove job search keywords
- **Outreach Stats Card** — sent / accepted / reply rate
- **Run Controls** — "Scan Jobs Now", "Send Connections Now" buttons → triggers API → queues task

---

## Scheduling (Per User)

Instead of one global cron job, each user has their own schedule stored in DB:

```
user_id | task_type        | cron_expr      | last_run | next_run | enabled
--------|------------------|----------------|----------|----------|--------
user_1  | scan_jobs        | 0 9 * * *      | ...      | ...      | true
user_1  | send_connections | 0 10 * * *     | ...      | ...      | true
user_1  | send_followups   | 0 */6 * * *    | ...      | ...      | true
```

A scheduler (Celery Beat or APScheduler) reads this table and dispatches tasks accordingly.

---

## Rate Limiting & Safety (Per User)

| Limit | Value | Why |
|---|---|---|
| Connection requests | Max 20/day per user | LinkedIn's ~100/week cap |
| Scrape pages | Max 3 pages per run | Avoid detection |
| Delay between actions | 4–8s randomised | Human-like behaviour |
| Follow-up messages | Max 10/day per user | Avoid spam flags |
| Concurrent workers | Max 3 users at a time | Server resource limit |

---

## Tech Stack Summary

| Layer | Technology |
|---|---|
| Frontend | React + Tailwind CSS |
| Backend | Python + Flask |
| Database | PostgreSQL |
| Task Queue | Celery + Redis |
| Browser Automation | Playwright (Python) |
| Credential Encryption | Python `cryptography` (AES-256-GCM) |
| AI Messages | Claude API (claude-sonnet-4-6) |
| Auth | Google OAuth 2.0 + JWT |
| Deployment | Docker Compose (backend + worker + redis + postgres) |

---

## Build Order (What We Build First → Last)

### Phase 1 — Foundation
- [ ] PostgreSQL schema + migrations
- [ ] Flask app skeleton + Google OAuth
- [ ] JWT middleware
- [ ] User model + API

### Phase 2 — LinkedIn Credential Vault
- [ ] Encrypt/decrypt utilities
- [ ] `POST /api/linkedin/credentials` endpoint
- [ ] `task_verify_session` Playwright task
- [ ] Session cookie caching in DB

### Phase 3 — Per-User Scraping
- [ ] Port `linkedin-scan.mjs` → Python Playwright (`task_scan_jobs`)
- [ ] Port `linkedin-posts.mjs` → Python Playwright (`task_scrape_posts`)
- [ ] Jobs API endpoints
- [ ] Frontend: Jobs table

### Phase 4 — Per-User Outreach
- [ ] Port `linkedin-connect.mjs` → Python Playwright (`task_send_connections`)
- [ ] Outreach DB table + tracking
- [ ] Outreach API endpoints
- [ ] Frontend: Outreach table

### Phase 5 — Follow-up Messages
- [ ] `task_send_followups` — detect accepted connections, send message
- [ ] Claude API integration for personalised messages
- [ ] Frontend: Message template editor

### Phase 6 — Scheduling & Dashboard
- [ ] Per-user schedules table + Celery Beat
- [ ] Dashboard stats API
- [ ] Frontend: Dashboard + Run Controls

### Phase 7 — Production
- [ ] Docker Compose setup
- [ ] Rate limiting middleware
- [ ] Error alerting (email user if their session breaks)
- [ ] Admin panel (monitor all users' run statuses)

---

## What to Build First

Tell me which phase to start with and I'll write the actual code. My recommendation: **start with Phase 1 + 2** (database schema + credential vault) since everything else depends on it.
