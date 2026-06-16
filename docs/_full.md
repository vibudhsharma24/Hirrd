# IITIIMJobAssistant — Multi-User AI Agent on EC2

## Goal
Transform the existing single-user local job automation toolkit into a multi-tenant SaaS deployed on AWS EC2, where each registered user provides their own LinkedIn account and the system applies to 5 jobs/day per user.

---

## Key Design Decisions

> [!IMPORTANT]
> **Language choice:** Your existing scrapers are in **Node.js (Playwright JS)**, but `linkedin-agent-system.md` proposes **Python (CrewAI + Playwright Python)**. I recommend **staying with Node.js** for the backend + workers since your 3 working scrapers are already in JS. Use Python only if you want CrewAI/Ollama integration for the LLM-driven form filling. A hybrid approach (Node.js API + Python agent workers) is also viable.

> [!IMPORTANT]
> **Session approach:** Use LinkedIn `li_at` session cookies instead of storing raw passwords. Users paste their cookie via a browser extension or manual export. This avoids storing passwords and eliminates login-from-EC2 issues entirely.

---

## Architecture Overview

```
┌────────────────────────────────────┐
│  FRONTEND (React / Next.js)        │
│  - User dashboard                  │
│  - Profile setup + resume upload   │
│  - LinkedIn cookie submission      │
│  - Job feed (per-user filtered)    │
│  - Real-time status (WebSocket)    │
└──────────────┬─────────────────────┘
               │
               ▼
┌────────────────────────────────────┐
│  API SERVER (Express.js on EC2)    │
│  - JWT auth (Google OAuth)         │
│  - REST: /users, /jobs, /apply     │
│  - WebSocket: live task status     │
│  - Enqueues tasks → BullMQ        │
└──────────────┬─────────────────────┘
               │
               ▼
┌────────────────────────────────────┐
│  QUEUE (Redis + BullMQ)            │
│  Queues: scan, apply, connect      │
│  { userId, taskType, params }      │
│  Scheduled: 5 jobs/user/day        │
└──────────────┬─────────────────────┘
               │
               ▼
┌────────────────────────────────────┐
│  WORKERS (Playwright headless)     │
│  - Agent 1: Job Scraper            │
│  - Agent 2: Application Bot        │
│  - Agent 3: Recruiter Messenger    │
│  - Self-learning portal memory     │
│  - Per-user cookies from DB        │
└──────────────┬─────────────────────┘
               │
               ▼
┌────────────────────────────────────┐
│  DATABASE (Amazon RDS PostgreSQL)  │
│  + S3 (resumes) + Redis (queue)    │
│  All tables scoped by user_id      │
│  Credentials AES-256 encrypted     │
└────────────────────────────────────┘
```

---

## Database Schema (RDS PostgreSQL)

```sql
-- Core user table
users (
  id SERIAL PK,
  name TEXT NOT NULL,
  email TEXT UNIQUE NOT NULL,
  password_hash TEXT NOT NULL,
  avatar TEXT,
  status TEXT DEFAULT 'pending',  -- pending | approved | rejected
  created_at TIMESTAMPTZ DEFAULT NOW()
);

-- User's job search preferences (replaces linkedin-config.yml per-user)
user_profiles (
  id SERIAL PK,
  user_id INT FK → users.id UNIQUE,
  full_name TEXT, phone TEXT, city TEXT,
  linkedin_url TEXT, github_url TEXT, portfolio_url TEXT,
  current_title TEXT, years_experience INT,
  notice_period TEXT, current_ctc TEXT, expected_ctc TEXT,
  work_preference TEXT,  -- Remote | Hybrid | On-site
  cover_letter_default TEXT,
  resume_s3_key TEXT,    -- S3 path to uploaded resume PDF
  search_keywords JSONB, -- ["backend developer india", "#hiring python"]
  negative_keywords JSONB, -- ["Intern", "Fresher", ".NET"]
  daily_apply_limit INT DEFAULT 5,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Encrypted LinkedIn session (NOT password — just li_at cookie)
user_sessions (
  id SERIAL PK,
  user_id INT FK → users.id UNIQUE,
  li_at_encrypted BYTEA NOT NULL,  -- AES-256 encrypted cookie
  expires_at TIMESTAMPTZ,
  last_verified_at TIMESTAMPTZ,
  status TEXT DEFAULT 'active'  -- active | expired | revoked
);

-- Scraped jobs (shared pool from public job board — no login needed)
jobs (
  id SERIAL PK,
  title TEXT NOT NULL,
  company TEXT DEFAULT '',
  location TEXT DEFAULT '',
  url TEXT UNIQUE NOT NULL,
  source TEXT DEFAULT 'linkedin',
  keywords TEXT DEFAULT '',
  scraped_at TIMESTAMPTZ NOT NULL,
  status TEXT DEFAULT 'new'
);

-- Scraped posts (per-user — requires their LinkedIn session)
posts (
  id SERIAL PK,
  user_id INT FK → users.id,
  title TEXT DEFAULT '',
  company TEXT DEFAULT '',
  location TEXT DEFAULT '',
  apply_link TEXT DEFAULT '',
  poster_name TEXT DEFAULT '',
  poster_url TEXT DEFAULT '',
  post_text TEXT DEFAULT '',
  keywords TEXT DEFAULT '',
  scraped_at TIMESTAMPTZ NOT NULL,
  status TEXT DEFAULT 'new',  -- new | reviewed | applied | dismissed
  post_urn TEXT,
  UNIQUE(user_id, post_urn)
);

-- Application tracking (per-user)
applications (
  id SERIAL PK,
  user_id INT FK → users.id,
  post_id INT FK → posts.id NULL,
  job_id INT FK → jobs.id NULL,
  portal_hostname TEXT NOT NULL,
  status TEXT NOT NULL,  -- applied | failed | paused | dismissed
  applied_at TIMESTAMPTZ,
  notes TEXT DEFAULT '',
  UNIQUE(user_id, post_id)
);

-- Portal knowledge base (SHARED across all users — the self-learning memory)
portal_profiles (
  id SERIAL PK,
  hostname TEXT UNIQUE NOT NULL,  -- lever.co, greenhouse.io, etc.
  portal_type TEXT,  -- ATS | Google Form | Company Careers | Custom
  login_required BOOLEAN DEFAULT FALSE,
  resume_upload TEXT,  -- PDF | PDF+DOCX | None
  cover_letter TEXT,  -- mandatory | optional | none
  steps_json JSONB NOT NULL,  -- ordered list of {action, selector, field_name}
  known_quirks TEXT DEFAULT '',
  success_count INT DEFAULT 0,
  last_used_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Connection request tracking (per-user)
connections (
  id SERIAL PK,
  user_id INT FK → users.id,
  post_id INT FK → posts.id,
  poster_url TEXT NOT NULL,
  note_sent TEXT,
  result TEXT,  -- sent | noted | already_connected | failed
  connected_at TIMESTAMPTZ,
  UNIQUE(user_id, poster_url)
);

-- Task queue audit log
task_logs (
  id SERIAL PK,
  user_id INT FK → users.id,
  task_type TEXT NOT NULL,  -- scan | apply | connect
  status TEXT NOT NULL,  -- queued | running | completed | failed
  started_at TIMESTAMPTZ,
  completed_at TIMESTAMPTZ,
  result_summary JSONB,
  error_message TEXT
);
```

---

## Phased Execution Plan

### Phase 1: Foundation — Database + API + Auth (Week 1–2)

**Goal:** Replace SQLite with RDS PostgreSQL, build proper auth, and set up the EC2 environment.

#### Tasks:
- [ ] Provision AWS resources: EC2 (`t3.medium`), RDS PostgreSQL (`db.t3.micro`), ElastiCache Redis (`cache.t3.micro`), S3 bucket for resumes
- [ ] Create the PostgreSQL schema (tables above)
- [ ] Rewrite `database.py` → `db.js` (or keep Python — your choice) using `pg` (node-postgres) or `psycopg2`
- [ ] Add `user_id` scoping to ALL data queries
- [ ] Implement JWT-based auth (register, login, Google OAuth)
- [ ] Build resume upload endpoint → S3
- [ ] Build user profile CRUD endpoints (replaces the YAML config)
- [ ] Build LinkedIn cookie submission + AES-256 encryption/storage endpoint
- [ ] Dockerize the API server

#### Files:
```
server/
  ├── index.js              (Express entry point)
  ├── routes/
  │   ├── auth.js           (register, login, Google OAuth)
  │   ├── profile.js        (user profile CRUD)
  │   ├── jobs.js            (job feed endpoints)
  │   ├── posts.js           (post feed endpoints)
  │   ├── apply.js           (trigger apply tasks)
  │   └── sessions.js        (LinkedIn cookie management)
  ├── middleware/
  │   ├── auth.js            (JWT verification)
  │   └── encrypt.js         (AES-256 helpers)
  ├── db/
  │   ├── pool.js            (pg connection pool)
  │   ├── schema.sql         (migration file)
  │   └── queries.js         (parameterized queries)
  └── Dockerfile
```

---

### Phase 2: Queue System + Worker Refactor (Week 3–4)

**Goal:** Wrap existing scrapers in BullMQ workers that process tasks per-user.

#### Tasks:
- [ ] Install Redis + BullMQ
- [ ] Create 3 queues: `scan-queue`, `apply-queue`, `connect-queue`
- [ ] Refactor `linkedin-posts.mjs` → `workers/scan-worker.js`
  - Accept `{ userId, cookies, keywords, maxPages }` as job payload
  - Write results to PostgreSQL with `user_id` scope
  - Emit progress events via Redis pub/sub
- [ ] Refactor `linkedin-connect.mjs` → `workers/connect-worker.js`
  - Accept `{ userId, cookies, postIds, limit }` as job payload
  - Use per-user cookies instead of config file
- [ ] Build scheduler: cron job that enqueues 5 apply tasks per user per day at random times (spread across 9am–6pm IST)
- [ ] Add WebSocket server to API for real-time status updates
- [ ] Add BullMQ dashboard (Bull Board) at `/admin/queues` for monitoring

#### Files:
```
workers/
  ├── scan-worker.js         (refactored linkedin-posts.mjs)
  ├── apply-worker.js        (new — the actual agent, Phase 3)
  ├── connect-worker.js      (refactored linkedin-connect.mjs)
  ├── scheduler.js           (cron: enqueue daily tasks per user)
  └── shared/
      ├── browser.js         (Playwright launcher with stealth + proxy)
      ├── cookie-loader.js   (decrypt user cookies from DB)
      └── status-emitter.js  (Redis pub/sub → WebSocket)
```

#### Key refactoring pattern:
```javascript
// BEFORE (linkedin-posts.mjs) — reads from local config
const config = yaml.load(readFileSync(CONFIG_PATH, 'utf-8'));
const email  = config.credentials.email;

// AFTER (workers/scan-worker.js) — receives per-user data from queue
scanQueue.process(async (job) => {
  const { userId, cookies, keywords, maxPages } = job.data;
  const context = await browser.newContext();
  await context.addCookies(cookies);  // per-user cookies
  // ... rest of scraping logic stays the same
  await db.query('INSERT INTO posts (user_id, ...) VALUES ($1, ...)', [userId, ...]);
});
```

---

### Phase 3: Application Agent — The Core Product (Week 5–8)

**Goal:** Build `apply-worker.js` — the actual job application bot described in `jobagent.md`.

This is the hardest phase. The agent must:
1. Visit an `apply_link`
2. Figure out the portal (Lever? Greenhouse? Custom?)
3. Fill the form with user profile data
4. Upload resume from S3
5. Submit and verify success
6. Record what it learned in `portal_profiles` table

#### Tasks:
- [ ] Build portal detection module (extract hostname → look up `portal_profiles` table)
- [ ] Build form-filler engine:
  - For **known portals** (Lever, Greenhouse, etc.): follow stored `steps_json` mechanically
  - For **unknown portals**: use LLM (Ollama or Groq free tier) to analyze the DOM and decide what to fill — then save the steps
- [ ] Implement the decision rules from `jobagent.md` §5:
  - Auto-apply: known portal + matching title + apply_link reachable
  - Auto-dismiss: negative keywords, 404, duplicate
  - Pause: CAPTCHA, OTP, video intro → notify user via WebSocket
- [ ] Build cover letter personalizer (template from `jobagent.md` §7)
- [ ] Implement Google Forms handler (generic, no portal profile needed)
- [ ] Build the self-learning loop:
  - On success at new portal → extract steps → INSERT into `portal_profiles`
  - On failure using existing profile → re-discover → UPDATE `portal_profiles`
- [ ] Download user's resume from S3 to temp file → upload to portal → cleanup
- [ ] Rate limiting: max 5 applications per user per day, random delays (3–8s between actions)

#### Portal handling priority:
```
1. LinkedIn Easy Apply     — most common, simplest flow
2. Lever (lever.co)        — standard ATS, no login
3. Greenhouse              — standard ATS, no login
4. Google Forms            — generic handler
5. Naukri Easy Apply       — Indian market, login required
6. Workday                 — complex, multi-page, skip initially
7. Unknown/custom portals  — LLM discovery mode
```

---

### Phase 4: Frontend Dashboard (Week 7–9, parallel with Phase 3)

**Goal:** Build a React dashboard replacing the monolithic HTML files.

#### Pages:
- [ ] **Login/Register** — Google OAuth + email/password
- [ ] **Onboarding** — Profile setup wizard (name, resume upload, LinkedIn cookie, search keywords)
- [ ] **Dashboard** — Stats overview: jobs found today, applications sent, connections made
- [ ] **Job Feed** — Filterable list of scraped posts/jobs with status badges
- [ ] **Application History** — Table of all applications with portal, status, timestamp
- [ ] **Settings** — Edit profile, update LinkedIn cookie, manage keywords
- [ ] **Live Status** — WebSocket-powered real-time view of running agent tasks

#### Tech:
```
frontend/
  ├── src/
  │   ├── pages/          (Login, Dashboard, Jobs, History, Settings)
  │   ├── components/     (JobCard, StatusBadge, ProfileForm, etc.)
  │   ├── hooks/          (useWebSocket, useAuth, useJobs)
  │   ├── api/            (axios client for backend)
  │   └── App.jsx
  ├── package.json
  └── vite.config.js
```

---

### Phase 5: Deployment + Security Hardening (Week 9–10)

#### Tasks:
- [ ] Dockerize everything: `docker-compose.yml` with API, workers, Redis
- [ ] Set up Nginx reverse proxy + SSL (Let's Encrypt)
- [ ] Configure residential proxy integration (Bright Data or IPRoyal)
- [ ] Add Playwright stealth plugin to all workers
- [ ] Implement cookie expiry checker (cron: verify each user's `li_at` weekly, notify if expired)
- [ ] Add rate limiting middleware (express-rate-limit)
- [ ] Set up CloudWatch logging / PM2 process management
- [ ] Set up daily DB backups (RDS automated snapshots)

#### EC2 setup:
```bash
# Docker Compose services
services:
  api:        Express.js API server (port 5000)
  worker:     BullMQ worker processes (scales horizontally)
  scheduler:  Cron-based task scheduler
  redis:      ElastiCache Redis (or local Redis in dev)
  nginx:      Reverse proxy + SSL termination
```

---

## Monthly Cost Estimate (~50 users)

| Service | Spec | $/month |
|---|---|---|
| EC2 (API + Workers) | `t3.medium` (2 vCPU, 4GB) | ~$30 |
| RDS PostgreSQL | `db.t3.micro` | ~$15 |
| ElastiCache Redis | `cache.t3.micro` | ~$12 |
| S3 (resumes) | <1 GB | ~$1 |
| Residential Proxies | ~5 GB | ~$50 |
| Domain + SSL | Let's Encrypt | $12/yr |
| **Total** | | **~$110/month** |

---

## Open Questions

> [!IMPORTANT]
> 1. **Node.js or Python for workers?** Your existing scrapers are Node.js. The `linkedin-agent-system.md` proposes Python + CrewAI + Ollama. Which direction do you want? A hybrid (Node API + Python workers) is possible but adds complexity.

> [!IMPORTANT]  
> 2. **LLM for unknown portals:** When the agent encounters a new/unknown job portal, it needs intelligence to navigate the DOM. Options:
>    - **Ollama locally on EC2** (free, but needs 8GB+ RAM on the instance — bumps EC2 to `t3.large`)
>    - **Groq free tier API** (free, cloud-based, Llama 3 70B — simpler but has rate limits)
>    - **Skip unknown portals initially** — only apply to known ATS (Lever, Greenhouse, Easy Apply) and add portals manually over time

> [!WARNING]
> 3. **Cookie collection UX:** How will users provide their LinkedIn `li_at` cookie? Options:
>    - Browser extension that auto-exports it (best UX, most work to build)
>    - Manual instructions ("Open DevTools → Application → Cookies → copy `li_at`")
>    - Store actual LinkedIn password + automate login from EC2 (highest risk)

---

## Recommended Build Order

```
Week 1–2:   Phase 1 (RDS + API + Auth)         ← foundation
Week 3–4:   Phase 2 (Queue + Worker refactor)   ← existing scrapers as workers
Week 5–8:   Phase 3 (Application Agent)         ← core product, hardest part
Week 7–9:   Phase 4 (Frontend)                  ← parallel with Phase 3
Week 9–10:  Phase 5 (Deploy + Harden)           ← ship it
```

Start with Phase 1. Once the database and API are live, everything else plugs in incrementally.
