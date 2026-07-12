import re
from datetime import datetime

def parse_date(date_str: str) -> datetime | None:
    """Normalize date strings like '2022-01', 'Jan 2020', 'December 2021', 'Present' to a datetime."""
    if not date_str:
        return None
    date_clean = date_str.lower().strip()
    if "present" in date_clean or "current" in date_clean or "now" in date_clean:
        return datetime.now()
        
    # Check for YYYY-MM
    m_ym = re.match(r'^(\d{4})[-/](\d{1,2})$', date_clean)
    if m_ym:
        try:
            return datetime(int(m_ym.group(1)), int(m_ym.group(2)), 1)
        except ValueError:
            pass
            
    # Check for just YYYY
    m_y = re.match(r'^(\d{4})$', date_clean)
    if m_y:
        return datetime(int(m_y.group(1)), 1, 1)
        
    # Check for text formats like "Jan 2020", "January 2020"
    months = {
        "jan": 1, "january": 1, "feb": 2, "february": 2, "mar": 3, "march": 3,
        "apr": 4, "april": 4, "may": 5, "jun": 6, "june": 6, "jul": 7, "july": 7,
        "aug": 8, "august": 8, "sep": 9, "september": 9, "oct": 10, "october": 10,
        "nov": 11, "november": 11, "dec": 12, "december": 12
    }
    
    m_text = re.findall(r'([a-zA-Z]+).+?(\d{4})|(\d{4}).+?([a-zA-Z]+)', date_clean)
    if m_text:
        parts = m_text[0]
        month_word = parts[0] or parts[3]
        year_val = parts[1] or parts[2]
        
        month_num = 1
        for m_name, m_val in months.items():
            if m_name in month_word.lower():
                month_num = m_val
                break
        try:
            return datetime(int(year_val), month_num, 1)
        except ValueError:
            pass
            
    return None


def calculate_cv_experience(cv_data: dict) -> float:
    """Calculate total years of experience from cv_data['experience']."""
    total_months = 0
    experiences = cv_data.get("experience", [])
    if not isinstance(experiences, list):
        return 0.0
        
    for exp in experiences:
        if not isinstance(exp, dict):
            continue
        start_str = exp.get("start_date", "")
        end_str = exp.get("end_date", "")
        if not start_str:
            continue
            
        start_dt = parse_date(start_str)
        if not start_dt:
            continue
            
        if not end_str or "present" in end_str.lower() or "current" in end_str.lower():
            end_dt = datetime.now()
        else:
            end_dt = parse_date(end_str) or datetime.now()
            
        diff = (end_dt.year - start_dt.year) * 12 + (end_dt.month - start_dt.month)
        if diff > 0:
            total_months += diff
            
    return round(total_months / 12, 1)


DEFAULT_WEIGHTS = {
    "skills": 0.40,
    "role": 0.30,
    "experience": 0.15,
    "location": 0.15
}


def score_job(job: dict, cv_data: dict, linkedin_prefs: dict, weights: dict = None) -> int:
    """
    Score a single job posting against CV data and LinkedIn preferences.
    Returns an integer score from 0 to 100.
    """
    if weights is None:
        weights = linkedin_prefs.get("relevance_weights") or DEFAULT_WEIGHTS
        
    # Normalize weights to sum to 1.0
    total_w = sum(weights.values())
    if total_w <= 0:
        weights = DEFAULT_WEIGHTS
        total_w = sum(weights.values())
    normalized_weights = {k: v / total_w for k, v in weights.items()}
    
    # ── 1. Skills Match Score ──────────────────
    candidate_skills = set()
    
    cv_skills = cv_data.get("skills", [])
    if isinstance(cv_skills, list):
        candidate_skills.update([s.lower().strip() for s in cv_skills if s])
    elif isinstance(cv_skills, str):
        candidate_skills.update([s.lower().strip() for s in cv_skills.split(",") if s])
        
    # Extract extra skill signals from CV headline
    headline = cv_data.get("personal", {}).get("headline", "")
    if headline:
        for w in re.split(r"[|,\-/]", headline):
            clean_w = w.strip().lower()
            if len(clean_w) > 2:
                candidate_skills.add(clean_w)
                
    job_desc = job.get("description", "").lower()
    job_title = job.get("title", "").lower()
    
    if not candidate_skills:
        skills_score = 100.0  # Fallback if no skills are defined
    else:
        matches = 0
        for skill in candidate_skills:
            # Word boundary search for the skill in description or title
            pattern = rf"\b{re.escape(skill)}\b"
            if re.search(pattern, job_desc) or re.search(pattern, job_title):
                matches += 1
            else:
                # Substring check for composite skills (e.g. "React" inside "ReactJS" or vice versa)
                if skill in job_desc or skill in job_title:
                    matches += 0.5
        skills_score = (matches / len(candidate_skills)) * 100.0
        skills_score = min(100.0, skills_score)
        
    # ── 2. Role Match Score ────────────────────
    candidate_roles = []
    candidate_roles.extend(linkedin_prefs.get("roles", []))
    if headline:
        candidate_roles.extend([r.strip() for r in headline.split("|")])
    for exp in cv_data.get("experience", []):
        if isinstance(exp, dict) and exp.get("role"):
            candidate_roles.append(exp["role"])
            
    candidate_roles = [r.lower().strip() for r in candidate_roles if r]
    
    if not candidate_roles:
        role_score = 50.0
    else:
        best_role_match = 0.0
        for cr in candidate_roles:
            if cr == job_title:
                best_role_match = max(best_role_match, 100.0)
            elif cr in job_title or job_title in cr:
                best_role_match = max(best_role_match, 85.0)
            else:
                cr_tokens = set(re.findall(r'[a-zA-Z\+#]+', cr))
                jt_tokens = set(re.findall(r'[a-zA-Z\+#]+', job_title))
                if cr_tokens and jt_tokens:
                    overlap = cr_tokens.intersection(jt_tokens)
                    if overlap:
                        ratio = len(overlap) / max(len(cr_tokens), len(jt_tokens))
                        best_role_match = max(best_role_match, ratio * 100.0)
        role_score = best_role_match
        
    # ── 3. Location Match Score ────────────────
    preferred_locations = [loc.lower().strip() for loc in linkedin_prefs.get("locations", []) if loc]
    job_location = job.get("location", "").lower().strip()
    
    if not preferred_locations:
        location_score = 100.0
    else:
        location_score = 0.0
        for pref in preferred_locations:
            pref_alt = None
            if pref == "bangalore":
                pref_alt = "bengaluru"
            elif pref == "bengaluru":
                pref_alt = "bangalore"
            elif pref == "delhi":
                pref_alt = "ncr"
            elif pref == "ncr":
                pref_alt = "delhi"
                
            if pref in job_location or (pref_alt and pref_alt in job_location):
                location_score = 100.0
                break
                
        if location_score < 100.0:
            if "remote" in job_location or "work from home" in job_location or "wfh" in job_location:
                location_score = 80.0
                
    # ── 4. Experience Match Score ──────────────
    candidate_exp = linkedin_prefs.get("experience")
    if candidate_exp is None:
        candidate_exp = calculate_cv_experience(cv_data)
        
    # Attempt to parse experience requirements from job description text
    min_exp = 0
    max_exp = 99
    
    # Match patterns like: "3-5 years", "3 to 5 yrs", "2 - 4 years"
    range_match = re.search(r"\b(\d+)\s*(?:to|-)\s*(\d+)\s*(?:years?|yrs?)\b", job_desc)
    # Match patterns like: "5+ years", "5+ yrs", "at least 3 years"
    min_match = re.search(r"\b(\d+)\+?\s*(?:years?|yrs?)\b", job_desc)
    
    if range_match:
        min_exp = int(range_match.group(1))
        max_exp = int(range_match.group(2))
    elif min_match:
        min_exp = int(min_match.group(1))
        max_exp = min_exp + 4  # Assume range buffer
        
    if min_exp == 0 and max_exp == 99:
        # No experience requirement identified
        exp_score = 100.0
    elif min_exp <= candidate_exp <= max_exp:
        exp_score = 100.0
    elif candidate_exp < min_exp:
        diff = min_exp - candidate_exp
        exp_score = max(0.0, 100.0 - (diff * 20.0))
    else:
        diff = candidate_exp - max_exp
        exp_score = max(0.0, 100.0 - (diff * 10.0))
        
    # ── Calculate Composite Weighted Score ─────
    final_score = (
        skills_score * normalized_weights.get("skills", 0.40) +
        role_score * normalized_weights.get("role", 0.30) +
        location_score * normalized_weights.get("location", 0.15) +
        exp_score * normalized_weights.get("experience", 0.15)
    )
    
    return int(round(final_score))


def score_jobs(jobs: list[dict], cv_data: dict, linkedin_prefs: dict, weights: dict = None) -> list[dict]:
    """
    Score a list of jobs against the CV and preferences.
    Injects 'relevance_percent' key into each job dict and returns the list.
    """
    if not cv_data:
        cv_data = {}
    if not linkedin_prefs:
        linkedin_prefs = {}
        
    scored = []
    for job in jobs:
        score = score_job(job, cv_data, linkedin_prefs, weights)
        job_copy = job.copy()
        job_copy["relevance_percent"] = score
        scored.append(job_copy)
        
    return scored
