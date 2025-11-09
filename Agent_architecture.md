## **🎯 Resume Agent System - Architecture**

---

## **Problem Statement**

You need to generate tailored resumes quickly for multiple job applications. The process should:
- Extract job descriptions from any website
- Match your experience with job requirements
- Rewrite your resume bullets to align with each specific JD
- Maintain professional formatting consistent with your existing resume
- Be fast (< 30 seconds per resume)
- Work completely locally except for LLM API calls

---

## **Solution Overview**

A local LangGraph agent system that:
1. Receives job descriptions from a Chrome extension
2. Dynamically loads your base experience pointers from Google Drive
3. Uses multiple specialized sub-agents to analyze, match, and optimize content
4. Generates formatted resumes using your existing Word template
5. Returns a shareable Google Drive link

---

## **Architecture**

### **Component Stack**

```
Browser Layer:
├─ Chrome Extension (UI)
└─ Captures JD + triggers workflow

Local Server Layer:
├─ Flask API (HTTP endpoint)
├─ LangGraph Orchestrator (main agent)
└─ Sub-agents:
    ├─ JD Analyzer Agent
    ├─ Resume Writer Agent (uses a bank of resume pointers to align with JD)
    └─ Quality Validator Agent

Data Layer:
├─ Google Drive (resume pointers - .md files)
├─ Local Template (resume.docx with placeholders)
└─ Google Drive (output PDFs)

External APIs:
├─ OpenAI GPT-4 (primary LLM)
├─ Claude (optional fallback/validation)
└─ Google Drive API
```

---

## **Detailed Flow**

### **1. Content Loading (Dynamic)**

**Every request starts by fetching fresh data:**
- Google Drive API lists files in `/Resume Pointers/` folder
- Loads all `.md` files:
  - `job1_experience.md`
  - `job2_experience.md`
  - `projects.md`
  - `skills.md`
- Parses bullet points from markdown
- Caches in memory for this request only

**Why this approach:**
You can update your resume pointers in Google Drive using Docs/mobile app and changes are immediately available without redeploying the agent.

---

### **2. LangGraph Agent System**

**Main Orchestrator (StateGraph):**
Manages the workflow state and routes between sub-agents.

class JobMetadata(TypedDict):
    """Structured metadata about the job posting"""
    title: str
    company: str
    role_level: Literal["Entry", "Mid", "Senior", "Staff", "Principal", "Lead", "Manager", "Director", "VP", "C-Level", "Not Specified"]
    sponsorship: Literal["Yes", "No", "Not Specified"] | str  # Allows custom text too
    posted_date: Optional[datetime]  # None if not specified
    posted_date_raw: str  # Raw text from JD (e.g., "Posted 3 days ago")
    location: Optional[str]
    job_type: Optional[Literal["Full-time", "Part-time", "Contract", "Internship"]]
    remote_policy: Optional[Literal["Remote", "Hybrid", "On-site", "Not Specified"]]
    salary_range: Optional[str]  # e.g., "$120k - $180k" or None
    job_url: str

class AnalyzedRequirements(TypedDict):
    """Structured output from JD Analyzer agent"""
    required_skills: List[str]  # ["Python", "AWS", "Docker"]
    preferred_skills: List[str]  # ["GraphQL", "Terraform"]
    soft_skills: List[str]  # ["Leadership", "Communication"]
    key_responsibilities: List[str]  # Main duties
    must_have_experience: List[str]  # Non-negotiable experience
    nice_to_have: List[str]  # Bonus qualifications
    domain_knowledge: List[str]  # ["Healthcare", "Fintech"]
    years_experience_required: Optional[int]
    education_requirements: Optional[str]
    certifications: List[str]  # ["AWS Solutions Architect"]
    keywords_for_ats: List[str]  # Critical keywords to include


**Sub-Agent 1: JD Analyzer**
- **Input:** Raw job description text
- **Task:** Extract key requirements, skills, keywords, seniority level
- **LLM Call:** GPT-4 with structured output
- **Output:** 
  - Required skills (Python, AWS, etc.)
  - Soft skills (leadership, communication)
  - Key responsibilities
  - Seniority indicators
  - Domain knowledge needed

**Sub-Agent 2: Resume Writer**
- **Input:** Base resume pointers + Analyzed job requirements
- **Task:** Transform base experience pointers into job-specific bullets
- **Guidelines:**
  - Use keywords from JD naturally
  - Maintain quantifiable metrics
  - Action verb + metric + outcome format
  - Match tone and seniority level
- **LLM Call:** GPT-4 for each bullet (parallel processing)
- **Output:** Polished, JD-aligned bullets

**Sub-Agent 3: Quality Validator**
- **Input:** Generated bullets + original JD
- **Task:** Validate quality and alignment
- **Checks:**
  - Keyword coverage (are JD keywords present?)
  - Truthfulness (did we over-promise?)
  - ATS compatibility (formatting, keywords)
  - Consistency (tone, style)
  - Grammar and spelling
- **Output:** Pass/fail + suggested fixes
- **Action:** If fails, loop back to Writer with feedback

**Agent Decision Flow:**
```
Load Pointers → JD Analyzer → Content Matcher → Resume Writer
                                                      ↓
                                          Quality Validator
                                                ↓ Pass  ↓ Fail
                                           Format       ← Loop back
```

---

### **3. Document Generation**

**Template System (python-docx):**

Your `resume_template.docx` contains placeholders: this will also be in google docs.
```
{{CANDIDATE_NAME}}
{{CONTACT_INFO}}

PROFESSIONAL SUMMARY
{{SUMMARY}}

EXPERIENCE

{{COMPANY_1_NAME}} | {{JOB_1_TITLE}} | {{JOB_1_DATES}}
{{EXPERIENCE_BULLETS_1}}

{{COMPANY_2_NAME}} | {{JOB_2_TITLE}} | {{JOB_2_DATES}}
{{EXPERIENCE_BULLETS_2}}

SKILLS
{{TECHNICAL_SKILLS}}

EDUCATION
{{EDUCATION}}
```

**Processing:**
1. Load template using `python-docx`
2. Iterate through all paragraphs and tables
3. Replace placeholders with generated content:
   - `{{EXPERIENCE_BULLETS_1}}` → Insert new paragraphs maintaining formatting
   - Each bullet inherits template's bullet style
4. Save as new `.docx` file
5. Convert to PDF using `docx2pdf` (uses Word's rendering engine)
6. Upload PDF to Google Drive
7. Delete local `.docx` and `.pdf` (cleanup)

**Why this matters:**
Your formatting (fonts, spacing, colors, layout) is preserved exactly. No need to fight with PDF libraries.

---

### **4. API Integration**

**OpenAI GPT-4 Primary:**
- Model: `gpt-4-turbo` or `gpt-4o`
- Used for: All agent reasoning tasks
- Why: Faster, cheaper, good at structured outputs
- Structured output mode for validation

**Claude (Optional):**
- Model: `claude-sonnet-4`
- Used for: Cross-validation on important bullets
- Why: Different perspective, catches GPT blind spots
- Only runs if enabled in config

**Google Drive API:**
- **Read operations:**
  - List files in specific folder
  - Download markdown files
- **Write operations:**
  - Upload final PDF
  - Set sharing permissions
  - Get shareable link

---

### **5. Request Flow (End-to-End)**

**User Action:**
1. Highlight JD on LinkedIn
2. Click Chrome extension button

**Extension:**
3. Extract JD text, title, company
4. POST to `localhost:8000/generate-resume`

**Flask Server:**
5. Receive request
6. Initialize LangGraph orchestrator
7. Start agent workflow

**LangGraph Workflow:**
8. Load base resume pointers from Google Drive (fresh)
9. JD Analyzer agent runs (GPT-4 call ~3 sec)
10. Content Matcher agent runs (GPT-4 call ~2 sec)
11. Resume Writer agent transforms pointers to tailored bullets (GPT-4 call ~5 sec, parallel bullets)
12. Quality Validator agent runs (GPT-4 call ~2 sec)
13. If validation fails → loop to step 11 with feedback (max 2 retries)

**Document Generation:**
14. Load `resume_template.docx`
15. Replace placeholders with validated content
16. Save as `.docx`
17. Convert to PDF using `docx2pdf` (~2 sec)
18. Upload to Google Drive (~3 sec)
19. Get shareable link

**Return to Extension:**
20. JSON response with Drive link
21. Display success message with clickable link

**Total Time:** ~15-25 seconds depending on retries

---

## **Key Design Decisions**

### **Why LangGraph?**
- **State management:** Tracks progress through multi-step workflow
- **Agent composition:** Each sub-agent is modular and testable
- **Retry logic:** Built-in handling for validation failures
- **Observability:** Can log each agent's decisions
- **Flexibility:** Easy to add new agents (e.g., skills optimizer)

### **Why Google Drive for Pointers?**
- **No redeployment:** Update content from phone/any device
- **Versioning:** Google Drive auto-saves versions
- **Accessibility:** Edit from anywhere
- **Backup:** Cloud-stored by default
- **Collaboration:** Share with resume coach if needed

### **Why Word Template + python-docx?**
- **Preserves formatting:** Fonts, spacing, colors exact
- **Professional output:** Uses Word's rendering
- **Easy updates:** Change template without code changes
- **ATS friendly:** Word → PDF conversion is standard
- **No PDF wrestling:** Let Word handle layout

### **Why Local LangGraph + Remote LLMs?**
- **Privacy:** Your resume pointers never leave your drive/machine
- **Cost control:** Only pay for LLM API calls
- **Customization:** Full control over agent logic
- **Speed:** No network latency for orchestration
- **Debugging:** Can inspect agent state locally

---

## **Configuration**

**Environment Variables:**
```
OPENAI_API_KEY=sk-...
GOOGLE_DRIVE_POINTERS_FOLDER_ID=folder_id
GOOGLE_DRIVE_OUTPUT_FOLDER_ID=folder_id
RESUME_TEMPLATE_PATH=./resume_template.docx
```

**Agent Settings:**
```python
{
  "validation_retries": 2,
  "llm_temperature": 0.0,
}
```


⏺ File Structure for Resume Agent System

  resume-agent-system/
  │
  ├── backend/
  │   ├── __init__.py
  │   ├── main.py                    # Flask API entry point
  │   ├── config.py                  # Environment variables & settings
  │   │
  │   ├── agents/
  │   │   ├── __init__.py
  │   │   ├── orchestrator.py        # Main LangGraph StateGraph
  │   │   ├── jd_analyzer.py         # JD Analyzer sub-agent
  │   │   ├── resume_writer.py       # Resume Writer sub-agent
  │   │   ├── quality_validator.py   # Quality Validator sub-agent
  │   │   └── state_definitions.py   # TypedDict definitions (JobMetadata, etc.)
  │   │
  │   ├── services/
  │   │   ├── __init__.py
  │   │   ├── google_drive.py        # Google Drive API operations
  │   │   ├── llm_client.py          # OpenAI/Claude API wrapper
  │   │   └── document_generator.py  # python-docx operations
  │   │
  │   ├── utils/
  │   │   ├── __init__.py
  │   │   ├── text_processing.py     # Bullet formatting, text cleanup
  │   │   └── logger.py              # Logging configuration
  │   │
  │   ├── templates/
  │   │   └── resume_template.docx   # Word template with placeholders
  │   │
  │   └── requirements.txt           # Python dependencies
  │
  ├── chrome-extension/
  │   ├── manifest.json              # Chrome extension manifest v3
  │   ├── background.js              # Service worker
  │   ├── content.js                 # Content script for JD extraction
  │   ├── popup.html                 # Extension popup UI
  │   ├── popup.js                   # Popup logic
  │   ├── popup.css                  # Popup styling
  │   └── icons/
  │       ├── icon16.png
  │       ├── icon48.png
  │       └── icon128.png
  │
  ├── tests/
  │   ├── __init__.py
  │   ├── test_agents.py             # Agent unit tests
  │   ├── test_document_gen.py       # Document generation tests
  │   ├── test_api.py                # API endpoint tests
  │   └── fixtures/
  │       ├── sample_jd.txt          # Sample job descriptions
  │       └── sample_pointers.md     # Sample resume pointers
  │
  ├── scripts/
  │   ├── setup_google_auth.py       # One-time Google OAuth setup
  │   └── test_full_flow.py          # End-to-end test script
  │
  ├── .env.example                   # Example environment variables
  ├── .gitignore
  ├── README.md                      # Setup & usage instructions
  └── docker-compose.yml             # Optional containerization

  Key Files Explained:

  backend/main.py:
  # Flask API with single endpoint
  @app.route('/generate-resume', methods=['POST'])
  def generate_resume():
      # Entry point for Chrome extension

  backend/agents/orchestrator.py:
  # Main LangGraph workflow
  class ResumeAgentGraph(StateGraph):
      # Coordinates all sub-agents

  backend/services/google_drive.py:
  # Handles all Google Drive operations
  def load_resume_pointers(folder_id: str) -> List[Dict]
  def upload_resume_pdf(file_path: str, filename: str) -> str

  chrome-extension/content.js:
  // Extracts JD from current page
  function extractJobDescription() {
      // LinkedIn, Indeed, etc. specific selectors