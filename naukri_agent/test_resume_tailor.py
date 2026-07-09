import os
import sys
import asyncio
import shutil
import sqlite3

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from core import database as db
from naukri_agent.resume_tailor import generate_tailored_resume, classify_role_family, merge_variant_overrides

def print_section(title):
    print("\n" + "=" * 80)
    print(f" {title.upper()}")
    print("=" * 80)

async def main():
    print_section("Resume Tailoring and Selection Test Suite")

    # Initialize DB
    db.init_db()
    
    user_id = 8888  # Dedicated test user ID for resume tailoring
    
    # 1. Clean previous state
    with db._connect_jobs() as conn:
        conn.execute("DELETE FROM naukri_applications WHERE user_id = ?", (user_id,))
        conn.commit()
    with db._connect() as conn:
        conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
        conn.execute(
            "INSERT INTO users (id, name, last_name, email, password_hash, submitted_at) VALUES (?, ?, ?, ?, ?, ?)",
            (user_id, "Test", "Candidate", "tailor_test@example.com", "mock_hash", "2026-07-07T00:00:00")
        )
        conn.execute("DELETE FROM master_cv WHERE user_id = ?", (user_id,))
        conn.commit()

    # 2. Setup mock CV with multiple variants: "Product Manager" and "Backend Developer"
    mock_cv = {
        "personal": {
            "name": "Ajay",
            "last_name": "Singh",
            "email": "ajay.singh@example.com",
            "phone": "+91 9999999999",
            "headline": "Software Engineer",
            "linkedin_url": "https://linkedin.com/in/ajay-singh",
            "gender": "Male",
            "age": "25"
        },
        "education": [
            {
                "degree": "MBA",
                "field_of_study": "Product Management",
                "institute": "IIM Bangalore",
                "gpa_or_percentage": "9.2/10",
                "end_year": "2025"
            },
            {
                "degree": "B.Tech",
                "field_of_study": "Computer Science",
                "institute": "IIT Delhi",
                "gpa_or_percentage": "9.5/10",
                "end_year": "2023"
            }
        ],
        "experience": [
            {
                "company": "Apple",
                "role": "Software Engineer",
                "project_title": "AI Supply Chain",
                "start_date": "2023-06",
                "end_date": "Present",
                "responsibilities": ["Developing core algorithms", "Debugging services"],
                "achievements": ["Sped up pipeline by 40%"]
            }
        ],
        "variants": {
            "Product Manager": {
                "headline": "Technical Product Manager | IIM Bangalore Alum",
                "skills": ["Product Strategy", "Agile", "Roadmapping"],
                "experience": [
                    {
                        "company": "Apple",
                        "role": "Product Manager Intern",
                        "responsibilities": ["Defined product roadmap", "Analyzed customer requirements"],
                        "achievements": ["Launched MVP which gained 10k users"]
                    }
                ]
            },
            "Backend Developer": {
                "headline": "Lead Backend Engineer | Python Specialist",
                "skills": ["Python", "FastAPI", "SQL", "Docker"],
                "experience": [
                    {
                        "company": "Apple",
                        "role": "Senior Backend Developer",
                        "responsibilities": ["Architected microservices using FastAPI", "Designed database schema"],
                        "achievements": ["Reduced latency by 50%"]
                    }
                ]
            }
        }
    }

    db.save_master_cv(user_id, mock_cv)
    print("Mock CV with variants registered in DB.")

    # 3. Test Classification
    print_section("Test 1: Role Family Classification")
    
    pm_job = {
        "title": "Technical Product Manager - Mobile Apps",
        "description": "Looking for a PM who can design roadmap, execute agile sprints, and coordinate with teams."
    }
    be_job = {
        "title": "Senior Python Backend Developer",
        "description": "Responsibilities include scaling FastAPI APIs, dockerizing services, and optimizing SQL."
    }
    generic_job = {
        "title": "Consultant",
        "description": "General consulting services."
    }
    
    pm_choice = classify_role_family(pm_job["title"], pm_job["description"], mock_cv)
    be_choice = classify_role_family(be_job["title"], be_job["description"], mock_cv)
    generic_choice = classify_role_family(generic_job["title"], generic_job["description"], mock_cv)
    
    print(f"  PM job classified as: '{pm_choice}' (Expected: 'Product Manager')")
    print(f"  Backend job classified as: '{be_choice}' (Expected: 'Backend Developer')")
    print(f"  Generic job classified as: '{generic_choice}' (Expected: 'default')")
    
    assert pm_choice == "Product Manager"
    assert be_choice == "Backend Developer"
    assert generic_choice == "default"
    print("[OK] Classification tests passed.")

    # 4. Test Override Merging
    print_section("Test 2: Override Merging")
    
    tailored_pm = merge_variant_overrides(mock_cv, "Product Manager")
    print(f"  PM Variant Headline: '{tailored_pm['personal']['headline']}'")
    print(f"  PM Variant Skills: {tailored_pm['skills']}")
    print(f"  PM Apple experience role: '{tailored_pm['experience'][0]['role']}'")
    
    assert tailored_pm['personal']['headline'] == "Technical Product Manager | IIM Bangalore Alum"
    assert "Product Strategy" in tailored_pm['skills']
    assert tailored_pm['experience'][0]['role'] == "Product Manager Intern"
    
    tailored_be = merge_variant_overrides(mock_cv, "Backend Developer")
    print(f"  Backend Variant Headline: '{tailored_be['personal']['headline']}'")
    print(f"  Backend Variant Skills: {tailored_be['skills']}")
    print(f"  Backend Apple experience role: '{tailored_be['experience'][0]['role']}'")
    
    assert tailored_be['personal']['headline'] == "Lead Backend Engineer | Python Specialist"
    assert "FastAPI" in tailored_be['skills']
    assert tailored_be['experience'][0]['role'] == "Senior Backend Developer"
    print("[OK] Override merging tests passed.")

    # 5. Test PDF Generation
    print_section("Test 3: Tailored PDF Generation")
    
    # Generate Backend Resume
    pdf_path_be = generate_tailored_resume(user_id, be_job, mock_cv)
    print(f"  Generated PDF path: {pdf_path_be}")
    
    assert os.path.exists(pdf_path_be)
    assert os.path.getsize(pdf_path_be) > 0
    print(f"[OK] Backend PDF exists and has size: {os.path.getsize(pdf_path_be)} bytes.")
    
    # Generate Product Manager Resume
    pdf_path_pm = generate_tailored_resume(user_id, pm_job, mock_cv)
    print(f"  Generated PDF path: {pdf_path_pm}")
    
    assert os.path.exists(pdf_path_pm)
    assert os.path.getsize(pdf_path_pm) > 0
    print(f"[OK] PM PDF exists and has size: {os.path.getsize(pdf_path_pm)} bytes.")

    # 6. Test DB application tracking integration
    print_section("Test 4: Crawler Integration Database Logs")
    
    # Add application with tailored resume path
    db.add_naukri_application(user_id, "mock-tailor-job-1", status="surfaced", tailored_resume_path=pdf_path_be)
    
    apps = db.get_naukri_applications(user_id)
    print(f"  Stored applications count: {len(apps)}")
    for app in apps:
        print(f"  Job ID: {app['job_id']} | Status: {app['status']} | Resume Path: {app.get('tailored_resume_path')}")
        
    assert len(apps) == 1
    assert apps[0]['job_id'] == "mock-tailor-job-1"
    assert apps[0]['tailored_resume_path'] == pdf_path_be
    print("[OK] Database tracking works perfectly.")
    
    print_section("All tests passed successfully!")

if __name__ == "__main__":
    asyncio.run(main())
