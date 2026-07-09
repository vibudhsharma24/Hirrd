import os
import sys
import json
import asyncio
from pathlib import Path
from playwright.async_api import async_playwright

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from core import database as db
from job_seeker_agent.resume_generator import tailor_cv_with_claude, generate_pdf_from_html

RESUMES_DIR = os.path.join(PROJECT_ROOT, "resumes")
GENERATED_DIR = os.path.join(RESUMES_DIR, "generated")

def classify_role_family(job_title: str, job_desc: str, cv_data: dict) -> str:
    """
    Classify the job into one of the role families defined in CV variants.
    If Anthropic API is configured, uses Claude, else falls back to keyword matching.
    """
    variants = cv_data.get("variants", {})
    if not variants:
        return "default"
        
    variant_keys = list(variants.keys())
    
    # Try using Claude if API key is present
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if api_key and api_key != "your_claude_api_key":
        try:
            import anthropic
            client = anthropic.Anthropic(api_key=api_key)
            prompt = f"""You are a resume matching assistant.
Given a job description:
Title: {job_title}
Description: {job_desc[:1000]}

And these candidate CV variants (role families):
{json.dumps(variant_keys)}

Select the variant that best matches this job.
Return ONLY the exact variant key, or return "default" if none of them fit the job description.
Do not output markdown, explanations, or extra spaces."""

            response = client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=50,
                messages=[{"role": "user", "content": prompt}],
            )
            choice = response.content[0].text.strip()
            if choice in variant_keys or choice == "default":
                return choice
        except Exception as e:
            print(f"[Resume Tailor] Claude classification failed, falling back to keywords: {e}")

    # Fallback keyword matching
    best_variant = "default"
    best_score = 0
    title_lower = job_title.lower()
    
    for v_key in variant_keys:
        score = 0
        v_key_lower = v_key.lower()
        # Direct word overlap
        words = v_key_lower.split()
        for w in words:
            if w in title_lower and len(w) > 2:
                score += 2
        # Check specific skills overlap
        v_skills = variants[v_key].get("skills", [])
        for skill in v_skills:
            if skill.lower() in title_lower or skill.lower() in job_desc.lower():
                score += 1
                
        if score > best_score:
            best_score = score
            best_variant = v_key
            
    return best_variant

def merge_variant_overrides(cv_data: dict, variant_key: str) -> dict:
    """
    Merge the selected variant overrides into a copy of the base cv_data.
    """
    import copy
    tailored_cv = copy.deepcopy(cv_data)
    
    if variant_key == "default" or "variants" not in cv_data or variant_key not in cv_data["variants"]:
        return tailored_cv
        
    overrides = cv_data["variants"][variant_key]
    
    # 1. Headline & Summary overrides
    if "headline" in overrides:
        tailored_cv.setdefault("personal", {})["headline"] = overrides["headline"]
    if "summary" in overrides:
        tailored_cv.setdefault("personal", {})["summary"] = overrides["summary"]
        
    # 2. Skills override
    if "skills" in overrides:
        tailored_cv["skills"] = overrides["skills"]
        
    # 3. Experience overrides (merge by company)
    if "experience" in overrides:
        exp_overrides = overrides["experience"]
        for override in exp_overrides:
            co_name = override.get("company", "").lower()
            for exp in tailored_cv.get("experience", []):
                if exp.get("company", "").lower() == co_name:
                    if "role" in override:
                        exp["role"] = override["role"]
                    if "responsibilities" in override:
                        exp["responsibilities"] = override["responsibilities"]
                    if "achievements" in override:
                        exp["achievements"] = override["achievements"]
                    if "project_title" in override:
                        exp["project_title"] = override["project_title"]
                        
    # 4. Internships overrides
    if "internships" in overrides:
        int_overrides = overrides["internships"]
        for override in int_overrides:
            co_name = override.get("company", "").lower()
            for exp in tailored_cv.get("internships", []):
                if exp.get("company", "").lower() == co_name:
                    if "role" in override:
                        exp["role"] = override["role"]
                    if "responsibilities" in override:
                        exp["responsibilities"] = override["responsibilities"]
                    if "achievements" in override:
                        exp["achievements"] = override["achievements"]
                        
    return tailored_cv

def render_default_layout(cv_data: dict) -> str:
    """
    Render CV into HTML replicating IITIIMJobAssistant_SampleCV.pdf styling.
    - Name and details centered at top.
    - ACADEMIC PROFILE table.
    - WORK EXPERIENCE with side-by-side label and bullet cells.
    - SUMMER INTERNSHIP with side-by-side label and bullet cells.
    - COURSEWORK electives list.
    - POSITION OF RESPONSIBILITY list.
    - AWARDS AND ACHIEVEMENTS lists.
    - HOBBIES list.
    """
    personal = cv_data.get("personal", {})
    education = cv_data.get("education", [])
    experience = cv_data.get("experience", [])
    internships = cv_data.get("internships", [])
    coursework = cv_data.get("coursework", [])
    por = cv_data.get("positions_of_responsibility", [])
    certifications = cv_data.get("certifications", [])
    hobbies = cv_data.get("hobbies", [])

    full_name = f"{personal.get('name', '')} {personal.get('last_name', '')}".strip() or "Ajay Singh"
    headline = personal.get("headline", "")
    email = personal.get("email", "")
    phone = personal.get("phone", "")
    linkedin = personal.get("linkedin_url", "")
    gender = personal.get("gender", "Male")
    age = personal.get("age", "")

    # Header Contact lines
    contact_parts = []
    if age:
        contact_parts.append(f"{age} Years")
    if gender:
        contact_parts.append(gender)
    if email:
        contact_parts.append(f"Email: {email}")
    if phone:
        contact_parts.append(f"Phone: {phone}")
    contact_row_1 = " | ".join(contact_parts)
    
    contact_row_2 = f"Linkedin: {linkedin}" if linkedin else ""

    # ACADEMIC PROFILE
    edu_rows = ""
    if education:
        for edu in education:
            degree = edu.get("degree", "")
            field = edu.get("field_of_study", "")
            inst = edu.get("institute", "")
            gpa = edu.get("gpa_or_percentage", "")
            year = edu.get("end_year", "")
            
            deg_display = f"{degree} ({field})" if field else degree
            edu_rows += f"""
            <tr>
                <td>{deg_display}</td>
                <td>{inst}</td>
                <td style="text-align: center;">{gpa}</td>
                <td style="text-align: center;">{year}</td>
            </tr>"""

    academic_section = ""
    if education:
        academic_section = f"""
        <div class="section-title">ACADEMIC PROFILE</div>
        <table class="academic-table">
            <thead>
                <tr>
                    <th style="width: 40%;">Degree</th>
                    <th style="width: 40%;">Institute</th>
                    <th style="width: 12%; text-align: center;">%/CGPA</th>
                    <th style="width: 8%; text-align: center;">Year</th>
                </tr>
            </thead>
            <tbody>
                {edu_rows}
            </tbody>
        </table>"""

    # Helper function for side-by-side Work Experience/Internship rows
    def render_experience_block(exp_list, title_label):
        if not exp_list:
            return ""
        
        block_html = f'<div class="section-title">{title_label}</div>'
        for exp in exp_list:
            company = exp.get("company", "")
            role = exp.get("role", "")
            project = exp.get("project_title", "")
            dates = ""
            if exp.get("start_date") and exp.get("end_date"):
                dates = f"{exp['start_date']}-{exp['end_date']}"
            elif exp.get("start_date"):
                dates = f"{exp['start_date']}-Present"
                
            proj_html = f'<div class="project-title">Project Title: {project}</div>' if project else ''
            
            # Roles & Responsibilities list
            resp_bullets = "".join([f"<li>{r}</li>" for r in exp.get("responsibilities", []) if r.strip()])
            resp_row = ""
            if resp_bullets:
                resp_row = f"""
                <tr class="detail-row">
                    <td class="detail-label">Roles & Responsibilities</td>
                    <td class="detail-content">
                        <ul>{resp_bullets}</ul>
                    </td>
                </tr>"""
                
            # Achievements list
            ach_bullets = "".join([f"<li>{a}</li>" for a in exp.get("achievements", []) if a.strip()])
            ach_row = ""
            if ach_bullets:
                ach_row = f"""
                <tr class="detail-row">
                    <td class="detail-label">Achievements</td>
                    <td class="detail-content">
                        <ul>{ach_bullets}</ul>
                    </td>
                </tr>"""
                
            block_html += f"""
            <div class="exp-entry">
                <div class="exp-header">
                    <span class="exp-company">{company}</span>
                    <span class="exp-role">{role}</span>
                    <span class="exp-dates">{dates}</span>
                </div>
                {proj_html}
                <table class="exp-detail-table">
                    {resp_row}
                    {ach_row}
                </table>
            </div>"""
        return block_html

    work_experience_section = render_experience_block(experience, "WORK EXPERIENCE")
    internships_section = render_experience_block(internships, "SUMMER INTERNSHIP")

    # COURSEWORK
    coursework_section = ""
    if coursework:
        cw_items = "".join([f"<li>{cw}</li>" for cw in coursework if cw.strip()])
        coursework_section = f"""
        <div class="section-title">COURSEWORK</div>
        <div class="coursework-container">
            <strong>Electives</strong>
            <ul class="cw-list">{cw_items}</ul>
        </div>"""

    # POSITION OF RESPONSIBILITY
    por_section = ""
    if por:
        por_rows = ""
        for p in por:
            title = p.get("title", "")
            org = p.get("organization", "")
            date = p.get("date", "") or p.get("start_date", "")
            bullets = "".join([f"<li>{b}</li>" for b in p.get("bullets", []) if b.strip()])
            
            por_rows += f"""
            <div class="por-entry">
                <div class="por-header">
                    <span class="por-title">{title}, {org}</span>
                    <span class="por-date">{date}</span>
                </div>
                {"<ul>" + bullets + "</ul>" if bullets else ""}
            </div>"""
        por_section = f"""
        <div class="section-title">POSITION OF RESPONSIBILITY</div>
        {por_rows}"""

    # AWARDS AND ACHIEVEMENTS
    awards_section = ""
    if certifications:
        cert_bullets = ""
        for c in certifications:
            title = c.get("title", "")
            issuer = c.get("issuer", "")
            date = c.get("date", "")
            desc = f" ({issuer})" if issuer else ""
            date_str = f" {date}" if date else ""
            cert_bullets += f"<li>{title}{desc}{date_str}</li>"
            
        awards_section = f"""
        <div class="section-title">AWARDS AND ACHIEVEMENTS</div>
        <ul class="standard-bullets">
            {cert_bullets}
        </ul>"""

    # HOBBIES
    hobbies_section = ""
    if hobbies:
        hobbies_list = "".join([f"<li>{h}</li>" for h in hobbies if h.strip()])
        hobbies_section = f"""
        <div class="section-title">HOBBIES</div>
        <ul class="hobbies-list">
            {hobbies_list}
        </ul>"""

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<style>
    @page {{ size: A4; margin: 10mm 12mm; }}
    body {{
        font-family: 'Segoe UI', Arial, sans-serif;
        font-size: 10px;
        line-height: 1.35;
        color: #111;
        margin: 0;
        padding: 0;
    }}
    /* Header styling */
    .header {{
        text-align: center;
        margin-bottom: 10px;
    }}
    .header .name {{
        font-size: 20px;
        font-weight: bold;
        text-transform: uppercase;
        margin-bottom: 2px;
    }}
    .header .info-row {{
        font-size: 9.5px;
        color: #333;
        margin-bottom: 2px;
    }}
    .header .headline {{
        font-size: 9.5px;
        font-weight: bold;
        font-style: italic;
        margin-top: 4px;
        color: #222;
        border-top: 1px solid #ccc;
        border-bottom: 1px solid #ccc;
        padding: 2px 0;
    }}
    
    /* Section title styling */
    .section-title {{
        font-size: 10.5px;
        font-weight: bold;
        background-color: #f1f5f9;
        border-bottom: 1.5px solid #1e293b;
        padding: 2px 5px;
        margin-top: 10px;
        margin-bottom: 6px;
        letter-spacing: 0.5px;
    }}
    
    /* Academic Table */
    .academic-table {{
        width: 100%;
        border-collapse: collapse;
        margin-bottom: 8px;
    }}
    .academic-table th {{
        font-weight: bold;
        background-color: #f8fafc;
        border: 1px solid #cbd5e1;
        padding: 4px 6px;
        font-size: 9.5px;
        text-align: left;
    }}
    .academic-table td {{
        border: 1px solid #cbd5e1;
        padding: 4px 6px;
        font-size: 9.5px;
    }}
    
    /* Experience Entries */
    .exp-entry {{
        margin-bottom: 8px;
    }}
    .exp-header {{
        display: flex;
        justify-content: space-between;
        font-weight: bold;
        font-size: 10px;
        margin-bottom: 1px;
    }}
    .exp-company {{
        width: 35%;
    }}
    .exp-role {{
        width: 45%;
        text-align: left;
    }}
    .exp-dates {{
        width: 20%;
        text-align: right;
    }}
    .project-title {{
        font-size: 9.5px;
        font-weight: bold;
        margin-bottom: 3px;
        color: #334155;
    }}
    
    /* Side-by-Side Tabular Layout */
    .exp-detail-table {{
        width: 100%;
        border-collapse: collapse;
    }}
    .detail-row {{
        vertical-align: top;
    }}
    .detail-label {{
        width: 120px;
        font-size: 8.5px;
        font-weight: bold;
        text-transform: uppercase;
        color: #475569;
        border-right: 1.5px solid #cbd5e1;
        padding: 2px 6px 2px 0;
        line-height: 1.2;
    }}
    .detail-content {{
        padding: 1px 0 1px 8px;
    }}
    .detail-content ul {{
        margin: 0;
        padding-left: 12px;
        list-style-type: square;
    }}
    .detail-content li {{
        margin-bottom: 2px;
        font-size: 9.5px;
    }}
    
    /* Lists & Inline formatting */
    .coursework-container {{
        display: flex;
        font-size: 9.5px;
    }}
    .coursework-container strong {{
        width: 120px;
    }}
    .cw-list {{
        display: flex;
        flex-wrap: wrap;
        list-style: none;
        margin: 0;
        padding: 0;
    }}
    .cw-list li {{
        margin-right: 15px;
    }}
    .cw-list li::before {{
        content: "■  ";
        color: #475569;
        font-size: 8px;
    }}
    
    .por-entry {{
        margin-bottom: 4px;
        font-size: 9.5px;
    }}
    .por-header {{
        display: flex;
        justify-content: space-between;
        font-weight: bold;
    }}
    .por-entry ul {{
        margin: 2px 0;
        padding-left: 15px;
    }}
    .por-entry li {{
        margin-bottom: 1px;
    }}
    
    .standard-bullets {{
        margin: 0;
        padding-left: 15px;
    }}
    .standard-bullets li {{
        margin-bottom: 2px;
        font-size: 9.5px;
    }}
    
    .hobbies-list {{
        display: flex;
        flex-wrap: wrap;
        list-style: none;
        margin: 0;
        padding: 0;
        font-size: 9.5px;
    }}
    .hobbies-list li {{
        margin-right: 15px;
    }}
    .hobbies-list li::before {{
        content: "■  ";
        color: #475569;
        font-size: 8px;
    }}
</style>
</head>
<body>
    <div class="header">
        <div class="name">{full_name}</div>
        <div class="info-row">{contact_row_1}</div>
        {f'<div class="info-row">{contact_row_2}</div>' if contact_row_2 else ''}
        {f'<div class="headline">{headline}</div>' if headline else ''}
    </div>
    
    {academic_section}
    {work_experience_section}
    {internships_section}
    {coursework_section}
    {por_section}
    {awards_section}
    {hobbies_section}
</body>
</html>"""
    return html

def load_template() -> str | None:
    """
    Look for a shared HTML template at resumes/shared_template.html or resumes/naukri_template.html.
    Returns the string content of the template, or None if not found.
    """
    paths = [
        os.path.join(RESUMES_DIR, "shared_template.html"),
        os.path.join(RESUMES_DIR, "naukri_template.html")
    ]
    for p in paths:
        if os.path.exists(p):
            try:
                with open(p, "r", encoding="utf-8") as f:
                    return f.read()
            except Exception as e:
                print(f"[Resume Tailor] Failed reading template {p}: {e}")
    return None

def generate_tailored_resume(user_id: int, job: dict, cv_data: dict) -> str:
    """
    Runs the complete selection, override merging, dynamic tailoring, and PDF export pipeline.
    Saves the PDF to resumes/generated/naukri_tailored_{user_id}_{job_id}.pdf.
    Returns the absolute path of the generated PDF.
    """
    job_id = job.get("job_id") or job.get("url", "").split("/")[-1] or "temp"
    job_title = job.get("title", "")
    job_desc = job.get("description", "") or job.get("skills", "") or ""
    if isinstance(job_desc, list):
        job_desc = ", ".join(job_desc)

    print(f"[Resume Tailor] Beginning tailoring process for job='{job_title}'...")

    # 1. Pick correct resume variant by role family
    variant_key = classify_role_family(job_title, job_desc, cv_data)
    print(f"  Selected Role Family Variant: '{variant_key}'")

    # 2. Merge overrides
    tailored_cv = merge_variant_overrides(cv_data, variant_key)

    # 3. Dynamic tailoring via Claude if key is present
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if api_key and api_key != "your_claude_api_key":
        try:
            print("  Performing dynamic bullet rephrasing with Claude...")
            tailored_cv = tailor_cv_with_claude(tailored_cv, job_desc)
        except Exception as e:
            print(f"  Dynamic tailoring failed: {e}")
    else:
        print("  Anthropic API key not provided or placeholder. Skipping dynamic Claude tailoring.")

    # 4. Handle Template rendering
    template_html = load_template()
    if template_html:
        print("  Using custom shared HTML template...")
        # Basic variable interpolation for template placeholder tags
        html_content = template_html
        personal = tailored_cv.get("personal", {})
        full_name = f"{personal.get('name', '')} {personal.get('last_name', '')}".strip()
        
        replacements = {
            "{{name}}": full_name,
            "{{headline}}": personal.get("headline", ""),
            "{{email}}": personal.get("email", ""),
            "{{phone}}": personal.get("phone", ""),
            "{{linkedin}}": personal.get("linkedin_url", ""),
            "{{summary}}": personal.get("summary", ""),
        }
        for k, v in replacements.items():
            html_content = html_content.replace(k, v)
    else:
        print("  Using premium default academic/corporate layout matching Sample CV...")
        html_content = render_default_layout(tailored_cv)

    # 5. Export to PDF
    os.makedirs(GENERATED_DIR, exist_ok=True)
    pdf_filename = f"naukri_tailored_{user_id}_{job_id}.pdf"
    pdf_path = os.path.join(GENERATED_DIR, pdf_filename)
    
    print(f"  Printing tailored HTML resume to PDF via Playwright...")
    generate_pdf_from_html(html_content, pdf_path)
    
    if os.path.exists(pdf_path) and os.path.getsize(pdf_path) > 0:
        abs_path = os.path.abspath(pdf_path)
        print(f"[Resume Tailor] Success! Tailored PDF generated at: {abs_path}")
        return abs_path
    else:
        raise RuntimeError("PDF generation failed or output file is empty.")
