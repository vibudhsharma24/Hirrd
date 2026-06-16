# Role-Based Access Control (RBAC)

The IITIIMJobAssistant Admin Console uses Role-Based Access Control (RBAC) to enforce security boundaries between different administrative accounts.

## Admin Roles

The system supports three hierarchical administrative roles:

1. **SUPER_ADMIN**: Full system administrator. Authorized to perform all management operations, database migrations, and administrative user management (creating, updating, and deleting other admin/moderator accounts).
2. **ADMIN**: Standard moderator/analyst. Authorized to view the dashboard, approve/reject user verification requests, view the user directory, view audit logs, and modify candidate subscriptions.
3. **USER**: Read-only analyst. Authorized to view the dashboard and user directories, but cannot take action on verification approvals or modify subscriptions.

## Permission Matrix

| Endpoint | Description | USER | ADMIN | SUPER_ADMIN |
|---|---|:---:|:---:|:---:|
| `POST /admin/login` | Authentication | ✔ | ✔ | ✔ |
| `GET /admin/me` | Current Session Info | ✔ | ✔ | ✔ |
| `GET /admin/dashboard` | Dashboard Metrics & Trends | ✔ | ✔ | ✔ |
| `GET /admin/users` | View User Directory | ✔ | ✔ | ✔ |
| `GET /admin/users/:id` | View User Details & Profile | ✔ | ✔ | ✔ |
| `GET /admin/verifications` | View Verification Queue | ✔ | ✔ | ✔ |
| `GET /admin/audit-logs` | View Audit Trails | ✔ | ✔ | ✔ |
| `POST /admin/verifications/:id/approve` | Approve Verification Requests | ❌ | ✔ | ✔ |
| `POST /admin/verifications/:id/reject` | Reject Verification Requests | ❌ | ✔ | ✔ |
| `POST /admin/users/:id/subscription` | Update User Subscription | ❌ | ✔ | ✔ |
| `POST /admin/admins` | Create Admin Users | ❌ | ❌ | ✔ |
| `DELETE /admin/admins/:id` | Delete Admin Users | ❌ | ❌ | ✔ |

## Implementation in Backend

The authorization rules are enforced via the `@require_role` decorator in the Flask backend (`app.py`).

### Helper Decorator

```python
def require_role(*roles):
    """Decorator to enforce role permissions on API endpoints."""
    def decorator(f):
        @functools.wraps(f)
        def decorated(*args, **kwargs):
            # request.admin is populated by the @admin_required JWT middleware
            if not request.admin or request.admin.get("role") not in roles:
                return jsonify({"ok": False, "error": "Insufficient permissions"}), 403
            return f(*args, **kwargs)
        return decorated
    return decorator
```

### Usage Example

To restrict an endpoint to `SUPER_ADMIN` only:

```python
@app.route("/admin/admins", methods=["POST"])
@admin_required
@require_role("SUPER_ADMIN")
def api_create_admin():
    data = request.get_json() or {}
    # logic to create admin ...
```

To allow both `ADMIN` and `SUPER_ADMIN`:

```python
@app.route("/admin/verifications/<int:verif_id>/approve", methods=["POST"])
@admin_required
@require_role("ADMIN", "SUPER_ADMIN")
def api_approve_verification(verif_id):
    # logic to approve ...
```
