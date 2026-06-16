# User Acceptance Testing (UAT) Documentation

This document maps the project milestones of the **IITIIM Job Assistant** platform to their respective codebase implementations, database schemas, and verification procedures. Use this guide to audit, test, and verify deliverables for Milestones 1, 2, and 4.

---

*** milestone 1 ***

## Milestone 1: User Registration & Google OAuth

### 1. Description & Goal
Provide secure onboarding and authentication for site visitors. Users can register with credentials or sign up via Google OAuth. To maintain exclusivity, all new accounts are registered in a `pending` state and require manual review by an administrator before they can access platform features.

### 2. Codebase Mapping
*   **OAuth Callback Route (`app.py`):**
    *   `@app.route("/auth/google/callback")` (app.py: L75-170): Implements Google's OAuth2 flow. It exchanges the authorization code for an access token, calls Google's userinfo API (`https://www.googleapis.com/oauth2/v2/userinfo`) to retrieve the user's profile details (name, email, avatar), and redirects back to the frontend with query parameters (`oauth_ok=1&name=...&email=...`) to pre-fill the registration form.
*   **Standard Registration Route (`app.py`):**
    *   `@app.route("/api/signup", methods=["POST"])` (app.py: L174-212): Accepts registration details (`name`, `last_name`, `email`, `password`, `linkedin_url`, `mobile_number`). It validates that the LinkedIn URL is a valid LinkedIn profile and passes the request to the database layer.
*   **Database Operations & Hashing (`database.py`):**
    *   `save_user()`: Inserts standard and OAuth registrations into the `users` table. The password is dynamically hashed using SHA-256 with a salt before storage. It initializes `status = 'pending'` and sets the `submitted_at` timestamp.
    *   `validate_linkedin_url()`: Validates user-submitted LinkedIn URLs using regular expressions to ensure they point to legitimate profiles.
*   **Frontend Integration:**
    *   `IITIIMJobAssistant_v3.html` & `config.js`: Google client-side OAuth button triggers authorization redirect. URL-parameter parsing logic extracts Google profile data to populate the signup fields automatically.

### 3. Database Schema (`users.db`)
```sql
CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    name          TEXT    NOT NULL,
    last_name     TEXT    NOT NULL,
    email         TEXT    NOT NULL UNIQUE,
    password_hash TEXT    NOT NULL, -- SHA-256 hashed password
    linkedin_url  TEXT    DEFAULT '',
    mobile_number TEXT    DEFAULT '',
    avatar        TEXT    DEFAULT '',
    status        TEXT    DEFAULT 'pending', -- pending | approved | rejected
    reject_reason TEXT    DEFAULT '',
    submitted_at  TEXT    NOT NULL
);
```

### 4. Verification & Testing Procedure
1.  **Google OAuth Sign Up:**
    *   Navigate to the registration portal. Click **Sign up with Google**.
    *   Complete the Google authorization window.
    *   Verify that you are redirected back to the sign up form with your name and email pre-filled.
2.  **Standard Registration Validation:**
    *   Attempt to register with an invalid LinkedIn URL (e.g., `google.com`). Verify that the API rejects it with a `400 Bad Request`.
    *   Submit a valid registration. Verify a `201 Created` response.
    *   Inspect `users.db` and verify the password is not stored in plaintext (is a 64-character SHA-256 hex digest) and `status` is `'pending'`.

---

***milestone 2***

## Milestone 2: LinkedIn Automation & ATS Memory System

***milestone 2.1***

### Milestone 2.1: LinkedIn Scrapers, Connection Manager & DM Outreach Agent

#### 1. Description & Goal
Automate job discovery and outreach on LinkedIn. The system discovers job posts from LinkedIn's public job board and feed posts, automatically sends connection requests with personalized invitations to job posters, and follows up with AI-personalized direct messages once connection requests are accepted.

#### 2. Codebase Mapping
*   **Role-Based Job Scraper (`linkedin-scan.mjs`):**
    *   Uses Playwright to scan the public LinkedIn jobs board by role/keyword.
    *   Deduplicates job postings by saving canonical URLs to SQLite `jobs.db`.
    *   Executes fully headlessly without requiring a logged-in LinkedIn session, saving API credits.
*   **Feed Post Scraper (`linkedin-posts.mjs`):**
    *   Authenticates on LinkedIn using cookies cached in `linkedin-cookies.json`.
    *   Scrapes LinkedIn feed posts containing job announcements.
    *   Extracts structural details (job title, company, location, poster details, and apply links).
    *   **Url Resolver:** Resolves shortened redirect URLs (e.g., `lnkd.in`, `bit.ly`) to their final destination targets using HTTP request headers, and cleans tracking variables (`utm_*`, etc.).
    *   **Text Processing:** Normalizes job titles by removing emojis and filtering out common recruiter filler words (like "hiring", "looking for", "join our team").
*   **Connection Manager (`linkedin-connect.mjs`):**
    *   Reads new posts from `jobs.db` where `poster_url` is present but `connected_at` is null.
    *   Visits the profile pages of the job posters via Playwright.
    *   Builds a dynamic connection note of under 200 characters containing the poster's first name, role title, and company.
    *   Finds and clicks the "Connect" button (including checking the "More actions" overflow menu).
    *   Selects "Other" on the relational prompt, enters the message note, submits the invitation, and records the timestamp in `connected_at`.
*   **DM Follow-Up Agent (`linkedin_followup.py`):**
    *   Queries `jobs.db` for profiles where connection invitations were sent (`connected_at` is populated) but no follow-up has been attempted (`followup_sent_at` is null).
    *   Visits the profiles of those job posters via Playwright.
    *   Checks if the "Message" button is visible (confirming they accepted the connection request).
    *   **AI Message Generation:** Initializes the Anthropic Claude API client. Sends a prompt containing the recruiter's name, company, job title, and a snippet of the original post, as well as candidate information (name, college, title). Claude generates a highly contextual, personalized, plain-text DM (< 300 characters, no emojis or hashtags). If the API key is not configured, it falls back to a high-quality local template.
    *   Clicks the message compose window, fills the AI-generated message, clicks send, and updates the database record.

#### 3. Database Schema (`jobs.db` - `posts` & `jobs` tables)
```sql
CREATE TABLE IF NOT EXISTS jobs (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    title      TEXT NOT NULL,
    company    TEXT NOT NULL DEFAULT '',
    location   TEXT NOT NULL DEFAULT '',
    url        TEXT UNIQUE NOT NULL,
    apply_link TEXT NOT NULL DEFAULT '',
    source     TEXT NOT NULL DEFAULT 'linkedin',
    keywords   TEXT NOT NULL DEFAULT '',
    scraped_at TEXT NOT NULL,
    status     TEXT NOT NULL DEFAULT 'new'
);

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
    apply_url        TEXT    NOT NULL DEFAULT '',
    connected_at     TEXT    DEFAULT NULL,
    followup_sent_at TEXT    DEFAULT NULL,
    followup_status  TEXT    DEFAULT NULL,
    followup_msg     TEXT    DEFAULT NULL
);
```

#### 4. Verification & Testing Procedure
1.  **Job Scraper:**
    *   Run: `npm run linkedin -- --dry-run` to preview jobs without saving.
    *   Run: `npm run linkedin -- --role "Software Engineer"` to execute database writes. Verify additions in `jobs` table.
2.  **Feed Post Scraper:**
    *   Run: `npm run posts -- --headed` on the first execution. Complete any LinkedIn 2FA challenge. Verify cookies save to `linkedin-cookies.json`.
    *   Inspect `posts` table to verify resolved redirect URLs, stripped tracking parameters, and cleaned titles.
3.  **Connection Manager:**
    *   Run: `npm run connect -- --dry-run` to inspect generated templates under 200 characters.
    *   Run: `npm run connect -- --limit 2` to send requests. Confirm page interactions in browser and verify the `connected_at` column is updated.
4.  **DM Follow-Up Agent:**
    *   Run: `python linkedin_followup.py --dry-run` to verify API connection and view AI-generated message templates.
    *   Run: `python linkedin_followup.py --headed` to verify automated modal navigation, message injection, and database updates.

***milestone 2.2***

### Milestone 2.2: Job Application Orchestrator & Self-Learning Portal Memory System

#### 1. Description & Goal
Automate job application form filling and submission. The agent detects the ATS portal type, fills form fields based on the candidate's profile, uploads the resume, and clicks submit. 
To prevent expensive LLM operations and save API credits, the system implements a **Portal Memory System**. The first time the agent applies to a portal (Lever, Workday, Custom, etc.), it records the interactive form fields, CSS selectors, and page flow in a structured markdown file (`apply_history/<hostname>.md`). On subsequent applications to that portal, the file is loaded and injected as context, permitting the agent to apply deterministically.

#### 2. Codebase Mapping
*   **Apply Orchestrator (`apply_orchestrator.py`):**
    *   Selects jobs to apply to. It checks if the candidate is registered in the database as an active paid buyer (`database.is_buyer_active()`).
    *   Extracts the hostname from the job's application link.
    *   Calls `portal_memory.get_portal_memory()` to find if a cached markdown history file exists.
    *   Uses `ats_detector.detect_from_url()` to determine the portal type (Lever, Greenhouse, Workday, Ashby, SmartRecruiters, Google Forms, or Custom).
    *   Retrieves the corresponding adapter, injects the loaded portal memory, fills in form fields, uploads the resume, submits, and records success logs or redirects failures to the failure queue.
    *   If no memory file existed, it writes the successfully recorded steps to a new markdown file.
*   **ATS Detector (`ats_detector.py`):**
    *   Uses regular expressions to classify application links by portal pattern (e.g., `jobs.lever.co` to `lever`, `*myworkdayjobs.com` to `workday`, Google Forms URLs to `google_forms`).
*   **Portal Memory Manager (`portal_memory.py`):**
    *   Implements normalisation of hostnames (`jobs.eu.lever.co` → `lever.co`).
    *   Reads and writes markdown files in `apply_history/` following the standardized schema (Overview, Flow, Quirks, Human Input, Changelog, and Applied Jobs).
*   **ATS Adapters (`adapters/`):**
    *   `lever_adapter.py`, `greenhouse_adapter.py`, `ashby_adapter.py`, `smartrecruiters_adapter.py`, `workday_adapter.py`: Deterministic adapters. If a markdown memory file is passed, they extract the selector maps and complete form fields immediately. If not, they explore the fields, fill them, and return `recorded_steps` in the final `ApplyResult`.
    *   `google_forms_adapter.py`: Integrates Google Forms. Rather than exact selectors, it reads fields dynamically, matching labels to the candidate's profile.
    *   `custom_adapter.py`: General fallback adapter using a browser agent. It reads the `<hostname>.md` file and injects the text directly into the agent's prompt context, allowing the model to follow the recorded flow instead of using multiple LLM calls to re-explore the site.
*   **Agent Core (`agent.py`):**
    *   Initializes the browser-use Agent framework for automated form filling.

#### 3. Database Schema (`jobs.db` - `applications` & `failure_queue` tables)
```sql
CREATE TABLE IF NOT EXISTS applications (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    buyer_id        INTEGER NOT NULL,
    post_id         INTEGER,
    job_id          INTEGER,
    portal_hostname TEXT    NOT NULL DEFAULT '',
    ats_type        TEXT    NOT NULL DEFAULT '',
    status          TEXT    NOT NULL DEFAULT 'pending', -- applied | failed | paused
    confirmation_id TEXT    DEFAULT '',
    resume_used     TEXT    DEFAULT '',
    cover_letter    TEXT    DEFAULT '',
    applied_at      TEXT,
    notes           TEXT    DEFAULT '',
    created_at      TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS failure_queue (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    application_id  INTEGER NOT NULL,
    apply_url       TEXT    NOT NULL,
    failure_reason  TEXT    NOT NULL,
    failure_type    TEXT    NOT NULL,
    buyer_id        INTEGER NOT NULL,
    post_title      TEXT    DEFAULT '',
    company         TEXT    DEFAULT '',
    resolved        INTEGER DEFAULT 0,
    resolved_at     TEXT,
    created_at      TEXT    NOT NULL
);
```

#### 4. Verification & Testing Procedure
1.  **Unit & Integration Tests:**
    *   Run: `pytest test_portal_memory.py` to verify hostname normalisation, markdown generation, changelog updates, and files parsing.
    *   Run: `python test_memory_integration.py` to verify orchestration integration.
2.  **Dry Run Orchestrator:**
    *   Run: `python apply_orchestrator.py --dry-run` to verify orchestrator database lookups, paid buyer checks, and ATS detection flows.
3.  **Application Learning & Retrieval Loop:**
    *   Select a post ID with a Lever application URL. Verify `apply_history/lever.co.md` is present.
    *   Run: `python apply_orchestrator.py --id <post_id> --headed`. Verify in Playwright that the adapter extracts selectors from the markdown file and directly fills the fields without using exploratory loops.
    *   Delete `apply_history/lever.co.md`. Run the command again. Verify the adapter explore the form, writes the selectors to `recorded_steps`, submits the form, and generates a fresh `lever.co.md` file.

---

***milestone 4***

## Milestone 4: Admin Login & Approval Workflow

### 1. Description & Goal
Provide administrators with a console to review visitor registrations, view analytics, manage candidate subscription tiers, and audit administrative actions. Access boundaries are protected using Role-Based Access Control (RBAC).

### 2. Codebase Mapping
*   **Flask Authentication & RBAC (`app.py`):**
    *   `@app.route("/admin/login")` (app.py: L731-775): Authenticates admin accounts by comparing passwords using SHA-256. Generates a signed JWT token with a 24-hour expiration duration containing `admin_id`, `email`, and `role`.
    *   `admin_required` Decorator (app.py: L694-713): Middleware that intercepts admin API routes, checks for a valid Bearer JWT token in the `Authorization` header, decodes it with `ADMIN_JWT_SECRET`, and populates `request.admin` with database details.
    *   `require_role` Decorator (app.py: L716-726): Enforces granular permissions (e.g., restricting administrative updates to `SUPER_ADMIN` and `ADMIN` roles, and blocking read-only `USER` accounts).
*   **Admin Management API Routes (`app.py`):**
    *   `@app.route("/admin/verifications/<int:verif_id>/approve")` (app.py: L843-870): Approves a pending user registration and logs the action in the audit table.
    *   `@app.route("/admin/verifications/<int:verif_id>/reject")` (app.py: L873-906): Rejects a pending registration. Requires a rejection reason, updates the account state, and logs the action.
    *   `@app.route("/admin/dashboard")` (app.py: L797-805): Computes user counts, verified/pending/rejected metrics, active subscriptions, and conversion rates.
    *   `@app.route("/admin/audit-logs")` (app.py: L941-952): Exposes a paginated search and filter endpoint for administrative actions.
*   **Database Operations (`database.py`):**
    *   Contains the underlying queries for auditing, verification approvals/rejections, and analytics dashboard computations.
*   **Frontend Console Layout (`IITIIMJobAssistant_Admin_v3.html`):**
    *   Provides the administration page layout. Contains a login card view (`#view-login`) and the main workspace app shell (`#app-shell`) with navigation sub-views: Dashboard, Approval Queue, User Directory, and Audit Log. Uses Chart.js for rendering signup trend charts.
*   **Console Client Script (`admin.js`):**
    *   Handles sign-in, session storage (`sessionStorage` caching of JWT token), state routing between sub-views, paginated tables, search triggers, filtering, approval/rejection triggers, and toast notices.
*   **Console Design Stylesheet (`admin.css`):**
    *   Features a responsive layout utilizing variables, a modern font stack, side navigation menus, glassmorphic header panels, custom tables, grid elements, badging components, status dot elements, and animated transitions.

### 3. Database Schema (`users.db` - Admin & Audit tables)
```sql
CREATE TABLE IF NOT EXISTS admin_users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    email         TEXT    NOT NULL UNIQUE,
    password_hash TEXT    NOT NULL,
    role          TEXT    NOT NULL DEFAULT 'ADMIN', -- SUPER_ADMIN | ADMIN | USER
    name          TEXT    NOT NULL DEFAULT '',
    created_at    TEXT    NOT NULL,
    updated_at    TEXT    NOT NULL,
    last_login_at TEXT    DEFAULT ''
);

CREATE TABLE IF NOT EXISTS audit_logs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    admin_id        INTEGER NOT NULL,
    admin_email     TEXT    NOT NULL DEFAULT '',
    action          TEXT    NOT NULL, -- VERIFICATION_APPROVED | VERIFICATION_REJECTED | ADMIN_LOGIN
    target_user_id  INTEGER,
    previous_value  TEXT    DEFAULT '',
    new_value       TEXT    DEFAULT '',
    reason          TEXT    DEFAULT '',
    timestamp       TEXT    NOT NULL,
    ip_address      TEXT    DEFAULT ''
);
```

### 4. Verification & Testing Procedure
1.  **Admin Sign In:**
    *   Start the Flask application. Navigate to `http://localhost:5000/admin`.
    *   Attempt login with incorrect credentials. Verify the "Invalid email or password" error banner.
    *   Login with valid admin credentials. Verify you are redirected to the dashboard, and `admin_token` is saved in session storage.
2.  **Dashboard Analytics Validation:**
    *   Review the stat cards. Ensure the values match real registration statuses in `users.db`. Verify the registration line graph renders.
3.  **Approval Queue Verification:**
    *   Navigate to **Approval Queue**. Ensure pending users are listed with their LinkedIn URLs.
    *   Click **Approve** on a user. Confirm the prompt. Verify the card vanishes and the user's status in `users.db` updates to `approved`.
    *   Click **Reject** on a user. Verify the modal opens and requires a reason. Select a reason, add notes, and submit. Verify the card vanishes, status updates to `rejected`, and `reject_reason` is stored.
4.  **Audit Trail Audit:**
    *   Navigate to **Audit Log**.
    *   Verify there are logs matching your login, approval, and rejection actions, including the IP address and change details.
5.  **RBAC Check:**
    *   Attempt an admin action (e.g., approving a user) by sending a request to the API without the JWT token, or with an expired token. Verify the request is rejected with `401 Unauthorized`.
    *   Login as an account with `USER` role. Attempt to trigger approval via the console. Verify that the action fails and returns `403 Forbidden`.
