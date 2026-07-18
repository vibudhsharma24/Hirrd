"""
database.py
-----------
SQLite database layer for IITIIMJobAssistant.
All DB files live in the project root (one directory up from core/).
"""

import pymysql
import pymysql.cursors
import hashlib
import os
import re
import json
from datetime import datetime, timezone
from urllib.parse import urlparse

# ── Wrapper classes to emulate SQLite DB-API and Row factory in PyMySQL ────────
class MySQLCursorWrapper:
    def __init__(self, cursor):
        self.cursor = cursor

    def execute(self, sql, params=None):
        # Translate SQLite ? to MySQL %s, ignoring ? inside string literals
        pattern = r"('[^']*'|\"[^\"]*\"|\?[?]*)"
        def repl(match):
            token = match.group(0)
            return '%s' if token == '?' else token
        sql = re.sub(pattern, repl, sql)

        # Translate other SQLite-specific keywords
        sql = re.sub(r'(?i)\bINSERT\s+OR\s+IGNORE\b', 'INSERT IGNORE', sql)
        sql = re.sub(r'(?i)\bINSERT\s+OR\s+REPLACE\b', 'REPLACE', sql)
        sql = re.sub(r'(?i)\bCREATE\s+INDEX\s+IF\s+NOT\s+EXISTS\b', 'CREATE INDEX', sql)
        sql = re.sub(r'(?i)\bINTEGER\s+PRIMARY\s+KEY\s+AUTOINCREMENT\b', 'INT AUTO_INCREMENT PRIMARY KEY', sql)

        self.cursor.execute(sql, params)
        return self

    def fetchone(self):
        row = self.cursor.fetchone()
        if row is None:
            return None
        return MySQLRowWrapper(row)

    def fetchall(self):
        rows = self.cursor.fetchall()
        return [MySQLRowWrapper(r) for r in rows]

    @property
    def lastrowid(self):
        return self.cursor.lastrowid

    @property
    def rowcount(self):
        return self.cursor.rowcount

    def __iter__(self):
        return self

    def __next__(self):
        row = self.cursor.fetchone()
        if row is None:
            raise StopIteration
        return MySQLRowWrapper(row)


class MySQLRowWrapper(dict):
    """Emulate sqlite3.Row: access columns by name (dict keys) and index (0, 1, 2, ...)."""
    def __init__(self, data):
        super().__init__(data)
        self._keys = list(data.keys())
        self._values = list(data.values())

    def __getitem__(self, key):
        if isinstance(key, int):
            return self._values[key]
        return super().__getitem__(key)

    def keys(self):
        return self._keys


class MySQLConnectionWrapper:
    def __init__(self, conn):
        self.conn = conn

    def cursor(self):
        return MySQLCursorWrapper(self.conn.cursor())

    def execute(self, sql, params=None):
        cursor = self.cursor()
        cursor.execute(sql, params)
        return cursor

    def commit(self):
        self.conn.commit()

    def rollback(self):
        self.conn.rollback()

    def close(self):
        try:
            self.conn.close()
        except Exception:
            pass

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type:
            self.rollback()
        else:
            self.commit()
        self.close()


# ── Paths — everything is relative to the project root (parent of core/) ──────
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DB_PATH          = os.path.join(PROJECT_ROOT, "users.db")
JOBS_DB_PATH     = os.path.join(PROJECT_ROOT, "jobs.db")
RESUMES_DIR      = os.path.join(PROJECT_ROOT, "resumes")
SCREENSHOTS_DIR  = os.path.join(PROJECT_ROOT, "screenshots")
GENERATED_RESUMES_DIR = os.path.join(PROJECT_ROOT, "resumes", "generated")


# ── Connection helpers ─────────────────────────────────────────────────────────
def _connect():
    """Connection to RDS MySQL database."""
    conn = pymysql.connect(
        host=os.getenv("DB_HOST"),
        port=int(os.getenv("DB_PORT", 3306)),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
        database=os.getenv("DB_NAME"),
        charset='utf8mb4',
        cursorclass=pymysql.cursors.DictCursor,
        autocommit=True
    )
    return MySQLConnectionWrapper(conn)


def _connect_jobs():
    """Connection to RDS MySQL database (sharing same RDS instance)."""
    return _connect()


def get_db_connection(db_name: str = "users"):
    """Public helper to get a DB connection by name.
    Args:
        db_name: 'users' for users.db, 'jobs' for jobs.db
    Returns:
        MySQLConnectionWrapper connection.
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
                id            INT AUTO_INCREMENT PRIMARY KEY,
                name          VARCHAR(255) NOT NULL DEFAULT '',
                last_name     VARCHAR(255) NOT NULL DEFAULT '',
                email         VARCHAR(255) NOT NULL UNIQUE,
                password_hash VARCHAR(255) NOT NULL,
                linkedin_url  VARCHAR(512) DEFAULT '',
                mobile_number VARCHAR(50)  DEFAULT '',
                avatar        VARCHAR(10)  DEFAULT '',
                status        VARCHAR(50)  DEFAULT 'pending',
                reject_reason TEXT,
                submitted_at  VARCHAR(100) NOT NULL
            )
        """)

        # Create google_connections table if it doesn't exist
        conn.execute("""
            CREATE TABLE IF NOT EXISTS google_connections (
                id            INT AUTO_INCREMENT PRIMARY KEY,
                user_id       INT NOT NULL UNIQUE,
                google_email  VARCHAR(255) NOT NULL,
                access_token  TEXT    NOT NULL,
                refresh_token TEXT    NOT NULL,
                token_expiry  VARCHAR(100) NOT NULL,
                scopes        TEXT    NOT NULL,
                connected_at  VARCHAR(100) NOT NULL,
                FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
            )
        """)

        # Create agent_buyers table if it doesn't already exist (preserves existing buyers)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS agent_buyers (
                id                     INT AUTO_INCREMENT PRIMARY KEY,
                name                   VARCHAR(255) NOT NULL,
                last_name              VARCHAR(255) NOT NULL,
                email                  VARCHAR(255) NOT NULL,
                resume_path            VARCHAR(512) NOT NULL,
                subscription_status    VARCHAR(50)  NOT NULL DEFAULT 'active',
                subscription_expires_at VARCHAR(100) DEFAULT '',
                daily_apply_limit      INT          NOT NULL DEFAULT 5,
                created_at             VARCHAR(100) NOT NULL
            )
        """)

        # Migrate agent_buyers with password columns
        for col in ["workday_password", "lever_password", "greenhouse_password", "ashby_password", "smartrecruiters_password", "other_passwords"]:
            try:
                conn.execute(f"ALTER TABLE agent_buyers ADD COLUMN {col} VARCHAR(255) DEFAULT ''")
                conn.commit()
            except Exception:
                pass

        conn.execute("""
            CREATE TABLE IF NOT EXISTS jobs (
                id         INT AUTO_INCREMENT PRIMARY KEY,
                title      VARCHAR(255) NOT NULL,
                company    VARCHAR(255) NOT NULL DEFAULT '',
                location   VARCHAR(255) NOT NULL DEFAULT '',
                url        VARCHAR(512) NOT NULL UNIQUE,
                apply_link TEXT    NOT NULL,
                source     VARCHAR(100) NOT NULL DEFAULT 'linkedin',
                keywords   VARCHAR(255) NOT NULL DEFAULT '',
                scraped_at VARCHAR(100) NOT NULL,
                status     VARCHAR(50)  NOT NULL DEFAULT 'new'
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
                id              INT AUTO_INCREMENT PRIMARY KEY,
                buyer_id        INT NOT NULL,
                post_id         INT,
                job_id          INT,
                portal_hostname VARCHAR(255) NOT NULL DEFAULT '',
                ats_type        VARCHAR(100) NOT NULL DEFAULT '',
                status          VARCHAR(50)  NOT NULL DEFAULT 'pending',
                confirmation_id VARCHAR(255) DEFAULT '',
                resume_used     VARCHAR(512) DEFAULT '',
                cover_letter    VARCHAR(512) DEFAULT '',
                applied_at      VARCHAR(100),
                notes           TEXT,
                created_at      VARCHAR(100) NOT NULL
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS submission_logs (
                id              INT AUTO_INCREMENT PRIMARY KEY,
                application_id  INT NOT NULL,
                step_name       VARCHAR(255) NOT NULL,
                screenshot_path VARCHAR(512) DEFAULT '',
                dom_snapshot    TEXT,
                page_url        VARCHAR(512) DEFAULT '',
                timestamp       VARCHAR(100) NOT NULL
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS failure_queue (
                id              INT AUTO_INCREMENT PRIMARY KEY,
                application_id  INT NOT NULL,
                apply_url       VARCHAR(512) NOT NULL,
                failure_reason  VARCHAR(512) NOT NULL,
                failure_type    VARCHAR(100) NOT NULL,
                buyer_id        INT NOT NULL,
                post_title      VARCHAR(255) DEFAULT '',
                company         VARCHAR(255) DEFAULT '',
                resolved        INT DEFAULT 0,
                resolved_at     VARCHAR(100),
                created_at      VARCHAR(100) NOT NULL
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS portal_profiles (
                id              INT AUTO_INCREMENT PRIMARY KEY,
                hostname        VARCHAR(255) UNIQUE NOT NULL,
                ats_type        VARCHAR(100) NOT NULL,
                login_required  INT DEFAULT 0,
                resume_upload   VARCHAR(50) DEFAULT 'pdf',
                cover_letter    VARCHAR(50) DEFAULT 'optional',
                steps_json      TEXT    NOT NULL,
                known_quirks    TEXT,
                success_count   INT DEFAULT 0,
                fail_count      INT DEFAULT 0,
                last_used_at    VARCHAR(100),
                created_at      VARCHAR(100) NOT NULL
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS payments (
                id                  INT AUTO_INCREMENT PRIMARY KEY,
                razorpay_order_id   VARCHAR(255) UNIQUE NOT NULL,
                razorpay_payment_id VARCHAR(255) DEFAULT '',
                razorpay_signature  VARCHAR(255) DEFAULT '',
                amount_paise        INT NOT NULL,
                currency            VARCHAR(10) NOT NULL DEFAULT 'INR',
                receipt             VARCHAR(255) DEFAULT '',
                buyer_id            INT,
                status              VARCHAR(50) NOT NULL DEFAULT 'created',
                verified_at         VARCHAR(100) DEFAULT '',
                created_at          VARCHAR(100) NOT NULL
            )
        """)

        # Migrate payments with user_id and coupon columns
        try:
            conn.execute("ALTER TABLE payments ADD COLUMN user_id INTEGER")
            conn.commit()
        except Exception:
            pass
        try:
            conn.execute("ALTER TABLE payments ADD COLUMN coupon VARCHAR(255) DEFAULT ''")
            conn.commit()
        except Exception:
            pass

        conn.execute("""
            CREATE TABLE IF NOT EXISTS naukri_jobs (
                id                INT AUTO_INCREMENT PRIMARY KEY,
                job_id            VARCHAR(255) NOT NULL DEFAULT '',
                title             VARCHAR(255) NOT NULL DEFAULT '',
                company           VARCHAR(255) NOT NULL DEFAULT '',
                location          VARCHAR(255) NOT NULL DEFAULT '',
                experience        VARCHAR(100) NOT NULL DEFAULT '',
                description       TEXT    NOT NULL,
                skills            TEXT    NOT NULL,
                posted_date       VARCHAR(100) NOT NULL DEFAULT '',
                url               VARCHAR(512) UNIQUE NOT NULL,
                portal            VARCHAR(100) NOT NULL DEFAULT 'naukri.com',
                scraped_at        VARCHAR(100) NOT NULL,
                status            VARCHAR(50)  NOT NULL DEFAULT 'new',
                relevance_percent INT DEFAULT 0
            )
        """)

        # Migration: Add relevance_percent column to naukri_jobs if not exists
        try:
            conn.execute("ALTER TABLE naukri_jobs ADD COLUMN relevance_percent INTEGER DEFAULT 0")
        except Exception:
            pass

        conn.execute("""
            CREATE TABLE IF NOT EXISTS naukri_applications (
                id                INT AUTO_INCREMENT PRIMARY KEY,
                user_id           INT NOT NULL,
                job_id            VARCHAR(255) NOT NULL,
                status            VARCHAR(50)  NOT NULL DEFAULT 'surfaced',
                applied_at        VARCHAR(100) NOT NULL,
                tailored_resume_path TEXT,
                UNIQUE(user_id, job_id)
            )
        """)

        # Migration: Add tailored_resume_path column to naukri_applications if not exists
        try:
            conn.execute("ALTER TABLE naukri_applications ADD COLUMN tailored_resume_path TEXT")
        except Exception:
            pass

        # Migration: Add retry_count column to naukri_applications if not exists
        try:
            conn.execute("ALTER TABLE naukri_applications ADD COLUMN retry_count INTEGER DEFAULT 0")
        except Exception:
            pass

        # Migration: Add last_error column to naukri_applications if not exists
        try:
            conn.execute("ALTER TABLE naukri_applications ADD COLUMN last_error TEXT")
        except Exception:
            pass

        # Create naukri_application_logs table
        conn.execute("""
            CREATE TABLE IF NOT EXISTS naukri_application_logs (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id         INTEGER NOT NULL,
                job_id          TEXT    NOT NULL,
                attempt_number  INTEGER NOT NULL,
                status          TEXT    NOT NULL,
                error_message   TEXT,
                screenshot_path TEXT,
                attempted_at    TEXT    NOT NULL
            )
        """)

        # Create linkedin_jobs table
        conn.execute("""
            CREATE TABLE IF NOT EXISTS linkedin_jobs (
                id                INT AUTO_INCREMENT PRIMARY KEY,
                job_id            VARCHAR(255) NOT NULL DEFAULT '',
                title             VARCHAR(255) NOT NULL DEFAULT '',
                company           VARCHAR(255) NOT NULL DEFAULT '',
                location          VARCHAR(255) NOT NULL DEFAULT '',
                description       TEXT    NOT NULL,
                poster_info       TEXT,
                poster_name       VARCHAR(255) NOT NULL DEFAULT '',
                poster_url        VARCHAR(512) NOT NULL DEFAULT '',
                has_recruiter_outreach INT DEFAULT 0,
                posted_date       VARCHAR(100) NOT NULL DEFAULT '',
                url               VARCHAR(512) UNIQUE NOT NULL,
                portal            VARCHAR(100) NOT NULL DEFAULT 'linkedin.com',
                scraped_at        VARCHAR(100) NOT NULL,
                status            VARCHAR(50)  NOT NULL DEFAULT 'new',
                relevance_percent INT DEFAULT 0
            )
        """)

        # Migration: Add columns to linkedin_jobs if not exists (for existing tables)
        for col, col_type in [("poster_name", "TEXT DEFAULT ''"), ("poster_url", "TEXT DEFAULT ''"), ("has_recruiter_outreach", "INTEGER DEFAULT 0")]:
            try:
                conn.execute(f"ALTER TABLE linkedin_jobs ADD COLUMN {col} {col_type}")
            except Exception:
                pass

        # Create linkedin_applications table
        conn.execute("""
            CREATE TABLE IF NOT EXISTS linkedin_applications (
                id                INT AUTO_INCREMENT PRIMARY KEY,
                user_id           INT NOT NULL,
                job_id            VARCHAR(255) NOT NULL,
                status            VARCHAR(50)  NOT NULL DEFAULT 'surfaced',
                applied_at        VARCHAR(100) NOT NULL,
                tailored_resume_path TEXT,
                retry_count       INT DEFAULT 0,
                last_error        TEXT,
                UNIQUE(user_id, job_id)
            )
        """)

        # Create linkedin_outreach table
        conn.execute("""
            CREATE TABLE IF NOT EXISTS linkedin_outreach (
                id                  INT AUTO_INCREMENT PRIMARY KEY,
                user_id             INT NOT NULL,
                job_id              VARCHAR(255) NOT NULL,
                poster_url          VARCHAR(512) NOT NULL,
                connection_status   VARCHAR(50)  NOT NULL DEFAULT 'none',
                note                TEXT,
                follow_up_message   TEXT,
                follow_up_sent      INT DEFAULT 0,
                created_at          VARCHAR(100) NOT NULL,
                updated_at          VARCHAR(100) NOT NULL,
                UNIQUE(user_id, job_id)
            )
        """)

        # Create linkedin_jobs_tracking table
        conn.execute("""
            CREATE TABLE IF NOT EXISTS linkedin_jobs_tracking (
                user_id             INT NOT NULL,
                job_id              VARCHAR(255) NOT NULL,
                surfaced_at         VARCHAR(100) NOT NULL,
                actioned            INT DEFAULT 0,
                PRIMARY KEY (user_id, job_id)
            )
        """)

        conn.commit()

    # ── Admin & Audit tables in users.db ───────────────────────────────────
    with _connect() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS admin_users (
                id            INT AUTO_INCREMENT PRIMARY KEY,
                email         VARCHAR(255) NOT NULL UNIQUE,
                password_hash VARCHAR(255) NOT NULL,
                role          VARCHAR(50)  NOT NULL DEFAULT 'ADMIN',
                name          VARCHAR(255) NOT NULL DEFAULT '',
                permissions   TEXT,
                created_at    VARCHAR(100) NOT NULL,
                updated_at    VARCHAR(100) NOT NULL,
                last_login_at VARCHAR(100) DEFAULT ''
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS naukri_answer_bank (
                id           INT AUTO_INCREMENT PRIMARY KEY,
                user_id      INT NOT NULL,
                question     VARCHAR(512) NOT NULL,
                answer       TEXT    NOT NULL,
                status       VARCHAR(50)  NOT NULL DEFAULT 'approved',
                updated_at   VARCHAR(100) NOT NULL,
                UNIQUE(user_id, question)
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS audit_logs (
                id              INT AUTO_INCREMENT PRIMARY KEY,
                admin_id        INT NOT NULL,
                admin_email     VARCHAR(255) NOT NULL DEFAULT '',
                action          VARCHAR(255) NOT NULL,
                target_user_id  INT,
                previous_value  TEXT,
                new_value       TEXT,
                reason          TEXT,
                timestamp       VARCHAR(100) NOT NULL,
                ip_address      VARCHAR(50)  DEFAULT ''
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
                id               INT AUTO_INCREMENT PRIMARY KEY,
                user_id          INT NOT NULL UNIQUE,
                linkedin_url     VARCHAR(512) DEFAULT '',
                status           VARCHAR(50)  NOT NULL DEFAULT 'PENDING',
                parsed_data      TEXT,
                raw_evidence     TEXT,
                reviewed_by      INT,
                reviewed_at      VARCHAR(100) DEFAULT '',
                rejection_reason TEXT,
                created_at       VARCHAR(100) NOT NULL,
                updated_at       VARCHAR(100) NOT NULL
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
            ("users", "agent_status",       "VARCHAR(50) DEFAULT 'inactive'"),
            ("users", "linkedin_username",  "TEXT DEFAULT ''"),
            ("users", "linkedin_password",  "TEXT DEFAULT ''"),
            ("users", "job_preferences",    "VARCHAR(4096) DEFAULT '{}'"),
            ("users", "auth_provider",      "VARCHAR(50) DEFAULT 'email'"),
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
            ("users", "naukri_preferences",  "VARCHAR(4096) DEFAULT '{}'"),
            # ── LinkedIn profile name column ──────────────────────────
            ("users", "linkedin_profile_name", "TEXT DEFAULT ''"),
            # ── LinkedIn preferences column ───────────────────────────
            ("users", "linkedin_preferences", "VARCHAR(4096) DEFAULT '{}'"),
            # ── Password reset code columns ───────────────────────────
            ("users", "reset_code",          "TEXT DEFAULT ''"),
            ("users", "reset_code_expires_at", "TEXT DEFAULT ''"),
            # ── LinkedIn Jobs Agent Subscription ──────────────────────
            ("users", "linkedin_jobs_subscribed", "INTEGER DEFAULT 0"),
            # ── Naukri AI Agent Subscription ──────────────────────────
            ("users", "naukri_subscribed",      "INTEGER DEFAULT 0"),
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
                id            INT AUTO_INCREMENT PRIMARY KEY,
                user_id       INT NOT NULL UNIQUE,
                cv_data       TEXT    NOT NULL,
                updated_at    VARCHAR(100) NOT NULL,
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
        
    # Transparently parse linkedin_preferences JSON
    if d.get("linkedin_preferences"):
        try:
            d["linkedin_preferences"] = json.loads(d["linkedin_preferences"])
        except Exception:
            d["linkedin_preferences"] = {}
    else:
        d["linkedin_preferences"] = {}
        
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


def set_user_linkedin_jobs_subscribed(user_id: int, subscribed: bool = True) -> bool:
    """Set LinkedIn Jobs Agent subscription status for a user."""
    with _connect() as conn:
        cur = conn.execute(
            "UPDATE users SET linkedin_jobs_subscribed = ? WHERE id = ?",
            (1 if subscribed else 0, user_id),
        )
        conn.commit()
    return cur.rowcount > 0


def set_user_naukri_subscribed(user_id: int, subscribed: bool = True) -> bool:
    """Set Naukri AI Agent subscription status for a user."""
    with _connect() as conn:
        cur = conn.execute(
            "UPDATE users SET naukri_subscribed = ? WHERE id = ?",
            (1 if subscribed else 0, user_id),
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


# ── Naukri Jobs Helper Functions ───────────────────────────────────────────────

def save_naukri_jobs(jobs: list[dict]):
    """Save scraped Naukri jobs to the database."""
    import json
    with _connect_jobs() as conn:
        for job in jobs:
            try:
                # Serialize skills list to JSON string
                skills_json = json.dumps(job.get("skills", []))
                conn.execute(
                    """INSERT INTO naukri_jobs
                       (job_id, title, company, location, experience, description, skills, posted_date, url, portal, scraped_at, status, relevance_percent)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'new', ?)
                       ON CONFLICT(url) DO UPDATE SET
                           relevance_percent = excluded.relevance_percent,
                           scraped_at = excluded.scraped_at,
                           posted_date = excluded.posted_date""",
                    (
                        job.get("job_id", ""),
                        job.get("title", ""),
                        job.get("company", ""),
                        job.get("location", ""),
                        job.get("experience", ""),
                        job.get("description", ""),
                        skills_json,
                        job.get("posted_date", ""),
                        job.get("url", ""),
                        job.get("portal", "naukri.com"),
                        job.get("scraped_at", ""),
                        job.get("relevance_percent", 0),
                    ),
                )
            except Exception as e:
                print(f"[DB] Error saving Naukri job {job.get('url')}: {e}")
        conn.commit()
    print(f"[DB] Saved {len(jobs)} Naukri jobs to database")


def get_all_naukri_jobs(status: str | None = None) -> list[dict]:
    """Return all Naukri jobs from jobs.db, optionally filtered by status."""
    with _connect_jobs() as conn:
        if status:
            rows = conn.execute(
                "SELECT * FROM naukri_jobs WHERE status = ? ORDER BY scraped_at DESC",
                (status,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM naukri_jobs ORDER BY scraped_at DESC"
            ).fetchall()
    
    # De-serialize skills JSON to list
    res = []
    import json
    for r in rows:
        d = _row_to_dict(r)
        if d.get("skills"):
            try:
                d["skills"] = json.loads(d["skills"])
            except Exception:
                d["skills"] = []
        else:
            d["skills"] = []
        res.append(d)
    return res


def update_naukri_job_status(job_id: int, status: str) -> bool:
    """Update the status of a Naukri job in jobs.db. Returns True if a row was updated."""
    valid = {"new", "reviewed", "applied", "dismissed"}
    if status not in valid:
        raise ValueError(f"Invalid status '{status}'. Must be one of: {valid}")
    with _connect_jobs() as conn:
        cur = conn.execute(
            "UPDATE naukri_jobs SET status = ? WHERE id = ?",
            (status, job_id),
        )
        conn.commit()
    return cur.rowcount > 0


# ── Naukri Applications Helper Functions ──────────────────────────────────────────

def is_naukri_job_processed(user_id: int, job_id: str) -> bool:
    """Check if a Naukri job has already been surfaced or applied to by the user."""
    with _connect_jobs() as conn:
        row = conn.execute(
            "SELECT 1 FROM naukri_applications WHERE user_id = ? AND job_id = ?",
            (user_id, job_id)
        ).fetchone()
    return row is not None


def add_naukri_application(user_id: int, job_id: str, status: str = "surfaced", tailored_resume_path: str = None) -> bool:
    """Record that a Naukri job has been surfaced or applied to by a user. Returns True on success."""
    from datetime import datetime
    applied_at = datetime.now().isoformat()
    with _connect_jobs() as conn:
        try:
            conn.execute(
                """INSERT INTO naukri_applications (user_id, job_id, status, applied_at, tailored_resume_path)
                   VALUES (?, ?, ?, ?, ?)
                   ON CONFLICT(user_id, job_id) DO UPDATE SET
                       status = excluded.status,
                       applied_at = excluded.applied_at,
                       tailored_resume_path = CASE WHEN excluded.tailored_resume_path IS NOT NULL THEN excluded.tailored_resume_path ELSE naukri_applications.tailored_resume_path END""",
                (user_id, job_id, status, applied_at, tailored_resume_path)
            )
            conn.commit()
            return True
        except Exception as e:
            print(f"[DB] Error adding/updating Naukri application record: {e}")
            return False


def get_naukri_applications(user_id: int) -> list[dict]:
    """Get all naukri application records for a user."""
    with _connect_jobs() as conn:
        rows = conn.execute(
            "SELECT * FROM naukri_applications WHERE user_id = ?",
            (user_id,)
        ).fetchall()
    return [_row_to_dict(r) for r in rows]


# ── LinkedIn Jobs Helper Functions ─────────────────────────────────────────────

def save_linkedin_jobs(jobs: list[dict]):
    """Save scraped LinkedIn jobs to the database."""
    import json
    with _connect_jobs() as conn:
        for job in jobs:
            try:
                conn.execute(
                    """INSERT INTO linkedin_jobs
                       (job_id, title, company, location, description, poster_info, poster_name, poster_url, has_recruiter_outreach, posted_date, url, portal, scraped_at, status, relevance_percent)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'new', ?)
                       ON CONFLICT(url) DO UPDATE SET
                           relevance_percent = excluded.relevance_percent,
                           scraped_at = excluded.scraped_at,
                           posted_date = excluded.posted_date,
                           poster_info = excluded.poster_info,
                           poster_name = excluded.poster_name,
                           poster_url = excluded.poster_url,
                           has_recruiter_outreach = excluded.has_recruiter_outreach""",
                    (
                        job.get("job_id", ""),
                        job.get("title", ""),
                        job.get("company", ""),
                        job.get("location", ""),
                        job.get("description", ""),
                        job.get("poster_info", ""),
                        job.get("poster_name", ""),
                        job.get("poster_url", ""),
                        job.get("has_recruiter_outreach", 0),
                        job.get("posted_date", ""),
                        job.get("url", ""),
                        job.get("portal", "linkedin.com"),
                        job.get("scraped_at", ""),
                        job.get("relevance_percent", 0),
                    ),
                )
            except Exception as e:
                print(f"[DB] Error saving LinkedIn job {job.get('url')}: {e}")
        conn.commit()
    print(f"[DB] Saved {len(jobs)} LinkedIn jobs to database")


def get_all_linkedin_jobs(status: str | None = None) -> list[dict]:
    """Return all LinkedIn jobs from jobs.db, optionally filtered by status."""
    with _connect_jobs() as conn:
        if status:
            rows = conn.execute(
                "SELECT * FROM linkedin_jobs WHERE status = ? ORDER BY scraped_at DESC",
                (status,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM linkedin_jobs ORDER BY scraped_at DESC"
            ).fetchall()
    return [_row_to_dict(r) for r in rows]


def get_linkedin_job_by_id(job_id: str) -> dict | None:
    """Retrieve a LinkedIn job by its job_id."""
    with _connect_jobs() as conn:
        row = conn.execute(
            "SELECT * FROM linkedin_jobs WHERE job_id = ?",
            (job_id,),
        ).fetchone()
    return _row_to_dict(row) if row else None


def update_linkedin_job_status(job_id: int, status: str) -> bool:
    """Update the status of a LinkedIn job."""
    with _connect_jobs() as conn:
        cur = conn.execute(
            "UPDATE linkedin_jobs SET status = ? WHERE id = ?",
            (status, job_id),
        )
        conn.commit()
    return cur.rowcount > 0


def is_linkedin_job_processed(user_id: int, job_id: str) -> bool:
    """Check if a LinkedIn job has already been surfaced or applied to for a user."""
    with _connect_jobs() as conn:
        row = conn.execute(
            "SELECT 1 FROM linkedin_applications WHERE user_id = ? AND job_id = ?",
            (user_id, job_id),
        ).fetchone()
    return row is not None


def add_linkedin_application(user_id: int, job_id: str, status: str = "surfaced", tailored_resume_path: str = None) -> bool:
    """Record that a LinkedIn job was surfaced or applied to."""
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()
    try:
        with _connect_jobs() as conn:
            conn.execute(
                """INSERT INTO linkedin_applications (user_id, job_id, status, applied_at, tailored_resume_path)
                   VALUES (?, ?, ?, ?, ?)
                   ON CONFLICT(user_id, job_id) DO UPDATE SET
                       status = excluded.status,
                       applied_at = excluded.applied_at,
                       tailored_resume_path = CASE WHEN excluded.tailored_resume_path IS NOT NULL THEN excluded.tailored_resume_path ELSE linkedin_applications.tailored_resume_path END""",
                (user_id, job_id, status, now, tailored_resume_path),
            )
            conn.commit()
        return True
    except Exception as e:
        print(f"[DB] Error adding/updating LinkedIn application record: {e}")
        return False


def get_linkedin_applications(user_id: int) -> list[dict]:
    """Get all linkedin application records for a user."""
    with _connect_jobs() as conn:
        rows = conn.execute(
            "SELECT * FROM linkedin_applications WHERE user_id = ?",
            (user_id,)
        ).fetchall()
    return [_row_to_dict(r) for r in rows]


def update_user_linkedin_preferences(user_id: int, preferences: dict) -> bool:
    """Store user preferences for LinkedIn job search."""
    import json
    pref_json = json.dumps(preferences)
    with _connect() as conn:
        cur = conn.execute(
            "UPDATE users SET linkedin_preferences = ? WHERE id = ?",
            (pref_json, user_id),
        )
        conn.commit()
    return cur.rowcount > 0


def add_linkedin_outreach(user_id: int, job_id: str, poster_url: str, connection_status: str = 'none', note: str = '', follow_up_message: str = '') -> bool:
    """Insert or update a LinkedIn recruiter outreach entry."""
    from datetime import datetime
    now = datetime.now().isoformat()
    try:
        with _connect_jobs() as conn:
            conn.execute(
                """INSERT INTO linkedin_outreach (user_id, job_id, poster_url, connection_status, note, follow_up_message, follow_up_sent, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, 0, ?, ?)
                   ON CONFLICT(user_id, job_id) DO UPDATE SET
                       connection_status = excluded.connection_status,
                       note = CASE WHEN excluded.note != '' THEN excluded.note ELSE linkedin_outreach.note END,
                       follow_up_message = CASE WHEN excluded.follow_up_message != '' THEN excluded.follow_up_message ELSE linkedin_outreach.follow_up_message END,
                       updated_at = excluded.updated_at""",
                (user_id, job_id, poster_url, connection_status, note, follow_up_message, now, now),
            )
            conn.commit()
        return True
    except Exception as e:
        print(f"[DB] Error adding/updating LinkedIn outreach record: {e}")
        return False


def get_pending_linkedin_outreaches(user_id: int) -> list[dict]:
    """Get all pending LinkedIn outreaches for a user (status is 'sent' and follow_up_sent is 0)."""
    with _connect_jobs() as conn:
        rows = conn.execute(
            "SELECT * FROM linkedin_outreach WHERE user_id = ? AND connection_status = 'sent' AND follow_up_sent = 0",
            (user_id,)
        ).fetchall()
    return [_row_to_dict(r) for r in rows]


def get_active_linkedin_outreaches(user_id: int) -> list[dict]:
    """Get all active LinkedIn outreaches (follow_up_sent = 1 and connection_status != 'escalated')."""
    with _connect_jobs() as conn:
        rows = conn.execute(
            "SELECT * FROM linkedin_outreach WHERE user_id = ? AND follow_up_sent = 1 AND connection_status != 'escalated'",
            (user_id,)
        ).fetchall()
    return [_row_to_dict(r) for r in rows]


def get_daily_action_counts(user_id: int) -> dict:
    """Get the count of connection requests and follow-up DMs sent today."""
    from datetime import datetime
    today_str = datetime.now().date().isoformat()
    try:
        with _connect_jobs() as conn:
            connects_today = conn.execute(
                "SELECT COUNT(*) FROM linkedin_outreach WHERE user_id = ? AND connection_status IN ('sent', 'connected_already') AND created_at LIKE ?",
                (user_id, f"{today_str}%")
            ).fetchone()[0]
            
            dms_today = conn.execute(
                "SELECT COUNT(*) FROM linkedin_outreach WHERE user_id = ? AND follow_up_sent = 1 AND updated_at LIKE ?",
                (user_id, f"{today_str}%")
            ).fetchone()[0]
    except Exception as e:
        print(f"[DB] Error getting daily action counts: {e}")
        return {"connection_requests": 0, "direct_messages": 0}
        
    return {"connection_requests": connects_today, "direct_messages": dms_today}


def update_linkedin_outreach_status(user_id: int, job_id: str, connection_status: str, follow_up_sent: int = 0) -> bool:
    """Update the connection status and follow-up status for a LinkedIn outreach entry."""
    from datetime import datetime
    now = datetime.now().isoformat()
    try:
        with _connect_jobs() as conn:
            conn.execute(
                """UPDATE linkedin_outreach 
                   SET connection_status = ?, follow_up_sent = ?, updated_at = ?
                   WHERE user_id = ? AND job_id = ?""",
                (connection_status, follow_up_sent, now, user_id, job_id),
            )
            conn.commit()
        return True
    except Exception as e:
        print(f"[DB] Error updating LinkedIn outreach status: {e}")
        return False


def is_linkedin_job_tracked(user_id: int, job_id: str) -> bool:
    """Check if a LinkedIn job has already been tracked (surfaced or actioned) for a user."""
    with _connect_jobs() as conn:
        row = conn.execute(
            "SELECT 1 FROM linkedin_jobs_tracking WHERE user_id = ? AND job_id = ?",
            (user_id, job_id),
        ).fetchone()
    return row is not None


def track_linkedin_job(user_id: int, job_id: str, actioned: int = 0) -> bool:
    """Track a LinkedIn job to prevent it from being surfaced again."""
    from datetime import datetime
    now = datetime.now().isoformat()
    try:
        with _connect_jobs() as conn:
            conn.execute(
                """INSERT INTO linkedin_jobs_tracking (user_id, job_id, surfaced_at, actioned)
                   VALUES (?, ?, ?, ?)
                   ON CONFLICT(user_id, job_id) DO UPDATE SET
                       actioned = excluded.actioned""",
                (user_id, job_id, now, actioned),
            )
            conn.commit()
        return True
    except Exception as e:
        print(f"[DB] Error tracking LinkedIn job: {e}")
        return False


def get_linkedin_outreach_funnel(user_id: int) -> list[dict]:
    """
    Returns structured data tracking each LinkedIn job posting's status
    through the outreach funnel: job found -> recruiter identified -> connection sent -> message sent -> reply received.
    """
    with _connect_jobs() as conn:
        rows = conn.execute(
            """
            SELECT 
                t.job_id,
                j.title,
                j.company,
                j.location,
                j.url,
                j.scraped_at,
                j.relevance_percent,
                j.poster_name,
                j.poster_url,
                j.has_recruiter_outreach,
                o.connection_status,
                o.follow_up_sent,
                o.note,
                o.follow_up_message,
                o.updated_at
            FROM linkedin_jobs_tracking t
            LEFT JOIN linkedin_jobs j ON t.job_id = j.job_id
            LEFT JOIN linkedin_outreach o ON t.user_id = o.user_id AND t.job_id = o.job_id
            WHERE t.user_id = ?
            ORDER BY t.surfaced_at DESC
            """,
            (user_id,),
        ).fetchall()
        
    funnel_data = []
    for r in rows:
        d = _row_to_dict(r)
        
        # Calculate current funnel stage
        stage = "job_found"
        
        p_name = d.get("poster_name") or ""
        p_url = d.get("poster_url") or ""
        has_rec = d.get("has_recruiter_outreach") or 0
        
        # 1. Recruiter identified
        if (p_url and p_url.strip()) or (p_name and p_name.strip() and "linkedin member" not in p_name.lower()) or has_rec == 1:
            stage = "recruiter_identified"
            
        # 2. Connection sent
        conn_status = d.get("connection_status") or "none"
        if conn_status in ('sent', 'pending_already', 'connected_already', 'accepted', 'replied_auto', 'escalated'):
            stage = "connection_sent"
            
        # 3. Message sent
        follow_sent = d.get("follow_up_sent") or 0
        if follow_sent == 1 or conn_status in ('accepted', 'replied_auto', 'escalated'):
            stage = "message_sent"
            
        # 4. Reply received
        if conn_status in ('replied_auto', 'escalated'):
            stage = "reply_received"
            
        d["funnel_stage"] = stage
        funnel_data.append(d)
        
    return funnel_data


# ── Posts (scraped by linkedin-posts.mjs) ─────────────────────────────────────────────

def init_posts_table():
    """Ensure the posts table exists in jobs.db (also created by the scraper itself)."""
    with _connect_jobs() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS posts (
                id               INT AUTO_INCREMENT PRIMARY KEY,
                title            VARCHAR(255) NOT NULL DEFAULT '',
                company          VARCHAR(255) NOT NULL DEFAULT '',
                location         VARCHAR(255) NOT NULL DEFAULT '',
                apply_link       TEXT,
                poster_name      VARCHAR(255) NOT NULL DEFAULT '',
                poster_url       VARCHAR(512) NOT NULL DEFAULT '',
                post_text        TEXT,
                source           VARCHAR(100) NOT NULL DEFAULT 'linkedin-posts',
                keywords         VARCHAR(255) NOT NULL DEFAULT '',
                scraped_at       VARCHAR(100) NOT NULL,
                status           VARCHAR(50)  NOT NULL DEFAULT 'new',
                post_urn         VARCHAR(255) UNIQUE DEFAULT NULL,
                post_url         VARCHAR(512) NOT NULL DEFAULT '',
                apply_url        VARCHAR(512) NOT NULL DEFAULT '',
                apply_method     VARCHAR(100) NOT NULL DEFAULT '',
                connected_at     VARCHAR(100) DEFAULT NULL,
                followup_sent_at VARCHAR(100) DEFAULT NULL,
                followup_status  VARCHAR(50)  DEFAULT NULL,
                followup_msg     TEXT
            )
        """)
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
    user_id: int | None = None,
    coupon: str = "",
) -> dict:
    """Insert a new payment record after creating a Razorpay order."""
    created_at = datetime.now(timezone.utc).isoformat()
    with _connect_jobs() as conn:
        cur = conn.execute(
            """INSERT INTO payments
               (razorpay_order_id, amount_paise, currency, receipt, buyer_id, user_id, coupon, status, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, 'created', ?)""",
            (razorpay_order_id, amount_paise, currency, receipt, buyer_id, user_id, coupon, created_at),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM payments WHERE id = ?", (cur.lastrowid,)).fetchone()
    return _row_to_dict(row) if row else {}


def has_user_used_coupon(user_id: int, coupon_code: str) -> bool:
    """Check if the user has already successfully used the coupon code."""
    # First get buyer_id if exists
    with _connect() as conn:
        user_row = conn.execute("SELECT email FROM users WHERE id = ?", (user_id,)).fetchone()
        email = user_row["email"] if user_row else None

    buyer_id = None
    if email:
        with _connect() as conn:
            buyer_row = conn.execute("SELECT id FROM agent_buyers WHERE email = ?", (email,)).fetchone()
            buyer_id = buyer_row["id"] if buyer_row else None

    with _connect_jobs() as conn:
        if buyer_id:
            row = conn.execute(
                """SELECT 1 FROM payments 
                   WHERE (user_id = ? OR buyer_id = ?) 
                     AND UPPER(coupon) = ? 
                     AND status = 'paid' 
                   LIMIT 1""",
                (user_id, buyer_id, coupon_code.strip().upper())
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT 1 FROM payments WHERE user_id = ? AND UPPER(coupon) = ? AND status = 'paid' LIMIT 1",
                (user_id, coupon_code.strip().upper())
            ).fetchone()
    return row is not None


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


def get_naukri_answer_bank(user_id: int) -> list[dict]:
    """Get all answer bank entries for a user."""
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM naukri_answer_bank WHERE user_id = ? ORDER BY id DESC",
            (user_id,)
        ).fetchall()
    return [_row_to_dict(r) for r in rows]


def save_naukri_answer_bank_entry(user_id: int, question: str, answer: str, status: str = 'approved') -> bool:
    """Add or update an answer bank entry for a user."""
    now = datetime.now(timezone.utc).isoformat()
    with _connect() as conn:
        try:
            conn.execute(
                """INSERT INTO naukri_answer_bank (user_id, question, answer, status, updated_at)
                   VALUES (?, ?, ?, ?, ?)
                   ON CONFLICT(user_id, question) DO UPDATE SET
                       answer = excluded.answer,
                       status = excluded.status,
                       updated_at = excluded.updated_at""",
                (user_id, question, answer, status, now)
            )
            conn.commit()
            return True
        except Exception as e:
            print(f"[DB] Error saving answer bank entry: {e}")
            return False


def delete_naukri_answer_bank_entry(user_id: int, question: str) -> bool:
    """Delete an answer bank entry for a user."""
    with _connect() as conn:
        try:
            conn.execute(
                "DELETE FROM naukri_answer_bank WHERE user_id = ? AND question = ?",
                (user_id, question)
            )
            conn.commit()
            return True
        except Exception as e:
            print(f"[DB] Error deleting answer bank entry: {e}")
            return False


def get_naukri_job_details(job_id: str) -> dict | None:
    """Fetch details of a Naukri job by job_id or url."""
    with _connect_jobs() as conn:
        row = conn.execute(
            "SELECT * FROM naukri_jobs WHERE job_id = ? OR url = ? LIMIT 1",
            (job_id, job_id)
        ).fetchone()
    return _row_to_dict(row) if row else None


def add_naukri_application_attempt(user_id: int, job_id: str, attempt_number: int, status: str, error_message: str | None, screenshot_path: str | None) -> bool:
    """Record an application attempt in the audit logs."""
    from datetime import datetime
    attempted_at = datetime.now().isoformat()
    with _connect_jobs() as conn:
        try:
            conn.execute(
                """INSERT INTO naukri_application_logs (user_id, job_id, attempt_number, status, error_message, screenshot_path, attempted_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (user_id, job_id, attempt_number, status, error_message, screenshot_path, attempted_at)
            )
            conn.commit()
            return True
        except Exception as e:
            print(f"[DB] Error adding naukri application attempt log: {e}")
            return False


def get_naukri_application_logs(user_id: int, job_id: str | None = None) -> list[dict]:
    """Retrieve all application attempts for a user/job."""
    with _connect_jobs() as conn:
        if job_id:
            rows = conn.execute(
                "SELECT * FROM naukri_application_logs WHERE user_id = ? AND job_id = ? ORDER BY attempted_at DESC",
                (user_id, job_id)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM naukri_application_logs WHERE user_id = ? ORDER BY attempted_at DESC",
                (user_id,)
            ).fetchall()
    return [_row_to_dict(r) for r in rows]


def update_naukri_application_retry(user_id: int, job_id: str, status: str, retry_count: int, last_error: str | None) -> bool:
    """Update retry count and last error for a Naukri application."""
    with _connect_jobs() as conn:
        try:
            conn.execute(
                """UPDATE naukri_applications 
                   SET status = ?, retry_count = ?, last_error = ? 
                   WHERE user_id = ? AND job_id = ?""",
                (status, retry_count, last_error, user_id, job_id)
            )
            conn.commit()
            return True
        except Exception as e:
            print(f"[DB] Error updating naukri application retry status: {e}")
            return False


def get_naukri_terminal_failures(user_id: int) -> list[dict]:
    """Get all failed/terminal applications for a user, including job details and the latest screenshot path."""
    with _connect_jobs() as conn:
        rows = conn.execute(
            """SELECT a.*, j.title, j.company, j.url, 
                      (SELECT screenshot_path FROM naukri_application_logs l 
                       WHERE l.user_id = a.user_id AND l.job_id = a.job_id 
                       ORDER BY l.attempted_at DESC LIMIT 1) as screenshot_path
               FROM naukri_applications a
               JOIN naukri_jobs j ON a.job_id = j.job_id OR a.job_id = j.url
               WHERE a.user_id = ? AND a.status = 'failed'
               ORDER BY a.applied_at DESC""",
            (user_id,)
        ).fetchall()
    return [_row_to_dict(r) for r in rows]


def dismiss_naukri_application(user_id: int, job_id: str) -> bool:
    """Change status of a failed Naukri application to 'dismissed'."""
    with _connect_jobs() as conn:
        try:
            conn.execute(
                "UPDATE naukri_applications SET status = 'dismissed' WHERE user_id = ? AND job_id = ?",
                (user_id, job_id)
            )
            conn.commit()
            return True
        except Exception as e:
            print(f"[DB] Error dismissing naukri application: {e}")
            return False



