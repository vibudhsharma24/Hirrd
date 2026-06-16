"""
resume_generator.py
───────────────────
Simplified resume handler for the auto-apply engine.

Per user request: uses the uploaded resume as-is (no modifications).
Future versions can add AI-enhanced bullet point rewriting and template support.
"""

import os
import shutil
from pathlib import Path

RESUMES_DIR = os.path.join(os.path.dirname(__file__), "resumes")
GENERATED_DIR = os.path.join(RESUMES_DIR, "generated")


def get_resume_for_application(buyer: dict, post: dict | None = None) -> str:
    """Get the resume file path to use for an application.

    Currently returns the buyer's uploaded resume as-is.

    Args:
        buyer: Agent buyer dict with 'resume_path' key
        post: Optional post dict (for future job-specific tailoring)

    Returns:
        Absolute path to the resume file to upload.

    Raises:
        FileNotFoundError: If the resume file doesn't exist on disk.
    """
    resume_path = buyer.get("resume_path", "")

    if not resume_path:
        raise FileNotFoundError("No resume path configured for this buyer")

    if not os.path.exists(resume_path):
        raise FileNotFoundError(f"Resume file not found: {resume_path}")

    return os.path.abspath(resume_path)


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
                model="claude-sonnet-4-20250514",
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
