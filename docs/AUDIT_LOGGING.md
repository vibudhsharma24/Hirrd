# Audit Logging

Every admin action is recorded in the `audit_logs` table with full context.

## Action Types

| Action                   | Trigger                          | Target        |
|--------------------------|----------------------------------|---------------|
| `ADMIN_LOGIN`            | Admin signs in                   | —             |
| `VERIFICATION_APPROVED`  | Admin approves a verification    | User ID       |
| `VERIFICATION_REJECTED`  | Admin rejects a verification     | User ID       |
| `ADMIN_CREATED`          | Super Admin creates a new admin  | —             |
| `USER_UPDATED`           | Admin modifies a user record     | User ID       |
| `SUBSCRIPTION_UPDATED`   | Subscription status changes      | User ID       |

## Schema

| Column           | Type    | Description                           |
|------------------|---------|---------------------------------------|
| `id`             | INTEGER | Auto-increment primary key            |
| `admin_id`       | INTEGER | FK to admin_users.id                  |
| `admin_email`    | TEXT    | Denormalized for quick display        |
| `action`         | TEXT    | Action type (see table above)         |
| `target_user_id` | INTEGER | FK to users.id (nullable)             |
| `previous_value` | TEXT    | State before the action               |
| `new_value`      | TEXT    | State after the action                |
| `reason`         | TEXT    | Human-readable reason/notes           |
| `timestamp`      | TEXT    | ISO 8601 UTC timestamp                |
| `ip_address`     | TEXT    | Client IP (from X-Forwarded-For)      |

## Querying

```bash
# All logs
GET /admin/audit-logs

# Filter by action
GET /admin/audit-logs?action=VERIFICATION_REJECTED

# Search by reason/email
GET /admin/audit-logs?search=duplicate

# Date range
GET /admin/audit-logs?date_from=2026-05-01&date_to=2026-05-31

# Paginate
GET /admin/audit-logs?page=2&per_page=25
```
