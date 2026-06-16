# System Readiness Assessment: IITIIM Job Assistant

This document identifies the remaining steps, credentials, code integrations, and operational tasks required to make the multi-tenant IITIIM Job Assistant SaaS fully operational in a production or live local testing environment.

---

## 1. Environment Configuration & API Keys

The system backend is running, but several integration keys are missing or use default development values in `.env`. The following keys must be configured:

| Category | Environment Variable | Purpose | Status |
| :--- | :--- | :--- | :--- |
| **AI Processing** | `ANTHROPIC_API_KEY` | Used by Claude to parse candidate resumes and generate personalized direct message copy. | **Present** (configured with a development key) |
| **Job Discovery** | `LINKUP_API_KEY` | Required by `job_seeker_agent/scraper.py` to fetch job postings from the Linkup search API. If missing, the scraping cycles are skipped. | **Missing** |
| **OAuth Auth** | `GOOGLE_CLIENT_ID`<br>`GOOGLE_CLIENT_SECRET`<br>`GOOGLE_REDIRECT_URI` | Required by Google OAuth 2.0 to authenticate and register users securely. | **Missing** (only in `.env.example`) |
| **Payment Gateway**| `RAZORPAY_KEY_ID`<br>`RAZORPAY_KEY_SECRET` | Required to create customer subscriptions and verify payment signatures. | **Present** (configured with test keys) |
| **Payment Webhooks**| `RAZORPAY_WEBHOOK_SECRET` | Required to securely verify server-to-server webhook captures on payment completion. | **Missing** |
| **Security Keys** | `SECRET_KEY`<br>`ENCRYPTION_KEY` | Used to encrypt Flask sessions, JWT admin tokens, and encrypt/decrypt user credentials. | **Missing** (falls back to defaults) |
| **Email Services** | `SMTP_HOST`<br>`SMTP_PORT`<br>`SMTP_USER`<br>`SMTP_PASS`<br>`EMAIL_FROM` | Used to email onboarding approval/rejection notifications to registered candidates. | **Missing** (only in `.env.example`) |

---

## 2. Code Integrations & Security Enhancements

We discovered two major architectural gaps in the current implementation that prevent the system from operating autonomously and securely:

### 2.1 LinkedIn Credential Encryption
While the encryption/decryption routines (`encrypt_credential` and `decrypt_credential`) are implemented using `cryptography` in [core/auth.py](file:///c:/Users/VIBUDH/Desktop/projects/job%20assistant/core/auth.py#L182-L214), they are **never called** in [core/database.py](file:///c:/Users/VIBUDH/Desktop/projects/job%20assistant/core/database.py#L558-L567) or [core/app.py](file:///c:/Users/VIBUDH/Desktop/projects/job%20assistant/core/app.py). Currently, user LinkedIn passwords are saved in **plaintext** in `users.db`.

> [!WARNING]
> To protect candidate credentials, the `update_user_linkedin_creds` and credential retrieval queries should be updated to encrypt/decrypt values using the AES-256-GCM helpers:
> ```python
> from core.auth import encrypt_credential, decrypt_credential
> ```

### 2.2 Background Scheduler Activation
The background scheduler loop ([job_seeker_agent/runner.py](file:///c:/Users/VIBUDH/Desktop/projects/job%20assistant/job_seeker_agent/runner.py)) is implemented, but the thread starter (`start_agent`) is **never imported or invoked** by the main Flask application on startup. 

> [!IMPORTANT]
> The background agent runner needs to be registered with the Flask application lifecycle. On boot (e.g. inside `create_app()` in `core/app.py`), the app should query the database for all active buyer IDs and spawn their agent scheduler threads:
> ```python
> from job_seeker_agent.runner import start_agent
> # Inside create_app() or on server startup:
> active_buyers = db.get_active_agent_buyers()
> for buyer in active_buyers:
>     start_agent(buyer["id"])
> ```

---

## 3. Operational Setup

To successfully deploy and test the agent workflows, the following operational steps are required:

1. **Verify Playwright Browser Installation**:
   Confirm that the Chromium browser binary is properly installed in the server environment so Playwright can run headlessly:
   ```bash
   venv\Scripts\playwright.exe install chromium
   ```

2. **Seed or Configure Target User Profile**:
   Ensure target user profiles are created in `users.db` and marked as `approved` so they can log in.

3. **Purchase or Upgrade to Agent Buyer status**:
   To test form filling, a user must be marked as an active agent buyer (`is_agent_buyer = 1`) by completing the Razorpay payment checkout at `/pay` or having an admin manually flag them.

4. **Add Resume files**:
   Upload a candidate's resume PDF or DOCX file to the dashboard (or save it directly in `resumes/` folder using the standard naming format: `<last_name>_<first_name>_<timestamp>.<ext>`).

5. **Rotate Admin Passwords**:
   On initial database generation, the system seeds a default super-admin credential:
   * **Email**: `admin@iitiim.ai`
   * **Password**: `admin123`
   
   This must be changed or deleted in production.
