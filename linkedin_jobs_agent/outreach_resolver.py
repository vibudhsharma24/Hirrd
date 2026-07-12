"""
outreach_resolver.py
───────────────────
Analyzes job postings to identify if direct recruiter or job poster outreach is possible.
"""

def resolve_outreach_status(job: dict) -> dict:
    """
    Inspects a job listing dictionary and determines whether a recruiter or job poster is available.
    Sets 'has_recruiter_outreach' (1 or 0) and 'outreach_status' ('available' or 'unavailable').
    """
    name = (job.get("poster_name") or "").strip()
    url = (job.get("poster_url") or "").strip()
    info = (job.get("poster_info") or "").strip()
    
    # Set of generic/placeholder names that don't represent a specific reachable person
    generic_names = {
        "linkedin member", 
        "member", 
        "anonymous", 
        "hiring manager", 
        "recruiter", 
        "poster", 
        "talent acquisition",
        "human resources"
    }
    
    is_available = False
    
    # Check 1: We have a non-generic name
    if name and name.lower() not in generic_names and len(name) > 2:
        is_available = True
        
    # Check 2: We have a valid profile link
    if url and "/in/" in url.lower():
        is_available = True
        
    # Fallback: If poster_name is empty but poster_info looks like a name (e.g. short text, no generic terms)
    if not is_available and info:
        info_clean = info.lower()
        if len(info) > 3 and not any(gen in info_clean for gen in generic_names):
            # If the block is very short (under 4 words), it might be a name
            words = info.split()
            if len(words) <= 3:
                is_available = True
                if not name:
                    name = info
                    
    job_copy = job.copy()
    job_copy["has_recruiter_outreach"] = 1 if is_available else 0
    job_copy["outreach_status"] = "available" if is_available else "unavailable"
    job_copy["poster_name"] = name
    job_copy["poster_url"] = url
    
    return job_copy


def resolve_outreach_statuses(jobs: list[dict]) -> list[dict]:
    """Resolve outreach status for a list of jobs."""
    return [resolve_outreach_status(j) for j in jobs]
