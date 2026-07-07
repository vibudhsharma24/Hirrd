import sys
import os

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from core import database as db

def main():
    print("Initializing database...")
    db.init_db()
    
    print("\nChecking if table exists and retrieving all current naukri jobs...")
    try:
        jobs = db.get_all_naukri_jobs()
        print(f"Success! Retrieved {len(jobs)} jobs from 'naukri_jobs'.")
    except Exception as e:
        print(f"Error retrieving jobs: {e}")
        sys.exit(1)

    print("\nSaving a mock scraped Naukri job to 'naukri_jobs'...")
    mock_jobs = [
        {
            "job_id": "123456789012",
            "title": "Senior AI Engineer",
            "company": "DeepMind Partner",
            "location": "Bangalore",
            "experience": "5-8 Yrs",
            "description": "Develop state of the art agentic workflows.",
            "skills": ["Python", "Playwright", "LLMs", "AI Agent"],
            "posted_date": "1 Day Ago",
            "url": "https://www.naukri.com/job-123456789012",
            "portal": "naukri.com",
            "scraped_at": "2026-07-07T19:00:00"
        }
    ]
    
    try:
        db.save_naukri_jobs(mock_jobs)
        print("Mock job saved.")
    except Exception as e:
        print(f"Error saving job: {e}")
        sys.exit(1)

    print("\nRetrieving jobs again to verify mock job is saved...")
    jobs_after = db.get_all_naukri_jobs()
    print(f"Found {len(jobs_after)} jobs in database.")
    
    mock_retrieved = [j for j in jobs_after if j["job_id"] == "123456789012"]
    if mock_retrieved:
        job = mock_retrieved[0]
        print("\n=== Verified Stored Job Details ===")
        print(f"ID:          {job['id']}")
        print(f"Job ID:      {job['job_id']}")
        print(f"Title:       {job['title']}")
        print(f"Company:     {job['company']}")
        print(f"Location:    {job['location']}")
        print(f"Experience:  {job['experience']}")
        print(f"Description: {job['description']}")
        print(f"Skills:      {job['skills']} (Type: {type(job['skills'])})")
        print(f"URL:         {job['url']}")
        print(f"Status:      {job['status']}")
        print(f"Scraped At:  {job['scraped_at']}")
        print("====================================")
        print("\nAll database checks passed successfully!")
    else:
        print("Error: Mock job was not found in the retrieved list!")
        sys.exit(1)

if __name__ == "__main__":
    main()
