"""
auth.py
-------
Authentication & authorization for IITIIMJobAssistant.

Provides:
  - Flask-Login integration (session-based auth for regular users)
  - JWT-based auth for admin panel (kept for backwards compat with admin.js)
  - AES-256-GCM encryption helpers for LinkedIn credentials
"""

import os
import jwt
import hashlib
import base64
import functools
from datetime import datetime, timezone, timedelta
from flask import request, jsonify, session
from flask_login import LoginManager, UserMixin, login_user, logout_user, current_user

from core.database import (
    get_user, get_user_by_email, verify_user_login,
    verify_admin_login, get_admin_by_id,
)

# ── Flask-Login Setup ──────────────────────────────────────────────────────────

login_manager = LoginManager()
login_manager.login_view = "login_page"
login_manager.login_message_category = "info"


class User(UserMixin):
    """Flask-Login user wrapper around the DB user dict."""

    def __init__(self, user_dict):
        self._data = user_dict

    def get_id(self):
        return str(self._data["id"])

    @property
    def id(self):
        return self._data["id"]

    @property
    def email(self):
        return self._data.get("email", "")

    @property
    def name(self):
        return self._data.get("name", "")

    @property
    def last_name(self):
        return self._data.get("last_name", "")

    @property
    def full_name(self):
        return f"{self.name} {self.last_name}".strip()

    @property
    def status(self):
        return self._data.get("status", "pending")

    @property
    def is_agent_buyer(self):
        return bool(self._data.get("is_agent_buyer", 0))

    @property
    def agent_status(self):
        return self._data.get("agent_status", "inactive")

    @property
    def avatar(self):
        return self._data.get("avatar", "??")

    @property
    def password_set(self):
        return bool(self._data.get("password_set", 1))

    @property
    def auth_provider(self):
        return self._data.get("auth_provider", "email")

    def to_dict(self):
        """Return a safe dict (no password_hash) for API responses."""
        safe = {k: v for k, v in self._data.items() if k != "password_hash"}
        safe["full_name"] = self.full_name
        return safe


@login_manager.user_loader
def load_user(user_id):
    """Called by Flask-Login to reload user from session."""
    user_dict = get_user(int(user_id))
    if user_dict:
        return User(user_dict)
    return None


# ── JWT Auth for Admin Panel ───────────────────────────────────────────────────

def get_secret_key():
    return os.environ.get("SECRET_KEY", "iitiim-default-secret-change-me")


def generate_admin_token(admin_dict: dict) -> str:
    """Generate a JWT for an authenticated admin."""
    payload = {
        "admin_id": admin_dict["id"],
        "email": admin_dict["email"],
        "role": admin_dict["role"],
        "name": admin_dict.get("name", ""),
        "exp": datetime.now(timezone.utc) + timedelta(hours=8),
        "iat": datetime.now(timezone.utc),
    }
    return jwt.encode(payload, get_secret_key(), algorithm="HS256")


def decode_admin_token(token: str) -> dict | None:
    """Decode and validate an admin JWT. Returns payload or None."""
    try:
        payload = jwt.decode(token, get_secret_key(), algorithms=["HS256"])
        return payload
    except (jwt.ExpiredSignatureError, jwt.InvalidTokenError):
        return None


def admin_required(f):
    """Decorator: require a valid admin JWT in Authorization header."""
    @functools.wraps(f)
    def decorated(*args, **kwargs):
        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            return jsonify({"error": "Missing or invalid Authorization header"}), 401
        token = auth_header.split(" ", 1)[1]
        payload = decode_admin_token(token)
        if not payload:
            return jsonify({"error": "Invalid or expired token"}), 401
        request.admin = payload
        return f(*args, **kwargs)
    return decorated


def super_admin_required(f):
    """Decorator: require SUPER_ADMIN role."""
    @functools.wraps(f)
    @admin_required
    def decorated(*args, **kwargs):
        if request.admin.get("role") != "SUPER_ADMIN":
            return jsonify({"error": "Super Admin access required"}), 403
        return f(*args, **kwargs)
    return decorated


def restricted_admin_block(f):
    """Decorator: block restricted admin users (officishiv582@gmail.com) from accessing specific endpoints."""
    @functools.wraps(f)
    def decorated(*args, **kwargs):
        if hasattr(request, "admin") and request.admin.get("email") == "officishiv582@gmail.com":
            return jsonify({"ok": False, "error": "Insufficient permissions"}), 403
        return f(*args, **kwargs)
    return decorated


# ── AES-256-GCM Encryption for LinkedIn Credentials ───────────────────────────
#
# HOW IT WORKS:
# 1. A master ENCRYPTION_KEY is stored in .env (32+ char hex string)
# 2. When a user saves their LinkedIn credentials, we encrypt them using
#    AES-256-GCM with the master key
# 3. Each encrypted value gets a unique 12-byte nonce (IV) prepended
# 4. Format stored in DB: base64(nonce + ciphertext + tag)
# 5. To decrypt: decode base64 → split nonce (12 bytes) + rest → decrypt
#
# The master key NEVER leaves the server. If .env is compromised,
# rotate the key and re-encrypt all credentials.

def _get_encryption_key() -> bytes:
    """Get the 32-byte AES key from ENCRYPTION_KEY env var."""
    key_hex = os.environ.get("ENCRYPTION_KEY", "")
    if not key_hex:
        # Fallback: derive from SECRET_KEY (not ideal but functional)
        key_hex = hashlib.sha256(
            get_secret_key().encode("utf-8")
        ).hexdigest()
    # Ensure exactly 32 bytes
    return bytes.fromhex(key_hex[:64])


def encrypt_credential(plaintext: str) -> str:
    """Encrypt a string using AES-256-GCM. Returns base64-encoded result."""
    if not plaintext:
        return ""
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        key = _get_encryption_key()
        nonce = os.urandom(12)
        aesgcm = AESGCM(key)
        ciphertext = aesgcm.encrypt(nonce, plaintext.encode("utf-8"), None)
        return base64.b64encode(nonce + ciphertext).decode("utf-8")
    except ImportError:
        # cryptography not installed — store as-is (dev mode)
        return plaintext


def decrypt_credential(encrypted: str) -> str:
    """Decrypt an AES-256-GCM encrypted string. Returns plaintext."""
    if not encrypted:
        return ""
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        try:
            raw = base64.b64decode(encrypted)
        except Exception:
            return encrypted
        if len(raw) < 12:
            return encrypted
        key = _get_encryption_key()
        nonce = raw[:12]
        ciphertext = raw[12:]
        aesgcm = AESGCM(key)
        return aesgcm.decrypt(nonce, ciphertext, None).decode("utf-8")
    except ImportError:
        return encrypted
    except Exception:
        return encrypted

