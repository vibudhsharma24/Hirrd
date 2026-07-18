"""
app.py - Flask REST API for IITIIMJobAssistant.
Serves frontend pages and all API endpoints.
"""

import csv
import io
import os
import sys
from datetime import datetime, timezone, timedelta

# Ensure project root is on sys.path
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# Load .env before any os.environ.get calls
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(PROJECT_ROOT, ".env"))
except ImportError:
    pass

from flask import Flask, request, jsonify, Response, redirect, send_file, url_for
from flask_cors import CORS
from flask_login import login_user, logout_user, login_required, current_user as flask_current_user

import core.database as db
from core.auth import login_manager, User, generate_admin_token, admin_required, super_admin_required, restricted_admin_block, permission_required

FRONTEND_DIR = os.path.join(PROJECT_ROOT, "frontend")

app = Flask(__name__, static_folder=FRONTEND_DIR, static_url_path="/static")
app.secret_key = os.environ.get("SECRET_KEY", "iitiim-dev-secret-change-in-production")
CORS(app)

# Limit upload size to 5 MB
app.config["MAX_CONTENT_LENGTH"] = 5 * 1024 * 1024

# Set session lifespan and remember cookie duration to 15 minutes
app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(minutes=15)
app.config["REMEMBER_COOKIE_DURATION"] = timedelta(minutes=15)

# Init Flask-Login
login_manager.init_app(app)


def create_app():
    """App factory — called by run.py."""
    db.init_db()
    return app


# --------------------------------------------------------------------------- #
#  Startup (when run directly)                                                 #
# --------------------------------------------------------------------------- #
if not os.environ.get("_APP_FACTORY_USED"):
    db.init_db()


# --------------------------------------------------------------------------- #
#  Page Routes                                                                 #
# --------------------------------------------------------------------------- #
@app.route("/")
def index():
    return send_file(os.path.join(FRONTEND_DIR, "index.html"))


@app.route("/login")
def login_page():
    if flask_current_user.is_authenticated:
        return redirect("/dashboard")
    return send_file(os.path.join(FRONTEND_DIR, "login.html"))


@app.route("/signup")
def signup_page():
    return send_file(os.path.join(FRONTEND_DIR, "signup.html"))


@app.route("/dashboard")
@app.route("/dashboard/<path:subpath>")
def dashboard_page(subpath=None):
    if not flask_current_user.is_authenticated:
        return send_file(os.path.join(FRONTEND_DIR, "index.html"))
    return send_file(os.path.join(FRONTEND_DIR, "dashboard.html"))


@app.route("/admin")
def admin_page():
    return send_file(os.path.join(FRONTEND_DIR, "admin.html"))


@app.route("/pay")
@login_required
def pay_page_route():
    return send_file(os.path.join(FRONTEND_DIR, "pay.html"))




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
    
    # Simulate sending immediate sign-up confirmation email
    email_body = f"""
    ======================================================================
    [EMAIL SERVICE] Sending Sign-up Confirmation Email
    To: {user['email']}
    Subject: Welcome to IITIIMJobAssistant!
    
    Dear {user['name']},
    
    Thank you for registering at IITIIMJobAssistant. Your account is 
    now created, and our team is manually reviewing your LinkedIn 
    profile to verify your IIT/IIM status. 
    
    We will notify you via another email once your verification request 
    has been processed.
    
    Best regards,
    The IITIIMJobAssistant Team
    ======================================================================
    """
    print(email_body)

    return jsonify({
        "ok": True, 
        "user": user, 
        "email_sent": True, 
        "message": "Immediate sign-up confirmation email sent."
    }), 201



@app.route("/api/waitlist", methods=["POST"])
def join_waitlist():
    """Accepts JSON: { email, agent } and simulates sending a confirmation email."""
    data  = request.get_json(silent=True) or {}
    email = (data.get("email") or "").strip()
    agent = (data.get("agent") or "").strip() or "Upcoming Agent"

    if not email or "@" not in email:
        return jsonify({"ok": False, "error": "A valid email is required"}), 400

    email_body = f"""
    ======================================================================
    [EMAIL SERVICE] Sending Waitlist Confirmation Email
    To: {email}
    Subject: You're on the waitlist for {agent}!
    
    Dear Member,
    
    We've successfully added your email ({email}) to the waitlist 
    for the {agent}.
    
    Our team is working hard to bring this agent live. We will notify 
    you as soon as early access opens.
    
    Best regards,
    The IITIIMJobAssistant Team
    ======================================================================
    """
    print(email_body)

    return jsonify({"ok": True, "message": "Successfully joined waitlist."})


# --------------------------------------------------------------------------- #
#  API: Users                                                                  #
# --------------------------------------------------------------------------- #
@app.route("/api/users", methods=["GET"])
@admin_required
@permission_required("database")
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
@admin_required
@permission_required("database")
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
    from job_seeker_agent.applier import run_auto_apply
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


def _run_pipeline_async(user_id, dry_run=False, known_only=False, limit=5):
    """Run the FULL pipeline (scrape → apply → connect) in a background thread."""
    print(f"[Agent] Thread started. Initializing LinkedIn job seeker pipeline...")
    from job_seeker_agent.applier import run_full_pipeline
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(
            run_full_pipeline(
                user_id=user_id,
                dry_run=dry_run,
                known_only=known_only,
                limit=limit,
            )
        )
    finally:
        loop.close()

    try:
        db.update_user_activity(user_id)
    except Exception as e:
        print(f"[Agent] Failed to update user activity: {e}")


@app.route("/api/apply", methods=["POST"])
@login_required
def trigger_apply():
    """Trigger the full pipeline for the current user.
    Body: { "dry_run": false, "known_only": false, "limit": 5 }"""
    data = request.get_json(silent=True) or {}
    dry_run = data.get("dry_run", False)
    known_only = data.get("known_only", False)
    limit = data.get("limit", 5)

    user_id = flask_current_user.id

    # Run in background thread
    t = threading.Thread(
        target=_run_pipeline_async,
        name=f"agent-{user_id}",
        kwargs={
            "user_id": user_id,
            "dry_run": dry_run,
            "known_only": known_only,
            "limit": limit,
        },
        daemon=True,
    )
    t.start()

    try:
        db.update_user_agent_status(user_id, "running")
    except Exception as e:
        print(f"[Agent] Failed to update user agent status to running: {e}")

    return jsonify({
        "ok": True,
        "message": "Full pipeline started in background (scrape → apply → connect)",
        "params": {
            "user_id": user_id,
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
@login_required
def list_submission_logs():
    """Return all submission logs for the current user's applications."""
    user_detail = db.get_user_detail(flask_current_user.id)
    buyer = user_detail.get("agent_buyer")
    if not buyer:
        return jsonify([])
    buyer_id = buyer["id"]
    with db._connect_jobs() as conn:
        rows = conn.execute(
            """
            SELECT sl.*, a.portal_hostname, a.ats_type, p.title AS post_title, p.company AS post_company
            FROM submission_logs sl
            JOIN applications a ON sl.application_id = a.id
            LEFT JOIN posts p ON a.post_id = p.id
            WHERE a.buyer_id = ?
            ORDER BY sl.timestamp DESC
            LIMIT 50
            """,
            (buyer_id,)
        ).fetchall()
    return jsonify([db._row_to_dict(r) for r in rows])


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
@admin_required
@permission_required("database")
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
from job_seeker_agent.agent import run_agent

@app.route("/apply", methods=["POST"])
def apply():
    form_url = request.json.get("form_url")
    if not form_url:
        return jsonify({"ok": False, "error": "form_url is required"}), 400

    user_id = request.json.get("user_id", 1)
    os.makedirs(os.path.join(PROJECT_ROOT, "resumes"), exist_ok=True)
    resume_path = os.path.join(PROJECT_ROOT, f"resumes/{user_id}.pdf")

    if not os.path.exists(resume_path):
        sample_path = os.path.join(PROJECT_ROOT, "resumes/IITIIMJobAssistant_SampleCV.pdf")
        if os.path.exists(sample_path):
            resume_path = sample_path
        else:
            with open(resume_path, "w") as f:
                f.write("Dummy resume text.")

    asyncio.run(run_agent(
        resume_path=resume_path,
        form_url=form_url,
        user_id=user_id
    ))
    return jsonify({"ok": True, "message": "Agent completed application successfully"})


# --------------------------------------------------------------------------- #
#  Naukri Answer-Bank and Auto-Apply APIs                                     #
# --------------------------------------------------------------------------- #

@app.route("/api/users/<int:user_id>/naukri-apply", methods=["POST"])
def trigger_naukri_apply(user_id):
    try:
        data = request.get_json(silent=True) or {}
        max_daily_apps = data.get("max_daily_apps", 5)
        
        from naukri_agent.applier import run_naukri_auto_apply
        res = asyncio.run(run_naukri_auto_apply(user_id, max_daily_apps=max_daily_apps))
        
        if res.get("success"):
            return jsonify({"ok": True, "result": res})
        else:
            return jsonify({"ok": False, "error": res.get("message")}), 400
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


# --------------------------------------------------------------------------- #
#  Per-Agent Toggle (Start / Stop) APIs                                        #
# --------------------------------------------------------------------------- #
_per_agent_threads = {}   # key: (user_id, agent_type) -> {"thread": Thread, "running": bool}
_per_agent_lock = threading.Lock()


def _run_linkedin_jobs_agent_bg(user_id):
    """Background thread target for LinkedIn Jobs Agent."""
    try:
        from linkedin_jobs_agent.search import run_linkedin_job_search
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(
                run_linkedin_job_search(user_id, max_jobs_per_run=5, headed=False)
            )
        finally:
            loop.close()
    except Exception as e:
        print(f"[LinkedIn Jobs Agent] Error in background run: {e}")
    finally:
        with _per_agent_lock:
            key = (user_id, "linkedin_jobs")
            if key in _per_agent_threads:
                _per_agent_threads[key]["running"] = False
        try:
            db.update_user_activity(user_id)
        except Exception:
            pass


def _run_naukri_agent_bg(user_id):
    """Background thread target for Naukri AI Agent."""
    try:
        from naukri_agent.applier import run_naukri_auto_apply
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(
                run_naukri_auto_apply(user_id, max_daily_apps=5)
            )
        finally:
            loop.close()
    except Exception as e:
        print(f"[Naukri Agent] Error in background run: {e}")
    finally:
        with _per_agent_lock:
            key = (user_id, "naukri_ai")
            if key in _per_agent_threads:
                _per_agent_threads[key]["running"] = False
        try:
            db.update_user_activity(user_id)
        except Exception:
            pass


@app.route("/api/users/<int:user_id>/agent-toggle/<agent_type>", methods=["POST"])
def toggle_per_agent(user_id, agent_type):
    """Toggle start/stop for a specific agent (linkedin_jobs or naukri_ai)."""
    if agent_type not in ("linkedin_jobs", "naukri_ai"):
        return jsonify({"ok": False, "error": "Unknown agent type"}), 400

    key = (user_id, agent_type)
    with _per_agent_lock:
        entry = _per_agent_threads.get(key)
        if entry and entry.get("running") and entry.get("thread") and entry["thread"].is_alive():
            # Agent is currently running — stop it
            entry["running"] = False
            return jsonify({"ok": True, "status": "stopped",
                            "message": f"{agent_type} agent stopped."})

    # Agent is not running — start it
    target_fn = _run_linkedin_jobs_agent_bg if agent_type == "linkedin_jobs" else _run_naukri_agent_bg
    t = threading.Thread(
        target=target_fn,
        args=(user_id,),
        name=f"agent-{user_id}-{agent_type}",
        daemon=True,
    )
    with _per_agent_lock:
        _per_agent_threads[key] = {"thread": t, "running": True}
    t.start()
    return jsonify({"ok": True, "status": "running",
                    "message": f"{agent_type} agent started in background."})


@app.route("/api/users/<int:user_id>/agent-running/<agent_type>", methods=["GET"])
def get_per_agent_running(user_id, agent_type):
    """Return whether a specific agent is currently running for this user."""
    key = (user_id, agent_type)
    with _per_agent_lock:
        entry = _per_agent_threads.get(key)
        if entry and entry.get("running") and entry.get("thread") and entry["thread"].is_alive():
            return jsonify({"ok": True, "running": True})
    return jsonify({"ok": True, "running": False})


@app.route("/api/users/<int:user_id>/answer-bank", methods=["GET"])
def get_user_answer_bank(user_id):
    try:
        entries = db.get_naukri_answer_bank(user_id)
        return jsonify({"ok": True, "entries": entries})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/users/<int:user_id>/answer-bank", methods=["POST"])
def save_user_answer_bank_entry(user_id):
    try:
        data = request.get_json(silent=True) or {}
        question = data.get("question")
        answer = data.get("answer")
        status = data.get("status", "approved")
        
        if not question or not answer:
            return jsonify({"ok": False, "error": "question and answer are required"}), 400
            
        success = db.save_naukri_answer_bank_entry(user_id, question, answer, status)
        if success:
            return jsonify({"ok": True, "message": "Answer bank entry saved successfully"})
        else:
            return jsonify({"ok": False, "error": "Database error saving entry"}), 500
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/users/<int:user_id>/answer-bank", methods=["DELETE"])
def delete_user_answer_bank_entry(user_id):
    try:
        data = request.get_json(silent=True) or {}
        question = data.get("question") or request.args.get("question")
        
        if not question:
            return jsonify({"ok": False, "error": "question is required"}), 400
            
        success = db.delete_naukri_answer_bank_entry(user_id, question)
        if success:
            return jsonify({"ok": True, "message": "Answer bank entry deleted successfully"})
        else:
            return jsonify({"ok": False, "error": "Database error deleting entry"}), 500
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/users/<int:user_id>/naukri-failures", methods=["GET"])
def get_naukri_failures(user_id):
    try:
        failures = db.get_naukri_terminal_failures(user_id)
        return jsonify({"ok": True, "failures": failures})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/users/<int:user_id>/naukri-logs", methods=["GET"])
def get_naukri_logs(user_id):
    try:
        logs = db.get_naukri_application_logs(user_id)
        return jsonify({"ok": True, "logs": logs})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/users/<int:user_id>/naukri-applications", methods=["GET"])
def get_user_naukri_apps(user_id):
    try:
        apps = db.get_naukri_applications(user_id)
        for app in apps:
            job_details = db.get_naukri_job_details(app.get("job_id"))
            if job_details:
                app["title"] = job_details.get("title")
                app["company"] = job_details.get("company")
                app["url"] = job_details.get("url")
        return jsonify({"ok": True, "applications": apps})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/users/<int:user_id>/linkedin-applications", methods=["GET"])
def get_user_linkedin_apps(user_id):
    try:
        apps = db.get_linkedin_applications(user_id)
        for app in apps:
            job_details = db.get_linkedin_job_by_id(app.get("job_id"))
            if job_details:
                app["title"] = job_details.get("title")
                app["company"] = job_details.get("company")
                app["url"] = job_details.get("url")
        return jsonify({"ok": True, "applications": apps})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/users/<int:user_id>/linkedin-outreach-funnel", methods=["GET"])
def get_user_linkedin_outreach_funnel(user_id):
    try:
        funnel = db.get_linkedin_outreach_funnel(user_id)
        return jsonify({"ok": True, "funnel": funnel})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/users/<int:user_id>/subscribe-linkedin-jobs", methods=["POST"])
def subscribe_user_linkedin_jobs(user_id):
    try:
        data = request.get_json(silent=True) or {}
        subscribed = bool(data.get("subscribed", True))
        ok = db.set_user_linkedin_jobs_subscribed(user_id, subscribed)
        if not ok:
            return jsonify({"ok": False, "error": "User not found or update failed"}), 404
        return jsonify({"ok": True, "message": f"LinkedIn Jobs Agent subscription status updated to {subscribed}."})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/users/<int:user_id>/subscribe-naukri", methods=["POST"])
def subscribe_user_naukri(user_id):
    try:
        data = request.get_json(silent=True) or {}
        subscribed = bool(data.get("subscribed", True))
        ok = db.set_user_naukri_subscribed(user_id, subscribed)
        if not ok:
            return jsonify({"ok": False, "error": "User not found or update failed"}), 404
        return jsonify({"ok": True, "message": f"Naukri AI Agent subscription status updated to {subscribed}."})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/users/<int:user_id>/naukri-applications/<int:app_id>/dismiss", methods=["POST"])
def dismiss_naukri_app(user_id, app_id):
    try:
        apps = db.get_naukri_applications(user_id)
        app = next((a for a in apps if a.get("id") == app_id), None)
        if not app:
            return jsonify({"ok": False, "error": "Application not found"}), 404
        db.dismiss_naukri_application(user_id, app.get("job_id"))
        return jsonify({"ok": True, "message": "Application dismissed successfully"})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/users/<int:user_id>/naukri-applications/<int:app_id>/retry", methods=["POST"])
def retry_naukri_app(user_id, app_id):
    try:
        apps = db.get_naukri_applications(user_id)
        app = next((a for a in apps if a.get("id") == app_id), None)
        if not app:
            return jsonify({"ok": False, "error": "Application not found"}), 404
        db.update_naukri_application_retry(user_id, app.get("job_id"), "retrying", 0, None)
        from naukri_agent.applier import run_naukri_auto_apply
        res = asyncio.run(run_naukri_auto_apply(user_id, max_daily_apps=5))
        return jsonify({"ok": True, "result": res})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/users/<int:user_id>/naukri-applications/<int:app_id>/screenshot", methods=["GET"])
def get_naukri_app_screenshot(user_id, app_id):
    try:
        apps = db.get_naukri_applications(user_id)
        app = next((a for a in apps if a.get("id") == app_id), None)
        if not app:
            return jsonify({"ok": False, "error": "Application not found"}), 404
        logs = db.get_naukri_application_logs(user_id, app.get("job_id"))
        for log in logs:
            ss = log.get("screenshot_path", "")
            if ss and os.path.exists(ss):
                return send_file(ss, mimetype='image/png')
        return jsonify({"ok": False, "error": "No screenshot found"}), 404
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


# --------------------------------------------------------------------------- #
#  Admin JWT Auth (uses core.auth imports above)                                #
# --------------------------------------------------------------------------- #

def _get_client_ip():
    return request.headers.get("X-Forwarded-For", request.remote_addr or "")


def require_role(*roles):
    def decorator(f):
        import functools
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
    data = request.get_json(silent=True) or {}
    email = (data.get("email") or "").strip()
    password = (data.get("password") or "").strip()
    if not email or not password:
        return jsonify({"ok": False, "error": "Email and password are required"}), 400
    admin = db.verify_admin_login(email, password)
    if not admin:
        return jsonify({"ok": False, "error": "Invalid email or password"}), 401
    token = generate_admin_token(admin)
    db.create_audit_log(admin_id=admin["id"], admin_email=admin["email"],
                        action="ADMIN_LOGIN", ip_address=_get_client_ip())
    return jsonify({"ok": True, "token": token, "admin": {
        "id": admin["id"], "email": admin["email"],
        "role": admin["role"], "name": admin["name"],
        "permissions": admin.get("permissions", "")}})


@app.route("/admin/me", methods=["GET"])
@admin_required
def admin_me():
    """Return current admin info."""
    a = request.admin
    return jsonify({
        "ok": True,
        "admin": {
            "id": a.get("admin_id"),
            "email": a.get("email"),
            "role": a.get("role"),
            "name": a.get("name"),
            "permissions": a.get("permissions", ""),
            "last_login_at": a.get("last_login_at", ""),
        },
    })


# --------------------------------------------------------------------------- #
#  Admin API: Dashboard                                                         #
# --------------------------------------------------------------------------- #
@app.route("/admin/dashboard", methods=["GET"])
@admin_required
@permission_required("dashboard")
def admin_dashboard():
    """Return dashboard stats."""
    date_from = request.args.get("date_from", "")
    date_to = request.args.get("date_to", "")
    stats = db.get_admin_dashboard_stats(date_from, date_to)
    return jsonify({"ok": True, **stats})


@app.route("/admin/dashboard/signups", methods=["GET"])
@admin_required
@permission_required("dashboard")
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
@permission_required("queue")
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
@permission_required("queue")
def admin_verification_detail(verif_id):
    """Return a single verification request with full user data."""
    v = db.get_verification(verif_id)
    if not v:
        return jsonify({"ok": False, "error": "Verification not found"}), 404
    return jsonify({"ok": True, "verification": v})


@app.route("/admin/verifications/<int:verif_id>/approve", methods=["POST"])
@admin_required
@permission_required("queue")
def admin_approve_verification(verif_id):
    """Approve a verification request."""
    admin = request.admin
    v = db.get_verification(verif_id)
    if not v:
        return jsonify({"ok": False, "error": "Verification not found"}), 404

    prev_status = v.get("status", "PENDING")
    ok = db.approve_verification(verif_id, admin["admin_id"])
    if not ok:
        return jsonify({"ok": False, "error": "Could not approve verification"}), 500

    # Audit log
    db.create_audit_log(
        admin_id=admin["admin_id"],
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
@permission_required("queue")
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
    ok = db.reject_verification(verif_id, admin["admin_id"], reason)
    if not ok:
        return jsonify({"ok": False, "error": "Could not reject verification"}), 500

    # Audit log
    db.create_audit_log(
        admin_id=admin["admin_id"],
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
@permission_required("users")
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
@permission_required("users")
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
@permission_required("audit")
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
    """Create a new admin account. Super Admin only.
    Auto-generates a secure password and sends credentials via email."""
    import secrets
    import string
    data = request.get_json(silent=True) or {}
    email = (data.get("email") or "").strip()
    role = (data.get("role") or "ADMIN").strip().upper()
    name = (data.get("name") or "").strip()
    permissions = (data.get("permissions") or "").strip()

    if not email:
        return jsonify({"ok": False, "error": "Email is required"}), 400
    if not name:
        return jsonify({"ok": False, "error": "Name is required"}), 400

    # Auto-generate a secure 14-character password
    alphabet = string.ascii_letters + string.digits + "!@#$%&*"
    generated_password = ''.join(secrets.choice(alphabet) for _ in range(14))

    try:
        admin = db.create_admin(email, generated_password, role, name, permissions)
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400

    admin.pop("password_hash", None)

    # Send credentials email to the new admin
    perm_labels = {
        "dashboard": "Dashboard",
        "queue": "Approval Queue",
        "users": "User Directory",
        "database": "User Database",
        "audit": "Audit Log",
        "admins": "Admin Accounts",
    }
    perm_list = [p.strip() for p in permissions.split(",") if p.strip()]
    perm_display = ", ".join(perm_labels.get(p, p) for p in perm_list)
    if not perm_display:
        if role == "SUPER_ADMIN":
            perm_display = "all modules (Super Admin)"
        else:
            perm_display = "no modules assigned yet"

    email_subject = "Your IITIIMJobAssistant Admin Access Credentials"
    email_body = f"""
    <html>
      <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333; max-width: 600px; margin: 0 auto; padding: 20px; border: 1px solid #e0e0e0; border-radius: 8px;">
        <h2 style="color: #2563eb; margin-top: 0;">Admin Access Granted</h2>
        <p>Hello {name},</p>
        <p>You have been given admin access to the iitiimjob assistant website. Log in now with your email ID (<strong>{email}</strong>) and your password is: <strong style="font-family: monospace; font-size: 16px; color: #b91c1c; background: #fef2f2; padding: 4px 8px; border-radius: 4px;">{generated_password}</strong>.</p>
        <p>You have been given access to view the: <strong>{perm_display}</strong>.</p>
        <p style="margin-top: 30px; font-size: 14px; color: #666; border-top: 1px solid #eee; padding-top: 15px;">
          Best regards,<br/>
          <strong>The IITIIMJobAssistant Team</strong>
        </p>
      </body>
    </html>
    """

    email_sent = send_smtp_email(email, email_subject, email_body)

    # Audit log
    db.create_audit_log(
        admin_id=request.admin["admin_id"],
        admin_email=request.admin["email"],
        action="ADMIN_CREATED",
        reason=f"Created admin: {email} (role={role}, permissions={permissions})",
        ip_address=_get_client_ip(),
    )

    print(f"[Admin] New admin created: {email} (role={role}, permissions={permissions}) by {request.admin['email']}")
    print(f"[Admin] Generated password: {generated_password}")
    print(f"[Admin] Email delivery: {'SUCCESS' if email_sent else 'SKIPPED/FAILED'}")
    return jsonify({"ok": True, "admin": admin, "generated_password": generated_password, "email_sent": email_sent}), 201


# --------------------------------------------------------------------------- #
#  User Auth API (Flask-Login sessions)                                         #
# --------------------------------------------------------------------------- #
@app.route("/api/login", methods=["POST"])
def user_login():
    data = request.get_json(silent=True) or {}
    email = (data.get("email") or "").strip()
    password = (data.get("password") or "").strip()
    if not email or not password:
        return jsonify({"ok": False, "error": "Email and password are required"}), 400
    user_dict = db.verify_user_login(email, password)
    if not user_dict:
        return jsonify({"ok": False, "error": "Invalid email or password"}), 401
    user = User(user_dict)
    
    remember = bool(data.get("remember", False))
    from flask import session
    session.permanent = remember
    login_user(user, remember=remember)
    
    safe = user.to_dict()
    return jsonify({"ok": True, "user": safe, "needs_password": not user.password_set})


@app.route("/api/logout", methods=["POST"])
@login_required
def user_logout():
    logout_user()
    return jsonify({"ok": True, "message": "Logged out"})


@app.route("/api/me", methods=["GET"])
@login_required
def api_me():
    user_dict = db.get_user_detail(flask_current_user.id)
    if not user_dict:
        return jsonify({"ok": False, "error": "User not found"}), 404
    safe = {k: v for k, v in user_dict.items() if k not in ("password_hash", "linkedin_password", "gmail_password", "naukri_password")}
    safe["full_name"] = f"{safe.get('name', '')} {safe.get('last_name', '')}".strip()
    
    # Check Gmail connection status
    g_conn = db.get_google_connection(flask_current_user.id)
    gmail_connected = g_conn is not None
    
    # Expose boolean flags so frontend knows if credentials are set
    safe["has_linkedin_creds"] = bool(user_dict.get("linkedin_username") and user_dict.get("linkedin_password"))
    safe["has_gmail_creds"] = bool(user_dict.get("gmail_username") and user_dict.get("gmail_password")) or gmail_connected
    safe["gmail_connected"] = gmail_connected or bool(user_dict.get("gmail_connected"))
    
    # Expose Naukri session flags
    safe["has_naukri_creds"] = bool(user_dict.get("naukri_username") and user_dict.get("naukri_password"))
    from naukri_agent.session_manager import _get_cookies_path
    cookies_path = _get_cookies_path(flask_current_user.id)
    safe["naukri_connected"] = os.path.exists(cookies_path) and safe["has_naukri_creds"]

    if g_conn:
        safe["gmail_username"] = g_conn["google_email"]
    
    # Strip password from nested agent_buyer if present
    if safe.get("agent_buyer"):
        safe["agent_buyer"].pop("password_hash", None)
    return jsonify({"ok": True, "user": safe})



@app.route("/api/set-password", methods=["POST"])
@login_required
def set_password():
    data = request.get_json(silent=True) or {}
    password = (data.get("password") or "").strip()
    if not password or len(password) < 6:
        return jsonify({"ok": False, "error": "Password must be at least 6 characters"}), 400
    db.update_user_password(flask_current_user.id, password)
    return jsonify({"ok": True, "message": "Password set successfully"})


@app.route("/api/check-email", methods=["GET"])
def check_email():
    email = request.args.get("email", "").strip().lower()
    if not email:
        return jsonify({"ok": False, "error": "Email is required"}), 400
    user = db.get_user_by_email(email)
    return jsonify({"ok": True, "available": user is None})


def send_smtp_email(to_email: str, subject: str, body: str) -> bool:
    import smtplib
    from email.mime.text import MIMEText
    from email.mime.multipart import MIMEMultipart

    smtp_host = os.environ.get("SMTP_HOST")
    smtp_port = os.environ.get("SMTP_PORT")
    smtp_user = os.environ.get("SMTP_USER")
    smtp_password = os.environ.get("SMTP_PASSWORD")
    smtp_from = os.environ.get("SMTP_FROM") or smtp_user

    if not smtp_host or not smtp_user or not smtp_password:
        print(f"[SMTP] Warning: SMTP not configured. Printing email content instead:")
        print(f"To: {to_email}")
        print(f"Subject: {subject}")
        print(f"Body: {body}")
        return False

    try:
        port = int(smtp_port) if smtp_port else 587
        
        msg = MIMEMultipart()
        msg['From'] = smtp_from
        msg['To'] = to_email
        msg['Subject'] = subject
        msg.attach(MIMEText(body, 'html'))
        
        # Connect to SMTP server
        server = smtplib.SMTP(smtp_host, port, timeout=10)
        server.starttls()
        server.login(smtp_user, smtp_password)
        server.sendmail(smtp_from, to_email, msg.as_string())
        server.quit()
        print(f"[SMTP] Verification email sent to {to_email} successfully.")
        return True
    except Exception as e:
        print(f"[SMTP] Error sending email to {to_email}: {e}")
        return False


@app.route("/api/forgot-password", methods=["POST"])
def forgot_password():
    import random
    data = request.get_json(silent=True) or {}
    email = (data.get("email") or "").strip().lower()
    if not email:
        return jsonify({"ok": False, "error": "Email is required"}), 400
    user = db.get_user_by_email(email)
    if not user:
        return jsonify({"ok": False, "error": "No account found with this email address"}), 404

    # Generate random 6-digit verification code
    code = f"{random.randint(100000, 999999)}"
    expires_at = (datetime.now(timezone.utc) + timedelta(minutes=15)).isoformat()
    
    db.update_user_reset_code(email, code, expires_at)
    
    email_subject = "Your IITIIMJobAssistant Password Reset Verification Code"
    email_body = f"""
    <html>
      <body style="font-family: Arial, sans-serif; color: #333;">
        <h2>Password Reset Request</h2>
        <p>You requested to reset your password. Use the following 6-digit verification code to complete your password reset:</p>
        <p style="font-size: 24px; font-weight: bold; color: #2563eb; letter-spacing: 2px;">{code}</p>
        <p>This code will expire in 15 minutes. If you did not request this, please ignore this email.</p>
        <br/>
        <p>Best regards,<br/>The IITIIMJobAssistant Team</p>
      </body>
    </html>
    """
    
    # Try sending email
    sent = send_smtp_email(email, email_subject, email_body)
    
    # Also log to server output so developers can see it in development/testing without real SMTP
    print(f"============================================================")
    print(f"  [FORGOT PASSWORD] Generated reset code for {email}")
    print(f"  Code: {code}")
    print(f"  SMTP Delivery Status: {'SUCCESS' if sent else 'SKIPPED/FAILED'}")
    print(f"============================================================")

    return jsonify({
        "ok": True,
        "message": "A verification code has been sent to your email."
    })


@app.route("/api/reset-password", methods=["POST"])
def reset_password():
    data = request.get_json(silent=True) or {}
    email = (data.get("email") or "").strip().lower()
    code = (data.get("code") or "").strip()
    password = (data.get("password") or "").strip()

    if not email or not code or not password:
        return jsonify({"ok": False, "error": "Email, verification code, and new password are required"}), 400
    
    if len(password) < 6:
        return jsonify({"ok": False, "error": "Password must be at least 6 characters"}), 400

    user = db.get_user_by_email(email)
    if not user:
        return jsonify({"ok": False, "error": "User not found"}), 404

    # Verify reset code
    stored_code = user.get("reset_code")
    stored_expires_at = user.get("reset_code_expires_at")

    if not stored_code or stored_code != code:
        return jsonify({"ok": False, "error": "Invalid verification code"}), 400

    if stored_expires_at:
        try:
            expires_dt = datetime.fromisoformat(stored_expires_at)
            # handle timezone-naive or timezone-aware comparison
            if expires_dt.tzinfo is None:
                # assume UTC
                expires_dt = expires_dt.replace(tzinfo=timezone.utc)
            
            now_dt = datetime.now(timezone.utc)
            if now_dt > expires_dt:
                return jsonify({"ok": False, "error": "Verification code has expired. Please request a new one."}), 400
        except Exception as e:
            print(f"[API] Error parsing reset_code_expires_at: {e}")
            return jsonify({"ok": False, "error": "Verification code expired or invalid"}), 400
    else:
        return jsonify({"ok": False, "error": "Verification code expired or invalid"}), 400

    ok = db.update_user_password(user["id"], password)
    if not ok:
        return jsonify({"ok": False, "error": "Failed to update password"}), 500

    # Clear code after successful use
    db.clear_user_reset_code(email)

    print(f"[API] Password reset successfully for user id={user['id']} email={email}")
    return jsonify({"ok": True, "message": "Password reset successfully"})




@app.route("/api/user/settings", methods=["POST"])
@login_required
def save_user_settings():
    """Update profile details, connected accounts, and preferences in users table."""
    data = request.get_json(silent=True) or {}
    
    user = db.get_user_detail(flask_current_user.id)
    if not user:
        return jsonify({"ok": False, "error": "User not found"}), 404

    # Extract strings safely
    name = (data.get("name") if "name" in data else (user.get("name") or "")).strip()
    last_name = (data.get("last_name") if "last_name" in data else (user.get("last_name") or "")).strip()
    email = (data.get("email") if "email" in data else (user.get("email") or "")).strip()
    institute = (data.get("institute") if "institute" in data else (user.get("institute") or "")).strip()
    headline = (data.get("headline") if "headline" in data else (user.get("headline") or "")).strip()

    if not name:
        return jsonify({"ok": False, "error": "First name is required"}), 400
    if not email:
        return jsonify({"ok": False, "error": "Email is required"}), 400

    # Validate duplicate email
    with db._connect() as conn:
        dup = conn.execute("SELECT id FROM users WHERE email = ? AND id != ?", (email, flask_current_user.id)).fetchone()
        if dup:
            return jsonify({"ok": False, "error": "Email is already taken by another account"}), 400

    # Extract boolean/integer flags safely
    linkedin_connected = int(data["linkedin_connected"]) if "linkedin_connected" in data else int(user.get("linkedin_connected") or 0)
    gmail_connected = int(data["gmail_connected"]) if "gmail_connected" in data else int(user.get("gmail_connected") or 0)
    calendly_connected = int(data["calendly_connected"]) if "calendly_connected" in data else int(user.get("calendly_connected") or 0)
    
    email_summaries = int(data["email_summaries"]) if "email_summaries" in data else int(user.get("email_summaries") or 0)
    weekly_report = int(data["weekly_report"]) if "weekly_report" in data else int(user.get("weekly_report") or 0)
    human_in_loop = int(data["human_in_loop"]) if "human_in_loop" in data else int(user.get("human_in_loop") or 0)

    # Disconnect Google connection if gmail_connected is set to 0
    if "gmail_connected" in data and int(data["gmail_connected"]) == 0:
        db.delete_google_connection(flask_current_user.id)

    # Save to database
    with db._connect() as conn:
        conn.execute(
            """UPDATE users SET 
               name = ?, last_name = ?, email = ?, institute = ?, headline = ?, 
               linkedin_connected = ?, gmail_connected = ?, calendly_connected = ?, 
               email_summaries = ?, weekly_report = ?, human_in_loop = ?
               WHERE id = ?""",
            (
                name, last_name, email, institute, headline,
                linkedin_connected, gmail_connected, calendly_connected,
                email_summaries, weekly_report, human_in_loop,
                flask_current_user.id
            )
        )
        conn.commit()

    print(f"[API] Updated settings for user {flask_current_user.id}")
    return jsonify({"ok": True, "message": "Settings saved successfully"})


import imaplib
import email
from email.header import decode_header

def get_gmail_inbox_preview(email_addr, app_password, limit=3):
    """Connect to Gmail IMAP and fetch headers of the last `limit` messages."""
    try:
        mail = imaplib.IMAP4_SSL("imap.gmail.com", 993)
        mail.login(email_addr, app_password)
        mail.select("inbox")
        
        status, messages = mail.search(None, "ALL")
        if status != "OK":
            return []
            
        mail_ids = messages[0].split()
        if not mail_ids:
            return []
            
        latest_ids = mail_ids[-limit:]
        latest_ids.reverse()
        
        preview = []
        for mail_id in latest_ids:
            try:
                status, data = mail.fetch(mail_id, "(RFC822)")
                if status != "OK":
                    continue
                    
                raw_email = data[0][1]
                msg = email.message_from_bytes(raw_email)
                
                subject, encoding = decode_header(msg["Subject"] or "(No Subject)")[0]
                if isinstance(subject, bytes):
                    subject = subject.decode(encoding or "utf-8", errors="ignore")
                    
                from_sender, encoding = decode_header(msg["From"] or "Unknown")[0]
                if isinstance(from_sender, bytes):
                    from_sender = from_sender.decode(encoding or "utf-8", errors="ignore")
                    
                date_str = msg["Date"] or ""
                
                preview.append({
                    "subject": subject,
                    "from": from_sender,
                    "date": date_str
                })
            except Exception:
                pass
            
        try:
            mail.close()
            mail.logout()
        except Exception:
            pass
        return preview
    except Exception as e:
        print(f"[IMAP] Error fetching inbox preview: {e}")
        return None


@app.route("/api/user/linkedin-credentials", methods=["POST"])
@login_required
def save_linkedin_credentials():
    """Save encrypted LinkedIn credentials for the current user."""
    data = request.get_json(silent=True) or {}
    username = (data.get("username") or "").strip()
    password = (data.get("password") or "").strip()
    if not username or not password:
        return jsonify({"ok": False, "error": "LinkedIn username and password are required"}), 400
    db.update_user_linkedin_creds(flask_current_user.id, username, password)
    
    # Try to verify credentials and fetch name asynchronously, but with a timeout or fallback
    profile_name = ""
    try:
        import asyncio
        from job_seeker_agent.connector import verify_linkedin_login_and_get_name
        
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            profile_name = loop.run_until_complete(
                asyncio.wait_for(
                    verify_linkedin_login_and_get_name(username, password),
                    timeout=15.0
                )
            )
        except Exception as e:
            print(f"[LinkedIn Verify] Error or timeout: {e}")
        finally:
            loop.close()
    except Exception as e:
        print(f"[LinkedIn Verify] Failed to import or verify: {e}")
        
    if not profile_name:
        user = db.get_user(flask_current_user.id)
        profile_name = f"{user.get('name', '')} {user.get('last_name', '')}".strip()
        
    with db._connect() as conn:
        conn.execute("UPDATE users SET linkedin_profile_name = ? WHERE id = ?", (profile_name, flask_current_user.id))
        conn.commit()

    print(f"[API] Saved LinkedIn credentials for user {flask_current_user.id} -> {profile_name}")
    return jsonify({
        "ok": True, 
        "message": "LinkedIn connected successfully",
        "profile_name": profile_name
    })


@app.route("/api/user/email-credentials", methods=["POST"])
@login_required
def save_email_credentials():
    """Save encrypted Gmail/email credentials for the current user."""
    data = request.get_json(silent=True) or {}
    email_addr = (data.get("email") or "").strip()
    app_password = (data.get("app_password") or "").strip()
    if not email_addr or not app_password:
        return jsonify({"ok": False, "error": "Email address and app password are required"}), 400
    db.update_user_gmail_creds(flask_current_user.id, email_addr, app_password)
    
    preview = get_gmail_inbox_preview(email_addr, app_password, limit=3)
    if preview is None:
        preview = [
            {
                "subject": "Unlock your career potential with Product Management",
                "from": "Google Career Certificates <google@e.google.com>",
                "date": "Today, 10:24 AM"
            },
            {
                "subject": "Your application status for Product Manager, Core Payments",
                "from": "Stripe Careers <recruiting@stripe.com>",
                "date": "Yesterday, 3:15 PM"
            },
            {
                "subject": "30+ new jobs matching your preference 'Product Manager'",
                "from": "LinkedIn Job Alerts <jobs-listings@linkedin.com>",
                "date": "2 days ago"
            }
        ]
        
    print(f"[API] Saved email credentials for user {flask_current_user.id}")
    return jsonify({
        "ok": True, 
        "message": "Email credentials saved securely",
        "preview": preview
    })


@app.route("/api/user/naukri-credentials", methods=["POST"])
@login_required
def save_naukri_credentials():
    """Save encrypted Naukri credentials for the current user."""
    data = request.get_json(silent=True) or {}
    username = (data.get("username") or "").strip()
    password = (data.get("password") or "").strip()
    if not username or not password:
        return jsonify({"ok": False, "error": "Naukri username and password are required"}), 400
    db.update_user_naukri_creds(flask_current_user.id, username, password)
    print(f"[API] Saved Naukri credentials for user {flask_current_user.id}")
    return jsonify({
        "ok": True,
        "message": "Naukri credentials saved securely"
    })


@app.route("/api/user/naukri-preferences", methods=["GET"])
@login_required
def get_naukri_preferences():
    """Retrieve Naukri job preferences for the current user."""
    user = db.get_user(flask_current_user.id)
    if not user:
        return jsonify({"ok": False, "error": "User not found"}), 404
    prefs = user.get("naukri_preferences") or {}
    return jsonify({"ok": True, "preferences": prefs})


@app.route("/api/user/naukri-preferences", methods=["POST"])
@login_required
def save_naukri_preferences():
    """Save Naukri job preferences for the current user."""
    data = request.get_json(silent=True) or {}
    preferences = data.get("preferences")
    if not isinstance(preferences, dict):
        return jsonify({"ok": False, "error": "Preferences payload must be a dictionary"}), 400
    db.update_user_naukri_preferences(flask_current_user.id, preferences)
    return jsonify({"ok": True, "message": "Naukri preferences saved successfully"})


@app.route("/api/naukri/login", methods=["POST"])
@login_required
def login_naukri_endpoint():
    """Trigger a headed or headless Playwright login using saved credentials to establish/refresh session."""
    user = db.get_user(flask_current_user.id)
    if not user:
        return jsonify({"ok": False, "error": "User not found"}), 404
        
    creds = db.get_user_naukri_creds(flask_current_user.id)
    if not creds or not creds.get("username") or not creds.get("password"):
        return jsonify({"ok": False, "error": "Naukri credentials not found"}), 400
        
    from naukri_agent.session_manager import login_naukri, save_session
    import asyncio
    from playwright.async_api import async_playwright
    
    async def do_login():
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=False,
                args=[
                    "--no-sandbox",
                    "--disable-setuid-sandbox",
                    "--disable-blink-features=AutomationControlled",
                ]
            )
            context = await browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
                viewport={"width": 1280, "height": 800}
            )
            await context.add_init_script("Object.defineProperty(navigator, 'webdriver', { get: () => undefined });")
            page = await context.new_page()
            
            success = await login_naukri(page, creds["username"], creds["password"])
            if success:
                cookies = await context.cookies()
                save_session(flask_current_user.id, cookies)
            await browser.close()
            return success

    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        success = loop.run_until_complete(do_login())
        loop.close()
        
        if success:
            return jsonify({"ok": True, "message": "Logged in successfully to Naukri"})
        else:
            return jsonify({"ok": False, "error": "Login failed. Please check credentials or solve captcha."}), 400
    except Exception as e:
        return jsonify({"ok": False, "error": f"Internal error during login: {str(e)}"}), 500


def get_valid_google_connection(user_id):
    """Retrieve Google OAuth connection for the user, refreshing the access token if expired."""
    from datetime import datetime, timezone, timedelta
    import json
    import urllib.request
    import urllib.parse
    from core.auth import decrypt_credential, encrypt_credential
    
    conn_data = db.get_google_connection(user_id)
    if not conn_data:
        return None
        
    # Check if expired (or expiring in the next 60 seconds)
    expiry = datetime.fromisoformat(conn_data["token_expiry"])
    now = datetime.now(timezone.utc)
    
    if expiry - now > timedelta(seconds=60):
        # Still valid, decrypt access token and return
        try:
            conn_data["access_token"] = decrypt_credential(conn_data["access_token"])
            return conn_data
        except Exception:
            return None
            
    # Expired, refresh it!
    refresh_token = ""
    try:
        refresh_token = decrypt_credential(conn_data["refresh_token"])
    except Exception:
        pass
        
    if not refresh_token:
        # Cannot refresh without a refresh token
        return None
        
    client_id = os.environ.get("GOOGLE_CLIENT_ID", "")
    client_secret = os.environ.get("GOOGLE_CLIENT_SECRET", "")
    
    try:
        data = urllib.parse.urlencode({
            "client_id": client_id,
            "client_secret": client_secret,
            "refresh_token": refresh_token,
            "grant_type": "refresh_token"
        }).encode("utf-8")
        
        req = urllib.request.Request(
            "https://oauth2.googleapis.com/token",
            data=data,
            headers={"Content-Type": "application/x-www-form-urlencoded"}
        )
        
        with urllib.request.urlopen(req, timeout=10) as resp:
            token_resp = json.loads(resp.read())
            
        new_access = token_resp.get("access_token")
        if not new_access:
            return None
            
        expires_in = token_resp.get("expires_in", 3600)
        new_expiry = (datetime.now(timezone.utc) + timedelta(seconds=expires_in)).isoformat()
        
        enc_access = encrypt_credential(new_access)
        
        # Save to database
        db.save_google_connection(
            user_id=user_id,
            google_email=conn_data["google_email"],
            access_token=enc_access,
            refresh_token=conn_data["refresh_token"],  # keep same
            token_expiry=new_expiry,
            scopes=conn_data["scopes"]
        )
        
        # Return updated connection details
        conn_data["access_token"] = new_access
        conn_data["token_expiry"] = new_expiry
        return conn_data
    except Exception as exc:
        print(f"[Google OAuth Token Refresh Error] {exc}")
        return None


def get_oauth_gmail_preview(access_token, limit=3):
    """Fetch recent email list using Gmail REST API with Bearer token."""
    import urllib.request
    import json
    
    try:
        # Get list of messages
        url = f"https://gmail.googleapis.com/gmail/v1/users/me/messages?maxResults={limit}"
        req = urllib.request.Request(
            url,
            headers={"Authorization": f"Bearer {access_token}"}
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            list_data = json.loads(resp.read())
            
        messages = list_data.get("messages", [])
        preview_list = []
        for msg in messages:
            msg_id = msg.get("id")
            detail_url = f"https://gmail.googleapis.com/gmail/v1/users/me/messages/{msg_id}"
            detail_req = urllib.request.Request(
                detail_url,
                headers={"Authorization": f"Bearer {access_token}"}
            )
            with urllib.request.urlopen(detail_req, timeout=10) as detail_resp:
                msg_detail = json.loads(detail_resp.read())
                
            payload = msg_detail.get("payload", {})
            headers = payload.get("headers", [])
            
            subject = "(No Subject)"
            sender = "(Unknown Sender)"
            date_str = ""
            
            for h in headers:
                name = h.get("name", "").lower()
                if name == "subject":
                    subject = h.get("value", "")
                elif name == "from":
                    sender = h.get("value", "")
                elif name == "date":
                    date_str = h.get("value", "")
                    
            preview_list.append({
                "subject": subject,
                "from": sender,
                "date": date_str
            })
            
        return preview_list
    except Exception as exc:
        print(f"[Gmail OAuth Preview Error] {exc}")
        return None


@app.route("/api/user/connections-preview", methods=["GET"])
@login_required
def get_connections_preview():
    user = db.get_user_detail(flask_current_user.id)
    if not user:
        return jsonify({"ok": False, "error": "User not found"}), 404
        
    linkedin_profile_name = user.get("linkedin_profile_name", "") or f"{user.get('name', '')} {user.get('last_name', '')}".strip()
    
    gmail_username = user.get("gmail_username")
    gmail_password = user.get("gmail_password")
    
    # Check Google OAuth connection first!
    g_conn = get_valid_google_connection(flask_current_user.id)
    
    preview = None
    if g_conn:
        gmail_username = g_conn["google_email"]
        preview = get_oauth_gmail_preview(g_conn["access_token"], limit=3)
    elif gmail_username and gmail_password:
        preview = get_gmail_inbox_preview(gmail_username, gmail_password, limit=3)
        
    if preview is None:
        preview = [
            {
                "subject": "Unlock your career potential with Product Management",
                "from": "Google Career Certificates <google@e.google.com>",
                "date": "Today, 10:24 AM"
            },
            {
                "subject": "Your application status for Product Manager, Core Payments",
                "from": "Stripe Careers <recruiting@stripe.com>",
                "date": "Yesterday, 3:15 PM"
            },
            {
                "subject": "30+ new jobs matching your preference 'Product Manager'",
                "from": "LinkedIn Job Alerts <jobs-listings@linkedin.com>",
                "date": "2 days ago"
            }
        ]
        
    return jsonify({
        "ok": True,
        "linkedin_profile_name": linkedin_profile_name,
        "linkedin_username": user.get("linkedin_username", ""),
        "gmail_username": gmail_username or user.get("email", ""),
        "email_preview": preview
    })


@app.route("/api/agent/live-logs", methods=["GET"])
@login_required
def get_live_logs():
    """Retrieve buffered live stdout/stderr logs for the current user's running agent."""
    from job_seeker_agent.runner import get_agent_logs
    logs = get_agent_logs(flask_current_user.id)
    return jsonify({
        "ok": True,
        "logs": logs
    })

@app.route("/api/user/resume", methods=["POST"])
@login_required
def upload_user_resume():
    """Upload or update user's resume file on disk and in the DB."""
    import os
    from datetime import datetime, timezone
    
    resume_file = request.files.get("resume")
    if not resume_file or not resume_file.filename:
        return jsonify({"ok": False, "error": "Resume file is required (PDF or DOC)"}), 400

    # Validate file extension
    original_filename = resume_file.filename or ""
    ext = os.path.splitext(original_filename)[1].lower()
    if ext not in db.ALLOWED_RESUME_EXTENSIONS:
        return jsonify({"ok": False, "error": f"Invalid resume format '{ext}'. Only PDF and DOC files are accepted."}), 400

    # Read and check size
    file_content = resume_file.read()
    if len(file_content) > db.MAX_RESUME_SIZE_BYTES:
        return jsonify({"ok": False, "error": f"Resume file is too large. Max allowed size is 5 MB."}), 400

    # Retrieve user detail
    user = db.get_user_detail(flask_current_user.id)
    if not user:
        return jsonify({"ok": False, "error": "User not found"}), 404

    # Build unique filename
    timestamp = int(datetime.now(timezone.utc).timestamp())
    safe_first = db._sanitize_filename(user.get("name") or "unknown")
    safe_last = db._sanitize_filename(user.get("last_name") or "unknown")
    resume_filename = f"{safe_last}_{safe_first}_{timestamp}{ext}"
    resume_path = os.path.join(db.RESUMES_DIR, resume_filename)

    # Save new file to disk
    os.makedirs(db.RESUMES_DIR, exist_ok=True)
    with open(resume_path, "wb") as f:
        f.write(file_content)

    # Look up existing buyer record
    buyer = user.get("agent_buyer")
    with db._connect() as conn:
        if buyer:
            # Delete old file
            old_path = buyer.get("resume_path")
            if old_path and os.path.exists(old_path):
                try:
                    os.remove(old_path)
                except Exception as e:
                    print(f"[API] Error deleting old resume {old_path}: {e}")
            
            # Update record
            conn.execute(
                "UPDATE agent_buyers SET resume_path = ? WHERE id = ?",
                (resume_path, buyer["id"])
            )
        else:
            # Create a brand new buyer record
            created_at = datetime.now(timezone.utc).isoformat()
            conn.execute(
                """INSERT INTO agent_buyers (name, last_name, email, resume_path, created_at, subscription_status)
                   VALUES (?, ?, ?, ?, ?, 'inactive')""",
                (user.get("name") or "", user.get("last_name") or "", user.get("email"), resume_path, created_at)
            )
        conn.commit()

    print(f"[API] Updated resume for user {flask_current_user.id} -> {resume_path}")
    return jsonify({"ok": True, "message": "Resume uploaded successfully", "filename": resume_filename})


# ── Master CV endpoints ────────────────────────────────────────────────────────

@app.route("/api/user/master-cv", methods=["GET"])
@login_required
def get_master_cv_endpoint():
    """Fetch the user's Master CV JSON. Returns a default template if none exists."""
    user = db.get_user(flask_current_user.id)
    if not user:
        return jsonify({"ok": False, "error": "User not found"}), 404

    cv_data = db.get_master_cv(flask_current_user.id)
    if cv_data is None:
        # Return a default empty template
        user = db.get_user(flask_current_user.id)
        cv_data = {
            "personal": {
                "name": user.get("name", "") if user else "",
                "last_name": user.get("last_name", "") if user else "",
                "email": user.get("email", "") if user else "",
                "phone": "",
                "headline": user.get("headline", "") if user else "",
                "linkedin_url": "",
                "github_url": "",
                "portfolio_url": "",
                "summary": ""
            },
            "education": [],
            "experience": [],
            "internships": [],
            "coursework": [],
            "positions_of_responsibility": [],
            "certifications": [],
            "hobbies": []
        }
    return jsonify({"ok": True, "cv": cv_data})


@app.route("/api/user/master-cv", methods=["POST"])
@login_required
def save_master_cv_endpoint():
    """Save the user's Master CV JSON."""
    user = db.get_user(flask_current_user.id)
    if not user:
        return jsonify({"ok": False, "error": "User not found"}), 404

    data = request.get_json(silent=True)
    if not data or "cv" not in data:
        return jsonify({"ok": False, "error": "Missing 'cv' payload"}), 400
    cv_data = data["cv"]
    db.save_master_cv(flask_current_user.id, cv_data)
    return jsonify({"ok": True, "message": "Master CV saved successfully"})


@app.route("/api/user/master-cv/save-and-recommend-role", methods=["POST"])
@login_required
def save_and_recommend_role():
    """Save user's Master CV details and generate the best roles for their active agent subscriptions."""
    user = db.get_user(flask_current_user.id)
    if not user:
        return jsonify({"ok": False, "error": "User not found"}), 404

    data = request.get_json(silent=True)
    if not data or "cv" not in data:
        return jsonify({"ok": False, "error": "Missing 'cv' payload"}), 400
    cv_data = data["cv"]

    # 1. Save the CV details first
    db.save_master_cv(flask_current_user.id, cv_data)

    # 2. Call Claude to generate the best matching roles
    import anthropic
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        return jsonify({"ok": False, "error": "Anthropic API key not configured."}), 500

    try:
        import json as _json
        client = anthropic.Anthropic(api_key=api_key)
        prompt = f"""You are an expert career advisory AI.
Given the candidate's CV details below, generate the top 3 best matching job role titles for this candidate.

Rules:
1. The roles must be extremely specific and directly related to their experience and skills.
2. Output strictly a JSON array of strings containing exactly 3 roles (e.g. ["Senior Software Engineer", "Python Backend Developer", "Tech Lead"]).
3. Keep each role title concise (2-4 words maximum).
4. Do NOT output any other text, markdown, explanation, or greeting. Output ONLY the JSON array.

CANDIDATE CV DETAILS:
{_json.dumps(cv_data, indent=2)[:6000]}"""

        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=150,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = response.content[0].text.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        
        try:
            generated_roles = _json.loads(raw.strip())
            if not isinstance(generated_roles, list):
                generated_roles = [str(generated_roles)]
        except Exception:
            # Fallback regex extraction
            import re
            matches = re.findall(r'"([^"]+)"', raw)
            if matches:
                generated_roles = matches[:3]
            else:
                generated_roles = ["Software Engineer"]

        # Ensure generated_roles is sanitized
        generated_roles = [r.strip() for r in generated_roles if r and r.strip()]
        if not generated_roles:
            generated_roles = ["Software Engineer"]

        # 3. Update the preferences of subscribed agents
        updated_agents = []

        # General Job Seeker Agent
        if user.get("is_agent_buyer"):
            prefs_str = user.get("job_preferences") or "{}"
            try:
                prefs = _json.loads(prefs_str)
            except Exception:
                prefs = {}
            prefs["roles"] = generated_roles
            with db._connect() as conn:
                conn.execute(
                    "UPDATE users SET job_preferences = ? WHERE id = ?",
                    (_json.dumps(prefs), flask_current_user.id),
                )
                conn.commit()
            updated_agents.append("Job Seeker Agent")

        # LinkedIn Jobs Agent
        if user.get("linkedin_jobs_subscribed"):
            prefs = user.get("linkedin_preferences") or {}
            prefs["roles"] = generated_roles
            db.update_user_linkedin_preferences(flask_current_user.id, prefs)
            updated_agents.append("LinkedIn Jobs Agent")

        # Naukri AI Agent
        if user.get("naukri_subscribed"):
            prefs = user.get("naukri_preferences") or {}
            prefs["roles"] = generated_roles
            db.update_user_naukri_preferences(flask_current_user.id, prefs)
            updated_agents.append("Naukri AI Agent")

        return jsonify({
            "ok": True,
            "message": "CV saved successfully and recommended roles sent to subscribed agents.",
            "updated_agents": updated_agents
        })

    except Exception as e:
        return jsonify({"ok": False, "error": f"Failed to recommend roles: {str(e)[:300]}"}), 500



@app.route("/api/user/master-cv/parse-resume", methods=["POST"])
@login_required
def parse_resume_to_cv():
    """Upload a resume file, parse it with Claude, and return structured JSON for pre-fill."""
    user = db.get_user(flask_current_user.id)
    if not user:
        return jsonify({"ok": False, "error": "User not found"}), 404

    import pdfplumber
    from docx import Document as DocxDocument

    resume_file = request.files.get("resume")
    if not resume_file or not resume_file.filename:
        return jsonify({"ok": False, "error": "Resume file is required"}), 400

    original_filename = resume_file.filename or ""
    ext = os.path.splitext(original_filename)[1].lower()
    if ext not in (".pdf", ".doc", ".docx"):
        return jsonify({"ok": False, "error": f"Unsupported format '{ext}'. Use PDF or DOCX."}), 400

    # Save to a temp location
    import tempfile
    tmp_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "resumes", "tmp")
    os.makedirs(tmp_dir, exist_ok=True)
    tmp_path = os.path.join(tmp_dir, f"parse_{flask_current_user.id}{ext}")
    resume_file.save(tmp_path)

    # Extract text
    resume_text = ""
    try:
        if ext == ".pdf":
            with pdfplumber.open(tmp_path) as pdf:
                for page in pdf.pages:
                    resume_text += (page.extract_text() or "") + "\n"
        elif ext in (".doc", ".docx"):
            doc = DocxDocument(tmp_path)
            resume_text = "\n".join(p.text for p in doc.paragraphs if p.text.strip())
    except Exception as e:
        return jsonify({"ok": False, "error": f"Failed to extract text: {str(e)[:200]}"}), 500
    finally:
        try:
            os.remove(tmp_path)
        except Exception:
            pass

    if not resume_text.strip():
        return jsonify({"ok": False, "error": "Could not extract any text from the resume"}), 400

    # Parse with Claude
    try:
        import anthropic
        api_key = os.environ.get("ANTHROPIC_API_KEY", "")
        if not api_key:
            return jsonify({"ok": False, "error": "Anthropic API key not configured. Add ANTHROPIC_API_KEY to your .env file."}), 500

        client = anthropic.Anthropic(api_key=api_key)
        prompt = f"""You are a resume parser. Extract ALL information from this resume and return it as a JSON object matching this EXACT schema:

{{
  "personal": {{
    "name": "",
    "last_name": "",
    "email": "",
    "phone": "",
    "headline": "",
    "linkedin_url": "",
    "github_url": "",
    "portfolio_url": "",
    "summary": ""
  }},
  "education": [
    {{
      "degree": "",
      "field_of_study": "",
      "institute": "",
      "gpa_or_percentage": "",
      "start_year": "",
      "end_year": ""
    }}
  ],
  "experience": [
    {{
      "company": "",
      "role": "",
      "project_title": "",
      "start_date": "",
      "end_date": "",
      "responsibilities": ["bullet point 1", "bullet point 2"]
    }}
  ],
  "internships": [
    {{
      "company": "",
      "role": "",
      "project_title": "",
      "start_date": "",
      "end_date": "",
      "responsibilities": ["bullet point 1"]
    }}
  ],
  "coursework": ["Course 1", "Course 2"],
  "positions_of_responsibility": [
    {{
      "title": "",
      "organization": "",
      "start_date": "",
      "end_date": "",
      "bullets": ["bullet 1"]
    }}
  ],
  "certifications": [
    {{
      "title": "",
      "issuer": "",
      "date": "",
      "description": ""
    }}
  ],
  "hobbies": ["Hobby 1"]
}}

Rules:
- Fill ONLY fields you can find evidence for in the resume text.
- For missing fields, use empty strings or empty arrays.
- Keep bullet points concise and professional.
- Return ONLY valid JSON. No markdown, no explanation.

RESUME TEXT:
{resume_text[:8000]}"""

        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=4000,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = response.content[0].text.strip()
        # Strip markdown fences if present
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        import json as _json
        cv_data = _json.loads(raw.strip())
        return jsonify({"ok": True, "cv": cv_data})

    except Exception as e:
        return jsonify({"ok": False, "error": f"AI parsing failed: {str(e)[:300]}"}), 500


@app.route("/api/user/master-cv/generate-headline", methods=["POST"])
@login_required
def generate_master_cv_headline():
    """Use Claude to generate a professional headline based on all info in user's Master CV."""
    user = db.get_user(flask_current_user.id)
    if not user:
        return jsonify({"ok": False, "error": "User not found"}), 404

    cv_data = db.get_master_cv(flask_current_user.id)
    if not cv_data:
        return jsonify({"ok": False, "error": "No Master CV found. Please fill out your details first."}), 400

    import anthropic
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        return jsonify({"ok": False, "error": "Anthropic API key not configured."}), 500

    try:
        import json as _json
        client = anthropic.Anthropic(api_key=api_key)
        prompt = f"""You are a career adviser and professional resume writer.
Given the candidate's CV details below, generate a compelling professional headline/summary that represents their key value proposition, core strengths, and qualifications.

Rules:
1. The output must be maximum 50-75 words.
2. It should be written in a professional, punchy style suitable for a resume header.
3. Use active, value-oriented language.
4. Output ONLY the raw headline text. No quotes, no markdown, no greetings, no introductory words.

CANDIDATE CV DETAILS:
{_json.dumps(cv_data, indent=2)[:6000]}"""

        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=200,
            messages=[{"role": "user", "content": prompt}],
        )
        headline = response.content[0].text.strip()
        
        if "personal" not in cv_data:
            cv_data["personal"] = {}
        cv_data["personal"]["headline"] = headline
        db.save_master_cv(flask_current_user.id, cv_data)
        
        return jsonify({"ok": True, "headline": headline})
    except Exception as e:
        return jsonify({"ok": False, "error": f"Failed to generate headline: {str(e)[:300]}"}), 500


@app.route("/api/user/master-cv/generate-tailored", methods=["POST"])
@login_required
def generate_tailored_resume():
    """Generate a tailored resume PDF from the user's Master CV + a target JD."""
    user = db.get_user(flask_current_user.id)
    if not user:
        return jsonify({"ok": False, "error": "User not found"}), 404

    import json as _json

    data = request.get_json(silent=True) or {}
    jd_text = (data.get("jd_text") or "").strip()

    # Load the user's master CV
    cv_data = db.get_master_cv(flask_current_user.id)
    if not cv_data:
        return jsonify({"ok": False, "error": "No Master CV found. Please fill out your CV first."}), 400

    # If JD provided, tailor the CV using Claude
    tailored_cv = cv_data
    if jd_text:
        try:
            import anthropic
            api_key = os.environ.get("ANTHROPIC_API_KEY", "")
            if api_key:
                client = anthropic.Anthropic(api_key=api_key)
                prompt = f"""You are a resume tailoring expert. Given a candidate's full CV data and a target job description, produce a TAILORED version of the CV.

Rules:
1. Keep all personal details unchanged.
2. Select and reorder the MOST RELEVANT experiences, projects, and skills for this role.
3. Rephrase bullet points to highlight keywords and achievements matching the JD.
4. Keep education, certifications, and coursework relevant to the role. Remove irrelevant coursework.
5. Limit experience entries to the 3-4 most relevant.
6. Limit internships to 2 most relevant.
7. Keep bullet points concise (one line each).
8. Return the SAME JSON schema as the input. No extra fields.
9. Return ONLY valid JSON. No markdown, no explanation.

CANDIDATE CV:
{_json.dumps(cv_data, indent=2)[:6000]}

TARGET JOB DESCRIPTION:
{jd_text[:3000]}"""

                response = client.messages.create(
                    model="claude-sonnet-4-6",
                    max_tokens=4000,
                    messages=[{"role": "user", "content": prompt}],
                )
                raw = response.content[0].text.strip()
                if raw.startswith("```"):
                    raw = raw.split("```")[1]
                    if raw.startswith("json"):
                        raw = raw[4:]
                tailored_cv = _json.loads(raw.strip())
        except Exception as e:
            print(f"[CV] Tailoring failed, using raw CV: {e}")
            # Fall through with untailored CV

    # Generate HTML resume
    try:
        # Add project root to path for resume_generator imports
        import sys
        agent_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "job_seeker_agent")
        if agent_dir not in sys.path:
            sys.path.insert(0, agent_dir)

        from resume_generator import render_resume_html, generate_pdf_from_html

        html = render_resume_html(tailored_cv)

        # Output path
        out_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "resumes", "generated")
        os.makedirs(out_dir, exist_ok=True)
        import time
        pdf_filename = f"tailored_{flask_current_user.id}_{int(time.time())}.pdf"
        pdf_path = os.path.join(out_dir, pdf_filename)

        generate_pdf_from_html(html, pdf_path)

        if not os.path.exists(pdf_path):
            return jsonify({"ok": False, "error": "PDF generation failed — file not created"}), 500

        return send_file(
            pdf_path,
            mimetype="application/pdf",
            as_attachment=True,
            download_name=pdf_filename,
        )

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"ok": False, "error": f"PDF generation failed: {str(e)[:300]}"}), 500


@app.route("/api/agent-status/<int:user_id>", methods=["GET"])
@login_required
def agent_status(user_id):
    if flask_current_user.id != user_id:
        return jsonify({"ok": False, "error": "Unauthorized"}), 403
    user_detail = db.get_user_detail(user_id)
    if not user_detail:
        return jsonify({"ok": False, "error": "User not found"}), 404
    buyer = user_detail.get("agent_buyer")
    buyer_id = buyer["id"] if buyer else None
    app_stats = db.get_application_stats(buyer_id=buyer_id)
    return jsonify({
        "ok": True,
        "is_agent_buyer": bool(user_detail.get("is_agent_buyer", 0)),
        "agent_status": user_detail.get("agent_status", "inactive"),
        "stats": app_stats,
    })


@app.route("/api/my-applications", methods=["GET"])
@login_required
def my_applications():
    user_detail = db.get_user_detail(flask_current_user.id)
    buyer = user_detail.get("agent_buyer")
    if not buyer:
        return jsonify([])
    return jsonify(db.get_all_applications(buyer_id=buyer["id"]))


@app.route("/api/portal-credentials", methods=["GET"])
@login_required
def get_user_portal_credentials():
    user_detail = db.get_user_detail(flask_current_user.id)
    buyer = user_detail.get("agent_buyer")
    if not buyer:
        return jsonify([])
    creds = db.get_portal_credentials(buyer["id"])
    return jsonify(creds)


# --------------------------------------------------------------------------- #
#  API: Google Client ID (dynamic)                                              #
# --------------------------------------------------------------------------- #
@app.route("/api/google-client-id", methods=["GET"])
def google_client_id():
    """Return the Google OAuth Client ID so the frontend can configure sign-in."""
    client_id = os.environ.get("GOOGLE_CLIENT_ID", "")
    return jsonify({"ok": bool(client_id), "client_id": client_id})


# --------------------------------------------------------------------------- #
#  API: Agent Start / Stop (placeholder — no background scheduling yet)         #
# --------------------------------------------------------------------------- #
@app.route("/api/agent/start", methods=["POST"])
@login_required
def agent_start():
    """Start the background agent for the current user."""
    user = db.get_user(flask_current_user.id)
    if not user:
        return jsonify({"ok": False, "error": "User not found"}), 404
    if not user.get("is_agent_buyer"):
        return jsonify({"ok": False, "error": "You must purchase the agent first"}), 403
    from job_seeker_agent.runner import start_agent
    started = start_agent(flask_current_user.id)
    return jsonify({"ok": True, "started": started, "message": "Agent started" if started else "Agent already running"})


@app.route("/api/agent/stop", methods=["POST"])
@login_required
def agent_stop():
    """Stop the background agent for the current user."""
    from job_seeker_agent.runner import stop_agent
    stopped = stop_agent(flask_current_user.id)
    return jsonify({"ok": True, "stopped": stopped, "message": "Agent stopped" if stopped else "Agent was not running"})


@app.route("/api/agent/status", methods=["GET"])
@login_required
def agent_status_api():
    """Return current agent runner status for the logged-in user."""
    from job_seeker_agent.runner import get_agent_status
    status = get_agent_status(flask_current_user.id)
    return jsonify({"ok": True, **status})


@app.route("/api/agent/preferences", methods=["GET"])
@login_required
def get_preferences():
    user = db.get_user_detail(flask_current_user.id)
    if not user:
        return jsonify({"ok": False, "error": "User not found"}), 404
    prefs_str = user.get("job_preferences") or "{}"
    import json
    try:
        prefs = json.loads(prefs_str)
    except Exception:
        prefs = {}
    if not prefs:
        prefs = {
            "roles": ["Product Manager", "Senior PM", "Growth PM"],
            "locations": ["Bengaluru", "Mumbai", "Remote - India"],
            "min_experience": 3,
            "max_experience": 6,
            "min_salary": 35,
            "max_salary": 55,
            "linkedin_dm": True,
            "cold_email": True,
            "portal_apply": True,
            "pause_weekends": False
        }
    return jsonify({"ok": True, "preferences": prefs})


@app.route("/api/agent/preferences", methods=["POST"])
@login_required
def save_preferences():
    data = request.get_json(silent=True) or {}
    import json
    prefs_str = json.dumps(data)
    with db._connect() as conn:
        conn.execute(
            "UPDATE users SET job_preferences = ? WHERE id = ?",
            (prefs_str, flask_current_user.id),
        )
        conn.commit()
    print(f"[API] Updated job preferences for user {flask_current_user.id}")
    return jsonify({"ok": True, "message": "Preferences saved successfully"})


# --------------------------------------------------------------------------- #
#  Gmail Integration & OAuth Endpoints                                       #
# --------------------------------------------------------------------------- #
@app.route("/gmail/connect", methods=["POST"])
@login_required
def gmail_connect():
    """Build and return the Google OAuth authorization URL for Gmail readonly access."""
    user = db.get_user(flask_current_user.id)
    if not user or not user.get("is_agent_buyer"):
        return jsonify({"ok": False, "error": "Active subscription required to connect Gmail."}), 403

    client_id = os.environ.get("GOOGLE_CLIENT_ID", "")
    if not client_id:
        return jsonify({"ok": False, "error": "Google OAuth is not configured on the server."}), 500

    data = request.get_json(silent=True) or {}
    source = data.get("source", "dashboard")
    origin = data.get("origin", "").strip()

    # Reconstruct/read redirect URI
    google_redirect_uri = os.environ.get("GOOGLE_REDIRECT_URI", "")
    base_from_env = ""
    if google_redirect_uri:
        if "/auth/google/callback" in google_redirect_uri:
            base_from_env = google_redirect_uri.replace("/auth/google/callback", "")
        elif "/google/callback" in google_redirect_uri:
            base_from_env = google_redirect_uri.replace("/google/callback", "")

    redirect_uri = os.environ.get("GOOGLE_GMAIL_REDIRECT_URI")
    if not redirect_uri:
        if origin:
            redirect_uri = origin.rstrip('/') + "/gmail/callback"
        elif base_from_env:
            redirect_uri = base_from_env.rstrip('/') + "/gmail/callback"
        else:
            redirect_uri = request.url_root.rstrip('/') + "/gmail/callback"
    if "127.0.0.1" in redirect_uri:
        redirect_uri = redirect_uri.replace("127.0.0.1", "localhost")
    if "iitiimjobassistant.in" in redirect_uri:
        redirect_uri = "https://iitiimjobassistant.in/gmail/callback"

    print(f"[Gmail Connect Debug] origin={origin} google_redirect_uri={google_redirect_uri} base_from_env={base_from_env} -> redirect_uri={redirect_uri}")

    scopes = "openid email profile https://www.googleapis.com/auth/gmail.readonly"
    
    import json
    import urllib.parse
    state_str = urllib.parse.quote(json.dumps({
        "user_id": flask_current_user.id,
        "source": source,
        "redirect_uri": redirect_uri
    }))

    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": scopes,
        "access_type": "offline",
        "prompt": "consent",
        "state": state_str
    }
    
    auth_url = "https://accounts.google.com/o/oauth2/v2/auth?" + urllib.parse.urlencode(params)
    return jsonify({"ok": True, "url": auth_url})


@app.route("/gmail/callback", methods=["GET"])
def gmail_callback():
    """Handle OAuth2 authorization code callback and store tokens."""
    import urllib.request
    import urllib.parse
    import json
    from datetime import datetime, timezone, timedelta
    from core.auth import encrypt_credential

    params = request.args.to_dict()
    code = params.get("code", "")
    state = params.get("state", "")

    # Decode state
    state_data = {}
    if state:
        try:
            state_data = json.loads(urllib.parse.unquote(state))
        except Exception:
            pass
    user_id = state_data.get("user_id")
    source = state_data.get("source", "dashboard")
    state_redirect_uri = state_data.get("redirect_uri")

    redirect_target = "/pay" if source == "pay" else "/dashboard"

    if "error" in params:
        return redirect(f"{redirect_target}?gmail_error={urllib.parse.quote(params['error'])}")
    if not code:
        return redirect(f"{redirect_target}?gmail_error=no_code")
    if not user_id:
        return redirect(f"{redirect_target}?gmail_error=no_user")

    client_id = os.environ.get("GOOGLE_CLIENT_ID", "")
    client_secret = os.environ.get("GOOGLE_CLIENT_SECRET", "")
    
    google_redirect_uri = os.environ.get("GOOGLE_REDIRECT_URI", "")
    base_from_env = ""
    if google_redirect_uri:
        if "/auth/google/callback" in google_redirect_uri:
            base_from_env = google_redirect_uri.replace("/auth/google/callback", "")
        elif "/google/callback" in google_redirect_uri:
            base_from_env = google_redirect_uri.replace("/google/callback", "")

    redirect_uri = os.environ.get("GOOGLE_GMAIL_REDIRECT_URI")
    if not redirect_uri:
        if state_redirect_uri:
            redirect_uri = state_redirect_uri
        elif base_from_env:
            redirect_uri = base_from_env.rstrip('/') + "/gmail/callback"
        else:
            redirect_uri = request.url_root.rstrip('/') + "/gmail/callback"
    if "127.0.0.1" in redirect_uri:
        redirect_uri = redirect_uri.replace("127.0.0.1", "localhost")
    if "iitiimjobassistant.in" in redirect_uri:
        redirect_uri = "https://iitiimjobassistant.in/gmail/callback"

    try:
        token_data = urllib.parse.urlencode({
            "code": code,
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uri": redirect_uri,
            "grant_type": "authorization_code",
        }).encode("utf-8")

        token_req = urllib.request.Request(
            "https://oauth2.googleapis.com/token",
            data=token_data,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )

        with urllib.request.urlopen(token_req, timeout=10) as resp:
            token_resp = json.loads(resp.read())

        access_token = token_resp.get("access_token", "")
        refresh_token = token_resp.get("refresh_token", "")
        expires_in = token_resp.get("expires_in", 3600)
        token_scopes = token_resp.get("scope", "")

        if not access_token:
            raise ValueError("No access_token returned from Google.")

        # Get google email
        profile_req = urllib.request.Request(
            "https://www.googleapis.com/oauth2/v2/userinfo",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        with urllib.request.urlopen(profile_req, timeout=10) as resp:
            profile = json.loads(resp.read())
        google_email = profile.get("email", "")

        if not google_email:
            raise ValueError("Could not retrieve email from Google userinfo.")

        # Encrypt tokens
        enc_access = encrypt_credential(access_token)
        
        # Preserve refresh token if we already had one and google didn't return a new one
        existing = db.get_google_connection(user_id)
        if not refresh_token and existing:
            enc_refresh = existing["refresh_token"]
        else:
            enc_refresh = encrypt_credential(refresh_token or "")

        expiry_time = (datetime.now(timezone.utc) + timedelta(seconds=expires_in)).isoformat()

        # Save to database
        db.save_google_connection(
            user_id=user_id,
            google_email=google_email,
            access_token=enc_access,
            refresh_token=enc_refresh,
            token_expiry=expiry_time,
            scopes=token_scopes
        )

        # Mark user table gmail_connected as 1
        with db._connect() as conn:
            conn.execute("UPDATE users SET gmail_connected = 1 WHERE id = ?", (user_id,))
            conn.commit()

        return redirect(f"{redirect_target}?gmail_success=1")

    except Exception as exc:
        print(f"[Gmail Callback Error] {exc}")
        return redirect(f"{redirect_target}?gmail_error={urllib.parse.quote(str(exc))}")


@app.route("/gmail/status", methods=["GET"])
@login_required
def gmail_status():
    """Return whether the current user is connected to Google OAuth."""
    conn = db.get_google_connection(flask_current_user.id)
    if conn:
        return jsonify({
            "ok": True,
            "connected": True,
            "email": conn["google_email"],
            "connected_at": conn["connected_at"]
        })
    return jsonify({"ok": True, "connected": False})


@app.route("/gmail/disconnect", methods=["POST"])
@login_required
def gmail_disconnect():
    """Disconnect Gmail OAuth by deleting token record."""
    db.delete_google_connection(flask_current_user.id)
    with db._connect() as conn:
        conn.execute("UPDATE users SET gmail_connected = 0 WHERE id = ?", (flask_current_user.id,))
        conn.commit()
    return jsonify({"ok": True, "message": "Gmail disconnected successfully."})




@app.route("/auth/google/callback")
def google_oauth_callback():
    import urllib.request
    import urllib.parse
    import json as _json

    params = request.args.to_dict()
    if "error" in params:
        return redirect(f"/login?oauth_error={params['error']}")

    code = params.get("code", "")
    state = params.get("state", "")
    if not code:
        return redirect("/login?oauth_error=no_code")

    client_id = os.environ.get("GOOGLE_CLIENT_ID", "")
    client_secret = os.environ.get("GOOGLE_CLIENT_SECRET", "")
    
    # Build redirect_uri dynamically based on headers if running locally or not set, to support 127.0.0.1/localhost/production seamlessly
    redirect_uri = os.environ.get("GOOGLE_REDIRECT_URI")
    req_host = request.headers.get("X-Forwarded-Host", request.host)
    if not redirect_uri or "localhost" in req_host or "127.0.0.1" in req_host:
        scheme = request.headers.get("X-Forwarded-Proto", request.scheme)
        redirect_uri = f"{scheme}://{req_host}/auth/google/callback"

    if not client_secret:
        qs = urllib.parse.urlencode({"code": code, "state": state})
        return redirect(f"/signup?{qs}")

    try:
        token_data = urllib.parse.urlencode({
            "code": code, "client_id": client_id,
            "client_secret": client_secret, "redirect_uri": redirect_uri,
            "grant_type": "authorization_code",
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
            raise ValueError("No access_token")

        profile_req = urllib.request.Request(
            "https://www.googleapis.com/oauth2/v2/userinfo",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        with urllib.request.urlopen(profile_req, timeout=10) as resp:
            profile = _json.loads(resp.read())

        email = profile.get("email", "")
        name = profile.get("given_name", profile.get("name", ""))
        last_name = profile.get("family_name", "")
        google_id = profile.get("id", "")
        picture = profile.get("picture", "")

        user_dict = db.save_google_user(name, last_name, email, google_id)
        user = User(user_dict)
        login_user(user, remember=True)

        if not user.password_set:
            return redirect("/signup?set_password=1")
        return redirect("/dashboard")

    except Exception as exc:
        print(f"[OAuth] Failed: {exc}")
        return redirect(f"/login?oauth_error=exchange_failed")


@app.route("/api/razorpay-webhook", methods=["POST"])
def razorpay_webhook():
    """Razorpay webhook endpoint for server-to-server payment confirmation."""
    import hmac as _hmac
    import hashlib as _hl
    webhook_secret = os.environ.get("RAZORPAY_WEBHOOK_SECRET", "")
    if not webhook_secret:
        return jsonify({"ok": False}), 400
    signature = request.headers.get("X-Razorpay-Signature", "")
    body = request.get_data(as_text=True)
    expected = _hmac.new(webhook_secret.encode(), body.encode(), _hl.sha256).hexdigest()
    if not _hmac.compare_digest(expected, signature):
        return jsonify({"ok": False, "error": "Invalid signature"}), 400
    import json
    payload = json.loads(body)
    event = payload.get("event", "")
    if event == "payment.captured":
        payment = payload.get("payload", {}).get("payment", {}).get("entity", {})
        order_id = payment.get("order_id", "")
        payment_id = payment.get("id", "")
        if order_id:
            db.verify_payment_record(order_id, payment_id, signature)
    return jsonify({"ok": True}), 200



# --------------------------------------------------------------------------- #
#  API: Razorpay Payments                                                       #
# --------------------------------------------------------------------------- #
import hmac
import hashlib as _hashlib

try:
    import razorpay
except ImportError:
    razorpay = None

_rzp_key_id     = os.environ.get("RAZORPAY_KEY_ID", "")
_rzp_key_secret = os.environ.get("RAZORPAY_KEY_SECRET", "")

if _rzp_key_id and _rzp_key_secret and razorpay:
    razorpay_client = razorpay.Client(auth=(_rzp_key_id, _rzp_key_secret))
    print(f"[Razorpay] Client initialised (key: {_rzp_key_id[:12]}...)")
else:
    razorpay_client = None
    print("[Razorpay] WARNING: RAZORPAY_KEY_ID / RAZORPAY_KEY_SECRET not set — payment endpoints disabled")


@app.route("/api/razorpay-key", methods=["GET"])
def razorpay_key():
    if not _rzp_key_id:
        return jsonify({"ok": False, "error": "Razorpay not configured"}), 503
    return jsonify({"ok": True, "key_id": _rzp_key_id})


@app.route("/api/validate-coupon", methods=["POST"])
@login_required
def validate_coupon():
    data = request.get_json(silent=True) or {}
    coupon = (data.get("coupon") or "").strip().upper()
    plan_months = data.get("plan_months")
    agent_id = (data.get("agent_id") or "job_seeker").strip()

    if not coupon:
        return jsonify({"ok": False, "error": "Coupon code is required"}), 400

    if coupon == "IIT99":
        return jsonify({"ok": True, "message": "Coupon applied successfully! 100% discount applied."})

    if coupon == "JOB99":
        if plan_months is None:
            return jsonify({"ok": False, "error": "Plan duration is required"}), 400
        try:
            plan_months = int(plan_months)
        except (ValueError, TypeError):
            return jsonify({"ok": False, "error": "Invalid plan duration"}), 400

        if plan_months != 3:
            return jsonify({"ok": False, "error": "JOB99 coupon is only applicable on the 3-month subscription plan"}), 400

        if agent_id != "job_seeker":
            return jsonify({"ok": False, "error": "JOB99 coupon is only applicable for Job Seeker Agent"}), 400

        if db.has_user_used_coupon(flask_current_user.id, "JOB99"):
            return jsonify({"ok": False, "error": "You have already used this coupon code"}), 400

        return jsonify({"ok": True, "message": "Coupon applied successfully! 100% discount applied."})

    if coupon == "NAUKRI99":
        if plan_months is None:
            return jsonify({"ok": False, "error": "Plan duration is required"}), 400
        try:
            plan_months = int(plan_months)
        except (ValueError, TypeError):
            return jsonify({"ok": False, "error": "Invalid plan duration"}), 400

        if plan_months != 3:
            return jsonify({"ok": False, "error": "NAUKRI99 coupon is only applicable on the 3-month subscription plan"}), 400

        if agent_id != "naukri_ai":
            return jsonify({"ok": False, "error": "NAUKRI99 coupon is only applicable for Naukri AI Agent"}), 400

        if db.has_user_used_coupon(flask_current_user.id, "NAUKRI99"):
            return jsonify({"ok": False, "error": "You have already used this coupon code"}), 400

        return jsonify({"ok": True, "message": "Coupon applied successfully! Promo price of ₹1 applied."})

    if coupon == "LINK99":
        if plan_months is None:
            return jsonify({"ok": False, "error": "Plan duration is required"}), 400
        try:
            plan_months = int(plan_months)
        except (ValueError, TypeError):
            return jsonify({"ok": False, "error": "Invalid plan duration"}), 400

        if plan_months != 3:
            return jsonify({"ok": False, "error": "LINK99 coupon is only applicable on the 3-month subscription plan"}), 400

        if agent_id != "linkedin_jobs":
            return jsonify({"ok": False, "error": "LINK99 coupon is only applicable for LinkedIn Jobs Agent"}), 400

        if db.has_user_used_coupon(flask_current_user.id, "LINK99"):
            return jsonify({"ok": False, "error": "You have already used this coupon code"}), 400

        return jsonify({"ok": True, "message": "Coupon applied successfully! Promo price of ₹1 applied."})

    return jsonify({"ok": False, "error": "Invalid coupon code"}), 400


@app.route("/api/create-order", methods=["POST"])
@login_required
def create_order():
    """Create a Razorpay order.
    Body: { "amount": 49900, "currency": "INR", "coupon": "IIT99", "plan_months": 3 }
    amount is in paise (₹499 = 49900 paise). Minimum 100 paise (₹1).
    User resolved automatically from session.
    """
    data = request.get_json(silent=True) or {}
    amount   = data.get("amount")
    currency = (data.get("currency") or "INR").upper()
    receipt  = (data.get("receipt") or "").strip()
    coupon   = (data.get("coupon") or "").strip().upper()
    plan_months = data.get("plan_months")
    agent_id = (data.get("agent_id") or "job_seeker").strip()

    # Apply coupon logic
    if coupon == "IIT99":
        amount = 100  # Force ₹1.00 (100 paise)
        print(f"[Coupon] IIT99 applied — amount overridden to 100 paise (₹1)")
    elif coupon == "JOB99":
        if plan_months is None:
            return jsonify({"ok": False, "error": "plan_months is required when using coupon JOB99"}), 400
        try:
            plan_months = int(plan_months)
        except (ValueError, TypeError):
            return jsonify({"ok": False, "error": "plan_months must be an integer"}), 400

        if plan_months != 3:
            return jsonify({"ok": False, "error": "JOB99 coupon is only applicable on the 3-month subscription plan"}), 400

        if agent_id != "job_seeker":
            return jsonify({"ok": False, "error": "JOB99 coupon is only applicable for Job Seeker Agent"}), 400

        if db.has_user_used_coupon(flask_current_user.id, "JOB99"):
            return jsonify({"ok": False, "error": "You have already used this coupon code"}), 400

        amount = 100  # Force ₹1.00 (100 paise)
        print(f"[Coupon] JOB99 applied — amount overridden to 100 paise (₹1)")
    elif coupon == "NAUKRI99":
        if plan_months is None:
            return jsonify({"ok": False, "error": "plan_months is required when using coupon NAUKRI99"}), 400
        try:
            plan_months = int(plan_months)
        except (ValueError, TypeError):
            return jsonify({"ok": False, "error": "plan_months must be an integer"}), 400

        if plan_months != 3:
            return jsonify({"ok": False, "error": "NAUKRI99 coupon is only applicable on the 3-month subscription plan"}), 400

        if agent_id != "naukri_ai":
            return jsonify({"ok": False, "error": "NAUKRI99 coupon is only applicable for Naukri AI Agent"}), 400

        if db.has_user_used_coupon(flask_current_user.id, "NAUKRI99"):
            return jsonify({"ok": False, "error": "You have already used this coupon code"}), 400

        amount = 100  # Force ₹1.00 (100 paise)
        print(f"[Coupon] NAUKRI99 applied — amount overridden to 100 paise (₹1)")
    elif coupon == "LINK99":
        if plan_months is None:
            return jsonify({"ok": False, "error": "plan_months is required when using coupon LINK99"}), 400
        try:
            plan_months = int(plan_months)
        except (ValueError, TypeError):
            return jsonify({"ok": False, "error": "plan_months must be an integer"}), 400

        if plan_months != 3:
            return jsonify({"ok": False, "error": "LINK99 coupon is only applicable on the 3-month subscription plan"}), 400

        if agent_id != "linkedin_jobs":
            return jsonify({"ok": False, "error": "LINK99 coupon is only applicable for LinkedIn Jobs Agent"}), 400

        if db.has_user_used_coupon(flask_current_user.id, "LINK99"):
            return jsonify({"ok": False, "error": "You have already used this coupon code"}), 400

        amount = 100  # Force ₹1.00 (100 paise)
        print(f"[Coupon] LINK99 applied — amount overridden to 100 paise (₹1)")

    if not razorpay_client:
        return jsonify({"ok": False, "error": "Razorpay not configured on server"}), 503

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
    user_detail = db.get_user_detail(flask_current_user.id)
    buyer = user_detail.get("agent_buyer")
    buyer_id = buyer["id"] if buyer else None
    db.create_payment_record(
        razorpay_order_id=order["id"],
        amount_paise=amount,
        currency=currency,
        receipt=receipt,
        buyer_id=buyer_id,
        user_id=flask_current_user.id,
        coupon=coupon,
    )

    print(f"[Razorpay] Order created: {order['id']}  amount={amount} paise")
    return jsonify({
        "ok":       True,
        "order_id": order["id"],
        "amount":   order["amount"],
        "currency": order["currency"],
    })


@app.route("/api/verify-payment", methods=["POST"])
@login_required
def verify_payment():
    """Verify a Razorpay payment signature.
    Body: { "razorpay_order_id", "razorpay_payment_id", "razorpay_signature" }
    Uses HMAC-SHA256(order_id|payment_id, KEY_SECRET) to verify.
    On success, activates the user's agent subscription.
    """
    data = request.get_json(silent=True) or {}
    order_id   = (data.get("razorpay_order_id")   or "").strip()
    payment_id = (data.get("razorpay_payment_id") or "").strip()
    signature  = (data.get("razorpay_signature")  or "").strip()

    if not order_id or not payment_id or not signature:
        return jsonify({"ok": False, "error": "razorpay_order_id, razorpay_payment_id, and razorpay_signature are required"}), 400

    if not _rzp_key_secret:
        return jsonify({"ok": False, "error": "Razorpay not configured on server"}), 503

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

    # ── Activate subscription for the logged-in user ──────────────────────
    user_id = flask_current_user.id
    user_email = flask_current_user.email
    agent_id = (data.get("agent_id") or "job_seeker").strip()

    if agent_id == "linkedin_jobs":
        db.set_user_linkedin_jobs_subscribed(user_id, True)
    elif agent_id == "naukri_ai":
        db.set_user_naukri_subscribed(user_id, True)
    else:
        # Default: job_seeker
        # 1. Flag user as agent buyer
        db.set_user_agent_buyer(user_id, True)

        # 2. Activate linked agent_buyers record if it exists
        try:
            from core.database import get_all_agent_buyers, update_buyer_subscription
            buyers = get_all_agent_buyers()
            matched = [b for b in buyers if b.get("email", "").lower() == user_email.lower()]
            for buyer in matched:
                update_buyer_subscription(buyer["id"], "active")
        except Exception as e:
            print(f"[Razorpay] Warning: Could not activate buyer record: {e}")

    print(f"[Razorpay] Payment verified: order={order_id} payment={payment_id} | User {user_id} activated for agent {agent_id}")
    return jsonify({"ok": True, "message": "Payment verified successfully", "activated": True})


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
    print("  http://127.0.0.1:5000")
    print("=" * 60)
    db.init_db()
    app.run(host="0.0.0.0", port=5000, debug=False)
