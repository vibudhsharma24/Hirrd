# Admin API Reference

All admin endpoints require a JWT token in the `Authorization: Bearer <token>` header, except `/admin/login`.

## Authentication

### `POST /admin/login`
Login and receive a JWT token (valid 24 hours).

**Request:** `{ "email": "admin@iitiim.ai", "password": "admin123" }`

**Response:** `{ "ok": true, "token": "eyJ...", "admin": { "id": 1, "email": "...", "role": "SUPER_ADMIN", "name": "..." } }`

### `GET /admin/me`
Return current admin info.

---

## Dashboard

### `GET /admin/dashboard`
Aggregate stats. Optional query: `?date_from=2026-01-01&date_to=2026-12-31`

**Response:** `{ "ok": true, "total_users": 120, "verified_users": 90, "pending_users": 20, "rejected_users": 10, "active_subscribers": 45, "inactive_subscribers": 5, "total_subscribers": 50, "verification_pass_rate": 90.0, "subscription_conversion_rate": 41.7 }`

### `GET /admin/dashboard/signups`
Daily signup chart data. Query: `?days=30` or `?date_from=...&date_to=...`

**Response:** `{ "ok": true, "signups": [{ "date": "2026-05-01", "count": 12 }, ...] }`

---

## Verification Queue

### `GET /admin/verifications`
List verification requests. Query: `?status=PENDING&page=1&per_page=50&search=...`

### `GET /admin/verifications/:id`
Single verification detail with user data.

### `POST /admin/verifications/:id/approve`
Approve a verification. Creates audit log entry.

### `POST /admin/verifications/:id/reject`
Reject a verification. **Body required:** `{ "reason": "No IIT/IIM found" }`. Returns 400 if reason is missing.

---

## User Directory

### `GET /admin/users`
Paginated user list. Query: `?page=1&per_page=20&search=...&status=pending&subscription=active&sort_by=submitted_at&sort_dir=DESC`

### `GET /admin/users/:id`
Full user detail with verification, subscription, and activity data.

---

## Audit Logs

### `GET /admin/audit-logs`
Paginated audit log. Query: `?page=1&per_page=50&search=...&action=VERIFICATION_APPROVED&date_from=...&date_to=...`

---

## Admin Management (Super Admin only)

### `GET /admin/admins`
List all admin accounts.

### `POST /admin/admins`
Create a new admin. **Body:** `{ "email": "...", "password": "...", "role": "ADMIN", "name": "..." }`
