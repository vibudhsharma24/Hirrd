"""
resume_generator.py
───────────────────
Resume handler for the auto-apply engine.

Supports:
  - Using the uploaded resume as-is (legacy)
  - Rendering a Master CV to a premium HTML resume
  - Generating a PDF via Playwright headless print
  - Tailoring the CV for a specific JD using Claude
"""

import os
import sys
import json
import shutil
from pathlib import Path

# Add project root so we can import core modules when running standalone
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

RESUMES_DIR = os.path.join(os.path.dirname(__file__), "resumes")
GENERATED_DIR = os.path.join(RESUMES_DIR, "generated")


# ══════════════════════════════════════════════
#  LEGACY — Get resume for an application
# ══════════════════════════════════════════════

def get_resume_for_application(buyer: dict, post: dict | None = None) -> str:
    """Get the resume file path to use for an application.

    Priority:
      1. If user has a Master CV → generate a tailored PDF
      2. Otherwise → return the uploaded resume file as-is

    Args:
        buyer: Agent buyer dict with 'resume_path' key
        post: Optional post dict (for future job-specific tailoring)

    Returns:
        Absolute path to the resume file to upload.

    Raises:
        FileNotFoundError: If no resume is available.
    """
    # Try Master CV first
    try:
        from core.database import get_master_cv
        # Buyer is linked via email, we need user_id
        from core.database import get_user_by_email
        user = get_user_by_email(buyer.get("email", ""))
        if user:
            cv_data = get_master_cv(user["id"])
            if cv_data:
                # If post has description text, tailor it
                jd_text = ""
                if post:
                    jd_text = post.get("post_text", "") or post.get("description", "") or ""

                if jd_text.strip():
                    try:
                        tailored = tailor_cv_with_claude(cv_data, jd_text)
                        cv_data = tailored
                    except Exception as e:
                        print(f"[Resume] Tailoring failed, using raw CV: {e}")

                # Generate PDF
                os.makedirs(GENERATED_DIR, exist_ok=True)
                post_id = post.get("id", "0") if post else "0"
                pdf_path = os.path.join(GENERATED_DIR, f"tailored_{user['id']}_{post_id}.pdf")
                html = render_resume_html(cv_data)
                generate_pdf_from_html(html, pdf_path)
                if os.path.exists(pdf_path) and os.path.getsize(pdf_path) > 0:
                    return os.path.abspath(pdf_path)
    except Exception as e:
        print(f"[Resume] Master CV path failed: {e}")

    # Fallback: uploaded resume
    resume_path = buyer.get("resume_path", "")
    if not resume_path:
        raise FileNotFoundError("No resume path configured for this buyer")
    if not os.path.exists(resume_path):
        raise FileNotFoundError(f"Resume file not found: {resume_path}")
    return os.path.abspath(resume_path)


# ══════════════════════════════════════════════
#  COVER LETTER
# ══════════════════════════════════════════════

def get_cover_letter(buyer: dict, post: dict, mandatory: bool = False) -> str:
    """Generate a cover letter for an application.

    Only generates if mandatory=True (per user request).
    Uses Claude API if available, otherwise returns a template.

    Args:
        buyer: Agent buyer dict
        post: Post dict with title, company, post_text
        mandatory: Whether the ATS requires a cover letter

    Returns:
        Cover letter text, or empty string if not mandatory.
    """
    if not mandatory:
        return ""

    title = post.get("title", "the role")
    company = post.get("company", "your company")
    name = f"{buyer.get('name', '')} {buyer.get('last_name', '')}".strip()
    post_text = post.get("post_text", "")

    # Try using Claude API for personalised cover letter
    try:
        import anthropic
        api_key = os.environ.get("ANTHROPIC_API_KEY", "")
        if api_key and api_key != "your_claude_api_key":
            client = anthropic.Anthropic(api_key=api_key)
            snippet = post_text[:400] if post_text else ""

            prompt = f"""Write a short, professional cover letter (under 150 words) for:
- Applicant: {name}
- Role: {title}
- Company: {company}
{"- Context from job posting: " + snippet if snippet else ""}

The cover letter should:
- Be warm but professional
- Mention genuine interest in the role
- Be concise (3-4 sentences max)
- NOT fabricate skills or experience
- Sound human, not generic

Output ONLY the cover letter text. No greeting or sign-off needed."""

            response = client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=300,
                messages=[{"role": "user", "content": prompt}],
            )
            return response.content[0].text.strip()
    except Exception:
        pass

    # Fallback template
    return (
        f"I am excited to apply for the {title} role at {company}. "
        f"With my experience and skills, I believe I can add immediate value to your team. "
        f"I look forward to discussing this opportunity further."
    )


# ══════════════════════════════════════════════
#  HTML RESUME TEMPLATE
# ══════════════════════════════════════════════

def render_resume_html(cv_data: dict) -> str:
    """Render a Master CV dict into a premium, print-ready HTML resume."""
    personal = cv_data.get("personal", {})
    education = cv_data.get("education", [])
    experience = cv_data.get("experience", [])
    internships = cv_data.get("internships", [])
    coursework = cv_data.get("coursework", [])
    por = cv_data.get("positions_of_responsibility", [])
    certifications = cv_data.get("certifications", [])
    hobbies = cv_data.get("hobbies", [])

    full_name = f"{personal.get('name', '')} {personal.get('last_name', '')}".strip() or "Your Name"
    headline = personal.get("headline", "")
    email = personal.get("email", "")
    phone = personal.get("phone", "")
    linkedin = personal.get("linkedin_url", "")
    github = personal.get("github_url", "")
    portfolio = personal.get("portfolio_url", "")
    summary = personal.get("summary", "")

    # Build contact line
    contact_parts = []
    if email:
        contact_parts.append(f'<a href="mailto:{_esc(email)}">{_esc(email)}</a>')
    if phone:
        contact_parts.append(f'<span>{_esc(phone)}</span>')
    if linkedin:
        label = linkedin.replace("https://", "").replace("http://", "").rstrip("/")
        contact_parts.append(f'<a href="{_esc(linkedin)}">{_esc(label)}</a>')
    if github:
        label = github.replace("https://", "").replace("http://", "").rstrip("/")
        contact_parts.append(f'<a href="{_esc(github)}">{_esc(label)}</a>')
    if portfolio:
        label = portfolio.replace("https://", "").replace("http://", "").rstrip("/")
        contact_parts.append(f'<a href="{_esc(portfolio)}">{_esc(label)}</a>')
    contact_html = ' <span class="sep">|</span> '.join(contact_parts)

    # Sections
    sections_html = ""

    # Summary
    if summary:
        sections_html += f"""
        <div class="section">
            <h2>Professional Summary</h2>
            <p class="summary">{_esc(summary)}</p>
        </div>"""

    # Education
    if education:
        rows = ""
        for edu in education:
            degree = edu.get("degree", "")
            field = edu.get("field_of_study", "")
            inst = edu.get("institute", "")
            gpa = edu.get("gpa_or_percentage", "")
            years = ""
            if edu.get("start_year") and edu.get("end_year"):
                years = f"{edu['start_year']} – {edu['end_year']}"
            elif edu.get("end_year"):
                years = f"Class of {edu['end_year']}"

            degree_line = f"{degree}"
            if field:
                degree_line += f" in {field}"

            rows += f"""
            <div class="entry">
                <div class="entry-header">
                    <div>
                        <span class="entry-title">{_esc(inst)}</span>
                        <span class="entry-subtitle">{_esc(degree_line)}</span>
                    </div>
                    <div class="entry-meta">
                        {f'<span class="gpa">{_esc(gpa)}</span>' if gpa else ''}
                        {f'<span>{_esc(years)}</span>' if years else ''}
                    </div>
                </div>
            </div>"""

        sections_html += f"""
        <div class="section">
            <h2>Education</h2>
            {rows}
        </div>"""

    # Experience
    if experience:
        rows = ""
        for exp in experience:
            company = exp.get("company", "")
            role = exp.get("role", "")
            project = exp.get("project_title", "")
            dates = ""
            if exp.get("start_date") and exp.get("end_date"):
                dates = f"{exp['start_date']} – {exp['end_date']}"
            elif exp.get("start_date"):
                dates = f"{exp['start_date']} – Present"

            title_line = role
            if project:
                title_line += f" — {project}"

            bullets = ""
            for r in exp.get("responsibilities", []):
                if r.strip():
                    bullets += f"<li>{_esc(r)}</li>"

            rows += f"""
            <div class="entry">
                <div class="entry-header">
                    <div>
                        <span class="entry-title">{_esc(company)}</span>
                        <span class="entry-subtitle">{_esc(title_line)}</span>
                    </div>
                    <div class="entry-meta"><span>{_esc(dates)}</span></div>
                </div>
                {"<ul>" + bullets + "</ul>" if bullets else ""}
            </div>"""

        sections_html += f"""
        <div class="section">
            <h2>Work Experience</h2>
            {rows}
        </div>"""

    # Internships
    if internships:
        rows = ""
        for exp in internships:
            company = exp.get("company", "")
            role = exp.get("role", "")
            project = exp.get("project_title", "")
            dates = ""
            if exp.get("start_date") and exp.get("end_date"):
                dates = f"{exp['start_date']} – {exp['end_date']}"
            elif exp.get("start_date"):
                dates = f"{exp['start_date']} – Present"

            title_line = role
            if project:
                title_line += f" — {project}"

            bullets = ""
            for r in exp.get("responsibilities", []):
                if r.strip():
                    bullets += f"<li>{_esc(r)}</li>"

            rows += f"""
            <div class="entry">
                <div class="entry-header">
                    <div>
                        <span class="entry-title">{_esc(company)}</span>
                        <span class="entry-subtitle">{_esc(title_line)}</span>
                    </div>
                    <div class="entry-meta"><span>{_esc(dates)}</span></div>
                </div>
                {"<ul>" + bullets + "</ul>" if bullets else ""}
            </div>"""

        sections_html += f"""
        <div class="section">
            <h2>Internships</h2>
            {rows}
        </div>"""

    # Positions of Responsibility
    if por:
        rows = ""
        for p in por:
            title = p.get("title", "")
            org = p.get("organization", "")
            dates = ""
            if p.get("start_date") and p.get("end_date"):
                dates = f"{p['start_date']} – {p['end_date']}"

            bullets = ""
            for b in p.get("bullets", []):
                if b.strip():
                    bullets += f"<li>{_esc(b)}</li>"

            rows += f"""
            <div class="entry">
                <div class="entry-header">
                    <div>
                        <span class="entry-title">{_esc(title)}</span>
                        <span class="entry-subtitle">{_esc(org)}</span>
                    </div>
                    <div class="entry-meta"><span>{_esc(dates)}</span></div>
                </div>
                {"<ul>" + bullets + "</ul>" if bullets else ""}
            </div>"""

        sections_html += f"""
        <div class="section">
            <h2>Positions of Responsibility</h2>
            {rows}
        </div>"""

    # Certifications
    if certifications:
        rows = ""
        for c in certifications:
            title = c.get("title", "")
            issuer = c.get("issuer", "")
            date = c.get("date", "")
            desc = c.get("description", "")

            rows += f"""
            <div class="entry compact">
                <div class="entry-header">
                    <div>
                        <span class="entry-title">{_esc(title)}</span>
                        {f'<span class="entry-subtitle">{_esc(issuer)}</span>' if issuer else ''}
                    </div>
                    <div class="entry-meta"><span>{_esc(date)}</span></div>
                </div>
                {f'<p class="cert-desc">{_esc(desc)}</p>' if desc else ''}
            </div>"""

        sections_html += f"""
        <div class="section">
            <h2>Awards & Certifications</h2>
            {rows}
        </div>"""

    # Coursework
    if coursework:
        chips = ", ".join(_esc(c) for c in coursework if c.strip())
        sections_html += f"""
        <div class="section">
            <h2>Coursework & Electives</h2>
            <p class="chips">{chips}</p>
        </div>"""

    # Hobbies
    if hobbies:
        chips = ", ".join(_esc(h) for h in hobbies if h.strip())
        sections_html += f"""
        <div class="section">
            <h2>Hobbies & Interests</h2>
            <p class="chips">{chips}</p>
        </div>"""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{_esc(full_name)} — Resume</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>
  @page {{ size: A4; margin: 0; }}
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  html, body {{ font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif; font-size: 10px; line-height: 1.5; color: #1a1a2e; background: #fff; }}
  body {{ padding: 36px 42px; max-width: 210mm; }}

  /* Header */
  .header {{ text-align: center; padding-bottom: 14px; border-bottom: 2px solid #1a1a2e; margin-bottom: 16px; }}
  .header h1 {{ font-size: 22px; font-weight: 700; letter-spacing: 1.5px; text-transform: uppercase; color: #1a1a2e; }}
  .header .headline {{ font-size: 11px; font-weight: 500; color: #444; margin-top: 3px; }}
  .header .contact {{ font-size: 9px; color: #555; margin-top: 6px; display: flex; flex-wrap: wrap; justify-content: center; gap: 2px 0; }}
  .header .contact a {{ color: #2563eb; text-decoration: none; }}
  .header .contact .sep {{ margin: 0 6px; color: #ccc; }}

  /* Sections */
  .section {{ margin-bottom: 14px; }}
  .section h2 {{
    font-size: 11px; font-weight: 700; text-transform: uppercase; letter-spacing: 1.2px;
    color: #1a1a2e; border-bottom: 1px solid #ddd; padding-bottom: 3px; margin-bottom: 8px;
  }}
  .summary {{ font-size: 10px; color: #333; line-height: 1.55; }}

  /* Entries */
  .entry {{ margin-bottom: 10px; }}
  .entry.compact {{ margin-bottom: 6px; }}
  .entry-header {{ display: flex; justify-content: space-between; align-items: baseline; }}
  .entry-title {{ font-weight: 700; font-size: 10.5px; color: #1a1a2e; }}
  .entry-subtitle {{ font-weight: 500; font-size: 10px; color: #444; margin-left: 6px; font-style: italic; }}
  .entry-meta {{ font-size: 9px; color: #666; text-align: right; white-space: nowrap; }}
  .entry-meta .gpa {{ background: #f0f0f5; padding: 1px 6px; border-radius: 3px; font-weight: 600; margin-right: 8px; }}

  ul {{ margin: 3px 0 0 18px; padding: 0; }}
  li {{ font-size: 9.5px; color: #333; line-height: 1.5; margin-bottom: 1.5px; }}
  .chips {{ font-size: 9.5px; color: #333; line-height: 1.6; }}
  .cert-desc {{ font-size: 9px; color: #555; margin-top: 2px; }}
</style>
</head>
<body>
  <div class="header">
    <h1>{_esc(full_name)}</h1>
    {f'<div class="headline">{_esc(headline)}</div>' if headline else ''}
    <div class="contact">{contact_html}</div>
  </div>
  {sections_html}
</body>
</html>"""


def _esc(text: str) -> str:
    """HTML-escape a string."""
    if not text:
        return ""
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


# ══════════════════════════════════════════════
#  PDF GENERATION (Playwright)
# ══════════════════════════════════════════════

def generate_pdf_from_html(html_content: str, output_path: str):
    """Use Playwright headless Chromium to print HTML to an A4 PDF."""
    import asyncio

    async def _print_pdf():
        from playwright.async_api import async_playwright
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()
            await page.set_content(html_content, wait_until="networkidle")
            await page.pdf(
                path=output_path,
                format="A4",
                margin={"top": "0mm", "right": "0mm", "bottom": "0mm", "left": "0mm"},
                print_background=True,
            )
            await browser.close()

    # Run in a new event loop to avoid issues when called from sync Flask context
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        # We're inside an already-running loop (e.g. in an async context)
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor() as pool:
            pool.submit(lambda: asyncio.run(_print_pdf())).result()
    else:
        asyncio.run(_print_pdf())


# ══════════════════════════════════════════════
#  CV TAILORING WITH CLAUDE
# ══════════════════════════════════════════════

def tailor_cv_with_claude(cv_data: dict, jd_text: str) -> dict:
    """Use Claude to tailor the Master CV for a specific job description.

    Returns a modified copy of cv_data with:
    - Reordered/filtered experience entries
    - Rephrased bullet points matching JD keywords
    - Trimmed coursework to relevant subjects
    """
    import anthropic

    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        return cv_data  # No API key → return as-is

    client = anthropic.Anthropic(api_key=api_key)

    prompt = f"""You are a resume tailoring expert. Given a candidate's full CV data and a target job description, produce a TAILORED version of the CV.

Rules:
1. Keep all personal details unchanged.
2. Select and reorder the MOST RELEVANT experiences, projects, and skills for this role.
3. Rephrase bullet points to highlight keywords and achievements matching the JD.
4. Keep education unchanged. Filter coursework to relevant subjects only.
5. Limit experience entries to the 3-4 most relevant.
6. Limit internships to 2 most relevant.
7. Keep bullet points concise (one line each).
8. Return the SAME JSON schema as the input. No extra fields.
9. Return ONLY valid JSON. No markdown, no explanation.

CANDIDATE CV:
{json.dumps(cv_data, indent=2)[:6000]}

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
    return json.loads(raw.strip())

