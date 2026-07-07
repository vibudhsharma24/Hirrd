"""
database.py
-----------
SQLite database layer for IITIIMJobAssistant.
All DB files live in the project root (one directory up from core/).
"""

import sqlite3
import hashlib
import os
import re
import json
from datetime import datetime, timezone
from urllib.parse import urlparse

# ── Paths — everything is relative to the project root (parent of core/) ──────
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DB_PATH          = os.path.join(PROJECT_ROOT, "users.db")
JOBS_DB_PATH     = os.path.join(PROJECT_ROOT, "jobs.db")
RESUMES_DIR      = os.path.join(PROJECT_ROOT, "resumes")
SCREENSHOTS_DIR  = os.path.join(PROJECT_ROOT, "screenshots")
GENERATED_RESUMES_DIR = os.path.join(PROJECT_ROOT, "resumes", "generated")


# ── Connection helpers ─────────────────────────────────────────────────────────
def _connect():
    """Connection to users.db (user registration system)."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row          # access columns by name
    conn.execute("PRAGMA journal_mode=WAL") # safe concurrent reads
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def _connect_jobs():
    """Connection to jobs.db (populated by linkedin-scan.mjs)."""
    conn = sqlite3.connect(JOBS_DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def get_db_connection(db_name: str = "users"):
    """Public helper to get a DB connection by name.
    Args:
        db_name: 'users' for users.db, 'jobs' for jobs.db
    Returns:
        sqlite3.Connection with row_factory set.
    """
    if db_name == "jobs":
        return _connect_jobs()
    return _connect()


# ── Schema ─────────────────────────────────────────────────────────────────────
def init_db():
    """Create / recreate the users and agent_buyers tables.
    Also ensures the resumes directory exists.
    """
    # Ensure directories exist
    os.makedirs(RESUMES_DIR, exist_ok=True)
    os.makedirs(SCREENSHOTS_DIR, exist_ok=True)
    os.makedirs(GENERATED_RESUMES_DIR, exist_ok=True)

    with _connect() as conn:
        # Create users table if it doesn't already exist (preserves existing data)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                name          TEXT    NOT NULL,
                last_name     TEXT    NOT NULL,
                email         TEXT    NOT NULL UNIQUE,
                password_hash TEXT    NOT NULL,
                linkedin_url  TEXT    DEFAULT '',
                mobile_number TEXT    DEFAULT '',
                avatar        TEXT    DEFAULT '',
                status        TEXT    DEFAULT 'pending',
                reject_reason TEXT    DEFAULT '',
                submitted_at  TEXT    NOT NULL
            )
        """)

        # Create google_connections table if it doesn't exist
        conn.execute("""
            CREATE TABLE IF NOT EXISTS google_connections (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id       INTEGER NOT NULL UNIQUE,
                google_email  TEXT    NOT NULL,
                access_token  TEXT    NOT NULL,
                refresh_token TEXT    NOT NULL,
                token_expiry  TEXT    NOT NULL,
                scopes        TEXT    NOT NULL,
                connected_at  TEXT    NOT NULL,
                FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
            )
        """)

        # Create agent_buyers table if it doesn't already exist (preserves existing buyers)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS agent_buyers (
                id                     INTEGER PRIMARY KEY AUTOINCREMENT,
                name                   TEXT    NOT NULL,
                last_name              TEXT    NOT NULL,
                email                  TEXT    NOT NULL,
                resume_path            TEXT    NOT NULL,
                subscription_status    TEXT    NOT NULL DEFAULT 'active',
                subscription_expires_at TEXT   DEFAULT '',
                daily_apply_limit      INTEGER NOT NULL DEFAULT 5,
                created_at             TEXT    NOT NULL
            )
        """)

        # Migrate agent_buyers with password columns
        for col in ["workday_password", "lever_password", "greenhouse_password", "ashby_password", "smartrecruiters_password", "other_passwords"]:
            try:
                conn.execute(f"ALTER TABLE agent_buyers ADD COLUMN {col} TEXT DEFAULT ''")
                conn.commit()
            except Exception:
                pass

        conn.execute("""
            CREATE TABLE IF NOT EXISTS jobs (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                title      TEXT    NOT NULL,
                company    TEXT    NOT NULL DEFAULT '',
                location   TEXT    NOT NULL DEFAULT '',
                url        TEXT    UNIQUE   NOT NULL,
                apply_link TEXT    NOT NULL DEFAULT '',
                source     TEXT    NOT NULL DEFAULT 'linkedin',
                keywords   TEXT    NOT NULL DEFAULT '',
                scraped_at TEXT    NOT NULL,
                status     TEXT    NOT NULL DEFAULT 'new'
            )
        """)
        # Migrate existing databases that don't have apply_link yet
        try:
            conn.execute("ALTER TABLE jobs ADD COLUMN apply_link TEXT NOT NULL DEFAULT ''")
            conn.commit()
        except Exception:
            pass  # column already exists
        conn.commit()

    # ── Auto-apply tables in jobs.db ───────────────────────────────────────
    with _connect_jobs() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS applications (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                buyer_id        INTEGER NOT NULL,
                post_id         INTEGER,
                job_id          INTEGER,
                portal_hostname TEXT    NOT NULL DEFAULT '',
                ats_type        TEXT    NOT NULL DEFAULT '',
                status          TEXT    NOT NULL DEFAULT 'pending',
                confirmation_id TEXT    DEFAULT '',
                resume_used     TEXT    DEFAULT '',
                cover_letter    TEXT    DEFAULT '',
                applied_at      TEXT,
                notes           TEXT    DEFAULT '',
                created_at      TEXT    NOT NULL
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS submission_logs (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                application_id  INTEGER NOT NULL,
                step_name       TEXT    NOT NULL,
                screenshot_path TEXT    DEFAULT '',
                dom_snapshot    TEXT    DEFAULT '',
                page_url        TEXT    DEFAULT '',
                timestamp       TEXT    NOT NULL
            )
        """)

        conn.execute("""
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
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS portal_profiles (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                hostname        TEXT    UNIQUE NOT NULL,
                ats_type        TEXT    NOT NULL,
                login_required  INTEGER DEFAULT 0,
                resume_upload   TEXT    DEFAULT 'pdf',
                cover_letter    TEXT    DEFAULT 'optional',
                steps_json      TEXT    NOT NULL DEFAULT '[]',
                known_quirks    TEXT    DEFAULT '',
                success_count   INTEGER DEFAULT 0,
                fail_count      INTEGER DEFAULT 0,
                last_used_at    TEXT,
                created_at      TEXT    NOT NULL
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS payments (
                id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                razorpay_order_id   TEXT    UNIQUE NOT NULL,
                razorpay_payment_id TEXT    DEFAULT '',
                razorpay_signature  TEXT    DEFAULT '',
                amount_paise        INTEGER NOT NULL,
                currency            TEXT    NOT NULL DEFAULT 'INR',
                receipt             TEXT    DEFAULT '',
                buyer_id            INTEGER,
                status              TEXT    NOT NULL DEFAULT 'created',
                verified_at         TEXT    DEFAULT '',
                created_at          TEXT    NOT NULL
            )
        """)
        conn.commit()

    # ── Admin & Audit tables in users.db ───────────────────────────────────
    with _connect() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS admin_users (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                email         TEXT    NOT NULL UNIQUE,
                password_hash TEXT    NOT NULL,
                role          TEXT    NOT NULL DEFAULT 'ADMIN',
                name          TEXT    NOT NULL DEFAULT '',
                permissions   TEXT    NOT NULL DEFAULT '',
                created_at    TEXT    NOT NULL,
                updated_at    TEXT    NOT NULL,
                last_login_at TEXT    DEFAULT ''
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS audit_logs (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                admin_id        INTEGER NOT NULL,
                admin_email     TEXT    NOT NULL DEFAULT '',
                action          TEXT    NOT NULL,
                target_user_id  INTEGER,
                previous_value  TEXT    DEFAULT '',
                new_value       TEXT    DEFAULT '',
                reason          TEXT    DEFAULT '',
                timestamp       TEXT    NOT NULL,
                ip_address      TEXT    DEFAULT ''
            )
        """)
        try:
            conn.execute("CREATE INDEX IF NOT EXISTS idx_audit_timestamp ON audit_logs(timestamp)")
        except Exception:
            pass
        try:
            conn.execute("CREATE INDEX IF NOT EXISTS idx_audit_admin ON audit_logs(admin_id)")
        except Exception:
            pass
        try:
            conn.execute("CREATE INDEX IF NOT EXISTS idx_audit_action ON audit_logs(action)")
        except Exception:
            pass

        conn.execute("""
            CREATE TABLE IF NOT EXISTS verification_requests (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id          INTEGER NOT NULL UNIQUE,
                linkedin_url     TEXT    NOT NULL DEFAULT '',
                status           TEXT    NOT NULL DEFAULT 'PENDING',
                parsed_data      TEXT    DEFAULT '',
                raw_evidence     TEXT    DEFAULT '',
                reviewed_by      INTEGER,
                reviewed_at      TEXT    DEFAULT '',
                rejection_reason TEXT    DEFAULT '',
                created_at       TEXT    NOT NULL,
                updated_at       TEXT    NOT NULL
            )
        """)
        try:
            conn.execute("CREATE INDEX IF NOT EXISTS idx_verif_status ON verification_requests(status)")
        except Exception:
            pass
        try:
            conn.execute("CREATE INDEX IF NOT EXISTS idx_verif_user ON verification_requests(user_id)")
        except Exception:
            pass

        # ── Idempotent migrations: add tracking columns to users ───────────
        _migrate_columns = [
            ("users", "last_login_at",      "TEXT DEFAULT ''"),
            ("users", "login_count",        "INTEGER DEFAULT 0"),
            ("users", "agent_usage_count",  "INTEGER DEFAULT 0"),
            ("users", "last_activity_at",   "TEXT DEFAULT ''"),
            ("users", "reviewed_by",        "INTEGER DEFAULT NULL"),
            ("users", "reviewed_at",        "TEXT DEFAULT ''"),
            # ── New columns for login, agent, and payment ─────────────
            ("users", "is_agent_buyer",     "INTEGER DEFAULT 0"),
            ("users", "agent_status",       "TEXT DEFAULT 'inactive'"),
            ("users", "linkedin_username",  "TEXT DEFAULT ''"),
            ("users", "linkedin_password",  "TEXT DEFAULT ''"),
            ("users", "job_preferences",    "TEXT DEFAULT '{}'"),
            ("users", "auth_provider",      "TEXT DEFAULT 'email'"),
            ("users", "google_id",          "TEXT DEFAULT ''"),
            ("users", "password_set",       "INTEGER DEFAULT 1"),
            # ── New settings columns ──────────────────────────────────
            ("users", "institute",          "TEXT DEFAULT ''"),
            ("users", "headline",           "TEXT DEFAULT ''"),
            ("users", "linkedin_connected", "INTEGER DEFAULT 1"),
            ("users", "gmail_connected",    "INTEGER DEFAULT 1"),
            ("users", "calendly_connected", "INTEGER DEFAULT 0"),
            ("users", "email_summaries",    "INTEGER DEFAULT 1"),
            ("users", "weekly_report",      "INTEGER DEFAULT 1"),
            ("users", "human_in_loop",      "INTEGER DEFAULT 0"),
            # ── Gmail credential columns ──────────────────────────────
            ("users", "gmail_username",      "TEXT DEFAULT ''"),
            ("users", "gmail_password",      "TEXT DEFAULT ''"),
            # ── Naukri credential columns ─────────────────────────────
            ("users", "naukri_username",     "TEXT DEFAULT ''"),
            ("users", "naukri_password",     "TEXT DEFAULT ''"),
            ("users", "naukri_preferences",  "TEXT DEFAULT '{}'"),
            # ── LinkedIn profile name column ──────────────────────────
            ("users", "linkedin_profile_name", "TEXT DEFAULT ''"),
            # ── Password reset code columns ───────────────────────────
            ("users", "reset_code",          "TEXT DEFAULT ''"),
            ("users", "reset_code_expires_at", "TEXT DEFAULT ''"),
        ]
        for table, col, typedef in _migrate_columns:
            try:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {typedef}")
            except Exception:
                pass  # column already exists

        # ── Migrate admin_users table ────────────────────────────────
        _admin_migrate = [
            ("admin_users", "permissions", "TEXT NOT NULL DEFAULT ''"),
        ]
        for table, col, typedef in _admin_migrate:
            try:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {typedef}")
            except Exception:
                pass  # column already exists

        # ── Master CV table ─────────────────────────────────────────
        conn.execute("""
            CREATE TABLE IF NOT EXISTS master_cv (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id       INTEGER NOT NULL UNIQUE,
                cv_data       TEXT    NOT NULL,
                updated_at    TEXT    NOT NULL,
                FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
            )
        """)

        conn.commit()

    # Seed default super admin
    _seed_default_admin()

    # Backfill verification_requests for existing users
    _backfill_verification_requests()

    print("[DB] Database ready -> " + DB_PATH)
    print("[DB] Jobs DB ready  -> " + JOBS_DB_PATH)
    print("[DB] Resumes dir    -> " + RESUMES_DIR)
    print("[DB] Screenshots    -> " + SCREENSHOTS_DIR)


def _seed_default_admin():
    """Create the default Super Admin and restricted admin if they don't exist."""
    now = datetime.now(timezone.utc).isoformat()
    with _connect() as conn:
        count = conn.execute("SELECT COUNT(*) FROM admin_users").fetchone()[0]
        if count == 0:
            conn.execute(
                """INSERT INTO admin_users (email, password_hash, role, name, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                ("admin@iitiim.ai", _sha256("admin123"), "SUPER_ADMIN", "Superadmin", now, now),
            )
            conn.commit()
            print("[DB] Default Super Admin created: admin@iitiim.ai / admin123")

        # Seed restricted admin officishiv582@gmail.com if not exists
        count_shiv = conn.execute("SELECT COUNT(*) FROM admin_users WHERE email = ?", ("officishiv582@gmail.com",)).fetchone()[0]
        if count_shiv == 0:
            conn.execute(
                """INSERT INTO admin_users (email, password_hash, role, name, permissions, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                ("officishiv582@gmail.com", _sha256("z8$Kp9!mL2#qN5xV"), "ADMIN", "Admin", "users", now, now),
            )
            conn.commit()
            print("[DB] Restricted Admin created: officishiv582@gmail.com / z8$Kp9!mL2#qN5xV")
        else:
            # Ensure existing restricted admin has permissions set
            conn.execute(
                "UPDATE admin_users SET permissions = 'users' WHERE email = ? AND (permissions IS NULL OR permissions = '')",
                ("officishiv582@gmail.com",),
            )
            conn.commit()


def _backfill_verification_requests():
    """Create verification_requests rows for any existing users that don't have one."""
    with _connect() as conn:
        rows = conn.execute("""
            SELECT u.id, u.linkedin_url, u.status, u.submitted_at
            FROM users u
            LEFT JOIN verification_requests v ON v.user_id = u.id
            WHERE v.id IS NULL
        """).fetchall()
        now = datetime.now(timezone.utc).isoformat()
        for r in rows:
            status_map = {"pending": "PENDING", "approved": "APPROVED", "rejected": "REJECTED"}
            v_status = status_map.get(r["status"], "PENDING")
            conn.execute(
                """INSERT OR IGNORE INTO verification_requests
                   (user_id, linkedin_url, status, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (r["id"], r["linkedin_url"] or "", v_status, r["submitted_at"] or now, now),
            )
        conn.commit()
        if rows:
            print(f"[DB] Backfilled {len(rows)} verification request(s)")


# ── Helpers ────────────────────────────────────────────────────────────────────
def _sha256(plain: str) -> str:
    """Return the SHA-256 hex digest of a plaintext string."""
    return hashlib.sha256(plain.encode("utf-8")).hexdigest()


def _make_avatar(name: str, last_name: str = "") -> str:
    """Generate 2-letter initials from first + last name."""
    first_initial = name.strip()[0].upper() if name.strip() else "?"
    last_initial  = last_name.strip()[0].upper() if last_name.strip() else "?"
    return first_initial + last_initial


def validate_linkedin_url(url: str) -> str:
    """Validate that the URL is a LinkedIn URL.
    Returns the cleaned URL on success.
    Raises ValueError with a user-friendly message on failure.
    """
    if not url or not url.strip():
        return ""

    url = url.strip()

    # Add https:// if no scheme is provided
    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    parsed = urlparse(url)
    hostname = (parsed.hostname or "").lower()

    # Check that the domain is linkedin.com or a subdomain of it
    if not (hostname == "linkedin.com" or hostname.endswith(".linkedin.com")):
        raise ValueError(
            "Invalid LinkedIn URL. Only linkedin.com URLs are accepted. "
            f"Got: {url}"
        )

    return url


# ── Users: Write operations ────────────────────────────────────────────────────
def save_user(
    name: str,
    last_name: str,
    email: str,
    password: str,
    linkedin_url: str,
    mobile_number: str,
) -> dict:
    """
    Validate LinkedIn URL, hash the password with SHA-256,
    and insert a new user row.
    Returns the newly inserted row as a dict.
    Raises ValueError if the LinkedIn URL is invalid.
    """
    # Validate LinkedIn URL (raises ValueError on bad URL)
    linkedin_url = validate_linkedin_url(linkedin_url)

    password_hash = _sha256(password)
    avatar        = _make_avatar(name, last_name)
    submitted_at  = datetime.now(timezone.utc).isoformat()

    with _connect() as conn:
        cur = conn.execute(
            """
            INSERT INTO users
                (name, last_name, email, password_hash, linkedin_url,
                 mobile_number, avatar, submitted_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (name, last_name, email, password_hash, linkedin_url,
             mobile_number, avatar, submitted_at),
        )
        conn.commit()
        row_id = cur.lastrowid

    # Auto-create a verification request for the approval queue
    create_verification_request(row_id, linkedin_url)

    return get_user(row_id)


def approve_user(user_id: int) -> bool:
    with _connect() as conn:
        cur = conn.execute(
            "UPDATE users SET status = 'approved', reject_reason = '' WHERE id = ?",
            (user_id,),
        )
        conn.commit()
    return cur.rowcount > 0


def reject_user(user_id: int, reason: str = "") -> bool:
    with _connect() as conn:
        cur = conn.execute(
            "UPDATE users SET status = 'rejected', reject_reason = ? WHERE id = ?",
            (reason, user_id),
        )
        conn.commit()
    return cur.rowcount > 0


def delete_all_users() -> int:
    with _connect() as conn:
        cur = conn.execute("DELETE FROM users")
        conn.commit()
    return cur.rowcount


# ── Users: Read operations ─────────────────────────────────────────────────────
def _row_to_dict(row) -> dict:
    d = dict(row)
    # Transparently decrypt linkedin_password if present and non-empty
    if d.get("linkedin_password"):
        try:
            from core.auth import decrypt_credential
            d["linkedin_password"] = decrypt_credential(d["linkedin_password"])
        except Exception:
            pass  # leave as-is if decryption fails
    # Transparently decrypt gmail_password if present and non-empty
    if d.get("gmail_password"):
        try:
            from core.auth import decrypt_credential
            d["gmail_password"] = decrypt_credential(d["gmail_password"])
        except Exception:
            pass  # leave as-is if decryption fails
    # Transparently decrypt naukri_password if present and non-empty
    if d.get("naukri_password"):
        try:
            from core.auth import decrypt_credential
            d["naukri_password"] = decrypt_credential(d["naukri_password"])
        except Exception:
            pass  # leave as-is if decryption fails
            
    # Transparently parse naukri_preferences JSON
    if d.get("naukri_preferences"):
        try:
            d["naukri_preferences"] = json.loads(d["naukri_preferences"])
        except Exception:
            d["naukri_preferences"] = {}
    else:
        d["naukri_preferences"] = {}
        
    return d


def get_user_by_email(email: str) -> dict | None:
    """Look up a user by email address."""
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM users WHERE email = ?", (email.strip().lower(),)
        ).fetchone()
    return _row_to_dict(row) if row else None


def verify_user_login(email: str, password: str) -> dict | None:
    """Verify user credentials. Returns user dict on success, None on failure."""
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM users WHERE email = ? AND password_hash = ?",
            (email.strip().lower(), _sha256(password)),
        ).fetchone()
        if row:
            now = datetime.now(timezone.utc).isoformat()
            conn.execute(
                """UPDATE users SET last_login_at = ?,
                   login_count = COALESCE(login_count, 0) + 1,
                   last_activity_at = ?
                   WHERE id = ?""",
                (now, now, row["id"]),
            )
            conn.commit()
            return _row_to_dict(row)
    return None


def update_user_password(user_id: int, new_password: str) -> bool:
    """Update a user's password. Used after Google OAuth to force password set."""
    with _connect() as conn:
        cur = conn.execute(
            "UPDATE users SET password_hash = ?, password_set = 1 WHERE id = ?",
            (_sha256(new_password), user_id),
        )
        conn.commit()
    return cur.rowcount > 0


def update_user_reset_code(email: str, code: str, expires_at: str) -> bool:
    """Store verification code and its expiration timestamp for forgot password."""
    with _connect() as conn:
        cur = conn.execute(
            "UPDATE users SET reset_code = ?, reset_code_expires_at = ? WHERE email = ?",
            (code, expires_at, email.strip().lower()),
        )
        conn.commit()
    return cur.rowcount > 0


def clear_user_reset_code(email: str) -> bool:
    """Clear user reset code after successful password reset."""
    with _connect() as conn:
        cur = conn.execute(
            "UPDATE users SET reset_code = '', reset_code_expires_at = '' WHERE email = ?",
            (email.strip().lower(),),
        )
        conn.commit()
    return cur.rowcount > 0



def save_google_user(name: str, last_name: str, email: str, google_id: str, avatar: str = "") -> dict:
    """Create or get a user from Google OAuth. Returns the user dict."""
    existing = get_user_by_email(email)
    if existing:
        # Update google_id if not set
        if not existing.get("google_id"):
            with _connect() as conn:
                conn.execute(
                    "UPDATE users SET google_id = ?, auth_provider = 'google' WHERE id = ?",
                    (google_id, existing["id"]),
                )
                conn.commit()
        return get_user(existing["id"])

    # Create new user with placeholder password (password_set = 0)
    submitted_at = datetime.now(timezone.utc).isoformat()
    if not avatar:
        avatar = _make_avatar(name, last_name)
    with _connect() as conn:
        cur = conn.execute(
            """INSERT INTO users
               (name, last_name, email, password_hash, linkedin_url,
                mobile_number, avatar, submitted_at, auth_provider, google_id, password_set)
               VALUES (?, ?, ?, ?, '', '', ?, ?, 'google', ?, 0)""",
            (name, last_name, email.strip().lower(),
             _sha256(os.urandom(32).hex()),  # random placeholder, user must set real password
             avatar, submitted_at, google_id),
        )
        conn.commit()
        row_id = cur.lastrowid

    from core.database import create_verification_request
    create_verification_request(row_id, "")
    return get_user(row_id)


def update_user_agent_status(user_id: int, status: str) -> bool:
    """Update agent_status for a user. Values: 'inactive', 'running', 'paused', 'error'."""
    with _connect() as conn:
        cur = conn.execute(
            "UPDATE users SET agent_status = ? WHERE id = ?",
            (status, user_id),
        )
        conn.commit()
    return cur.rowcount > 0


def set_user_agent_buyer(user_id: int, is_buyer: bool = True) -> bool:
    """Set is_agent_buyer flag for a user after successful payment."""
    with _connect() as conn:
        cur = conn.execute(
            "UPDATE users SET is_agent_buyer = ? WHERE id = ?",
            (1 if is_buyer else 0, user_id),
        )
        conn.commit()
    return cur.rowcount > 0


def update_user_linkedin_creds(user_id: int, username: str, password: str) -> bool:
    """Store encrypted LinkedIn credentials for a user."""
    # Encrypt the password before storing
    try:
        from core.auth import encrypt_credential
        encrypted_password = encrypt_credential(password)
    except Exception:
        encrypted_password = password  # fallback if encryption unavailable
    with _connect() as conn:
        cur = conn.execute(
            "UPDATE users SET linkedin_username = ?, linkedin_password = ? WHERE id = ?",
            (username, encrypted_password, user_id),
        )
        conn.commit()
    return cur.rowcount > 0


def update_user_gmail_creds(user_id: int, username: str, password: str) -> bool:
    """Store encrypted Gmail/email credentials for a user."""
    try:
        from core.auth import encrypt_credential
        encrypted_password = encrypt_credential(password)
    except Exception:
        encrypted_password = password  # fallback if encryption unavailable
    with _connect() as conn:
        cur = conn.execute(
            "UPDATE users SET gmail_username = ?, gmail_password = ? WHERE id = ?",
            (username, encrypted_password, user_id),
        )
        conn.commit()
    return cur.rowcount > 0


def update_user_naukri_creds(user_id: int, username: str, password: str) -> bool:
    """Store encrypted Naukri credentials for a user."""
    try:
        from core.auth import encrypt_credential
        encrypted_password = encrypt_credential(password)
    except Exception:
        encrypted_password = password  # fallback if encryption unavailable
    with _connect() as conn:
        cur = conn.execute(
            "UPDATE users SET naukri_username = ?, naukri_password = ? WHERE id = ?",
            (username, encrypted_password, user_id),
        )
        conn.commit()
    return cur.rowcount > 0


def update_user_naukri_preferences(user_id: int, preferences: dict) -> bool:
    """Store Naukri job search preferences for a user."""
    pref_json = json.dumps(preferences, ensure_ascii=False)
    with _connect() as conn:
        cur = conn.execute(
            "UPDATE users SET naukri_preferences = ? WHERE id = ?",
            (pref_json, user_id),
        )
        conn.commit()
    return cur.rowcount > 0


def get_user(user_id: int) -> dict | None:
    with _connect() as conn:
        row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    return _row_to_dict(row) if row else None


def get_all_users() -> list[dict]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM users ORDER BY submitted_at DESC"
        ).fetchall()
    return [_row_to_dict(r) for r in rows]


def get_pending_users() -> list[dict]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM users WHERE status = 'pending' ORDER BY submitted_at DESC"
        ).fetchall()
    return [_row_to_dict(r) for r in rows]


def get_stats() -> dict:
    with _connect() as conn:
        total    = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        pending  = conn.execute("SELECT COUNT(*) FROM users WHERE status='pending'").fetchone()[0]
        approved = conn.execute("SELECT COUNT(*) FROM users WHERE status='approved'").fetchone()[0]
        rejected = conn.execute("SELECT COUNT(*) FROM users WHERE status='rejected'").fetchone()[0]
        with_li  = conn.execute("SELECT COUNT(*) FROM users WHERE linkedin_url != ''").fetchone()[0]

    # Also include agent_buyers count
    try:
        with _connect() as conn:
            agent_buyers_total = conn.execute("SELECT COUNT(*) FROM agent_buyers").fetchone()[0]
    except Exception:
        agent_buyers_total = 0

    return {
        "total": total,
        "pending": pending,
        "approved": approved,
        "rejected": rejected,
        "with_linkedin": with_li,
        "agent_buyers_total": agent_buyers_total,
    }


# ── Agent Buyers: Write operations ─────────────────────────────────────────────

ALLOWED_RESUME_EXTENSIONS = {".pdf", ".doc", ".docx"}
MAX_RESUME_SIZE_BYTES = 5 * 1024 * 1024  # 5 MB


def _sanitize_filename(name: str) -> str:
    """Remove non-alphanumeric characters from a name for safe filenames."""
    return re.sub(r"[^a-zA-Z0-9]", "", name).lower()


def save_agent_buyer(
    name: str,
    last_name: str,
    email: str,
    resume_file,
) -> dict:
    """
    Save an agent buyer record and store their resume file on disk.

    Args:
        name:        First name
        last_name:   Last name
        email:       Email address
        resume_file: A Werkzeug FileStorage object (from Flask request.files)

    Returns:
        The newly inserted row as a dict.

    Raises:
        ValueError: If the resume file type is not allowed or file is too large.
    """
    # Validate resume file extension
    original_filename = resume_file.filename or ""
    ext = os.path.splitext(original_filename)[1].lower()
    if ext not in ALLOWED_RESUME_EXTENSIONS:
        raise ValueError(
            f"Invalid resume format '{ext}'. "
            f"Only PDF and DOC files are accepted ({', '.join(ALLOWED_RESUME_EXTENSIONS)})."
        )

    # Read file content to check size
    file_content = resume_file.read()
    if len(file_content) > MAX_RESUME_SIZE_BYTES:
        raise ValueError(
            f"Resume file is too large ({len(file_content) / 1024 / 1024:.1f} MB). "
            f"Maximum allowed size is {MAX_RESUME_SIZE_BYTES / 1024 / 1024:.0f} MB."
        )

    # Build a unique filename
    timestamp = int(datetime.now(timezone.utc).timestamp())
    safe_first = _sanitize_filename(name) or "unknown"
    safe_last  = _sanitize_filename(last_name) or "unknown"
    resume_filename = f"{safe_last}_{safe_first}_{timestamp}{ext}"
    resume_path = os.path.join(RESUMES_DIR, resume_filename)

    # Save file to disk
    os.makedirs(RESUMES_DIR, exist_ok=True)
    with open(resume_path, "wb") as f:
        f.write(file_content)

    # Insert DB record
    created_at = datetime.now(timezone.utc).isoformat()

    with _connect() as conn:
        cur = conn.execute(
            """
            INSERT INTO agent_buyers (name, last_name, email, resume_path, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (name, last_name, email, resume_path, created_at),
        )
        conn.commit()
        row_id = cur.lastrowid

    return get_agent_buyer(row_id)


def delete_agent_buyer(buyer_id: int) -> bool:
    """Delete an agent buyer and remove their resume file from disk."""
    buyer = get_agent_buyer(buyer_id)
    if not buyer:
        return False

    # Remove resume file from disk
    resume_path = buyer.get("resume_path", "")
    if resume_path and os.path.exists(resume_path):
        try:
            os.remove(resume_path)
            print(f"[DB] Deleted resume file: {resume_path}")
        except OSError as e:
            print(f"[DB] Warning: could not delete resume file {resume_path}: {e}")

    with _connect() as conn:
        cur = conn.execute("DELETE FROM agent_buyers WHERE id = ?", (buyer_id,))
        conn.commit()
    return cur.rowcount > 0


def delete_all_agent_buyers() -> int:
    """Delete all agent buyers and their resume files."""
    buyers = get_all_agent_buyers()

    # Remove all resume files
    for buyer in buyers:
        resume_path = buyer.get("resume_path", "")
        if resume_path and os.path.exists(resume_path):
            try:
                os.remove(resume_path)
            except OSError:
                pass

    with _connect() as conn:
        cur = conn.execute("DELETE FROM agent_buyers")
        conn.commit()
    return cur.rowcount


# ── Agent Buyers: Read operations ──────────────────────────────────────────────
def get_agent_buyer(buyer_id: int) -> dict | None:
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM agent_buyers WHERE id = ?", (buyer_id,)
        ).fetchone()
    return _row_to_dict(row) if row else None


def get_all_agent_buyers() -> list[dict]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM agent_buyers ORDER BY created_at DESC"
        ).fetchall()
    return [_row_to_dict(r) for r in rows]


def get_agent_buyers_stats() -> dict:
    with _connect() as conn:
        total = conn.execute("SELECT COUNT(*) FROM agent_buyers").fetchone()[0]
    return {"total": total}


# ── Jobs — read / update ───────────────────────────────────────────────────────

def get_all_jobs(status: str | None = None) -> list[dict]:
    """Return all jobs from jobs.db, optionally filtered by status."""
    with _connect_jobs() as conn:
        if status:
            rows = conn.execute(
                "SELECT * FROM jobs WHERE status = ? ORDER BY scraped_at DESC",
                (status,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM jobs ORDER BY scraped_at DESC"
            ).fetchall()
    return [_row_to_dict(r) for r in rows]


def get_jobs_stats() -> dict:
    """Return job counts from jobs.db grouped by status."""
    with _connect_jobs() as conn:
        total     = conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
        new       = conn.execute("SELECT COUNT(*) FROM jobs WHERE status='new'").fetchone()[0]
        reviewed  = conn.execute("SELECT COUNT(*) FROM jobs WHERE status='reviewed'").fetchone()[0]
        applied   = conn.execute("SELECT COUNT(*) FROM jobs WHERE status='applied'").fetchone()[0]
        dismissed = conn.execute("SELECT COUNT(*) FROM jobs WHERE status='dismissed'").fetchone()[0]
    return {
        "total":     total,
        "new":       new,
        "reviewed":  reviewed,
        "applied":   applied,
        "dismissed": dismissed,
    }


def update_job_status(job_id: int, status: str) -> bool:
    """Update the status of a job in jobs.db. Returns True if a row was updated."""
    valid = {"new", "reviewed", "applied", "dismissed"}
    if status not in valid:
        raise ValueError(f"Invalid status '{status}'. Must be one of: {valid}")
    with _connect_jobs() as conn:
        cur = conn.execute(
            "UPDATE jobs SET status = ? WHERE id = ?",
            (status, job_id),
        )
        conn.commit()
    return cur.rowcount > 0


# ── Posts (scraped by linkedin-posts.mjs) ─────────────────────────────────────────────

def init_posts_table():
    """Ensure the posts table exists in jobs.db (also created by the scraper itself)."""
    with _connect_jobs() as conn:
        conn.execute("""
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
                apply_method     TEXT    NOT NULL DEFAULT ''
            )
        """)
        # Idempotently add post_url column if it doesn't exist
        try:
            conn.execute("ALTER TABLE posts ADD COLUMN post_url TEXT NOT NULL DEFAULT ''")
        except Exception:
            pass
        # Idempotently add apply_url column if it doesn't exist
        try:
            conn.execute("ALTER TABLE posts ADD COLUMN apply_url TEXT NOT NULL DEFAULT ''")
        except Exception:
            pass
        # Idempotently add apply_method column if it doesn't exist
        try:
            conn.execute("ALTER TABLE posts ADD COLUMN apply_method TEXT NOT NULL DEFAULT ''")
        except Exception:
            pass
        conn.commit()


def get_all_posts(status: str | None = None) -> list[dict]:
    """Return all scraped posts from jobs.db, optionally filtered by status."""
    try:
        with _connect_jobs() as conn:
            if status:
                rows = conn.execute(
                    "SELECT * FROM posts WHERE status = ? ORDER BY scraped_at DESC",
                    (status,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM posts ORDER BY scraped_at DESC"
                ).fetchall()
        return [_row_to_dict(r) for r in rows]
    except Exception:
        return []   # posts table may not exist yet


def get_posts_stats() -> dict:
    """Return post counts from jobs.db grouped by status."""
    try:
        with _connect_jobs() as conn:
            total     = conn.execute("SELECT COUNT(*) FROM posts").fetchone()[0]
            new       = conn.execute("SELECT COUNT(*) FROM posts WHERE status='new'").fetchone()[0]
            reviewed  = conn.execute("SELECT COUNT(*) FROM posts WHERE status='reviewed'").fetchone()[0]
            applied   = conn.execute("SELECT COUNT(*) FROM posts WHERE status='applied'").fetchone()[0]
            dismissed = conn.execute("SELECT COUNT(*) FROM posts WHERE status='dismissed'").fetchone()[0]
        return {
            "total":     total,
            "new":       new,
            "reviewed":  reviewed,
            "applied":   applied,
            "dismissed": dismissed,
        }
    except Exception:
        return {"total": 0, "new": 0, "reviewed": 0, "applied": 0, "dismissed": 0}


def update_post_status(post_id: int, status: str) -> bool:
    """Update the status of a scraped post in jobs.db."""
    valid = {"new", "reviewed", "applied", "dismissed", "pending"}
    if status not in valid:
        raise ValueError(f"Invalid status '{status}'. Must be one of: {valid}")
    with _connect_jobs() as conn:
        cur = conn.execute(
            "UPDATE posts SET status = ? WHERE id = ?",
            (status, post_id),
        )
        conn.commit()
    return cur.rowcount > 0


# ── Active Agent Buyers ────────────────────────────────────────────────────────

def get_active_agent_buyers() -> list[dict]:
    """Return all agent buyers with subscription_status = 'active'."""
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM agent_buyers WHERE subscription_status = 'active' ORDER BY created_at DESC"
        ).fetchall()
    return [_row_to_dict(r) for r in rows]


def is_buyer_active(buyer_id: int) -> bool:
    """Check if a specific buyer has an active subscription."""
    buyer = get_agent_buyer(buyer_id)
    if not buyer:
        return False
    return buyer.get("subscription_status", "") == "active"


def update_buyer_subscription(buyer_id: int, status: str, expires_at: str = "") -> bool:
    """Update subscription status for an agent buyer.
    Args:
        buyer_id: Agent buyer ID
        status: 'active' or 'inactive'
        expires_at: ISO-8601 expiration date (optional)
    """
    valid = {"active", "inactive"}
    if status not in valid:
        raise ValueError(f"Invalid subscription status '{status}'. Must be one of: {valid}")
    with _connect() as conn:
        cur = conn.execute(
            "UPDATE agent_buyers SET subscription_status = ?, subscription_expires_at = ? WHERE id = ?",
            (status, expires_at, buyer_id),
        )
        conn.commit()
    return cur.rowcount > 0


# ── Applications CRUD ─────────────────────────────────────────────────────────

def create_application(
    buyer_id: int,
    portal_hostname: str = "",
    ats_type: str = "",
    post_id: int | None = None,
    job_id: int | None = None,
    resume_used: str = "",
    cover_letter: str = "",
    notes: str = "",
) -> dict:
    """Create a new application record in jobs.db."""
    created_at = datetime.now(timezone.utc).isoformat()
    with _connect_jobs() as conn:
        cur = conn.execute(
            """
            INSERT INTO applications
                (buyer_id, post_id, job_id, portal_hostname, ats_type,
                 status, resume_used, cover_letter, notes, created_at)
            VALUES (?, ?, ?, ?, ?, 'pending', ?, ?, ?, ?)
            """,
            (buyer_id, post_id, job_id, portal_hostname, ats_type,
             resume_used, cover_letter, notes, created_at),
        )
        conn.commit()
        row_id = cur.lastrowid

    return get_application(row_id)


def get_application(app_id: int) -> dict | None:
    """Get a single application by ID from jobs.db."""
    with _connect_jobs() as conn:
        row = conn.execute(
            """
            SELECT a.*, 
                   p.company AS post_company, p.title AS post_title,
                   j.company AS job_company, j.title AS job_title
            FROM applications a
            LEFT JOIN posts p ON a.post_id = p.id
            LEFT JOIN jobs j ON a.job_id = j.id
            WHERE a.id = ?
            """,
            (app_id,),
        ).fetchone()
    if not row:
        return None
    d = _row_to_dict(row)
    d["company"] = d.get("post_company") or d.get("job_company") or d.get("portal_hostname") or "Direct Apply"
    d["title"] = d.get("post_title") or d.get("job_title") or d.get("ats_type") or "Application"
    return d


def get_all_applications(buyer_id: int | None = None, status: str | None = None) -> list[dict]:
    """Return applications, optionally filtered by buyer and/or status."""
    query = """
        SELECT a.*, 
               p.company AS post_company, p.title AS post_title,
               j.company AS job_company, j.title AS job_title
        FROM applications a
        LEFT JOIN posts p ON a.post_id = p.id
        LEFT JOIN jobs j ON a.job_id = j.id
    """
    params = []
    conditions = []
    if buyer_id is not None:
        conditions.append("a.buyer_id = ?")
        params.append(buyer_id)
    if status:
        conditions.append("a.status = ?")
        params.append(status)
    if conditions:
        query += " WHERE " + " AND ".join(conditions)
    query += " ORDER BY a.created_at DESC"

    with _connect_jobs() as conn:
        rows = conn.execute(query, params).fetchall()
    
    res = []
    for r in rows:
        d = _row_to_dict(r)
        d["company"] = d.get("post_company") or d.get("job_company") or d.get("portal_hostname") or "Direct Apply"
        d["title"] = d.get("post_title") or d.get("job_title") or d.get("ats_type") or "Application"
        res.append(d)
    return res


def update_application_status(
    app_id: int,
    status: str,
    confirmation_id: str = "",
    notes: str = "",
) -> bool:
    """Update an application's status. Sets applied_at when status is 'applied'."""
    valid = {"pending", "applied", "failed", "paused", "dismissed"}
    if status not in valid:
        raise ValueError(f"Invalid application status '{status}'. Must be one of: {valid}")

    applied_at = datetime.now(timezone.utc).isoformat() if status == "applied" else None

    with _connect_jobs() as conn:
        if applied_at:
            cur = conn.execute(
                """UPDATE applications
                   SET status = ?, confirmation_id = ?, notes = ?, applied_at = ?
                   WHERE id = ?""",
                (status, confirmation_id, notes, applied_at, app_id),
            )
        else:
            cur = conn.execute(
                "UPDATE applications SET status = ?, confirmation_id = ?, notes = ? WHERE id = ?",
                (status, confirmation_id, notes, app_id),
            )
        conn.commit()
    return cur.rowcount > 0


def count_today_applications(buyer_id: int) -> int:
    """Count how many applications a buyer has made today (UTC)."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    with _connect_jobs() as conn:
        row = conn.execute(
            """SELECT COUNT(*) FROM applications
               WHERE buyer_id = ? AND status = 'applied'
               AND applied_at LIKE ?""",
            (buyer_id, f"{today}%"),
        ).fetchone()
    return row[0] if row else 0


def get_application_stats(buyer_id: int | None = None) -> dict:
    """Return application counts grouped by status."""
    try:
        with _connect_jobs() as conn:
            where = ""
            params = []
            if buyer_id is not None:
                where = " WHERE buyer_id = ?"
                params = [buyer_id]
            total    = conn.execute(f"SELECT COUNT(*) FROM applications{where}", params).fetchone()[0]
            applied  = conn.execute(f"SELECT COUNT(*) FROM applications{where} AND status='applied'" if where else "SELECT COUNT(*) FROM applications WHERE status='applied'", params).fetchone()[0]
            failed   = conn.execute(f"SELECT COUNT(*) FROM applications{where} AND status='failed'" if where else "SELECT COUNT(*) FROM applications WHERE status='failed'", params).fetchone()[0]
            pending  = conn.execute(f"SELECT COUNT(*) FROM applications{where} AND status='pending'" if where else "SELECT COUNT(*) FROM applications WHERE status='pending'", params).fetchone()[0]
        return {"total": total, "applied": applied, "failed": failed, "pending": pending}
    except Exception:
        return {"total": 0, "applied": 0, "failed": 0, "pending": 0}


# ── Submission Logs CRUD ───────────────────────────────────────────────────────

def add_submission_log(
    application_id: int,
    step_name: str,
    screenshot_path: str = "",
    dom_snapshot: str = "",
    page_url: str = "",
) -> int:
    """Add a log entry for an application step. Returns the log ID."""
    timestamp = datetime.now(timezone.utc).isoformat()
    with _connect_jobs() as conn:
        cur = conn.execute(
            """INSERT INTO submission_logs
                (application_id, step_name, screenshot_path, dom_snapshot, page_url, timestamp)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (application_id, step_name, screenshot_path, dom_snapshot, page_url, timestamp),
        )
        conn.commit()
    return cur.lastrowid


def get_submission_logs(application_id: int) -> list[dict]:
    """Return all log entries for a given application."""
    with _connect_jobs() as conn:
        rows = conn.execute(
            "SELECT * FROM submission_logs WHERE application_id = ? ORDER BY timestamp ASC",
            (application_id,),
        ).fetchall()
    return [_row_to_dict(r) for r in rows]


def get_all_submission_logs() -> list[dict]:
    """Return all submission logs."""
    with _connect_jobs() as conn:
        rows = conn.execute(
            "SELECT * FROM submission_logs ORDER BY timestamp DESC"
        ).fetchall()
    return [_row_to_dict(r) for r in rows]


# ── Failure Queue CRUD ─────────────────────────────────────────────────────────

def add_to_failure_queue(
    application_id: int,
    apply_url: str,
    failure_reason: str,
    failure_type: str,
    buyer_id: int,
    post_title: str = "",
    company: str = "",
) -> int:
    """Add a failed application to the human follow-through queue. Returns queue ID."""
    valid_types = {"captcha", "auth_required", "unsupported_ats", "form_error", "network", "unknown"}
    if failure_type not in valid_types:
        failure_type = "unknown"
    created_at = datetime.now(timezone.utc).isoformat()
    with _connect_jobs() as conn:
        cur = conn.execute(
            """INSERT INTO failure_queue
                (application_id, apply_url, failure_reason, failure_type,
                 buyer_id, post_title, company, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (application_id, apply_url, failure_reason, failure_type,
             buyer_id, post_title, company, created_at),
        )
        conn.commit()
    return cur.lastrowid


def get_failure_queue(buyer_id: int | None = None, resolved: bool = False) -> list[dict]:
    """Return failure queue entries, optionally filtered by buyer."""
    query = "SELECT * FROM failure_queue WHERE resolved = ?"
    params: list = [1 if resolved else 0]
    if buyer_id is not None:
        query += " AND buyer_id = ?"
        params.append(buyer_id)
    query += " ORDER BY created_at DESC"
    with _connect_jobs() as conn:
        rows = conn.execute(query, params).fetchall()
    return [_row_to_dict(r) for r in rows]


def resolve_failure(queue_id: int) -> bool:
    """Mark a failure queue entry as resolved."""
    resolved_at = datetime.now(timezone.utc).isoformat()
    with _connect_jobs() as conn:
        cur = conn.execute(
            "UPDATE failure_queue SET resolved = 1, resolved_at = ? WHERE id = ?",
            (resolved_at, queue_id),
        )
        conn.commit()
    return cur.rowcount > 0


# ── Portal Profiles CRUD ──────────────────────────────────────────────────────

def get_portal_profile(hostname: str) -> dict | None:
    """Look up a portal profile by hostname."""
    with _connect_jobs() as conn:
        row = conn.execute(
            "SELECT * FROM portal_profiles WHERE hostname = ?", (hostname,)
        ).fetchone()
    return _row_to_dict(row) if row else None


def get_all_portal_profiles() -> list[dict]:
    """Return all known portal profiles."""
    with _connect_jobs() as conn:
        rows = conn.execute(
            "SELECT * FROM portal_profiles ORDER BY success_count DESC"
        ).fetchall()
    return [_row_to_dict(r) for r in rows]


def upsert_portal_profile(
    hostname: str,
    ats_type: str,
    login_required: bool = False,
    resume_upload: str = "pdf",
    cover_letter: str = "optional",
    steps_json: str = "[]",
    known_quirks: str = "",
) -> dict:
    """Create or update a portal profile. Returns the profile dict."""
    now = datetime.now(timezone.utc).isoformat()
    with _connect_jobs() as conn:
        existing = conn.execute(
            "SELECT id FROM portal_profiles WHERE hostname = ?", (hostname,)
        ).fetchone()
        if existing:
            conn.execute(
                """UPDATE portal_profiles
                   SET ats_type = ?, login_required = ?, resume_upload = ?,
                       cover_letter = ?, steps_json = ?, known_quirks = ?,
                       last_used_at = ?
                   WHERE hostname = ?""",
                (ats_type, int(login_required), resume_upload, cover_letter,
                 steps_json, known_quirks, now, hostname),
            )
        else:
            conn.execute(
                """INSERT INTO portal_profiles
                    (hostname, ats_type, login_required, resume_upload, cover_letter,
                     steps_json, known_quirks, last_used_at, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (hostname, ats_type, int(login_required), resume_upload, cover_letter,
                 steps_json, known_quirks, now, now),
            )
        conn.commit()
    return get_portal_profile(hostname)


def increment_portal_success(hostname: str) -> None:
    """Increment the success count for a portal profile."""
    now = datetime.now(timezone.utc).isoformat()
    with _connect_jobs() as conn:
        conn.execute(
            "UPDATE portal_profiles SET success_count = success_count + 1, last_used_at = ? WHERE hostname = ?",
            (now, hostname),
        )
        conn.commit()


def increment_portal_failure(hostname: str) -> None:
    """Increment the failure count for a portal profile."""
    now = datetime.now(timezone.utc).isoformat()
    with _connect_jobs() as conn:
        conn.execute(
            "UPDATE portal_profiles SET fail_count = fail_count + 1, last_used_at = ? WHERE hostname = ?",
            (now, hostname),
        )
        conn.commit()


# ══════════════════════════════════════════════════════════════════════════════
#  ADMIN SYSTEM — Authentication, Verification Workflow, Audit, Analytics
# ══════════════════════════════════════════════════════════════════════════════


# ── Admin Users: CRUD ──────────────────────────────────────────────────────────

def create_admin(email: str, password: str, role: str = "ADMIN", name: str = "", permissions: str = "") -> dict:
    """Create a new admin user. Returns the admin dict.
    Roles: USER, ADMIN, SUPER_ADMIN
    permissions: comma-separated list of allowed sections (dashboard,queue,users,database,audit)"""
    valid_roles = {"USER", "ADMIN", "SUPER_ADMIN"}
    if role not in valid_roles:
        raise ValueError(f"Invalid role '{role}'. Must be one of: {valid_roles}")
    now = datetime.now(timezone.utc).isoformat()
    with _connect() as conn:
        cur = conn.execute(
            """INSERT INTO admin_users (email, password_hash, role, name, permissions, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (email.strip().lower(), _sha256(password), role, name.strip(), permissions.strip(), now, now),
        )
        conn.commit()
        row_id = cur.lastrowid
    return get_admin_by_id(row_id)


def verify_admin_login(email: str, password: str) -> dict | None:
    """Verify admin credentials. Returns admin dict on success, None on failure."""
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM admin_users WHERE email = ? AND password_hash = ?",
            (email.strip().lower(), _sha256(password)),
        ).fetchone()
        if row:
            now = datetime.now(timezone.utc).isoformat()
            conn.execute(
                "UPDATE admin_users SET last_login_at = ?, updated_at = ? WHERE id = ?",
                (now, now, row["id"]),
            )
            conn.commit()
            return _row_to_dict(row)
    return None


def get_admin_by_id(admin_id: int) -> dict | None:
    with _connect() as conn:
        row = conn.execute("SELECT * FROM admin_users WHERE id = ?", (admin_id,)).fetchone()
    return _row_to_dict(row) if row else None


def get_all_admins() -> list[dict]:
    with _connect() as conn:
        rows = conn.execute("SELECT * FROM admin_users ORDER BY created_at ASC").fetchall()
    return [_row_to_dict(r) for r in rows]


# ── Audit Logging ─────────────────────────────────────────────────────────────

def create_audit_log(
    admin_id: int,
    admin_email: str,
    action: str,
    target_user_id: int | None = None,
    previous_value: str = "",
    new_value: str = "",
    reason: str = "",
    ip_address: str = "",
) -> int:
    """Record an admin action. Returns audit log ID."""
    timestamp = datetime.now(timezone.utc).isoformat()
    with _connect() as conn:
        cur = conn.execute(
            """INSERT INTO audit_logs
               (admin_id, admin_email, action, target_user_id,
                previous_value, new_value, reason, timestamp, ip_address)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (admin_id, admin_email, action, target_user_id,
             previous_value, new_value, reason, timestamp, ip_address),
        )
        conn.commit()
    return cur.lastrowid


def get_audit_logs(
    page: int = 1,
    per_page: int = 50,
    search: str = "",
    action_filter: str = "",
    date_from: str = "",
    date_to: str = "",
    admin_id_filter: int | None = None,
) -> dict:
    """Return paginated audit logs with total count.
    Returns: { 'logs': [...], 'total': N, 'page': P, 'per_page': PP }"""
    with _connect() as conn:
        conditions = []
        params = []

        if search:
            conditions.append(
                "(admin_email LIKE ? OR reason LIKE ? OR action LIKE ?)"
            )
            s = f"%{search}%"
            params.extend([s, s, s])

        if action_filter:
            conditions.append("action = ?")
            params.append(action_filter)

        if date_from:
            conditions.append("timestamp >= ?")
            params.append(date_from)

        if date_to:
            conditions.append("timestamp <= ?")
            params.append(date_to + "T23:59:59")

        if admin_id_filter is not None:
            conditions.append("admin_id = ?")
            params.append(admin_id_filter)

        where = " WHERE " + " AND ".join(conditions) if conditions else ""

        total = conn.execute(
            f"SELECT COUNT(*) FROM audit_logs{where}", params
        ).fetchone()[0]

        offset = (page - 1) * per_page
        rows = conn.execute(
            f"""SELECT a.*, u.name as target_user_name, u.email as target_user_email
                FROM audit_logs a
                LEFT JOIN users u ON u.id = a.target_user_id
                {where}
                ORDER BY a.timestamp DESC
                LIMIT ? OFFSET ?""",
            params + [per_page, offset],
        ).fetchall()

    return {
        "logs": [_row_to_dict(r) for r in rows],
        "total": total,
        "page": page,
        "per_page": per_page,
    }


# ── Verification Requests ────────────────────────────────────────────────────

def create_verification_request(
    user_id: int,
    linkedin_url: str = "",
    parsed_data: str = "",
    raw_evidence: str = "",
) -> dict | None:
    """Create a verification request for a user. Returns the request dict."""
    now = datetime.now(timezone.utc).isoformat()
    with _connect() as conn:
        try:
            conn.execute(
                """INSERT INTO verification_requests
                   (user_id, linkedin_url, status, parsed_data, raw_evidence, created_at, updated_at)
                   VALUES (?, ?, 'PENDING', ?, ?, ?, ?)""",
                (user_id, linkedin_url, parsed_data, raw_evidence, now, now),
            )
            conn.commit()
        except Exception:
            pass  # already exists (UNIQUE constraint on user_id)
    return get_verification_by_user(user_id)


def get_verification(verif_id: int) -> dict | None:
    """Get a single verification request with joined user data."""
    with _connect() as conn:
        row = conn.execute(
            """SELECT v.*, u.name as user_name, u.last_name as user_last_name,
                      u.email as user_email, u.avatar as user_avatar,
                      u.submitted_at as user_signup_date, u.mobile_number,
                      u.password_hash,
                      a.name as reviewer_name, a.email as reviewer_email
               FROM verification_requests v
               JOIN users u ON u.id = v.user_id
               LEFT JOIN admin_users a ON a.id = v.reviewed_by
               WHERE v.id = ?""",
            (verif_id,),
        ).fetchone()
    return _row_to_dict(row) if row else None


def get_verification_by_user(user_id: int) -> dict | None:
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM verification_requests WHERE user_id = ?",
            (user_id,),
        ).fetchone()
    return _row_to_dict(row) if row else None


def get_verifications(
    status: str = "",
    page: int = 1,
    per_page: int = 50,
    search: str = "",
) -> dict:
    """Return paginated verification requests with user data.
    Returns: { 'verifications': [...], 'total': N, 'page': P, 'per_page': PP }"""
    with _connect() as conn:
        conditions = []
        params = []

        if status:
            conditions.append("v.status = ?")
            params.append(status.upper())

        if search:
            conditions.append(
                "(u.name LIKE ? OR u.last_name LIKE ? OR u.email LIKE ? OR v.linkedin_url LIKE ?)"
            )
            s = f"%{search}%"
            params.extend([s, s, s, s])

        where = " WHERE " + " AND ".join(conditions) if conditions else ""

        total = conn.execute(
            f"""SELECT COUNT(*) FROM verification_requests v
                JOIN users u ON u.id = v.user_id
                {where}""",
            params,
        ).fetchone()[0]

        offset = (page - 1) * per_page
        rows = conn.execute(
            f"""SELECT v.*, u.name as user_name, u.last_name as user_last_name,
                       u.email as user_email, u.avatar as user_avatar,
                       u.submitted_at as user_signup_date,
                       a.name as reviewer_name, a.email as reviewer_email
                FROM verification_requests v
                JOIN users u ON u.id = v.user_id
                LEFT JOIN admin_users a ON a.id = v.reviewed_by
                {where}
                ORDER BY v.created_at DESC
                LIMIT ? OFFSET ?""",
            params + [per_page, offset],
        ).fetchall()

    return {
        "verifications": [_row_to_dict(r) for r in rows],
        "total": total,
        "page": page,
        "per_page": per_page,
    }


def approve_verification(verif_id: int, admin_id: int) -> bool:
    """Approve a verification request. Also updates the user's status."""
    now = datetime.now(timezone.utc).isoformat()
    with _connect() as conn:
        verif = conn.execute(
            "SELECT * FROM verification_requests WHERE id = ?", (verif_id,)
        ).fetchone()
        if not verif:
            return False

        conn.execute(
            """UPDATE verification_requests
               SET status = 'APPROVED', reviewed_by = ?, reviewed_at = ?, updated_at = ?
               WHERE id = ?""",
            (admin_id, now, now, verif_id),
        )
        conn.execute(
            """UPDATE users
               SET status = 'approved', reject_reason = '',
                   reviewed_by = ?, reviewed_at = ?
               WHERE id = ?""",
            (admin_id, now, verif["user_id"]),
        )
        conn.commit()
    return True


def reject_verification(verif_id: int, admin_id: int, reason: str) -> bool:
    """Reject a verification request. Also updates the user's status."""
    now = datetime.now(timezone.utc).isoformat()
    with _connect() as conn:
        verif = conn.execute(
            "SELECT * FROM verification_requests WHERE id = ?", (verif_id,)
        ).fetchone()
        if not verif:
            return False

        conn.execute(
            """UPDATE verification_requests
               SET status = 'REJECTED', reviewed_by = ?, reviewed_at = ?,
                   rejection_reason = ?, updated_at = ?
               WHERE id = ?""",
            (admin_id, now, reason, now, verif_id),
        )
        conn.execute(
            """UPDATE users
               SET status = 'rejected', reject_reason = ?,
                   reviewed_by = ?, reviewed_at = ?
               WHERE id = ?""",
            (reason, admin_id, now, verif["user_id"]),
        )
        conn.commit()
    return True


# ── Admin Dashboard Stats ────────────────────────────────────────────────────

def get_admin_dashboard_stats(date_from: str = "", date_to: str = "") -> dict:
    """Return aggregate counts for the admin dashboard."""
    with _connect() as conn:
        date_conditions = ""
        params = []

        if date_from:
            date_conditions += " AND submitted_at >= ?"
            params.append(date_from)
        if date_to:
            date_conditions += " AND submitted_at <= ?"
            params.append(date_to + "T23:59:59")

        base = f"SELECT COUNT(*) FROM users WHERE 1=1{date_conditions}"

        total    = conn.execute(base, params).fetchone()[0]
        pending  = conn.execute(
            base.replace("1=1", "status='pending'"), params
        ).fetchone()[0]
        approved = conn.execute(
            base.replace("1=1", "status='approved'"), params
        ).fetchone()[0]
        rejected = conn.execute(
            base.replace("1=1", "status='rejected'"), params
        ).fetchone()[0]

        # Subscriber counts from agent_buyers
        buyer_conditions = date_conditions.replace("submitted_at", "created_at")
        buyer_params = params[:]  # same param values, just different column name
        active_subs = conn.execute(
            f"SELECT COUNT(*) FROM agent_buyers WHERE subscription_status='active'{buyer_conditions}",
            buyer_params,
        ).fetchone()[0]
        inactive_subs = conn.execute(
            f"SELECT COUNT(*) FROM agent_buyers WHERE subscription_status='inactive'{buyer_conditions}",
            buyer_params,
        ).fetchone()[0]
        total_buyers = conn.execute(
            f"SELECT COUNT(*) FROM agent_buyers WHERE 1=1{buyer_conditions}",
            buyer_params,
        ).fetchone()[0]

    # Verification pass rate
    pass_rate = 0.0
    if (approved + rejected) > 0:
        pass_rate = round(approved / (approved + rejected) * 100, 1)

    # Subscription conversion rate
    conversion_rate = 0.0
    if total > 0:
        conversion_rate = round(total_buyers / total * 100, 1)

    return {
        "total_users": total,
        "verified_users": approved,
        "pending_users": pending,
        "rejected_users": rejected,
        "active_subscribers": active_subs,
        "inactive_subscribers": inactive_subs,
        "total_subscribers": total_buyers,
        "verification_pass_rate": pass_rate,
        "subscription_conversion_rate": conversion_rate,
    }


def get_daily_signups(days: int = 30, date_from: str = "", date_to: str = "") -> list[dict]:
    """Return daily signup counts for chart data.
    Returns: [{ 'date': '2026-05-01', 'count': 12 }, ...]"""
    with _connect() as conn:
        if date_from and date_to:
            rows = conn.execute(
                """SELECT DATE(submitted_at) as date, COUNT(*) as count
                   FROM users
                   WHERE submitted_at >= ? AND submitted_at <= ?
                   GROUP BY DATE(submitted_at)
                   ORDER BY date ASC""",
                (date_from, date_to + "T23:59:59"),
            ).fetchall()
        else:
            rows = conn.execute(
                """SELECT DATE(submitted_at) as date, COUNT(*) as count
                   FROM users
                   WHERE submitted_at >= DATE('now', ?)
                   GROUP BY DATE(submitted_at)
                   ORDER BY date ASC""",
                (f"-{days} days",),
            ).fetchall()
    return [{"date": r["date"], "count": r["count"]} for r in rows if r["date"]]


# ── User Directory (Paginated) ────────────────────────────────────────────────

def get_users_paginated(
    page: int = 1,
    per_page: int = 20,
    search: str = "",
    status_filter: str = "",
    subscription_filter: str = "",
    sort_by: str = "submitted_at",
    sort_dir: str = "DESC",
) -> dict:
    """Return paginated user directory with filters.
    Returns: { 'users': [...], 'total': N, 'page': P, 'per_page': PP }"""
    valid_sort = {"submitted_at", "last_login_at", "status", "name", "email"}
    if sort_by not in valid_sort:
        sort_by = "submitted_at"
    if sort_dir.upper() not in {"ASC", "DESC"}:
        sort_dir = "DESC"

    with _connect() as conn:
        conditions = []
        params = []

        if search:
            conditions.append(
                "(u.name LIKE ? OR u.last_name LIKE ? OR u.email LIKE ? OR u.linkedin_url LIKE ?)"
            )
            s = f"%{search}%"
            params.extend([s, s, s, s])

        if status_filter:
            conditions.append("u.status = ?")
            params.append(status_filter)

        if subscription_filter == "active":
            conditions.append(
                "EXISTS (SELECT 1 FROM agent_buyers ab WHERE ab.email = u.email AND ab.subscription_status = 'active')"
            )
        elif subscription_filter == "inactive":
            conditions.append(
                "NOT EXISTS (SELECT 1 FROM agent_buyers ab WHERE ab.email = u.email AND ab.subscription_status = 'active')"
            )

        where = " WHERE " + " AND ".join(conditions) if conditions else ""

        total = conn.execute(
            f"SELECT COUNT(*) FROM users u{where}", params
        ).fetchone()[0]

        offset = (page - 1) * per_page
        rows = conn.execute(
            f"""SELECT u.*,
                       (SELECT ab.subscription_status FROM agent_buyers ab
                        WHERE ab.email = u.email
                        ORDER BY ab.created_at DESC LIMIT 1) as subscription_status
                FROM users u
                {where}
                ORDER BY u.{sort_by} {sort_dir}
                LIMIT ? OFFSET ?""",
            params + [per_page, offset],
        ).fetchall()

    return {
        "users": [_row_to_dict(r) for r in rows],
        "total": total,
        "page": page,
        "per_page": per_page,
    }


def get_user_detail(user_id: int) -> dict | None:
    """Return full user detail including activity and verification data."""
    with _connect() as conn:
        user = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        if not user:
            return None

        user_dict = _row_to_dict(user)

        # Get verification request
        verif = conn.execute(
            """SELECT v.*, a.name as reviewer_name, a.email as reviewer_email
               FROM verification_requests v
               LEFT JOIN admin_users a ON a.id = v.reviewed_by
               WHERE v.user_id = ?""",
            (user_id,),
        ).fetchone()
        user_dict["verification"] = _row_to_dict(verif) if verif else None

        # Get linked agent buyer
        buyer = conn.execute(
            "SELECT * FROM agent_buyers WHERE email = ? ORDER BY created_at DESC LIMIT 1",
            (user_dict["email"],),
        ).fetchone()
        user_dict["agent_buyer"] = _row_to_dict(buyer) if buyer else None

    # Get application count from jobs.db
    try:
        with _connect_jobs() as conn:
            if buyer:
                app_count = conn.execute(
                    "SELECT COUNT(*) FROM applications WHERE buyer_id = ?",
                    (buyer["id"],),
                ).fetchone()[0]
                user_dict["total_applications"] = app_count
            else:
                user_dict["total_applications"] = 0
    except Exception:
        user_dict["total_applications"] = 0

    return user_dict


def update_user_login(user_id: int) -> None:
    """Track a user login event."""
    now = datetime.now(timezone.utc).isoformat()
    with _connect() as conn:
        conn.execute(
            """UPDATE users
               SET last_login_at = ?, login_count = COALESCE(login_count, 0) + 1,
                   last_activity_at = ?
               WHERE id = ?""",
            (now, now, user_id),
        )
        conn.commit()


def update_user_activity(user_id: int) -> None:
    """Track a user activity event (agent usage)."""
    now = datetime.now(timezone.utc).isoformat()
    with _connect() as conn:
        conn.execute(
            """UPDATE users
               SET agent_usage_count = COALESCE(agent_usage_count, 0) + 1,
                   last_activity_at = ?
               WHERE id = ?""",
            (now, user_id),
        )
        conn.commit()


# ── Payments (Razorpay) ────────────────────────────────────────────────────────

def create_payment_record(
    razorpay_order_id: str,
    amount_paise: int,
    currency: str = "INR",
    receipt: str = "",
    buyer_id: int | None = None,
) -> dict:
    """Insert a new payment record after creating a Razorpay order."""
    created_at = datetime.now(timezone.utc).isoformat()
    with _connect_jobs() as conn:
        cur = conn.execute(
            """INSERT INTO payments
               (razorpay_order_id, amount_paise, currency, receipt, buyer_id, status, created_at)
               VALUES (?, ?, ?, ?, ?, 'created', ?)""",
            (razorpay_order_id, amount_paise, currency, receipt, buyer_id, created_at),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM payments WHERE id = ?", (cur.lastrowid,)).fetchone()
    return _row_to_dict(row) if row else {}


def verify_payment_record(
    razorpay_order_id: str,
    razorpay_payment_id: str,
    razorpay_signature: str,
) -> bool:
    """Mark a payment as verified (paid) after signature check."""
    now = datetime.now(timezone.utc).isoformat()
    with _connect_jobs() as conn:
        cur = conn.execute(
            """UPDATE payments
               SET razorpay_payment_id = ?,
                   razorpay_signature  = ?,
                   status              = 'paid',
                   verified_at         = ?
               WHERE razorpay_order_id = ?""",
            (razorpay_payment_id, razorpay_signature, now, razorpay_order_id),
        )
        conn.commit()
    return cur.rowcount > 0


def fail_payment_record(razorpay_order_id: str, reason: str = "") -> bool:
    """Mark a payment as failed."""
    with _connect_jobs() as conn:
        cur = conn.execute(
            "UPDATE payments SET status = 'failed', receipt = receipt || ? WHERE razorpay_order_id = ?",
            (f" | fail: {reason}" if reason else "", razorpay_order_id),
        )
        conn.commit()
    return cur.rowcount > 0


def get_payment(razorpay_order_id: str) -> dict | None:
    """Look up a payment by Razorpay order ID."""
    with _connect_jobs() as conn:
        row = conn.execute(
            "SELECT * FROM payments WHERE razorpay_order_id = ?", (razorpay_order_id,)
        ).fetchone()
    return _row_to_dict(row) if row else None


def get_all_payments(status: str | None = None) -> list[dict]:
    """Return all payment records, optionally filtered by status."""
    with _connect_jobs() as conn:
        if status:
            rows = conn.execute(
                "SELECT * FROM payments WHERE status = ? ORDER BY created_at DESC",
                (status,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM payments ORDER BY created_at DESC"
            ).fetchall()
    return [_row_to_dict(r) for r in rows]


# ── Portal Credentials (stored inside agent_buyers) ───────────────────────────

def get_portal_credentials(buyer_id: int) -> list[dict]:
    """Get all portal credentials for a given buyer.
    Returns list of dicts with: portal_hostname, email, password
    """
    with _connect() as conn:
        row = conn.execute("SELECT * FROM agent_buyers WHERE id = ?", (buyer_id,)).fetchone()
        if not row:
            return []
        buyer = _row_to_dict(row)
        
    email = buyer.get("email", "")
    creds = []
    
    # Check standard columns
    if buyer.get("workday_password"):
        creds.append({"portal_hostname": "workday.com", "email": email, "password": buyer["workday_password"]})
    if buyer.get("lever_password"):
        creds.append({"portal_hostname": "lever.co", "email": email, "password": buyer["lever_password"]})
    if buyer.get("greenhouse_password"):
        creds.append({"portal_hostname": "greenhouse.io", "email": email, "password": buyer["greenhouse_password"]})
    if buyer.get("ashby_password"):
        creds.append({"portal_hostname": "ashbyhq.com", "email": email, "password": buyer["ashby_password"]})
    if buyer.get("smartrecruiters_password"):
        creds.append({"portal_hostname": "smartrecruiters.com", "email": email, "password": buyer["smartrecruiters_password"]})
        
    # Check custom passwords (stored in other_passwords JSON column)
    other_str = buyer.get("other_passwords") or "{}"
    import json
    try:
        other_dict = json.loads(other_str)
        for host, pwd in other_dict.items():
            if pwd:
                creds.append({"portal_hostname": host, "email": email, "password": pwd})
    except Exception:
        pass
        
    return creds


def get_or_create_portal_credential(buyer_id: int, portal_hostname: str, firstname: str, email: str, required_length: int = 8) -> dict:
    """Return existing portal credential, or generate and save a new one in the agent_buyers table."""
    # Find which column matches this host/ats
    ats_type = ""
    host_lower = portal_hostname.lower()
    if "workday" in host_lower:
        ats_type = "workday"
    elif "lever" in host_lower:
        ats_type = "lever"
    elif "greenhouse" in host_lower:
        ats_type = "greenhouse"
    elif "ashby" in host_lower:
        ats_type = "ashby"
    elif "smartrecruiters" in host_lower:
        ats_type = "smartrecruiters"
        
    # Check if we already have it
    with _connect() as conn:
        row = conn.execute("SELECT * FROM agent_buyers WHERE id = ?", (buyer_id,)).fetchone()
        if not row:
            raise ValueError(f"Agent buyer with ID {buyer_id} not found")
        buyer = _row_to_dict(row)
        
    # Check if password already exists
    password = ""
    if ats_type == "workday":
        password = buyer.get("workday_password")
    elif ats_type == "lever":
        password = buyer.get("lever_password")
    elif ats_type == "greenhouse":
        password = buyer.get("greenhouse_password")
    elif ats_type == "ashby":
        password = buyer.get("ashby_password")
    elif ats_type == "smartrecruiters":
        password = buyer.get("smartrecruiters_password")
    else:
        # Check in other_passwords JSON
        import json
        try:
            other_dict = json.loads(buyer.get("other_passwords") or "{}")
            password = other_dict.get(portal_hostname, "")
        except Exception:
            pass
            
    if password:
        return {"portal_hostname": portal_hostname, "email": email, "password": password}
        
    # Generate new password
    # keep the password format as "{Firstname}@123$" where there is lenn amount of characters required
    # and when there is more than that fill with randomnumbers and end with $
    first_name = firstname.strip()
    if not first_name:
        first_name = "User"
    first_name = first_name[0].upper() + first_name[1:]
    
    base = f"{first_name}@123$"
    if len(base) >= required_length:
        password = base
    else:
        import random
        needed = required_length - len(base)
        random_digits = "".join(str(random.randint(0, 9)) for _ in range(needed))
        password = f"{first_name}@123{random_digits}$"
        
    # Save the generated password
    with _connect() as conn:
        if ats_type == "workday":
            conn.execute("UPDATE agent_buyers SET workday_password = ? WHERE id = ?", (password, buyer_id))
        elif ats_type == "lever":
            conn.execute("UPDATE agent_buyers SET lever_password = ? WHERE id = ?", (password, buyer_id))
        elif ats_type == "greenhouse":
            conn.execute("UPDATE agent_buyers SET greenhouse_password = ? WHERE id = ?", (password, buyer_id))
        elif ats_type == "ashby":
            conn.execute("UPDATE agent_buyers SET ashby_password = ? WHERE id = ?", (password, buyer_id))
        elif ats_type == "smartrecruiters":
            conn.execute("UPDATE agent_buyers SET smartrecruiters_password = ? WHERE id = ?", (password, buyer_id))
        else:
            import json
            try:
                other_dict = json.loads(buyer.get("other_passwords") or "{}")
            except Exception:
                other_dict = {}
            other_dict[portal_hostname] = password
            conn.execute("UPDATE agent_buyers SET other_passwords = ? WHERE id = ?", (json.dumps(other_dict), buyer_id))
        conn.commit()
        
    return {"portal_hostname": portal_hostname, "email": email, "password": password}


def save_google_connection(user_id: int, google_email: str, access_token: str, refresh_token: str, token_expiry: str, scopes: str):
    connected_at = datetime.now(timezone.utc).isoformat()
    with _connect() as conn:
        conn.execute(
            """INSERT OR REPLACE INTO google_connections 
               (user_id, google_email, access_token, refresh_token, token_expiry, scopes, connected_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (user_id, google_email, access_token, refresh_token, token_expiry, scopes, connected_at)
        )
        conn.commit()


def get_google_connection(user_id: int) -> dict | None:
    with _connect() as conn:
        row = conn.execute("SELECT * FROM google_connections WHERE user_id = ?", (user_id,)).fetchone()
        return _row_to_dict(row) if row else None


def delete_google_connection(user_id: int):
    with _connect() as conn:
        conn.execute("DELETE FROM google_connections WHERE user_id = ?", (user_id,))
        conn.commit()


# ── Master CV helpers ──────────────────────────────────────────────────────────

def get_master_cv(user_id: int) -> dict | None:
    """Return the master CV data dict for a user, or None if not set."""
    with _connect() as conn:
        row = conn.execute(
            "SELECT cv_data, updated_at FROM master_cv WHERE user_id = ?",
            (user_id,),
        ).fetchone()
        if not row:
            return None
        try:
            return json.loads(row["cv_data"])
        except (json.JSONDecodeError, TypeError):
            return None


def save_master_cv(user_id: int, cv_data: dict) -> bool:
    """Insert or replace the master CV for a user. Returns True on success."""
    now = datetime.now(timezone.utc).isoformat()
    data_json = json.dumps(cv_data, ensure_ascii=False)
    with _connect() as conn:
        conn.execute(
            """INSERT INTO master_cv (user_id, cv_data, updated_at)
               VALUES (?, ?, ?)
               ON CONFLICT(user_id) DO UPDATE SET cv_data = excluded.cv_data, updated_at = excluded.updated_at""",
            (user_id, data_json, now),
        )
        conn.commit()
    return True
