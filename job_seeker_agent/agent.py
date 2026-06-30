"""
Auto Job Application Agent
- Parses resume (PDF or DOCX) with Claude AI
- Fetches user profile from MySQL
- Auto-fills Google Forms using Playwright
"""

import os
import sys
import json
import time
import asyncio
import pdfplumber
import sqlite3
import anthropic
from pathlib import Path
from docx import Document
from playwright.async_api import async_playwright

# Force UTF-8 encoding on Windows consoles to prevent UnicodeEncodeError with emojis
if sys.platform.startswith("win"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass


# ─────────────────────────────────────────────
#  CONFIG
# ─────────────────────────────────────────────
_client = None

def get_anthropic_client():
    global _client
    if _client is None:
        api_key = os.getenv("ANTHROPIC_API_KEY", "")
        if api_key:
            _client = anthropic.Anthropic(api_key=api_key)
        else:
            _client = anthropic.Anthropic()
    return _client


# ══════════════════════════════════════════════
#  STEP 1 — RESUME PARSING
# ══════════════════════════════════════════════

def extract_text_from_pdf(path: str) -> str:
    """Extract raw text from a PDF resume."""
    text = ""
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            text += (page.extract_text() or "") + "\n"
    return text.strip()


def extract_text_from_docx(path: str) -> str:
    """Extract raw text from a DOCX resume."""
    doc = Document(path)
    return "\n".join(p.text for p in doc.paragraphs if p.text.strip())


def extract_resume_text(path: str) -> str:
    """Auto-detect format and extract resume text."""
    path = str(path).lower()
    if path.endswith(".pdf"):
        return extract_text_from_pdf(path)
    elif path.endswith(".docx"):
        return extract_text_from_docx(path)
    else:
        raise ValueError(f"Unsupported resume format: {path}")


def parse_resume_with_claude(resume_text: str) -> dict:
    """Use Claude to extract structured info from resume text."""
    print("🤖 Parsing resume with Claude AI...")

    prompt = f"""You are a resume parser. Extract ALL information from this resume and return it as a JSON object.

Include every field you can find. Common fields:
- full_name, email, phone, address, city, state, country, zip_code
- linkedin_url, github_url, portfolio_url, website
- current_title, years_of_experience
- summary / objective
- skills (list)
- education (list of: degree, field, institution, graduation_year, gpa)
- work_experience (list of: company, title, start_date, end_date, description)
- certifications (list)
- languages (list)
- projects (list of: name, description, url)

Return ONLY valid JSON, no markdown, no explanation.

RESUME TEXT:
{resume_text}"""

    response = get_anthropic_client().messages.create(
        model="claude-sonnet-4-6",
        max_tokens=2000,
        messages=[{"role": "user", "content": prompt}]
    )

    raw = response.content[0].text.strip()
    # Strip markdown fences if present
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    return json.loads(raw.strip())


# ══════════════════════════════════════════════
#  STEP 2 — FETCH USER FROM MySQL
# ══════════════════════════════════════════════

def fetch_user_from_db(user_id: int = None, email: str = None) -> dict:
    """
    Fetch user profile from the SQLite database.
    Looks up in both 'agent_buyers' and 'users' tables by user_id or email.
    """
    print("🗄️  Fetching user profile from SQLite...")

    db_path = os.path.join(os.path.dirname(__file__), "users.db")
    if not os.path.exists(db_path):
        print(f"⚠️  Database file not found at {db_path}. Running without DB data.")
        return {}

    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        row = None
        # 1. First look in agent_buyers table
        if user_id:
            cursor.execute("SELECT * FROM agent_buyers WHERE id = ? LIMIT 1", (user_id,))
            row = cursor.fetchone()
        elif email:
            cursor.execute("SELECT * FROM agent_buyers WHERE email = ? LIMIT 1", (email,))
            row = cursor.fetchone()

        # 2. If not found, look in users table
        if not row:
            if user_id:
                cursor.execute("SELECT * FROM users WHERE id = ? LIMIT 1", (user_id,))
                row = cursor.fetchone()
            elif email:
                cursor.execute("SELECT * FROM users WHERE email = ? LIMIT 1", (email,))
                row = cursor.fetchone()

        conn.close()
        return dict(row) if row else {}
    except Exception as e:
        print(f"⚠️  SQLite error: {e}. Running without DB data.")
        return {}


# ══════════════════════════════════════════════
#  STEP 3 — INTELLIGENT FORM FILLING
# ══════════════════════════════════════════════

def get_form_answers_from_claude(form_fields: list[dict], resume_data: dict, user_data: dict) -> dict:
    """
    Given a list of form field labels, ask Claude to map the best answer
    from the combined resume + user profile data.
    Returns: { "field_label": "answer", ... }
    """
    print("🧠 Claude is mapping form fields to your profile...")

    combined_profile = {
        "resume": resume_data,
        "user_profile": user_data,
    }

    prompt = f"""You are an expert job application assistant. 
You have a candidate's full profile and a list of Google Form fields to fill.

Your job:
1. For each form field, find the best matching answer from the candidate profile.
2. Keep answers concise and professional.
3. For Yes/No or multiple-choice fields, pick the closest matching option from the "options" list.
4. If information is genuinely not available, use an empty string "".
5. Return ONLY a JSON object: {{ "field_label": "your_answer", ... }}

CANDIDATE PROFILE:
{json.dumps(combined_profile, indent=2)}

FORM FIELDS TO FILL:
{json.dumps(form_fields, indent=2)}

Return ONLY valid JSON. No markdown, no explanation."""

    response = get_anthropic_client().messages.create(
        model="claude-sonnet-4-6",
        max_tokens=2000,
        messages=[{"role": "user", "content": prompt}]
    )

    raw = response.content[0].text.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    return json.loads(raw.strip())


# ══════════════════════════════════════════════
#  STEP 4 — PLAYWRIGHT GOOGLE FORM AUTO-FILL
# ══════════════════════════════════════════════

async def scrape_and_fill_google_form(form_url: str, resume_data: dict, user_data: dict):
    """Open a Google Form, scrape its fields, get Claude answers, and auto-fill it."""

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)  # Set True for silent mode
        page = await browser.new_page()

        print(f"🌐 Opening Google Form: {form_url}")
        await page.goto(form_url, wait_until="networkidle")
        await page.wait_for_timeout(2000)

        # ── Scrape all form fields ──────────────────
        print("🔍 Scraping form fields...")
        form_fields = await page.evaluate("""() => {
            const fields = [];

            // Text / paragraph inputs
            document.querySelectorAll('[data-params]').forEach(container => {
                const label = container.querySelector('[role="heading"]')?.innerText?.trim()
                            || container.querySelector('label')?.innerText?.trim()
                            || container.querySelector('.freebirdFormviewerComponentsQuestionBaseTitle')?.innerText?.trim();

                if (!label) return;

                // Radio / checkbox options
                const options = [...container.querySelectorAll('[role="radio"], [role="checkbox"]')]
                    .map(el => el.getAttribute('aria-label') || el.innerText?.trim())
                    .filter(Boolean);

                // Dropdown options
                const dropdownOptions = [...container.querySelectorAll('[role="option"]')]
                    .map(el => el.innerText?.trim())
                    .filter(Boolean);

                const inputType = container.querySelector('input[type="text"]')    ? 'text'
                                : container.querySelector('textarea')              ? 'textarea'
                                : options.length > 0                               ? 'radio_checkbox'
                                : dropdownOptions.length > 0                       ? 'dropdown'
                                : 'unknown';

                fields.push({
                    label,
                    type: inputType,
                    options: [...options, ...dropdownOptions],
                });
            });

            return fields;
        }""")

        if not form_fields:
            # Fallback: simpler selector for newer Google Forms layout
            form_fields = await page.evaluate("""() => {
                const fields = [];
                document.querySelectorAll('.freebirdFormviewerComponentsQuestionBaseRoot').forEach(q => {
                    const label = q.querySelector('.freebirdFormviewerComponentsQuestionBaseTitle')?.innerText?.trim();
                    if (!label) return;
                    const options = [...q.querySelectorAll('.docssharedWizToggleLabeledLabelText')]
                        .map(el => el.innerText?.trim()).filter(Boolean);
                    const isTextarea = !!q.querySelector('textarea');
                    const isText = !!q.querySelector('input[type="text"]');
                    fields.push({
                        label,
                        type: isTextarea ? 'textarea' : isText ? 'text' : options.length ? 'radio_checkbox' : 'unknown',
                        options,
                    });
                });
                return fields;
            }""")

        print(f"📋 Found {len(form_fields)} fields: {[f['label'] for f in form_fields]}")

        if not form_fields:
            print("⚠️  Could not detect form fields. The form may require sign-in or uses a custom layout.")
            await browser.close()
            return

        # ── Get Claude answers ──────────────────────
        answers = get_form_answers_from_claude(form_fields, resume_data, user_data)
        print(f"✅ Claude generated answers: {json.dumps(answers, indent=2)}")

        # ── Fill each field ─────────────────────────
        print("✍️  Filling the form...")

        for field in form_fields:
            label = field["label"]
            answer = answers.get(label, "")
            if not answer:
                continue

            try:
                if field["type"] in ("text", "textarea"):
                    # Find input by nearby label text
                    input_el = page.locator(f"text={label}").locator("..").locator("input, textarea").first
                    await input_el.fill(str(answer))
                    await page.wait_for_timeout(300)

                elif field["type"] == "radio_checkbox":
                    # Click the matching option
                    option_el = page.locator(f'[aria-label="{answer}"]').first
                    await option_el.click()
                    await page.wait_for_timeout(300)

                elif field["type"] == "dropdown":
                    # Click dropdown then select option
                    dropdown = page.locator(f"text={label}").locator("..").locator('[role="listbox"], select').first
                    await dropdown.click()
                    await page.wait_for_timeout(500)
                    option = page.locator(f'[role="option"]:has-text("{answer}")').first
                    await option.click()
                    await page.wait_for_timeout(300)

            except Exception as e:
                print(f"  ⚠️  Could not fill '{label}': {e}")

        # ── Screenshot before submit ────────────────
        screenshots_dir = os.path.join(os.path.dirname(__file__), "screenshots")
        os.makedirs(screenshots_dir, exist_ok=True)
        screenshot_path = os.path.join(screenshots_dir, f"filled_form_{int(time.time())}.png")
        await page.screenshot(path=screenshot_path, full_page=True)
        print(f"📸 Screenshot saved: {screenshot_path}")

        # ── Submit ──────────────────────────────────
        print("🚀 Submitting form...")
        submit_btn = page.locator('[role="button"]:has-text("Submit"), input[type="submit"]').first
        await submit_btn.click()
        await page.wait_for_timeout(3000)

        # Check for confirmation
        confirmed = await page.locator("text=Your response has been recorded").is_visible()
        if confirmed:
            print("🎉 Form submitted successfully!")
        else:
            print("⚠️  Submission may have failed or needs CAPTCHA. Check the browser.")

        await page.wait_for_timeout(2000)
        await browser.close()


# ══════════════════════════════════════════════
#  MAIN ORCHESTRATOR
# ══════════════════════════════════════════════

async def run_agent(
    resume_path: str,
    form_url: str,
    user_id: int = None,
    user_email: str = None,
):
    print("\n" + "═" * 50)
    print("  🤖 AUTO JOB APPLICATION AGENT STARTED")
    print("═" * 50 + "\n")

    # 1. Parse resume
    print("📄 Extracting resume text...")
    resume_text = extract_resume_text(resume_path)
    resume_data = parse_resume_with_claude(resume_text)
    print(f"✅ Resume parsed. Name: {resume_data.get('full_name', 'Unknown')}")

    # 2. Fetch user from DB
    user_data = {}
    if user_id or user_email:
        user_data = fetch_user_from_db(user_id=user_id, email=user_email)
        print(f"✅ User fetched: {user_data.get('email', 'N/A')}")
    else:
        print("ℹ️  No user_id/email provided — using resume data only.")

    # 3. Fill the Google Form
    await scrape_and_fill_google_form(form_url, resume_data, user_data)

    print("\n✅ Agent finished.\n")


# ══════════════════════════════════════════════
#  ENTRY POINT
# ══════════════════════════════════════════════

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Auto Job Application Agent")
    parser.add_argument("--resume",   required=True,  help="Path to resume (PDF or DOCX)")
    parser.add_argument("--form",     required=True,  help="Google Form URL")
    parser.add_argument("--user-id",  type=int,       help="User ID in your MySQL DB (optional)")
    parser.add_argument("--email",                    help="User email to look up in MySQL (optional)")
    args = parser.parse_args()

    asyncio.run(run_agent(
        resume_path=args.resume,
        form_url=args.form,
        user_id=args.user_id,
        user_email=args.email,
    ))
