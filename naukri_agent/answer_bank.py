import os
import sys
import re
from datetime import datetime, timezone

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from core import database as db
from naukri_agent.search import resolve_search_filters

# Predefined commonly asked questions and answers for Naukri.com AI screening
COMMON_QUESTIONS_BANK = {
    # Personal Details
    "Tell me about yourself.": (
        "I am a Software Engineer with around 1.5 years of professional experience specializing in AI systems, "
        "backend engineering, and cloud-native applications. I have worked on production RAG systems, distributed "
        "inference engines, scalable Flask and FastAPI microservices, and AWS deployments. I enjoy solving complex "
        "backend problems and building AI-powered applications that can scale in production."
    ),
    "What is your current role?": "Software Developer at Mkix Ventures Pvt. Ltd.",
    "Total years of experience?": "Approximately 1.5 years of full-time software engineering experience.",
    "Current location?": "Delhi NCR, India.",
    "Are you willing to relocate?": "Yes",
    "Are you available for Work From Office?": "Yes",
    "Notice period?": "Immediate / Serving notice (whichever is applicable when applying).",
    "Gender?": "Male",
    "Salary expectation?": "₹10–12 LPA",
    "Why are you looking for a change?": (
        "I am looking for opportunities where I can work on large-scale engineering challenges, "
        "distributed systems, AI infrastructure, and products that impact millions of users while continuing to grow technically."
    ),
    
    # Resume Questions
    "Explain your current work.": (
        "I build cloud-native AI systems on AWS involving distributed data collection pipelines, "
        "machine learning inference engines, LLM integrations, and automation platforms. My work focuses on "
        "scalability, performance, and production reliability."
    ),
    "What technologies do you use daily?": "Python, FastAPI, Flask, AWS, Docker, Redis, Playwright, LangChain, LLM APIs, SQL and Git.",
    "What cloud platform do you use?": "AWS",
    "Which AWS services have you worked on?": "EC2, Lambda, S3, RDS.",
    "Have you deployed applications to production?": "Yes. I have deployed multiple production AI systems and backend services on AWS.",
    "Have you worked on REST APIs?": "Yes. I have designed, developed, and maintained scalable REST APIs using Flask and FastAPI.",
    "Have you worked with microservices?": "Yes. I have developed modular backend services using Flask and FastAPI with asynchronous processing.",
    "Have you worked on scalable systems?": "Yes. My projects were designed for horizontal scalability and low latency.",
    "What databases have you worked with?": "SQL databases and vector databases including FAISS and Chroma.",
    "Have you worked in Agile?": "Yes",
    
    # AI / Machine Learning
    "What is RAG?": (
        "Retrieval-Augmented Generation combines an LLM with an external knowledge base "
        "by retrieving relevant documents before generating a response, improving factual accuracy."
    ),
    "What LLMs have you worked with?": "ChatGPT, Claude, DeepSeek and LLaMA.",
    "Have you fine-tuned models?": "Yes. I have worked with fine-tuned LLMs and optimized inference pipelines.",
    "Which ML algorithms have you used?": "XGBoost, LightGBM and LSTM.",
    "Difference between XGBoost and LightGBM?": (
        "XGBoost grows trees level-wise, while LightGBM grows leaf-wise, "
        "making it faster and more efficient on large datasets."
    ),
    "Explain vector databases.": "Vector databases store embeddings to enable semantic search using similarity instead of keyword matching.",
    "Have you used embeddings?": "Yes",
    "Explain semantic search.": "Semantic search retrieves results based on meaning using vector similarity rather than exact keyword matching.",
    "What is prompt engineering?": "Designing prompts that guide LLMs to generate more accurate and reliable outputs.",
    "Have you worked with LangChain?": "Yes. I have built production RAG pipelines using LangChain.",
    
    # Backend Questions
    "What backend frameworks have you used?": "FastAPI, Flask and Django.",
    "Which do you prefer—Flask or FastAPI?": (
        "FastAPI for high-performance APIs and asynchronous workloads, "
        "while Flask is ideal for lightweight applications."
    ),
    "Explain asynchronous programming.": (
        "It allows applications to execute multiple I/O-bound operations "
        "concurrently without blocking threads."
    ),
    "What is Redis used for?": "Caching, session storage, and task queue management.",
    "What is Celery?": "A distributed task queue used to execute asynchronous background jobs.",
    "What is API latency?": "The time taken for an API request to receive a response.",
    "How do you improve backend performance?": (
        "Database indexing, caching, asynchronous processing, efficient algorithms, "
        "load balancing, and query optimization."
    ),
    "Explain REST APIs.": "REST APIs expose resources over HTTP using methods like GET, POST, PUT, DELETE and PATCH.",
    "What is Docker?": "Docker packages applications with their dependencies into portable containers.",
    "Have you worked with Git?": "Yes",
    
    # Project Questions
    "Tell me about your AI prediction system.": (
        "I developed a cloud-native prediction system that combines distributed scraping, "
        "machine learning models, and LLMs to generate accurate predictions in real time while running on AWS infrastructure."
    ),
    "Explain your multi-agent automation platform.": (
        "It automates job applications by scraping ATS portals, filling forms, generating "
        "tailored responses, and learning page structures to reduce repeated LLM usage."
    ),
    "Explain HealBot.": (
        "HealBot is a distributed LLM inference system using FastAPI, LLaMA, RAG, "
        "and quantized models to deliver low-latency conversational AI."
    ),
    "Explain Hirrd.": (
        "Hirrd is a SaaS job automation platform with secure credential management, "
        "asynchronous processing, payment integration, and AI-powered automation."
    ),
    "Biggest technical challenge?": "Designing scalable AI systems that balance latency, cost, and inference accuracy while serving concurrent users.",
    
    # Behavioural Questions
    "Tell me about a difficult bug you solved.": (
        "I optimized a high-latency AI inference pipeline by introducing asynchronous processing, "
        "batching, and caching, significantly reducing response time."
    ),
    "How do you handle deadlines?": "I prioritize tasks based on impact, break work into milestones, and communicate proactively with stakeholders.",
    "Why should we hire you?": (
        "I combine strong software engineering fundamentals with practical experience in AI, "
        "backend development, cloud deployment, and scalable system design. I can contribute to both traditional backend engineering "
        "and modern AI-powered products."
    ),
    "What are your strengths?": "Problem solving, backend development, AI Engineering, distributed systems, quick learning, and ownership.",
    "What are your career goals?": (
        "I want to become a software engineer who builds large-scale AI platforms and distributed "
        "systems, eventually leading the design of intelligent, production-grade software used by millions of users."
    ),
    
    # Additional AI screening consistency keys
    "Current CTC": "Answer truthfully based on your current package.",
    "Expected CTC": "₹10–12 LPA",
    "Notice Period": "Immediate / As applicable",
    "Willing to relocate": "Yes",
    "Comfortable with hybrid/WFO": "Yes",
    "Highest Qualification": "B.Tech in Computer Science and Engineering",
    "Graduation Year": "2025",
    "Certifications": "AWS Certified Solutions Architect – Associate, AWS Certified Cloud Practitioner",
    "Preferred Role": "Software Engineer / Backend Engineer / AI Engineer",
    "Preferred Location": "Delhi NCR, Bengaluru, Hyderabad, Pune, Chennai",
}

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

def generate_openai_answer(question: str, cv_data: dict, preferences: dict, options: list[str] = None) -> str:
    """
    Call OpenAI API to generate a professional candidate answer based on Master CV and preferences.
    If options list is provided, OpenAI is instructed to choose the best option from the list.
    """
    openai_key = os.environ.get("OPENAI_API_KEY", "")
    if not openai_key or openai_key == "your_openai_api_key":
        print("[Answer Bank] WARNING: OpenAI API key is missing. Using heuristic fallback.")
        if options and len(options) > 0:
            return options[0]
        return f"Fallback Answer for: {question}"

    try:
        from openai import OpenAI
        client = OpenAI(api_key=openai_key)
        
        # Build comprehensive profile summary using all details from Master CV
        profile_summary = {
            "personal": cv_data.get("personal", {}),
            "experience": cv_data.get("experience", []),
            "education": cv_data.get("education", []),
            "skills": cv_data.get("skills", []),
            "projects": cv_data.get("projects", []),
            "certifications": cv_data.get("certifications", []),
            "preferences": preferences
        }
            
        if options and len(options) > 0:
            options_list = "\n".join([f"- {opt}" for opt in options])
            prompt = f"""You are a professional assistant answering screening questions for a job application on behalf of a candidate.

CANDIDATE INFORMATION:
{profile_summary}

QUESTION:
"{question}"

AVAILABLE OPTIONS:
{options_list}

Select the single best option from the list of AVAILABLE OPTIONS that matches the candidate's profile.
- You MUST output ONLY the exact text of the selected option, word-for-word.
- Do not include any explanation, introductory text, quotes, or additional formatting.
"""
        else:
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
        if options and len(options) > 0:
            return options[0]
        return f"Error generation fallback for: {question}"

def get_or_propose_answer(user_id: int, question: str, options: list[str] = None) -> tuple[str, str]:
    """
    Get the answer for a screening question.
    - If a matched question is approved in the database, return (answer, 'approved').
    - If a matched question is pending review, return (answer, 'pending_review').
    - If not found in database or static bank, call OpenAI to generate a proposal.
    """
    # 1. Load stored database answer bank
    stored_entries = db.get_naukri_answer_bank(user_id)
    
    # 2. Append static COMMON_QUESTIONS_BANK entries as fallback options
    static_entries = [
        {"question": q, "answer": a, "status": "approved"}
        for q, a in COMMON_QUESTIONS_BANK.items()
    ]
    
    # Check stored entries first, then static common questions bank
    all_entries = stored_entries + static_entries
    
    matched_entry = match_stored_question(question, all_entries)
    if matched_entry:
        ans = matched_entry.get("answer", "")
        status = matched_entry.get("status", "pending_review")
        # If options are provided, check if the matched answer fits one of the options
        if options and len(options) > 0:
            for opt in options:
                if clean_text(opt) == clean_text(ans) or ans.lower() in opt.lower() or opt.lower() in ans.lower():
                    print(f"[Answer Bank] Matched question and option: '{matched_entry['question']}' -> '{opt}'")
                    return opt, status
            # If no option matched, proceed to OpenAI to choose from options
            print(f"[Answer Bank] Stored answer '{ans}' does not match any of the available options: {options}. Consulting OpenAI...")
        else:
            print(f"[Answer Bank] Matched question: '{matched_entry['question']}' -> Answer: {ans} (Status: {status})")
            return ans, status
            
    print(f"[Answer Bank] Question not found or options mismatch for: '{question}'. Generating proposal via OpenAI...")
    
    # Load CV and preferences
    cv_data = db.get_master_cv(user_id) or {}
    preferences = resolve_search_filters(user_id)
    
    # Generate proposal using full CV context and options
    proposal = generate_openai_answer(question, cv_data, preferences, options)
    
    # Save as pending review so user can inspect it
    db.save_naukri_answer_bank_entry(user_id, question, proposal, status='pending_review')
    print(f"[Answer Bank] Saved proposed answer as 'pending_review'.")
    
    return proposal, 'pending_review'
