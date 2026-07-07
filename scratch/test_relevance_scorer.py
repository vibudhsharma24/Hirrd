import sys
import os

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from core import database as db
from naukri_agent.relevance_scorer import calculate_cv_experience, score_job, score_jobs

def main():
    print("=== Testing date parsing and experience calculation ===")
    mock_cv = {
        "experience": [
            {
                "role": "Python Developer",
                "start_date": "2020-01",
                "end_date": "2021-12",
                "description": "Built web applications using Python, Django, and PostgreSQL."
            },
            {
                "role": "Senior AI Engineer",
                "start_date": "Jan 2022",
                "end_date": "Present",
                "description": "Designed agentic workflows with LangChain, OpenAI, and python."
            }
        ],
        "skills": ["Python", "SQL", "LLM", "Agentic AI", "Git"]
    }
    
    cv_exp = calculate_cv_experience(mock_cv)
    print(f"Calculated CV Experience: {cv_exp} years (Expected ~6.5 years)")
    assert abs(cv_exp - 6.5) <= 0.2, f"Expected ~6.5 years, got {cv_exp}"

    # Stated preferences
    mock_prefs = {
        "roles": ["AI Engineer", "Python Developer"],
        "locations": ["Bangalore", "Remote"],
        "experience": 6
    }

    # Weights
    custom_weights = {
        "skills": 0.50,
        "role": 0.25,
        "experience": 0.15,
        "location": 0.10
    }

    print("\n=== Testing relevance scoring for various mock jobs ===")
    
    mock_jobs = [
        {
            "title": "Senior AI & LLM Engineer",
            "company": "Cognitive Systems",
            "location": "Bangalore/Bengaluru",
            "experience": "5-8 Yrs",
            "skills": ["python", "llm", "agentic ai", "langchain"],
            "url": "https://www.naukri.com/job-1"
        },
        {
            "title": "React Frontend Developer",
            "company": "UI Wizards",
            "location": "Mumbai",
            "experience": "2-4 Yrs",
            "skills": ["javascript", "react", "css", "html"],
            "url": "https://www.naukri.com/job-2"
        },
        {
            "title": "Python Specialist (Remote)",
            "company": "Global Solutions",
            "location": "Remote",
            "experience": "5-10 Yrs",
            "skills": ["python", "sql", "git", "fastapi"],
            "url": "https://www.naukri.com/job-3"
        }
    ]

    scored = score_jobs(mock_jobs, mock_cv, mock_prefs, custom_weights)
    
    # Sort descending by score
    scored.sort(key=lambda x: x["relevance_percent"], reverse=True)
    
    for j in scored:
        print(f"\nJob: {j['title']} at {j['company']}")
        print(f"  Location:   {j['location']}")
        print(f"  Experience: {j['experience']}")
        print(f"  Skills Required: {j['skills']}")
        print(f"  Relevance Score:  {j['relevance_percent']}%")

    # Assertions on relative order
    assert scored[0]["title"] == "Senior AI & LLM Engineer", "AI job should rank first"
    assert scored[1]["title"] == "Python Specialist (Remote)", "Python job should rank second"
    assert scored[2]["title"] == "React Frontend Developer", "React job should rank third (low relevance)"
    
    print("\n=== Testing database saving with relevance scores ===")
    db.init_db()
    
    # Save jobs to database
    db.save_naukri_jobs(scored)
    print("Saved jobs to database.")
    
    # Retrieve jobs from database
    db_jobs = db.get_all_naukri_jobs()
    print(f"Retrieved {len(db_jobs)} jobs from database.")
    
    # Check if relevance_percent matches for the stored jobs
    mismatches = 0
    for original in scored:
        stored = next((x for x in db_jobs if x["url"] == original["url"]), None)
        if stored:
            print(f"  URL: {stored['url']}")
            print(f"    Original Score: {original['relevance_percent']}%")
            print(f"    Stored Score:   {stored['relevance_percent']}%")
            if stored['relevance_percent'] != original['relevance_percent']:
                mismatches += 1
        else:
            print(f"  Error: Stored job not found for {original['url']}")
            sys.exit(1)
            
    assert mismatches == 0, f"Found {mismatches} relevance score mismatches in database!"
    print("\nAll unit tests passed successfully!")

if __name__ == "__main__":
    main()
