# Admin Setup Guide

## Default Super Admin

On first boot, the system creates a default Super Admin:

| Field    | Value              |
|----------|--------------------|
| Email    | `admin@iitiim.ai`  |
| Password | `admin123`         |
| Role     | `SUPER_ADMIN`      |

> **⚠️ Change the default password in production!**

## Accessing the Admin Console

1. Start the server: `.\venv\Scripts\python.exe app.py`
2. Navigate to: `http://127.0.0.1:5000/admin`
3. Login with the credentials above

## Environment Variables

| Variable           | Description                              | Default                  |
|--------------------|------------------------------------------|--------------------------|
| `ADMIN_JWT_SECRET` | Secret key for signing admin JWT tokens  | Auto-generated on boot   |

Set `ADMIN_JWT_SECRET` in your `.env` for persistence across restarts.

## Creating Additional Admins

### Via API (Super Admin only)

```bash
curl -X POST http://127.0.0.1:5000/admin/admins \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"email": "mod@company.com", "password": "securepass", "role": "ADMIN", "name": "Moderator"}'
```

### Via Python Shell

```python
import database as db
db.init_db()
db.create_admin("mod@company.com", "securepass", "ADMIN", "Moderator")
```

## Roles

| Role          | Permissions                                      |
|---------------|--------------------------------------------------|
| `SUPER_ADMIN` | Full access + manage other admin accounts        |
| `ADMIN`       | Dashboard, approve/reject, user directory, audit |
| `USER`        | Read-only dashboard access (future use)          |

Currently `ADMIN` and `SUPER_ADMIN` have the same permissions except admin account management, which is `SUPER_ADMIN` only. More granular RBAC can be added by using the `require_role()` decorator on any endpoint.
