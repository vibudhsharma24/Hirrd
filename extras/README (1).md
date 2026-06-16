# 🤖 Auto Job Application Agent

Automatically fills Google Forms for job applications using your resume (PDF/DOCX) and your MySQL user database — powered by Claude AI.

---

## How It Works

```
Your Resume (PDF/DOCX)
        │
        ▼
[1] Claude AI extracts structured data
        │
        ▼
[2] MySQL fetches user profile
        │
        ▼
[3] Claude maps data → form fields
        │
        ▼
[4] Playwright opens & auto-fills Google Form
        │
        ▼
    ✅ Submitted!
```

---

## Setup

### 1. Install dependencies

```bash
pip install -r requirements.txt
playwright install chromium
```

### 2. Configure environment

```bash
cp .env.example .env
# Edit .env with your real values
```

Your `.env` needs:
```
ANTHROPIC_API_KEY=sk-ant-...
DB_HOST=localhost
DB_PORT=3306
DB_USER=root
DB_PASSWORD=your_password
DB_NAME=your_database
```

### 3. MySQL Table Schema

The agent queries your `users` table. Make sure it has columns like:

```sql
CREATE TABLE users (
    id          INT PRIMARY KEY AUTO_INCREMENT,
    email       VARCHAR(255),
    full_name   VARCHAR(255),
    phone       VARCHAR(50),
    address     TEXT,
    city        VARCHAR(100),
    country     VARCHAR(100),
    linkedin    VARCHAR(255),
    -- any other fields your site collects
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

If your table has different column names, edit `fetch_user_from_db()` in `agent.py`.

---

## Usage

### Basic — resume only
```bash
python agent.py \
  --resume /path/to/resume.pdf \
  --form   "https://docs.google.com/forms/d/e/XXXXX/viewform"
```

### With MySQL user profile (by ID)
```bash
python agent.py \
  --resume  /path/to/resume.pdf \
  --form    "https://docs.google.com/forms/d/e/XXXXX/viewform" \
  --user-id 42
```

### With MySQL user profile (by email)
```bash
python agent.py \
  --resume /path/to/resume.pdf \
  --form   "https://docs.google.com/forms/d/e/XXXXX/viewform" \
  --email  user@example.com
```

---

## Integrate into Your Website (Flask/FastAPI Example)

```python
# In your web app backend:
import asyncio
from agent import run_agent

@app.route("/apply", methods=["POST"])
def apply_to_job():
    form_url    = request.json["form_url"]
    resume_path = f"/uploads/{current_user.id}/resume.pdf"
    
    asyncio.run(run_agent(
        resume_path=resume_path,
        form_url=form_url,
        user_id=current_user.id,
    ))
    return {"status": "applied"}
```

---

## Tips

| Scenario | What to do |
|---|---|
| Browser keeps closing before fill | Increase `wait_for_timeout` values in `agent.py` |
| Form fields not detected | Google updated their UI — check the JS selectors in `scrape_and_fill_google_form` |
| CAPTCHA appears | Run with `headless=False` and solve manually once |
| Form requires Google sign-in | Use `browser.new_context(storage_state="auth.json")` after saving login state |
| Want silent/background mode | Set `headless=True` in `p.chromium.launch(...)` |

---

## Files

```
job_agent/
├── agent.py          ← Main agent (all logic here)
├── requirements.txt  ← Python dependencies
├── .env.example      ← Config template
└── README.md         ← This file
```
