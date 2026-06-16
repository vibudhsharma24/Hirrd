# 🤖 IITIIM Job Assistant

An AI-powered multi-tenant SaaS platform that automates job discovery, form filling, and personalized LinkedIn outreach. The platform provides candidates with a dashboard to manage their profiles, track applications, and execute browser-based agent automation on their behalf.

---

## 🌟 Features

*   **🔒 Secure Credential Vault**: User credentials (such as LinkedIn passwords and SMTP app secrets) are encrypted on-disk using **AES-256-GCM** cryptography.
*   **📊 Dynamic Dashboard**: A responsive dashboard showing custom application stats, subscription states, and live agent execution logs.
*   **🤖 Playwright-Based Browser Agent**:
    *   **Job Discovery**: Automatically scrapes LinkedIn job boards and feed posts based on target keywords.
    *   **Auto-Apply**: Parses resume text using Claude, detects page structure on applicant portals (Workday, Greenhouse, Lever, etc.), and auto-fills fields.
    *   **LinkedIn Outreach**: Sends personalized invitation notes and follows up once connections are accepted.
*   **💳 Payment Gateway Integration**: Native integration with **Razorpay Checkout** (Test Mode configured) for candidates to unlock agent features.
*   **🛡️ Role-Based Admin Panel**:
    *   Separate admin route (`/admin`) to view audit logs, track platform metrics, and manage the candidate approval pipeline.

---

## 🛠️ Tech Stack

*   **Frontend**: Vanilla HTML5, CSS3, Tailwind CSS, Google Fonts (Space Grotesk & Inter)
*   **Backend**: Python, Flask, Flask-Login, APScheduler (for background loops)
*   **Database**: SQLite (isolated into `users.db` for auth/users, and `jobs.db` for job postings/agent logs)
*   **Browser Automation**: Playwright (Python)
*   **AI Engine**: Anthropic Claude API (`anthropic` python SDK)
*   **Encryption**: `cryptography` (AES-256-GCM)
*   **Payments**: Razorpay API

---

## 📂 Project Structure

```text
├── core/                       # Flask application factory, database model, & auth
│   ├── app.py                  # Server entry & API endpoint mappings
│   ├── auth.py                 # AES-256-GCM encryption & session helpers
│   └── database.py             # Database creation & SQLite interface
├── job_seeker_agent/           # Core AI agent modules
│   ├── agent.py                # Main orchestrator
│   ├── browser_manager.py      # Playwright browser context runner
│   ├── applier.py              # Automated form filler
│   ├── scraper.py              # LinkedIn job scraper
│   └── runner.py               # Background scheduler threads
├── frontend/                   # UI templates served by Flask
│   ├── index.html              # Landing page
│   ├── dashboard.html          # Candidate console & agent setup modal
│   ├── pay.html                # Razorpay checkout plans card
│   ├── login.html / signup.html# Auth views
│   └── admin.html              # Admin panel view
├── docs/                       # Internal project architecture & UAT logs
├── requirements.txt            # Python environment packages
├── run.py                      # Flask runner launcher script
└── start_server.ps1            # Windows PowerShell bootstrapper
```

---

## 🚀 Getting Started

### 1. Prerequisites
Ensure you have **Python 3.10+** and **Git** installed on your machine.

### 2. Setup Virtual Environment
Clone this repository locally, navigate to the directory, and set up a virtual environment:
```bash
# Create virtual environment
python -m venv venv

# Activate virtual environment
# On Windows:
venv\Scripts\activate
# On macOS/Linux:
source venv/bin/activate
```

### 3. Install Dependencies
```bash
# Install packages
pip install -r requirements.txt

# Install Playwright browser binaries
playwright install chromium
```

### 4. Configure Environment Variables
Copy `.env.example` to `.env` and fill in the required keys:
```bash
cp .env.example .env
```
Ensure you set:
*   `ANTHROPIC_API_KEY`: Your Claude API token for resume parsing.
*   `SECRET_KEY` & `ENCRYPTION_KEY`: Keys to secure sessions and encrypt credentials.
*   `RAZORPAY_KEY_ID` & `RAZORPAY_KEY_SECRET`: Your Razorpay developer dashboard credentials.

### 5. Running the Application
Run the Flask server:
```bash
python run.py
```
Or use the convenience powershell script on Windows:
```powershell
.\start_server.ps1
```
The server will start at **`http://127.0.0.1:5000`**.

---

## 🔑 Default Credentials (Seed Data)
On first run, the SQLite database is automatically generated and seeded with a default admin user:
*   **Admin Route**: `http://127.0.0.1:5000/admin`
*   **Email**: `admin@iitiim.ai`
*   **Password**: `admin123`
*(Make sure to change or remove this seed credential before exposing the platform).*
