# LinkedIn Job Application Agentic System
### A Cost-Effective, Mostly API-Key-Free Multi-Agent Architecture

---

## Table of Contents
1. [Project Overview](#project-overview)
2. [Tools Comparison (with Costs)](#tools-comparison)
   - Browser Automation
   - Agent Frameworks
   - Local LLM Runners
   - Scraping Libraries
   - LinkedIn Messaging
   - Memory & Storage
3. [Recommended Stack](#recommended-stack)
4. [System Architecture Framework](#system-architecture-framework)
5. [Agent Breakdown (3 Agents)](#agent-breakdown)
   - Agent 1: Job Scraper
   - Agent 2: Application Bot (with Self-Learning)
   - Agent 3: Recruiter Messenger
6. [Self-Learning Knowledge Base Design](#self-learning-knowledge-base)
7. [Token Optimization Strategy](#token-optimization)
8. [Project File Structure](#project-file-structure)
9. [Risks & Caveats](#risks-and-caveats)

---

## 1. Project Overview

You are building a **3-agent autonomous job application system** that:

- **Scrapes LinkedIn** for specific job postings matching your criteria
- **Applies to each job** — either directly on LinkedIn (Easy Apply) or navigates to the company website and applies there
- **Builds a self-learning memory** (Markdown files per company) so the system doesn't waste tokens re-discovering how to apply at the same company again
- **Messages the recruiter** or relevant person at that company on LinkedIn after applying

The system should run with **zero or near-zero API key costs**, using local LLMs via Ollama as the brain wherever possible, falling back to cheap/free cloud APIs only when truly necessary.

---

## 2. Tools Comparison

---

### 2A. Browser Automation (for Scraping + Applying)

These are the tools that will actually *control the browser* — clicking, typing, navigating LinkedIn and company sites.

| Tool | Cost | Language | Anti-Detection | Best For | Verdict |
|---|---|---|---|---|---|
| **Playwright** | Free / Open Source | Python, JS, Java | Moderate (needs stealth plugin) | Modern web apps, dynamic pages | ✅ **Top Pick** |
| **Selenium** | Free / Open Source | Python, JS, Java, C# | Low (easily flagged) | Legacy sites, broad compatibility | ⚠️ Older, more detectable |
| **Puppeteer** | Free / Open Source | JS/TS only | Low-Moderate | Chrome-only automation | ❌ JS-only, skip for Python stack |
| **Playwright + Stealth** (`playwright-stealth` or `undetected-playwright`) | Free | Python | High | Bypassing LinkedIn bot detection | ✅ Add this on top of Playwright |
| **undetected-chromedriver** | Free | Python | High | Selenium with anti-bot | ⚠️ Use if Playwright still gets blocked |
| **Apify** | $0–$49+/month | Any (cloud) | Very High | Managed cloud scraping at scale | ❌ Overkill, has costs |
| **Hyperbrowser** | $0–$100+/month | Any (cloud) | Very High | AI agent browsers in cloud | ❌ Has costs, not needed locally |

**Recommendation:** Use **Playwright (Python)** with the `playwright-stealth` plugin. It is free, supports Python natively, handles dynamic JavaScript pages, and has auto-wait built in so LinkedIn's lazy-loaded job cards are handled without fragile sleep timers.

---

### 2B. Agent Frameworks

These orchestrate your 3 agents — how they communicate, pass data, and handle state.

| Framework | Cost | Model-Agnostic | Learning Curve | Best For | Verdict |
|---|---|---|---|---|---|
| **CrewAI** | Free (MIT) | ✅ Yes (any LLM) | ⭐ Low | Role-based agent teams, fast setup | ✅ **Top Pick** |
| **LangGraph** | Free core / LangSmith paid | ✅ Yes | ⭐⭐⭐ High | Complex stateful workflows | ⚠️ Overkill unless you need fine control |
| **AutoGen / AG2** | Free (MIT) | ✅ Yes | ⭐⭐ Medium | Conversational multi-agent debate | ⚠️ High token overhead per call |
| **Raw Python (DIY)** | Free | ✅ Yes | ⭐⭐ Medium | Full control, zero overhead | ✅ Viable for this project's simplicity |

**Why CrewAI wins here:**
- You literally define `Agent(role="Job Scraper", goal="Find Python developer jobs on LinkedIn", backstory="...")` and assign tasks. It reads exactly like your 3-agent description.
- It is fully model-agnostic and works with Ollama locally — no API key needed.
- It has built-in task memory and output passing between agents.
- It costs nothing. The open-source core is MIT licensed.

**LangGraph** would be worth adopting later if you need fault-tolerant state machines (e.g., "resume from where the agent left off after a crash"), but for a first version, CrewAI is the fastest path to a working system.

---

### 2C. Local LLM Runners (The Brain — Zero API Cost)

This is how you eliminate API key costs entirely.

| Tool | Cost | Models Supported | Hardware Req. | API Compatible | Verdict |
|---|---|---|---|---|---|
| **Ollama** | Free / Open Source | Llama, Qwen, Mistral, Gemma, Phi, DeepSeek, etc. | 8GB+ RAM | ✅ OpenAI-compatible API at localhost:11434 | ✅ **Top Pick** |
| **LM Studio** | Free | Same as Ollama | 8GB+ RAM | ✅ Yes | ✅ Good GUI alternative |
| **llama.cpp** | Free | GGUF models | Lower RAM via quantization | ✅ Yes | ⚠️ More complex setup |
| **vLLM** | Free | Larger models | GPU recommended | ✅ Yes | ⚠️ Production server, overkill for 1 machine |
| **Groq API** | Free tier (generous) | Llama 3, Mixtral | Cloud | ✅ Yes | ✅ Best free cloud fallback if local is slow |
| **OpenRouter** | Free tier | 100+ models | Cloud | ✅ Yes | ✅ Second cloud fallback option |

**Recommended Local Models via Ollama:**

| Model | Size | RAM Needed | Best For |
|---|---|---|---|
| `qwen2.5:7b` | ~4.5GB | 8GB | General agent reasoning, tool use |
| `mistral:7b` | ~4.1GB | 8GB | Instruction following, form filling |
| `qwen2.5:14b` | ~8.5GB | 16GB | Better reasoning for complex decisions |
| `llama3.2:3b` | ~2GB | 6GB | Fast routing, lightweight tasks |
| `phi4:14b` | ~9GB | 16GB | Excellent at following instructions precisely |

**The Key Advantage of Ollama:** It exposes an OpenAI-compatible API at `http://localhost:11434`. This means CrewAI, LangChain, and ScrapeGraphAI can all point to your local Ollama instance instead of OpenAI — no API key, no cost, no data leaving your machine.

---

### 2D. Scraping / Data Extraction Libraries

These help extract structured job data from LinkedIn pages.

| Tool | Cost | Approach | LinkedIn-friendly | Verdict |
|---|---|---|---|---|
| **ScrapeGraphAI** | Free (MIT) + LLM costs | LLM-driven, prompt-based | ✅ Works on rendered pages | ✅ Use with local Ollama = free |
| **BeautifulSoup4** | Free | HTML parsing, CSS selectors | ✅ With Playwright fetching HTML | ✅ Lightweight for parsing |
| **Playwright (native)** | Free | Full browser DOM access | ✅ Best for dynamic content | ✅ Already in your stack |
| **Apify Actors** | $0–$49+/mo | Cloud scraping pipelines | ✅ Pre-built LinkedIn scrapers | ❌ Has cost, use only if blocked |
| **linkedin-api (unofficial)** | Free | LinkedIn's internal API | ✅ But violates ToS | ⚠️ Use carefully, risk of ban |

**Recommendation:** Use **Playwright** to load and render LinkedIn pages, then feed the HTML to **ScrapeGraphAI + local Ollama** to extract job details via a natural language prompt. This avoids brittle CSS selectors that break every time LinkedIn redesigns their UI.

---

### 2E. LinkedIn Messaging (Agent 3)

| Approach | Cost | Risk | Notes |
|---|---|---|---|
| **Playwright automation** (clicking LinkedIn UI) | Free | Medium | Mimics human, works for InMail + connection requests |
| **linkedin-api (unofficial Python lib)** | Free | High (ToS violation) | Direct API calls, faster but detectable |
| **PhantomBuster** (cloud tool) | $0–$69+/mo | Low | Purpose-built for LinkedIn outreach automation |
| **Dux-Soup / Expandi** | $15–$99/mo | Low | LinkedIn automation SaaS tools |

**Recommendation:** Use **Playwright automation** to click through LinkedIn's messaging UI. It is slower but looks like human behavior. Add random delays between messages (2–5 seconds per action). Keep daily message limits low (10–20/day) to avoid LinkedIn flags.

---

### 2F. Memory & Knowledge Storage (The Self-Learning Part)

| Tool | Cost | Use Case | Verdict |
|---|---|---|---|
| **Markdown files (local)** | Free | Company application guides (`microsoft.md`) | ✅ **Top Pick** for human-readable memory |
| **SQLite** | Free | Structured job application history | ✅ Track what was applied, status |
| **ChromaDB** | Free | Vector search over memory files | ✅ Use if you want semantic search over company guides |
| **JSON files** | Free | Simple key-value state | ✅ Good for application status tracking |

---

## 3. Recommended Stack (Final Choices)

```
Browser Automation:   Playwright (Python) + playwright-stealth
Agent Framework:      CrewAI (open source, free)
LLM Brain:            Ollama (local) → Qwen2.5:7b or Mistral:7b
                      Fallback: Groq free tier (Llama 3 70B)
Scraping/Parsing:     Playwright (render) + ScrapeGraphAI (extract) + BS4 (parse)
Messaging:            Playwright automation (clicks LinkedIn UI)
Memory:               Markdown files per company + SQLite for job history
Vector Search:        ChromaDB (optional, for semantic memory lookup)
Language:             Python 3.11+
```

**Total recurring cost: $0** (assuming you run Ollama locally)

---

## 4. System Architecture Framework

```
┌─────────────────────────────────────────────────────────┐
│                    ORCHESTRATOR                          │
│              (CrewAI Crew / Python main.py)              │
└────────────────────┬────────────────────────────────────┘
                     │
        ┌────────────┼────────────┐
        ▼            ▼            ▼
┌──────────────┐ ┌──────────────┐ ┌──────────────────────┐
│   AGENT 1    │ │   AGENT 2    │ │       AGENT 3        │
│ Job Scraper  │ │ Application  │ │ Recruiter Messenger  │
│              │ │    Bot       │ │                      │
└──────┬───────┘ └──────┬───────┘ └──────────┬───────────┘
       │                │                    │
       ▼                ▼                    ▼
┌──────────────┐ ┌──────────────┐ ┌──────────────────────┐
│  Playwright  │ │  Playwright  │ │      Playwright      │
│  + Stealth   │ │  + Stealth   │ │      + Stealth       │
│              │ │              │ │                      │
│  LinkedIn    │ │  LinkedIn    │ │  LinkedIn Messages   │
│  Job Search  │ │  Easy Apply  │ │  / Connection Req.   │
└──────────────┘ │  OR          │ └──────────────────────┘
                 │  Company     │
                 │  Website     │
                 └──────┬───────┘
                        │
                ┌───────▼────────┐
                │  Knowledge DB  │
                │                │
                │ /memory/       │
                │  microsoft.md  │
                │  google.md     │
                │  amazon.md     │
                │  ...           │
                │                │
                │ jobs.sqlite    │
                │  (history)     │
                └────────────────┘
                        │
                        ▼
                ┌───────────────┐
                │  Ollama       │
                │  (Local LLM)  │
                │  qwen2.5:7b   │
                │  localhost:   │
                │  11434        │
                └───────────────┘
```

**Data Flow:**
1. Agent 1 scrapes LinkedIn → returns list of `Job` objects (title, company, URL, job_id, apply_url, type)
2. Each job is passed to Agent 2 → checks SQLite (already applied?) → checks `/memory/company.md` (know how to apply?) → applies
3. After successful application → Agent 2 extracts recruiter name/profile from job post → passes to Agent 3
4. Agent 3 sends a connection request + message to the recruiter on LinkedIn
5. All results logged to SQLite

---

## 5. Agent Breakdown

---

### Agent 1: Job Scraper

**Role:** Find and return structured job listings from LinkedIn matching criteria.

**Tools:**
- Playwright (login, search, scroll, render)
- ScrapeGraphAI + Ollama (extract structured data from HTML)
- BeautifulSoup4 (fallback HTML parsing)

**What it does:**
1. Opens LinkedIn → navigates to Jobs section
2. Searches with your query (e.g., "Python Developer", "Delhi", "Remote")
3. Scrolls through results, loads all listings
4. For each job card: extracts title, company, location, posted date, job URL, apply type (Easy Apply vs external), recruiter info if visible
5. Checks SQLite → skips jobs already applied to
6. Returns a clean list of `Job` objects to the orchestrator

**Output format:**
```python
Job(
  id="job_123456",
  title="Senior Python Developer",
  company="Microsoft",
  location="Remote",
  apply_url="https://...",
  apply_type="external",  # or "easy_apply"
  recruiter_name="Sarah Khan",
  recruiter_profile_url="https://linkedin.com/in/...",
  posted_date="2026-05-14"
)
```

**Token usage:** Very low — the LLM is only used to parse HTML into structured JSON. The prompt is small: `"Extract job title, company name, apply URL, and recruiter name from this HTML"`. Each extraction costs ~500–800 tokens with a local 7B model.

---

### Agent 2: Application Bot (with Self-Learning)

**Role:** Apply to each job, learning how to navigate each company's application site and storing that knowledge.

**Tools:**
- Playwright (navigate, click, fill forms)
- Ollama / LLM (decide what to click, fill in answers)
- Markdown memory files (`/memory/company_name.md`)
- SQLite (log application status)

**Decision Tree:**

```
Receive Job
    │
    ├─ apply_type == "easy_apply"
    │       │
    │       └─ Fill LinkedIn Easy Apply form
    │          (standard fields: name, email, resume, screening questions)
    │
    └─ apply_type == "external"
            │
            ├─ Check /memory/microsoft.md  ← Does it exist?
            │       │
            │       ├─ YES → Load the guide, follow it step by step
            │       │         (low token usage, just execute known steps)
            │       │
            │       └─ NO → Enter "discovery mode":
            │                 Navigate to careers page
            │                 LLM observes DOM and decides what to click
            │                 Fills out application form
            │                 RECORDS every step taken
            │                 Saves new /memory/microsoft.md
            │
            └─ Log result to SQLite
```

**This is the key innovation — the self-learning loop:**

When Agent 2 successfully applies to a company it hasn't seen before, it writes a Markdown file:

```markdown
# Microsoft Application Guide
Last updated: 2026-05-15
Success rate: 3/3

## How to reach the application form
1. Go to careers.microsoft.com
2. Search for the job title in the search bar (top right)
3. Click the matching result
4. Click the blue "Apply" button (id: #apply-btn or text: "Apply Now")

## Form fields and how to fill them
- Full Name: [auto-fill from profile]
- Email: [auto-fill from profile]
- Resume: Upload PDF from /resume/resume.pdf
- "Why Microsoft?" field: LLM generates 2-paragraph response
- Citizenship status: Select "Yes, authorized to work"

## Known obstacles
- Step 3 sometimes shows a login wall → click "Continue as guest" or sign in
- File upload uses a hidden input, use Playwright's set_input_files()

## Screening questions seen
- "Years of Python experience?" → answer: 3
- "Are you willing to relocate?" → answer: No
```

Next time any job at Microsoft comes up, Agent 2 reads this file and executes the steps without an LLM reasoning call. **This is how you drop token usage dramatically over time.**

---

### Agent 3: Recruiter Messenger

**Role:** Find the recruiter or hiring manager for the job and send them a personalized connection request + message.

**Tools:**
- Playwright (navigate LinkedIn profiles, click connect, type message)
- Ollama (generate personalized message)
- SQLite (check if already messaged this person)

**Message Strategy:**

The LLM generates a short, personalized note based on:
- Job title
- Company name
- Recruiter's name
- 1-2 sentences from the job description

**Example prompt to local LLM:**
```
Write a 3-sentence LinkedIn connection message from a candidate applying for the 
"Senior Python Developer" role at Microsoft. The recruiter's name is Sarah. 
Be professional, brief, and genuine. Do not be sycophantic.
```

**Daily limits enforced in code:**
- Max 15 connection requests per day
- Max 10 messages per day
- Random 3–8 second delay between each action
- Random 5–15 minute break between job applications

---

## 6. Self-Learning Knowledge Base Design

```
/memory/
  ├── _index.json              ← maps company_name → file path + stats
  ├── microsoft.md
  ├── google.md
  ├── amazon.md
  ├── flipkart.md
  └── ...

/history/
  └── jobs.sqlite
       Tables:
         - jobs (id, title, company, url, apply_type, scraped_at)
         - applications (job_id, status, applied_at, notes)
         - messages (recruiter_url, sent_at, message_text)
```

**`_index.json` structure:**
```json
{
  "microsoft": {
    "file": "memory/microsoft.md",
    "success_count": 3,
    "last_used": "2026-05-15",
    "avg_steps": 7
  }
}
```

**When to update a memory file:**
- After each successful application, Agent 2 appends any new observations (new form fields, new obstacles encountered)
- If an application fails using the existing guide, Agent 2 enters re-discovery mode and overwrites the guide

---

## 7. Token Optimization Strategy

The entire goal of the self-learning memory is to minimize LLM calls. Here is the priority order:

```
1. ZERO tokens   → Already applied (skip entirely, SQLite check)
2. ~200 tokens   → Known company (read .md guide, execute mechanically)
3. ~1500 tokens  → Unknown external site (LLM navigates, then writes .md)
4. ~800 tokens   → Easy Apply form (LLM fills screening questions)
5. ~300 tokens   → Recruiter message (LLM generates personalized note)
```

**Other token-saving tactics:**
- Pass only relevant HTML snippets to the LLM, not full page source
- Use a small model (Qwen2.5:7b or Mistral:7b) for routine tasks
- Reserve a bigger model (Qwen2.5:14b or Groq Llama3 70B free tier) only for "discovery mode" on new company sites
- Cache LLM responses for identical screening questions (SQLite cache table)

---

## 8. Project File Structure

```
linkedin-agent/
│
├── main.py                    ← Orchestrator entry point
│
├── agents/
│   ├── scraper_agent.py       ← Agent 1: Job scraper
│   ├── application_agent.py   ← Agent 2: Application bot
│   └── messenger_agent.py     ← Agent 3: Recruiter messenger
│
├── tools/
│   ├── browser.py             ← Playwright wrapper (login, navigate, click)
│   ├── linkedin_scraper.py    ← LinkedIn-specific DOM interactions
│   ├── form_filler.py         ← Generic form filling logic
│   └── llm_client.py          ← Ollama client wrapper
│
├── memory/
│   ├── _index.json
│   ├── microsoft.md
│   └── google.md
│
├── history/
│   └── jobs.sqlite
│
├── resume/
│   └── resume.pdf
│
├── profile/
│   └── profile.json           ← Name, email, phone, links, preferences
│
├── config/
│   └── settings.yaml          ← Job search query, location, daily limits
│
└── requirements.txt
```

---

## 9. Risks & Caveats

**LinkedIn ToS:** LinkedIn explicitly prohibits automated scraping and bot activity in its Terms of Service. Running this system on your personal account carries a risk of account suspension. Mitigations:
- Use randomized delays between all actions
- Respect daily limits (never apply to more than 20–30 jobs/day)
- Use a dedicated LinkedIn account for testing before switching to your main account
- Rotate user-agent strings and browser fingerprints via playwright-stealth

**CAPTCHA / Bot Detection:** LinkedIn has active bot detection. Playwright with the stealth plugin reduces this risk significantly but does not eliminate it. If consistently flagged:
- Add `undetected-playwright` or `nodriver` to your stack
- Consider using a residential proxy (Webshare has a free tier for small usage)

**Easy Apply Changes:** LinkedIn's Easy Apply form structure changes periodically. If the scraper breaks, ScrapeGraphAI + Ollama can re-navigate it without code changes since it reasons about the DOM rather than using hardcoded selectors.

**Local LLM Quality:** Qwen2.5:7b is strong but may struggle with complex multi-step reasoning on new company application sites. In those cases, fall back to the Groq free tier (Llama 3 70B) for "discovery mode" only — it is free and significantly more capable.

**Legal note:** Web scraping legality varies by jurisdiction. This system is for personal job searching, not commercial data collection. Always comply with applicable laws and platform terms.

---

*Built with: CrewAI + Playwright + Ollama + ScrapeGraphAI + SQLite*
*Target cost: $0/month running entirely locally*
