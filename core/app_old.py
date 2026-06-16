"""
app.py - Flask REST API for IITIIMJobAssistant.

Endpoints:
  POST   /api/signup              Submit a new user (password hashed SHA-256)
  GET    /api/users               List all users
  GET    /api/users/pending        List pending users only
  POST   /api/users/<id>/approve  Approve a user
  POST   /api/users/<id>/reject   Reject a user (body: {"reason": "..."})
  GET    /api/stats               Aggregate counts
  GET    /api/export              Download users as CSV
  DELETE /api/users               Delete all users

  POST   /api/agent-buyers        Create an agent buyer (multipart form with resume)
  GET    /api/agent-buyers        List all agent buyers
  GET    /api/agent-buyers/<id>   Get a single agent buyer
  GET    /api/agent-buyers/<id>/resume   Download the resume file
  DELETE /api/agent-buyers/<id>   Delete an agent buyer + resume file
  DELETE /api/agent-buyers        Delete all agent buyers

Run:
  .\\venv\\Scripts\\python.exe app.py
  -> Server starts on http://127.0.0.1:5000
"""

import csv
import io
import os
from datetime import datetime, timezone

# Load .env before any os.environ.get calls
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from flask import Flask, request, jsonify, Response, redirect, send_file
from flask_cors import CORS

import database as db
from database import get_db_connection

app = Flask(__name__, static_folder=".", static_url_path="")
CORS(app)  # allow file:// HTML pages to call the API

# Limit upload size to 5 MB
app.config["MAX_CONTENT_LENGTH"] = 5 * 1024 * 1024


# --------------------------------------------------------------------------- #
#  Startup                                                                     #
# --------------------------------------------------------------------------- #
db.init_db()

# ── Load Google OAuth config from environment variables ─────────────────────
app.config.setdefault("GOOGLE_CLIENT_ID",     os.environ.get("GOOGLE_CLIENT_ID",     ""))
app.config.setdefault("GOOGLE_CLIENT_SECRET", os.environ.get("GOOGLE_CLIENT_SECRET", ""))
app.config.setdefault("GOOGLE_REDIRECT_URI",  os.environ.get("GOOGLE_REDIRECT_URI",  "http://localhost:5000/auth/google/callback"))

if app.config["GOOGLE_CLIENT_SECRET"]:
    print("[OAuth] Client secret loaded from environment")
else:
    print("[OAuth] No GOOGLE_CLIENT_SECRET set — token exchange will be skipped")


# --------------------------------------------------------------------------- #
#  Static pages                                                                #
# --------------------------------------------------------------------------- #
@app.route("/")
def index():
    return app.send_static_file("IITIIMJobAssistant_v3.html")


@app.route("/admin")
def admin():
    return app.send_static_file("IITIIMJobAssistant_Admin_v3.html")


# --------------------------------------------------------------------------- #
#  Google OAuth callback                                                       #
# --------------------------------------------------------------------------- #
@app.route("/auth/google/callback")
def google_oauth_callback():
    """
    Google redirects here after the user grants (or denies) consent.

    Step 1 — Validate the state param (CSRF protection).
    Step 2 — Exchange the one-time code for an access_token via Google's
             token endpoint (requires GOOGLE_CLIENT_SECRET from config).
    Step 3 — Fetch the user's Google profile (name, email, picture).
    Step 4 — Redirect to / with profile data in the query string so the
             client-side JS can pre-fill the signup form.

    Requires in config.py (or environment):
      GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, GOOGLE_REDIRECT_URI
    """
    import urllib.request
    import urllib.parse
    import json as _json

    params = request.args.to_dict()

    # ── Error from Google ──────────────────────────────────────────────────── #
    if "error" in params:
        err = params["error"]
        print(f"[OAuth] Google returned error: {err}")
        return redirect(f"/?oauth_error={err}")

    code  = params.get("code", "")
    state = params.get("state", "")

    if not code:
        return redirect("/?oauth_error=no_code")

    # ── Load config ────────────────────────────────────────────────────────── #
    client_id     = os.environ.get("GOOGLE_CLIENT_ID",     app.config.get("GOOGLE_CLIENT_ID",     ""))
    client_secret = os.environ.get("GOOGLE_CLIENT_SECRET", app.config.get("GOOGLE_CLIENT_SECRET", ""))
    redirect_uri  = os.environ.get("GOOGLE_REDIRECT_URI",  app.config.get("GOOGLE_REDIRECT_URI",  "http://localhost:5000/auth/google/callback"))

    if not client_secret:
        # Secret not configured — pass code through so the client can handle it
        print("[OAuth] GOOGLE_CLIENT_SECRET not set — forwarding code to client")
        qs = urllib.parse.urlencode({"code": code, "state": state})
        return redirect(f"/?{qs}")

    # ── Exchange code for token ────────────────────────────────────────────── #
    try:
        token_data = urllib.parse.urlencode({
            "code":          code,
            "client_id":     client_id,
            "client_secret": client_secret,
            "redirect_uri":  redirect_uri,
            "grant_type":    "authorization_code",
        }).encode("utf-8")

        token_req = urllib.request.Request(
            "https://oauth2.googleapis.com/token",
            data=token_data,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        with urllib.request.urlopen(token_req, timeout=10) as resp:
            token_resp = _json.loads(resp.read())

        access_token = token_resp.get("access_token", "")
        if not access_token:
            raise ValueError("No access_token in Google response")

        # ── Fetch user profile ─────────────────────────────────────────────── #
        profile_req = urllib.request.Request(
            "https://www.googleapis.com/oauth2/v2/userinfo",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        with urllib.request.urlopen(profile_req, timeout=10) as resp:
            profile = _json.loads(resp.read())

        name    = profile.get("name",    "")
        email   = profile.get("email",   "")
        picture = profile.get("picture", "")
        print(f"[OAuth] Google login  name={name}  email={email}")

        # Redirect back to the main page with the profile pre-filled
        qs = urllib.parse.urlencode({
            "oauth_ok":  "1",
            "state":     state,
            "name":      name,
            "email":     email,
            "picture":   picture,
        })
        return redirect(f"/?{qs}")

    except Exception as exc:
        print(f"[OAuth] Token exchange failed: {exc}")
        # Fall back: pass the raw code to the client
        qs = urllib.parse.urlencode({"code": code, "state": state, "oauth_error": "exchange_failed"})
        return redirect(f"/?{qs}")


# --------------------------------------------------------------------------- #
#  API: Signup                                                                 #
# --------------------------------------------------------------------------- #
@app.route("/api/signup", methods=["POST"])
def signup():
    """Accepts JSON: { name, last_name, email, password, linkedin_url, mobile_number }.
    Hashes the password with SHA-256 before storing.
    Validates that linkedin_url is a linkedin.com URL."""
    data = request.get_json(silent=True) or {}

    name          = (data.get("name")          or "").strip()
    last_name     = (data.get("last_name")     or "").strip()
    email         = (data.get("email")         or "").strip()
    password      = (data.get("password")      or "").strip()
    linkedin_url  = (data.get("linkedin_url")  or "").strip()
    mobile_number = (data.get("mobile_number") or "").strip()

    errors = []
    if not name:          errors.append("name is required")
    if not last_name:     errors.append("last_name is required")
    if not email:         errors.append("email is required")
    if not password:      errors.append("password is required")
    if not linkedin_url:  errors.append("linkedin_url is required")
    if not mobile_number: errors.append("mobile_number is required")
    if errors:
        return jsonify({"ok": False, "errors": errors}), 400

    # Validate LinkedIn URL
    try:
        db.validate_linkedin_url(linkedin_url)
    except ValueError as exc:
        return jsonify({"ok": False, "errors": [str(exc)]}), 400

    try:
        user = db.save_user(name, last_name, email, password, linkedin_url, mobile_number)
    except Exception as exc:
        # Handle duplicate email etc.
        return jsonify({"ok": False, "errors": [str(exc)]}), 400

    print(f"[API] New signup saved  id={user['id']}  email={user['email']}")
    return jsonify({"ok": True, "user": user}), 201


# --------------------------------------------------------------------------- #
#  API: Users                                                                  #
# --------------------------------------------------------------------------- #
@app.route("/api/users", methods=["GET"])
def list_users():
    return jsonify(db.get_all_users())


@app.route("/api/users/pending", methods=["GET"])
def list_pending():
    return jsonify(db.get_pending_users())


@app.route("/api/users/<int:user_id>/approve", methods=["POST"])
def approve(user_id):
    ok = db.approve_user(user_id)
    if not ok:
        return jsonify({"ok": False, "error": "User not found"}), 404
    print(f"[API] User {user_id} approved")
    return jsonify({"ok": True})


@app.route("/api/users/<int:user_id>/reject", methods=["POST"])
def reject(user_id):
    data   = request.get_json(silent=True) or {}
    reason = (data.get("reason") or "").strip()
    ok     = db.reject_user(user_id, reason)
    if not ok:
        return jsonify({"ok": False, "error": "User not found"}), 404
    print(f"[API] User {user_id} rejected  reason: {reason or '(none)'}")
    return jsonify({"ok": True})


@app.route("/api/users", methods=["DELETE"])
def clear_users():
    count = db.delete_all_users()
    print(f"[API] Deleted {count} user(s)")
    return jsonify({"ok": True, "deleted": count})


# --------------------------------------------------------------------------- #
#  API: Agent Buyers                                                           #
# --------------------------------------------------------------------------- #
@app.route("/api/agent-buyers", methods=["POST"])
def create_agent_buyer():
    """Create an agent buyer with a resume file upload.
    Expects multipart/form-data with fields: name, last_name, email
    and a file field: resume (PDF or DOC only, max 5 MB)."""

    name      = (request.form.get("name")      or "").strip()
    last_name = (request.form.get("last_name") or "").strip()
    email     = (request.form.get("email")     or "").strip()

    errors = []
    if not name:      errors.append("name is required")
    if not last_name: errors.append("last_name is required")
    if not email:     errors.append("email is required")

    # Check resume file
    resume_file = request.files.get("resume")
    if not resume_file or not resume_file.filename:
        errors.append("resume file is required (PDF or DOC)")

    if errors:
        return jsonify({"ok": False, "errors": errors}), 400

    try:
        buyer = db.save_agent_buyer(name, last_name, email, resume_file)
    except ValueError as exc:
        return jsonify({"ok": False, "errors": [str(exc)]}), 400
    except Exception as exc:
        return jsonify({"ok": False, "errors": [str(exc)]}), 500

    print(f"[API] New agent buyer saved  id={buyer['id']}  email={email}")
    return jsonify({"ok": True, "buyer": buyer}), 201


@app.route("/api/agent-buyers", methods=["GET"])
def list_agent_buyers():
    """Return all agent buyers."""
    return jsonify(db.get_all_agent_buyers())


@app.route("/api/agent-buyers/<int:buyer_id>", methods=["GET"])
def get_agent_buyer(buyer_id):
    """Return a single agent buyer by ID."""
    buyer = db.get_agent_buyer(buyer_id)
    if not buyer:
        return jsonify({"ok": False, "error": "Agent buyer not found"}), 404
    return jsonify(buyer)


@app.route("/api/agent-buyers/<int:buyer_id>/resume", methods=["GET"])
def download_resume(buyer_id):
    """Download the resume file for a given agent buyer."""
    buyer = db.get_agent_buyer(buyer_id)
    if not buyer:
        return jsonify({"ok": False, "error": "Agent buyer not found"}), 404

    resume_path = buyer.get("resume_path", "")
    if not resume_path or not os.path.exists(resume_path):
        return jsonify({"ok": False, "error": "Resume file not found on disk"}), 404

    return send_file(
        resume_path,
        as_attachment=True,
        download_name=os.path.basename(resume_path),
    )


@app.route("/api/agent-buyers/<int:buyer_id>", methods=["DELETE"])
def remove_agent_buyer(buyer_id):
    """Delete a single agent buyer and their resume file."""
    ok = db.delete_agent_buyer(buyer_id)
    if not ok:
        return jsonify({"ok": False, "error": "Agent buyer not found"}), 404
    print(f"[API] Agent buyer {buyer_id} deleted")
    return jsonify({"ok": True})


@app.route("/api/agent-buyers", methods=["DELETE"])
def clear_agent_buyers():
    """Delete all agent buyers and their resume files."""
    count = db.delete_all_agent_buyers()
    print(f"[API] Deleted {count} agent buyer(s)")
    return jsonify({"ok": True, "deleted": count})


@app.route("/api/agent-buyers/stats", methods=["GET"])
def agent_buyers_stats():
    """Return agent buyer counts."""
    return jsonify(db.get_agent_buyers_stats())


# --------------------------------------------------------------------------- #
#  API: Stats                                                                  #
# --------------------------------------------------------------------------- #
@app.route("/api/stats", methods=["GET"])
def stats():
    return jsonify(db.get_stats())


# --------------------------------------------------------------------------- #
#  API: Jobs (scraped by linkedin-scan.mjs)                                    #
# --------------------------------------------------------------------------- #
@app.route("/api/jobs", methods=["GET"])
def list_jobs():
    """Return all scraped jobs, optionally filtered by ?status=new|reviewed|applied|dismissed."""
    status = request.args.get("status", "").strip() or None
    return jsonify(db.get_all_jobs(status))


@app.route("/api/jobs/stats", methods=["GET"])
def jobs_stats():
    """Return job counts grouped by status."""
    return jsonify(db.get_jobs_stats())


@app.route("/api/jobs/<int:job_id>", methods=["PATCH"])
def update_job(job_id):
    """Update the status of a scraped job.
    Body: { "status": "reviewed" | "applied" | "dismissed" | "new" }"""
    data   = request.get_json(silent=True) or {}
    status = (data.get("status") or "").strip()
    if not status:
        return jsonify({"ok": False, "error": "status is required"}), 400
    try:
        ok = db.update_job_status(job_id, status)
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    if not ok:
        return jsonify({"ok": False, "error": "Job not found"}), 404
    print(f"[API] Job {job_id} status → {status}")
    return jsonify({"ok": True})


# --------------------------------------------------------------------------- #
#  API: Posts (scraped by linkedin-posts.mjs)                                  #
# --------------------------------------------------------------------------- #
@app.route("/api/posts", methods=["GET"])
def list_posts():
    """Return all scraped LinkedIn posts.
    Optional: ?status=new|reviewed|applied|dismissed"""
    status = request.args.get("status", "").strip() or None
    return jsonify(db.get_all_posts(status))


@app.route("/api/posts/stats", methods=["GET"])
def posts_stats():
    """Return post counts grouped by status."""
    return jsonify(db.get_posts_stats())


@app.route("/api/posts/<int:post_id>", methods=["PATCH"])
def update_post(post_id):
    """Update the status of a scraped post.
    Body: { "status": "reviewed" | "applied" | "dismissed" | "new" }"""
    data   = request.get_json(silent=True) or {}
    status = (data.get("status") or "").strip()
    if not status:
        return jsonify({"ok": False, "error": "status is required"}), 400
    try:
        ok = db.update_post_status(post_id, status)
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    if not ok:
        return jsonify({"ok": False, "error": "Post not found"}), 404
    print(f"[API] Post {post_id} status → {status}")
    return jsonify({"ok": True})


# --------------------------------------------------------------------------- #
#  API: Auto-Apply Engine                                                       #
# --------------------------------------------------------------------------- #
import asyncio
import threading

def _run_apply_async(buyer_id=None, post_id=None, dry_run=False, known_only=False, limit=5):
    """Run the auto-apply engine in a background thread."""
    from apply_orchestrator import run_auto_apply
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(
            run_auto_apply(
                buyer_id=buyer_id,
                post_id=post_id,
                dry_run=dry_run,
                known_only=known_only,
                limit=limit,
            )
        )
    finally:
        loop.close()


@app.route("/api/apply", methods=["POST"])
def trigger_apply():
    """Trigger auto-apply for all new posts (or filtered by buyer/post).
    Body: { "buyer_id": 1, "dry_run": false, "known_only": false, "limit": 5 }"""
    data = request.get_json(silent=True) or {}
    buyer_id = data.get("buyer_id")
    dry_run = data.get("dry_run", False)
    known_only = data.get("known_only", False)
    limit = data.get("limit", 5)

    # Validate buyer if specified
    if buyer_id:
        if not db.is_buyer_active(buyer_id):
            return jsonify({"ok": False, "error": "Buyer not found or subscription inactive"}), 400

    # Run in background thread
    t = threading.Thread(
        target=_run_apply_async,
        kwargs={
            "buyer_id": buyer_id,
            "dry_run": dry_run,
            "known_only": known_only,
            "limit": limit,
        },
        daemon=True,
    )
    t.start()

    return jsonify({
        "ok": True,
        "message": "Auto-apply started in background",
        "params": {
            "buyer_id": buyer_id,
            "dry_run": dry_run,
            "known_only": known_only,
            "limit": limit,
        },
    })


@app.route("/api/apply/<int:post_id>", methods=["POST"])
def trigger_apply_single(post_id):
    """Trigger auto-apply for a single post.
    Body: { "buyer_id": 1, "dry_run": false }"""
    data = request.get_json(silent=True) or {}
    buyer_id = data.get("buyer_id")
    dry_run = data.get("dry_run", False)

    if buyer_id and not db.is_buyer_active(buyer_id):
        return jsonify({"ok": False, "error": "Buyer not found or subscription inactive"}), 400

    t = threading.Thread(
        target=_run_apply_async,
        kwargs={"buyer_id": buyer_id, "post_id": post_id, "dry_run": dry_run, "limit": 1},
        daemon=True,
    )
    t.start()

    return jsonify({"ok": True, "message": f"Auto-apply started for post {post_id}"})


@app.route("/api/applications", methods=["GET"])
def list_applications():
    """Return all applications, optionally filtered by ?buyer_id=&status="""
    buyer_id = request.args.get("buyer_id", type=int)
    status = request.args.get("status", "").strip() or None
    return jsonify(db.get_all_applications(buyer_id=buyer_id, status=status))


@app.route("/api/applications/<int:app_id>", methods=["GET"])
def get_application_detail(app_id):
    """Return a single application with its submission logs."""
    app = db.get_application(app_id)
    if not app:
        return jsonify({"ok": False, "error": "Application not found"}), 404
    logs = db.get_submission_logs(app_id)
    return jsonify({"application": app, "logs": logs})


@app.route("/api/applications/<int:app_id>/screenshot", methods=["GET"])
def get_application_screenshot(app_id):
    """Download the latest screenshot for an application."""
    logs = db.get_submission_logs(app_id)
    for log in reversed(logs):
        ss = log.get("screenshot_path", "")
        if ss and os.path.exists(ss):
            return send_file(ss, as_attachment=True, download_name=os.path.basename(ss))
    return jsonify({"ok": False, "error": "No screenshot found"}), 404


@app.route("/api/apply/stats", methods=["GET"])
def apply_stats():
    """Return application statistics."""
    buyer_id = request.args.get("buyer_id", type=int)
    return jsonify(db.get_application_stats(buyer_id=buyer_id))


@app.route("/api/submission-logs", methods=["GET"])
def list_submission_logs():
    """Return all submission logs."""
    return jsonify(db.get_all_submission_logs())


@app.route("/api/failure-queue", methods=["GET"])
def list_failure_queue():
    """Return failure queue entries."""
    buyer_id = request.args.get("buyer_id", type=int)
    resolved = request.args.get("resolved", "false").lower() == "true"
    return jsonify(db.get_failure_queue(buyer_id=buyer_id, resolved=resolved))


@app.route("/api/failure-queue/<int:queue_id>/resolve", methods=["POST"])
def resolve_failure_entry(queue_id):
    """Mark a failure queue entry as resolved."""
    ok = db.resolve_failure(queue_id)
    if not ok:
        return jsonify({"ok": False, "error": "Queue entry not found"}), 404
    print(f"[API] Failure queue entry {queue_id} resolved")
    return jsonify({"ok": True})


@app.route("/api/portal-profiles", methods=["GET"])
def list_portal_profiles():
    """Return all known ATS portal profiles."""
    return jsonify(db.get_all_portal_profiles())


@app.route("/api/agent-buyers/<int:buyer_id>/subscription", methods=["PATCH"])
def update_subscription(buyer_id):
    """Update subscription status for an agent buyer.
    Body: { "status": "active"|"inactive", "expires_at": "2026-12-31" }"""
    data = request.get_json(silent=True) or {}
    status = (data.get("status") or "").strip()
    expires_at = (data.get("expires_at") or "").strip()
    if not status:
        return jsonify({"ok": False, "error": "status is required"}), 400
    try:
        ok = db.update_buyer_subscription(buyer_id, status, expires_at)
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    if not ok:
        return jsonify({"ok": False, "error": "Buyer not found"}), 404
    print(f"[API] Buyer {buyer_id} subscription → {status}")
    return jsonify({"ok": True})


# --------------------------------------------------------------------------- #
#  API: CSV export                                                             #
# --------------------------------------------------------------------------- #
@app.route("/api/export", methods=["GET"])
def export_csv():
    users  = db.get_all_users()
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "ID", "Name", "Last Name", "Email", "Password (SHA-256)",
        "LinkedIn URL", "Mobile Number", "Submitted At", "Status", "Reject Reason"
    ])
    for u in users:
        writer.writerow([
            u["id"],
            u["name"],
            u["last_name"],
            u["email"],
            u["password_hash"],
            u["linkedin_url"],
            u["mobile_number"],
            u["submitted_at"],
            u["status"],
            u.get("reject_reason", ""),
        ])
    output.seek(0)
    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=iitiim_users.csv"},
    )


# --------------------------------------------------------------------------- #
#  API: Agent Integration                                                      #
# --------------------------------------------------------------------------- #
from agent import run_agent

class CurrentUserHelper:
    @property
    def id(self):
        # Extract user_id from the JSON payload or query parameters, default to 1
        if request.is_json:
            return request.json.get("user_id") or 1
        return 1

current_user = CurrentUserHelper()

@app.route("/apply", methods=["POST"])
def apply():
    form_url = request.json.get("form_url")
    if not form_url:
        return jsonify({"ok": False, "error": "form_url is required"}), 400

    # Ensure resumes folder exists
    os.makedirs("resumes", exist_ok=True)
    resume_path = f"resumes/{current_user.id}.pdf"
    
    # Fallback to sample resume if user-specific resume doesn't exist yet
    if not os.path.exists(resume_path):
        sample_path = "resumes/IITIIMJobAssistant_SampleCV.pdf"
        if os.path.exists(sample_path):
            print(f"[API] {resume_path} not found. Using sample: {sample_path}")
            resume_path = sample_path
        else:
            # Create a dummy file if sample is missing to avoid erroring out immediately
            with open(resume_path, "w") as f:
                f.write("Dummy resume text.")

    asyncio.run(run_agent(
        resume_path=resume_path,
        form_url=form_url,
        user_id=current_user.id
    ))
    return jsonify({"ok": True, "message": "Agent completed application successfully"})


# --------------------------------------------------------------------------- #
#  Admin JWT Authentication & RBAC                                              #
# --------------------------------------------------------------------------- #
import jwt
import functools
import secrets

# JWT secret — auto-generated if not set in environment
ADMIN_JWT_SECRET = os.environ.get("ADMIN_JWT_SECRET", "")
if not ADMIN_JWT_SECRET:
    ADMIN_JWT_SECRET = secrets.token_hex(32)
    print(f"[Auth] Auto-generated ADMIN_JWT_SECRET (set in .env for persistence)")

ADMIN_JWT_EXPIRY_HOURS = 24


def _get_client_ip():
    """Extract client IP address from request."""
    return request.headers.get("X-Forwarded-For", request.remote_addr or "")


def admin_required(f):
    """Decorator: require a valid admin JWT token."""
    @functools.wraps(f)
    def decorated(*args, **kwargs):
        auth_header = request.headers.get("Authorization", "")
        token = auth_header.replace("Bearer ", "") if auth_header.startswith("Bearer ") else ""
        if not token:
            return jsonify({"ok": False, "error": "Authentication required"}), 401
        try:
            payload = jwt.decode(token, ADMIN_JWT_SECRET, algorithms=["HS256"])
            admin = db.get_admin_by_id(payload.get("admin_id"))
            if not admin:
                return jsonify({"ok": False, "error": "Admin account not found"}), 401
            request.admin = admin
        except jwt.ExpiredSignatureError:
            return jsonify({"ok": False, "error": "Token expired — please sign in again"}), 401
        except (jwt.InvalidTokenError, Exception):
            return jsonify({"ok": False, "error": "Invalid token"}), 401
        return f(*args, **kwargs)
    return decorated


def require_role(*roles):
    """Decorator: restrict to specific admin roles. Must be used AFTER @admin_required."""
    def decorator(f):
        @functools.wraps(f)
        def decorated(*args, **kwargs):
            if request.admin.get("role") not in roles:
                return jsonify({"ok": False, "error": "Insufficient permissions"}), 403
            return f(*args, **kwargs)
        return decorated
    return decorator


# --------------------------------------------------------------------------- #
#  Admin API: Login                                                             #
# --------------------------------------------------------------------------- #
@app.route("/admin/login", methods=["POST"])
def admin_login():
    """Admin login — returns a JWT token on success."""
    data = request.get_json(silent=True) or {}
    email = (data.get("email") or "").strip()
    password = (data.get("password") or "").strip()

    if not email or not password:
        return jsonify({"ok": False, "error": "Email and password are required"}), 400

    admin = db.verify_admin_login(email, password)
    if not admin:
        return jsonify({"ok": False, "error": "Invalid email or password"}), 401

    # Generate JWT
    from datetime import timedelta
    payload = {
        "admin_id": admin["id"],
        "email": admin["email"],
        "role": admin["role"],
        "exp": datetime.now(timezone.utc) + timedelta(hours=ADMIN_JWT_EXPIRY_HOURS),
        "iat": datetime.now(timezone.utc),
    }
    token = jwt.encode(payload, ADMIN_JWT_SECRET, algorithm="HS256")

    # Audit log
    db.create_audit_log(
        admin_id=admin["id"],
        admin_email=admin["email"],
        action="ADMIN_LOGIN",
        ip_address=_get_client_ip(),
    )

    print(f"[Admin] Login: {admin['email']} (role={admin['role']})")
    return jsonify({
        "ok": True,
        "token": token,
        "admin": {
            "id": admin["id"],
            "email": admin["email"],
            "role": admin["role"],
            "name": admin["name"],
        },
    })


@app.route("/admin/me", methods=["GET"])
@admin_required
def admin_me():
    """Return current admin info."""
    a = request.admin
    return jsonify({
        "ok": True,
        "admin": {
            "id": a["id"],
            "email": a["email"],
            "role": a["role"],
            "name": a["name"],
            "last_login_at": a.get("last_login_at", ""),
        },
    })


# --------------------------------------------------------------------------- #
#  Admin API: Dashboard                                                         #
# --------------------------------------------------------------------------- #
@app.route("/admin/dashboard", methods=["GET"])
@admin_required
def admin_dashboard():
    """Return dashboard stats."""
    date_from = request.args.get("date_from", "")
    date_to = request.args.get("date_to", "")
    stats = db.get_admin_dashboard_stats(date_from, date_to)
    return jsonify({"ok": True, **stats})


@app.route("/admin/dashboard/signups", methods=["GET"])
@admin_required
def admin_dashboard_signups():
    """Return daily signup data for chart."""
    days = request.args.get("days", 30, type=int)
    date_from = request.args.get("date_from", "")
    date_to = request.args.get("date_to", "")
    data = db.get_daily_signups(days, date_from, date_to)
    return jsonify({"ok": True, "signups": data})


# --------------------------------------------------------------------------- #
#  Admin API: Verifications (Approval Queue)                                    #
# --------------------------------------------------------------------------- #
@app.route("/admin/verifications", methods=["GET"])
@admin_required
def admin_verifications():
    """Return verification requests (approval queue)."""
    status = request.args.get("status", "")
    page = request.args.get("page", 1, type=int)
    per_page = request.args.get("per_page", 50, type=int)
    search = request.args.get("search", "")
    result = db.get_verifications(status, page, per_page, search)
    return jsonify({"ok": True, **result})


@app.route("/admin/verifications/<int:verif_id>", methods=["GET"])
@admin_required
def admin_verification_detail(verif_id):
    """Return a single verification request with full user data."""
    v = db.get_verification(verif_id)
    if not v:
        return jsonify({"ok": False, "error": "Verification not found"}), 404
    return jsonify({"ok": True, "verification": v})


@app.route("/admin/verifications/<int:verif_id>/approve", methods=["POST"])
@admin_required
def admin_approve_verification(verif_id):
    """Approve a verification request."""
    admin = request.admin
    v = db.get_verification(verif_id)
    if not v:
        return jsonify({"ok": False, "error": "Verification not found"}), 404

    prev_status = v.get("status", "PENDING")
    ok = db.approve_verification(verif_id, admin["id"])
    if not ok:
        return jsonify({"ok": False, "error": "Could not approve verification"}), 500

    # Audit log
    db.create_audit_log(
        admin_id=admin["id"],
        admin_email=admin["email"],
        action="VERIFICATION_APPROVED",
        target_user_id=v.get("user_id"),
        previous_value=prev_status,
        new_value="APPROVED",
        reason="Admin verified LinkedIn profile",
        ip_address=_get_client_ip(),
    )

    print(f"[Admin] Verification {verif_id} APPROVED by {admin['email']}")
    return jsonify({"ok": True})


@app.route("/admin/verifications/<int:verif_id>/reject", methods=["POST"])
@admin_required
def admin_reject_verification(verif_id):
    """Reject a verification request. Requires a reason."""
    admin = request.admin
    data = request.get_json(silent=True) or {}
    reason = (data.get("reason") or "").strip()

    if not reason:
        return jsonify({"ok": False, "error": "Rejection reason is required"}), 400

    v = db.get_verification(verif_id)
    if not v:
        return jsonify({"ok": False, "error": "Verification not found"}), 404

    prev_status = v.get("status", "PENDING")
    ok = db.reject_verification(verif_id, admin["id"], reason)
    if not ok:
        return jsonify({"ok": False, "error": "Could not reject verification"}), 500

    # Audit log
    db.create_audit_log(
        admin_id=admin["id"],
        admin_email=admin["email"],
        action="VERIFICATION_REJECTED",
        target_user_id=v.get("user_id"),
        previous_value=prev_status,
        new_value="REJECTED",
        reason=reason,
        ip_address=_get_client_ip(),
    )

    print(f"[Admin] Verification {verif_id} REJECTED by {admin['email']} — {reason}")
    return jsonify({"ok": True})


# --------------------------------------------------------------------------- #
#  Admin API: User Directory                                                    #
# --------------------------------------------------------------------------- #
@app.route("/admin/users", methods=["GET"])
@admin_required
def admin_users():
    """Paginated user directory with search, filter, sort."""
    page = request.args.get("page", 1, type=int)
    per_page = request.args.get("per_page", 20, type=int)
    search = request.args.get("search", "")
    status_filter = request.args.get("status", "")
    subscription_filter = request.args.get("subscription", "")
    sort_by = request.args.get("sort_by", "submitted_at")
    sort_dir = request.args.get("sort_dir", "DESC")
    result = db.get_users_paginated(page, per_page, search, status_filter,
                                     subscription_filter, sort_by, sort_dir)
    return jsonify({"ok": True, **result})


@app.route("/admin/users/<int:user_id>", methods=["GET"])
@admin_required
def admin_user_detail(user_id):
    """Return full user detail with activity summary."""
    user = db.get_user_detail(user_id)
    if not user:
        return jsonify({"ok": False, "error": "User not found"}), 404
    return jsonify({"ok": True, "user": user})


# --------------------------------------------------------------------------- #
#  Admin API: Audit Logs                                                        #
# --------------------------------------------------------------------------- #
@app.route("/admin/audit-logs", methods=["GET"])
@admin_required
def admin_audit_logs():
    """Paginated audit log with search, filter, date range."""
    page = request.args.get("page", 1, type=int)
    per_page = request.args.get("per_page", 50, type=int)
    search = request.args.get("search", "")
    action_filter = request.args.get("action", "")
    date_from = request.args.get("date_from", "")
    date_to = request.args.get("date_to", "")
    result = db.get_audit_logs(page, per_page, search, action_filter, date_from, date_to)
    return jsonify({"ok": True, **result})


# --------------------------------------------------------------------------- #
#  Admin API: Admin Management                                                  #
# --------------------------------------------------------------------------- #
@app.route("/admin/admins", methods=["GET"])
@admin_required
@require_role("SUPER_ADMIN")
def admin_list_admins():
    """List all admin accounts. Super Admin only."""
    admins = db.get_all_admins()
    # Remove password hashes from response
    for a in admins:
        a.pop("password_hash", None)
    return jsonify({"ok": True, "admins": admins})


@app.route("/admin/admins", methods=["POST"])
@admin_required
@require_role("SUPER_ADMIN")
def admin_create_admin():
    """Create a new admin account. Super Admin only."""
    data = request.get_json(silent=True) or {}
    email = (data.get("email") or "").strip()
    password = (data.get("password") or "").strip()
    role = (data.get("role") or "ADMIN").strip().upper()
    name = (data.get("name") or "").strip()

    if not email or not password:
        return jsonify({"ok": False, "error": "Email and password are required"}), 400

    try:
        admin = db.create_admin(email, password, role, name)
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400

    admin.pop("password_hash", None)

    # Audit log
    db.create_audit_log(
        admin_id=request.admin["id"],
        admin_email=request.admin["email"],
        action="ADMIN_CREATED",
        reason=f"Created admin: {email} (role={role})",
        ip_address=_get_client_ip(),
    )

    print(f"[Admin] New admin created: {email} (role={role}) by {request.admin['email']}")
    return jsonify({"ok": True, "admin": admin}), 201


# --------------------------------------------------------------------------- #
#  API: Razorpay Payments                                                       #
# --------------------------------------------------------------------------- #
import hmac
import hashlib as _hashlib
import razorpay

# Initialise Razorpay client from environment variables
_rzp_key_id     = os.environ.get("RAZORPAY_KEY_ID", "")
_rzp_key_secret = os.environ.get("RAZORPAY_KEY_SECRET", "")

if _rzp_key_id and _rzp_key_secret:
    razorpay_client = razorpay.Client(auth=(_rzp_key_id, _rzp_key_secret))
    print(f"[Razorpay] Client initialised (key: {_rzp_key_id[:12]}...)")
else:
    razorpay_client = None
    print("[Razorpay] WARNING: RAZORPAY_KEY_ID / RAZORPAY_KEY_SECRET not set — payment endpoints disabled")


@app.route("/pay")
def pay_page():
    """Serve the payment checkout page."""
    return app.send_static_file("pay.html")


@app.route("/api/razorpay-key", methods=["GET"])
def razorpay_key():
    """Return the public Razorpay Key ID to the frontend (never the secret)."""
    if not _rzp_key_id:
        return jsonify({"ok": False, "error": "Razorpay not configured"}), 503
    return jsonify({"ok": True, "key_id": _rzp_key_id})


@app.route("/api/create-order", methods=["POST"])
def create_order():
    """Create a Razorpay order.
    Body: { "amount": 49900, "currency": "INR", "receipt": "order_xyz", "buyer_id": 1 }
    amount is in paise (₹499 = 49900 paise). Minimum 100 paise (₹1).
    """
    if not razorpay_client:
        return jsonify({"ok": False, "error": "Razorpay not configured on server"}), 503

    data = request.get_json(silent=True) or {}
    amount   = data.get("amount")
    currency = (data.get("currency") or "INR").upper()
    receipt  = (data.get("receipt") or "").strip()
    buyer_id = data.get("buyer_id")

    # Validation
    if amount is None:
        return jsonify({"ok": False, "error": "amount is required (in paise)"}), 400
    try:
        amount = int(amount)
    except (ValueError, TypeError):
        return jsonify({"ok": False, "error": "amount must be an integer (paise)"}), 400
    if amount < 100:
        return jsonify({"ok": False, "error": "Minimum amount is 100 paise (₹1)"}), 400

    # Auto-generate receipt if not provided
    if not receipt:
        receipt = f"rcpt_{int(datetime.now(timezone.utc).timestamp())}"

    # Create order via Razorpay API
    try:
        order = razorpay_client.order.create({
            "amount":   amount,
            "currency": currency,
            "receipt":  receipt,
        })
    except razorpay.errors.BadRequestError as e:
        print(f"[Razorpay] Bad request: {e}")
        return jsonify({"ok": False, "error": f"Razorpay error: {str(e)}"}), 400
    except razorpay.errors.ServerError as e:
        print(f"[Razorpay] Server error: {e}")
        return jsonify({"ok": False, "error": "Razorpay server error — try again later"}), 500
    except Exception as e:
        print(f"[Razorpay] Unexpected error: {e}")
        return jsonify({"ok": False, "error": f"Payment gateway error: {str(e)[:100]}"}), 500

    # Record in DB
    db.create_payment_record(
        razorpay_order_id=order["id"],
        amount_paise=amount,
        currency=currency,
        receipt=receipt,
        buyer_id=buyer_id,
    )

    print(f"[Razorpay] Order created: {order['id']}  amount={amount} paise")
    return jsonify({
        "ok":       True,
        "order_id": order["id"],
        "amount":   order["amount"],
        "currency": order["currency"],
    })


@app.route("/api/verify-payment", methods=["POST"])
def verify_payment():
    """Verify a Razorpay payment signature.
    Body: { "razorpay_order_id", "razorpay_payment_id", "razorpay_signature" }
    Uses HMAC-SHA256(order_id|payment_id, KEY_SECRET) to verify.
    """
    if not _rzp_key_secret:
        return jsonify({"ok": False, "error": "Razorpay not configured on server"}), 503

    data = request.get_json(silent=True) or {}
    order_id   = (data.get("razorpay_order_id")   or "").strip()
    payment_id = (data.get("razorpay_payment_id") or "").strip()
    signature  = (data.get("razorpay_signature")  or "").strip()

    if not order_id or not payment_id or not signature:
        return jsonify({"ok": False, "error": "razorpay_order_id, razorpay_payment_id, and razorpay_signature are required"}), 400

    # HMAC-SHA256 verification
    message = f"{order_id}|{payment_id}"
    expected_signature = hmac.new(
        _rzp_key_secret.encode("utf-8"),
        message.encode("utf-8"),
        _hashlib.sha256,
    ).hexdigest()

    if not hmac.compare_digest(expected_signature, signature):
        print(f"[Razorpay] Signature mismatch for order {order_id}")
        db.fail_payment_record(order_id, "signature_mismatch")
        return jsonify({"ok": False, "error": "Payment verification failed — signature mismatch"}), 400

    # Mark payment as verified
    db.verify_payment_record(order_id, payment_id, signature)
    print(f"[Razorpay] Payment verified: order={order_id} payment={payment_id}")
    return jsonify({"ok": True, "message": "Payment verified successfully"})


@app.route("/api/payments", methods=["GET"])
def list_payments():
    """Return all payment records. Optional: ?status=created|paid|failed"""
    status = request.args.get("status", "").strip() or None
    return jsonify(db.get_all_payments(status))


# --------------------------------------------------------------------------- #
#  Run                                                                         #
# --------------------------------------------------------------------------- #
if __name__ == "__main__":
    print("=" * 60)
    print("  IITIIMJobAssistant Backend Server")
    print("  User app  : http://127.0.0.1:5000")
    print("  Admin     : http://127.0.0.1:5000/admin")
    print("  Payment   : http://127.0.0.1:5000/pay")
    print("  Jobs API  : http://127.0.0.1:5000/api/jobs")
    print("  Posts API : http://127.0.0.1:5000/api/posts")
    print("  Buyers API: http://127.0.0.1:5000/api/agent-buyers")
    print("  Apply API : http://127.0.0.1:5000/api/apply")
    print("  Apps API  : http://127.0.0.1:5000/api/applications")
    print("  Failures  : http://127.0.0.1:5000/api/failure-queue")
    print("  Payments  : http://127.0.0.1:5000/api/payments")
    print("  ─── Admin API ───")
    print("  POST /admin/login")
    print("  GET  /admin/dashboard")
    print("  GET  /admin/verifications")
    print("  GET  /admin/users")
    print("  GET  /admin/audit-logs")
    print("  ─── Razorpay API ───")
    print("  POST /api/create-order")
    print("  POST /api/verify-payment")
    print("  GET  /api/payments")
    print("=" * 60)
    app.run(host="0.0.0.0", port=5000, debug=False)

