# Database Schema Redesign: Two-Table User System

Split the single `users` table into two distinct tables — one for site signups and one for agent buyers — with updated fields, LinkedIn URL validation, and resume file storage.

## Proposed Changes

### New Schema

#### Table 1: `users` (site signups)

| Column | Type | Notes |
|---|---|---|
| `id` | INTEGER PK | Auto-increment |
| `name` | TEXT NOT NULL | First name |
| `last_name` | TEXT NOT NULL | **NEW** — Last name |
| `email` | TEXT NOT NULL | Keep existing |
| `password_hash` | TEXT NOT NULL | SHA-256 hash (unchanged) |
| `linkedin_url` | TEXT | **Validated** — must be a `linkedin.com` URL |
| `mobile_number` | TEXT | **NEW** |
| `avatar` | TEXT | 2-letter initials (now from name + last_name) |
| `status` | TEXT DEFAULT 'pending' | pending / approved / rejected |
| `reject_reason` | TEXT | |
| `submitted_at` | TEXT NOT NULL | ISO-8601 UTC |

#### Table 2: `agent_buyers` (NEW)

| Column | Type | Notes |
|---|---|---|
| `id` | INTEGER PK | Auto-increment |
| `name` | TEXT NOT NULL | First name |
| `last_name` | TEXT NOT NULL | Last name |
| `email` | TEXT NOT NULL | |
| `resume_path` | TEXT NOT NULL | File path to uploaded resume in `resumes/` |
| `created_at` | TEXT NOT NULL | ISO-8601 UTC |

---

### File System

#### [NEW] `resumes/` directory
- Created automatically on startup
- Stores uploaded resume files (PDF, DOCX, etc.)
- Naming convention: `<last_name>_<first_name>_<timestamp>.<ext>` (e.g., `doe_john_1716789000.pdf`)

---

### Database Layer

#### [MODIFY] [database.py](file:///c:/Users/VIBUDH/Desktop/projects/job%20assistant/database.py)

**Schema (`init_db`)**:
- Add `last_name` and `mobile_number` columns to `users` table
- Use `ALTER TABLE` migration for existing DB (adds columns if missing)
- Create new `agent_buyers` table

**LinkedIn validation**:
- New helper `_validate_linkedin_url(url)` — checks that the URL contains `linkedin.com`; raises `ValueError` otherwise

**`save_user()` updated signature**:
```python
def save_user(name, last_name, email, password, linkedin_url, mobile_number) -> dict
```

**New agent_buyers CRUD functions**:
- `save_agent_buyer(name, last_name, email, resume_file)` → saves file to `resumes/`, stores path in DB
- `get_agent_buyer(buyer_id)` → single row
- `get_all_agent_buyers()` → all rows
- `delete_agent_buyer(buyer_id)` → delete row + resume file from disk
- `get_agent_buyers_stats()` → total count

**Updated stats**:
- `get_stats()` now also returns `agent_buyers_total` count

---

### API Layer

#### [MODIFY] [app.py](file:///c:/Users/VIBUDH/Desktop/projects/job%20assistant/app.py)

**Updated endpoint**:
- `POST /api/signup` — now accepts `last_name` and `mobile_number`, validates LinkedIn URL

**New endpoints**:
| Method | Path | Description |
|---|---|---|
| `POST` | `/api/agent-buyers` | Create agent buyer (multipart form with resume file upload) |
| `GET` | `/api/agent-buyers` | List all agent buyers |
| `GET` | `/api/agent-buyers/<id>` | Get single agent buyer |
| `GET` | `/api/agent-buyers/<id>/resume` | Download the resume file |
| `DELETE` | `/api/agent-buyers/<id>` | Delete agent buyer + resume file |

**Updated endpoint**:
- `GET /api/export` — CSV export updated to include `last_name` and `mobile_number` columns

---

## User Review Required

> [!IMPORTANT]
> **Existing data migration**: The existing `users.db` has rows without `last_name` or `mobile_number`. I'll use `ALTER TABLE ADD COLUMN` to add these with defaults (`''`), so existing data is preserved but those fields will be empty for old rows.

> [!WARNING]
> **Resume file size**: There's no limit set on uploaded resume files by default. I'll add a **5 MB** max file size limit. Let me know if you want a different limit.

## Open Questions

1. **Allowed resume formats** — Should I restrict to PDF and DOCX only, or allow any file type?
2. **Email uniqueness** — Should `email` be `UNIQUE` in either/both tables to prevent duplicate signups?

## Verification Plan

### Automated Tests
- Run the Flask server and test all new endpoints via `curl` / API calls
- Verify LinkedIn URL validation rejects non-LinkedIn URLs
- Verify resume upload, storage, and download round-trip
- Verify existing user data is preserved after migration
