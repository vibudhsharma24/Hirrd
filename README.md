<p align="center">
  <img src="docs/UAT_Docs/banner%20image.jfif" alt="IITIIM Job Assistant Banner" width="100%">
</p>

# 🤖 IITIIM Job Assistant

An AI-powered, multi-tenant SaaS platform that **fully automates** the job hunting pipeline — from discovering opportunities on LinkedIn, to auto-filling application portals, to sending personalized outreach messages — all while the candidate sleeps.

---

## 🌟 Features

### 🔍 Intelligent Job Discovery
- **LinkedIn Feed Scraper** — A Playwright-based Python scraper that logs into the candidate's LinkedIn, searches for posts matching their target roles & locations, and extracts job details, apply links, and poster profiles.
- **Linkup API Integration** — Secondary discovery channel using the Linkup search API for broader job-board coverage.
- **Deduplication** — Posts are deduplicated by LinkedIn URN and apply URL to avoid repeat entries.

### 🚀 Automated Job Applications
- **ATS Detection Engine** — Automatically identifies the Applicant Tracking System (Workday, Greenhouse, Lever, Ashby, SmartRecruiters, Google Forms) from the apply URL.
- **Per-ATS Form-Filling Adapters** — Each ATS has a dedicated adapter that knows how to navigate its multi-step form, fill personal info, upload resumes, and click submit.
- **AI Fallback (browser-use)** — For unknown portals, an LLM-powered agent (Claude via `browser-use`) interprets the page and fills forms autonomously.
- **Portal Memory System** — Learned portal navigation steps are cached in Markdown files so repeat applications skip the exploration phase, saving LLM credits.
- **Password Manager** — Auto-generates portal-specific passwords using the format `{Firstname}@123$` (padded with random digits if the portal requires a longer password). Stored per-company in the `agent_buyers` table.

### 📧 Gmail OTP Verification
- **IMAP-Based Code Extraction** — When a job portal sends a verification email, the agent polls the candidate's Gmail inbox via IMAP SSL, extracts the OTP code using regex patterns, and automatically fills it into the verification input field.

### 🤝 LinkedIn Outreach
- **Connection Requests** — For job posts that don't include an apply link, the agent visits the poster's LinkedIn profile and sends a personalized connection request with a custom note.
- **DM Follow-Up** — After connections are accepted, an AI-powered follow-up agent (powered by Claude) generates personalized DMs and sends them through LinkedIn's messaging modal.

### 📊 Candidate Dashboard
- **Live Application Tracking** — Real-time view of application statuses (applied, pending, failed), submission logs with timestamps, and screenshot evidence.
- **Agent Controls** — Start/stop/pause the background agent, configure job preferences (roles, locations, salary range), and view agent execution logs.
- **Password Manager UI** — View all auto-generated portal passwords in a disclosure modal.
- **Settings Panel** — Update profile info, connect LinkedIn & Gmail credentials, upload resumes, and configure notification preferences.

### 💳 Payment & Subscription
- **Razorpay Integration** — Native checkout flow with plan selection (monthly/quarterly), payment verification, and webhook-driven subscription activation.
- **Subscription Management** — Track expiration dates, renewal status, and payment history.

### 🛡️ Admin Panel
- **User Approval Pipeline** — Review, approve, or reject candidate signups with audit logging.
- **Verification System** — Document-based identity verification workflow.
- **Platform Metrics** — Dashboard with signup trends, application stats, and revenue tracking.
- **Audit Logs** — Complete trail of all admin actions with IP tracking.

### 🔒 Security
- **AES-256-GCM Encryption** — All sensitive credentials (LinkedIn passwords, Gmail app passwords) are encrypted at rest.
- **JWT Admin Authentication** — Separate auth system for the admin panel.
- **Flask-Login Sessions** — Cookie-based session management for candidates.
- **Google OAuth 2.0** — Social login support via Google.

---

## 🛠️ Tech Stack

| Layer | Technology |
|-------|-----------|
| **Frontend** | Vanilla HTML5, CSS3, Tailwind CSS, Google Fonts (Space Grotesk & Inter) |
| **Backend** | Python 3.10+, Flask, Flask-Login |
| **Database** | SQLite (`users.db` for auth/users, `jobs.db` for posts/applications/logs) |
| **Browser Automation** | Playwright (Python) with stealth mode |
| **Cloud Browser** | Hyperbrowser API (optional — stealth proxies + CAPTCHA solving) |
| **AI Engine** | Anthropic Claude API, browser-use (LLM-driven form filling) |
| **Encryption** | `cryptography` library (AES-256-GCM) |
| **Payments** | Razorpay Checkout API |
| **Email** | Gmail IMAP (OTP extraction) |

---

## 📂 Project Structure

```text
├── core/                                 # Flask app, database, auth
│   ├── app.py                            # Server & all API endpoints
│   ├── auth.py                           # AES-256-GCM encryption & JWT helpers
│   └── database.py                       # SQLite schema, migrations & queries
│
├── job_seeker_agent/                     # Core AI agent pipeline
│   ├── applier.py                        # Auto-apply orchestrator & full pipeline
│   ├── linkedin_posts_scraper.py         # Python LinkedIn feed scraper (Playwright)
│   ├── gmail_otp_retriever.py            # Gmail IMAP OTP code extraction
│   ├── connector.py                      # LinkedIn connection request sender
│   ├── linkedin_followup.py              # AI-powered LinkedIn DM follow-up
│   ├── runner.py                         # Background agent loop (per-user threads)
│   ├── scraper.py                        # Linkup API job discovery
│   ├── agent.py                          # Legacy agent orchestrator
│   ├── browser_manager.py                # Playwright / Hyperbrowser session factory
│   ├── ats_detector.py                   # ATS type detection (URL + DOM)
│   ├── resume_generator.py               # Resume selection & cover letter generation
│   ├── portal_memory.py                  # Cached portal navigation knowledge
│   ├── messenger.py                      # Messaging utilities
│   └── adapters/                         # Per-ATS form-filling adapters
│       ├── base_adapter.py               # Abstract adapter interface
│       ├── greenhouse_adapter.py          # Greenhouse ATS
│       ├── lever_adapter.py              # Lever ATS
│       ├── workday_adapter.py            # Workday ATS
│       ├── ashby_adapter.py              # Ashby ATS
│       ├── smartrecruiters_adapter.py    # SmartRecruiters ATS
│       ├── google_forms_adapter.py       # Google Forms
│       └── custom_adapter.py            # AI fallback (browser-use + Claude)
│
├── frontend/                             # UI templates served by Flask
│   ├── index.html                        # Landing page
│   ├── dashboard.html                    # Candidate dashboard & agent console
│   ├── pay.html                          # Razorpay checkout & plans
│   ├── login.html                        # Login page
│   ├── signup.html                       # Signup page
│   ├── admin.html                        # Admin panel
│   ├── admin.css / admin.js              # Admin panel styles & logic
│   └── config.js                         # Frontend configuration
│
├── extras/legacy/                        # Legacy Node.js scrapers (reference only)
│   ├── linkedin-posts.mjs                # Original Node.js LinkedIn scraper
│   └── linkedin-connect.mjs              # Original Node.js connection sender
│
├── docs/                                 # Architecture docs & UAT logs
├── resumes/                              # Uploaded & generated resumes
├── screenshots/                          # Application screenshots (evidence)
├── requirements.txt                      # Python dependencies
├── run.py                                # Flask server launcher
├── start_server.ps1                      # Windows PowerShell bootstrapper
├── deploy_ec2.ps1                        # AWS EC2 deployment script
└── .env.example                          # Environment variables template
```

---

## 🔄 Agent Pipeline

When the **"Run Agent"** button is clicked on the dashboard, the following pipeline executes:

```
┌─────────────────────────────────────────────────────────────┐
│  Step 1: SCRAPE LinkedIn Feed                               │
│  • Login with user's LinkedIn credentials                   │
│  • Search for posts matching target roles & locations       │
│  • Extract job details, apply links, poster profiles        │
│  • Save to jobs.db → posts table                            │
├─────────────────────────────────────────────────────────────┤
│  Step 2: AUTO-APPLY (posts with apply links)                │
│  • Detect ATS type (Workday, Greenhouse, Lever, etc.)       │
│  • Select the appropriate adapter                           │
│  • Fill form fields, upload resume, submit                  │
│  • If email verification needed → fetch OTP from Gmail      │
│  • Log screenshots & update application status              │
├─────────────────────────────────────────────────────────────┤
│  Step 3: CONNECTION REQUESTS (posts without apply links)    │
│  • Visit poster's LinkedIn profile                          │
│  • Send personalized connection request                     │
│  • Create "pending" application record                      │
│  • Update dashboard                                         │
└─────────────────────────────────────────────────────────────┘
```

---

## 🚀 Getting Started

### 1. Prerequisites
- **Python 3.10+** and **Git**
- A LinkedIn account with credentials
- (Optional) Gmail App Password for OTP verification
- (Optional) Anthropic API key for AI-powered form filling

### 2. Clone & Setup Virtual Environment
```bash
git clone https://github.com/vibudhsharma24/Hirrd.git
cd Hirrd

# Create virtual environment
python -m venv venv

# Activate
# Windows:
venv\Scripts\activate
# macOS/Linux:
source venv/bin/activate
```

### 3. Install Dependencies
```bash
pip install -r requirements.txt

# Install Playwright browser binaries
playwright install chromium
```

### 4. Configure Environment Variables
```bash
cp .env.example .env
```
Edit `.env` and set the following:

| Variable | Description |
|----------|-------------|
| `SECRET_KEY` | Flask session secret key |
| `ENCRYPTION_KEY` | AES-256 key for credential encryption |
| `ANTHROPIC_API_KEY` | Claude API key (for AI form filling & DMs) |
| `RAZORPAY_KEY_ID` | Razorpay test/live key ID |
| `RAZORPAY_KEY_SECRET` | Razorpay test/live key secret |
| `GOOGLE_CLIENT_ID` | Google OAuth client ID (optional) |
| `GOOGLE_CLIENT_SECRET` | Google OAuth client secret (optional) |
| `HYPERBROWSER_API_KEY` | Hyperbrowser cloud browser key (optional) |
| `LINKUP_API_KEY` | Linkup search API key (optional) |

### 5. Run the Application
```bash
python run.py
```
Or on Windows:
```powershell
.\start_server.ps1
```
The server starts at **`http://127.0.0.1:5000`**.

---

## 📡 API Endpoints

### Authentication
| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/signup` | Register a new user |
| POST | `/api/login` | Login with email/password |
| POST | `/api/logout` | Logout |
| GET | `/api/me` | Get current user profile |
| POST | `/api/set-password` | Set password (for Google OAuth users) |

### Agent
| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/apply` | Run the full pipeline (scrape → apply → connect) |
| POST | `/api/agent/start` | Start background agent loop |
| POST | `/api/agent/stop` | Stop background agent loop |
| GET | `/api/agent/status` | Get agent running status |
| GET | `/api/agent/preferences` | Get job search preferences |
| POST | `/api/agent/preferences` | Update job preferences |

### Applications & Logs
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/my-applications` | List user's applications |
| GET | `/api/submission-logs` | Get agent submission logs |
| GET | `/api/portal-credentials` | List auto-generated passwords |
| GET | `/api/failure-queue` | View failed applications |

### User Settings
| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/user/settings` | Update profile settings |
| POST | `/api/user/resume` | Upload resume |
| POST | `/api/user/linkedin-credentials` | Save LinkedIn credentials |
| POST | `/api/user/email-credentials` | Save Gmail credentials |

### Payments
| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/create-order` | Create Razorpay order |
| POST | `/api/verify-payment` | Verify payment signature |
| POST | `/api/razorpay-webhook` | Razorpay webhook handler |

---

## 🗄️ Database Schema

### `users.db`
- **users** — Candidate profiles, credentials (encrypted), preferences, OAuth data
- **agent_buyers** — Subscription records, portal passwords, resume paths
- **admin_users** — Admin accounts with roles
- **verification_requests** — Identity verification workflow
- **audit_logs** — Admin action audit trail

### `jobs.db`
- **posts** — Scraped LinkedIn feed posts (title, company, apply_link, poster info)
- **jobs** — Jobs discovered via Linkup API
- **applications** — Application records with status tracking
- **submission_logs** — Step-by-step agent execution logs with screenshots
- **failure_queue** — Failed applications for manual review
- **portal_profiles** — Known ATS portal configurations
- **payments** — Razorpay payment records

---

## 🔑 Default Admin Credentials
On first run, a default admin account is seeded:
- **Admin Panel**: `http://127.0.0.1:5000/admin`
- **Email**: `admin@iitiim.ai`
- **Password**: `admin123`

> ⚠️ **Change these credentials before deploying to production.**

---

## 📄 License

This project is proprietary software. All rights reserved.
