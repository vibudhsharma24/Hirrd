import os
import sys
import re
from datetime import datetime, timezone

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from core import database as db
from naukri_agent.search import resolve_search_filters

def clean_text(text: str) -> str:
    """Normalize text by lowercasing, removing special characters, and collapsing whitespace."""
    if not text:
        return ""
    text = text.lower().strip()
    text = re.sub(r'[^\w\s]', '', text)
    return " ".join(text.split())

def match_stored_question(new_question: str, stored_entries: list[dict]) -> dict | None:
    """
    Match a new screening question against stored entries using exact or high token overlap.
    Returns the matched entry dict, or None if no match is found.
    """
    cleaned_new = clean_text(new_question)
    if not cleaned_new:
        return None
        
    new_words = set(cleaned_new.split())
    
    # 1. Look for an exact cleaned match first
    for entry in stored_entries:
        cleaned_stored = clean_text(entry.get("question", ""))
        if cleaned_new == cleaned_stored:
            return entry
            
    # 2. Look for high token overlap (Jaccard similarity >= 0.70)
    best_match = None
    best_ratio = 0.0
    for entry in stored_entries:
        cleaned_stored = clean_text(entry.get("question", ""))
        stored_words = set(cleaned_stored.split())
        if not new_words or not stored_words:
            continue
            
        intersection = new_words.intersection(stored_words)
        union = new_words.union(stored_words)
        ratio = len(intersection) / len(union)
        
        if ratio >= 0.70 and ratio > best_ratio:
            best_ratio = ratio
            best_match = entry
            
    return best_match

def generate_openai_answer(question: str, cv_data: dict, preferences: dict) -> str:
    """
    Call OpenAI API to generate a professional candidate answer based on Master CV and preferences.
    """
    openai_key = os.environ.get("OPENAI_API_KEY", "")
    if not openai_key or openai_key == "your_openai_api_key":
        print("[Answer Bank] WARNING: OpenAI API key is missing. Using heuristic fallback.")
        return f"Fallback Answer for: {question}"

    try:
        from openai import OpenAI
        client = OpenAI(api_key=openai_key)
        
        # Build concise profile summary to keep tokens low
        profile_summary = {
            "personal": cv_data.get("personal", {}),
            "education": cv_data.get("education", []),
            "skills": cv_data.get("skills", []),
            "preferences": preferences
        }
        
        # Pull recent experience summaries
        experience = cv_data.get("experience", [])
        if experience:
            profile_summary["experience"] = [
                {
                    "company": exp.get("company"),
                    "role": exp.get("role"),
                    "responsibilities": exp.get("responsibilities", [])[:2]
                }
                for exp in experience[:2]
            ]
            
        prompt = f"""You are a professional assistant answering screening questions for a job application on behalf of a candidate.

CANDIDATE INFORMATION:
{profile_summary}

QUESTION:
"{question}"

Please answer the question accurately, professionally, and concisely as the candidate themselves would (first-person). 
- If they ask for years of experience, current salary/CTC, expected salary, notice period, or skills, use the candidate's details.
- Provide ONLY the direct, final response. Do not include introductory text, explanations, or quotes.
"""
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=100,
            temperature=0.0
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        print(f"[Answer Bank] OpenAI API error: {e}")
        return f"Error generation fallback for: {question}"

def get_or_propose_answer(user_id: int, question: str) -> tuple[str, str]:
    """
    Get the answer for a screening question.
    - If a matched question is approved in the database, return (answer, 'approved').
    - If a matched question is pending review, return (answer, 'pending_review').
    - If not found, call OpenAI to generate a proposal, save it as 'pending_review', and return (proposal, 'pending_review').
    """
    # Load stored answer bank
    stored_entries = db.get_naukri_answer_bank(user_id)
    
    matched_entry = match_stored_question(question, stored_entries)
    if matched_entry:
        ans = matched_entry.get("answer", "")
        status = matched_entry.get("status", "pending_review")
        print(f"[Answer Bank] Matched question in database: '{matched_entry['question']}' -> Status: {status}")
        return ans, status
        
    print(f"[Answer Bank] Question not found in answer bank: '{question}'. Generating proposal via OpenAI...")
    
    # Load CV and preferences
    cv_data = db.get_master_cv(user_id) or {}
    preferences = resolve_search_filters(user_id)
    
    # Generate proposal
    proposal = generate_openai_answer(question, cv_data, preferences)
    
    # Save as pending review
    db.save_naukri_answer_bank_entry(user_id, question, proposal, status='pending_review')
    print(f"[Answer Bank] Saved proposed answer as 'pending_review'.")
    
    return proposal, 'pending_review'
