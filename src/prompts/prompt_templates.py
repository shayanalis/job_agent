"""Centralized prompt templates for all LLM agents.

This module contains all prompts used by different agents in the Job Assistant system.
Prompts are organized by agent type and include both system and user prompts.
"""

from dataclasses import dataclass
from typing import Any, Dict, List, Optional


@dataclass
class PromptTemplate:
    """Base class for prompt templates with parameter validation."""

    template: str
    required_params: List[str]
    optional_params: Optional[List[str]] = None

    def __post_init__(self) -> None:
        if self.optional_params is None:
            self.optional_params = []

    def format(self, **kwargs: Any) -> str:
        """Format the template with provided parameters."""
        missing = set(self.required_params) - set(kwargs.keys())
        if missing:
            raise ValueError(f"Missing required parameters: {missing}")

        for param in self.optional_params:
            if param not in kwargs:
                kwargs[param] = ""

        try:
            return self.template.format(**kwargs)
        except Exception as exc:  # pragma: no cover - logging path
            import logging

            logger = logging.getLogger(__name__)
            logger.error("Error formatting template: %s", exc)
            logger.error("Template preview: %s...", self.template[:200])
            logger.error("Provided kwargs: %s", list(kwargs.keys()))
            raise


# Initial Screening Prompts
SCREENING_SYSTEM_PROMPT = PromptTemplate(
    template="""You are the gatekeeper agent in a job application automation workflow.

Your responsibilities:
- Detect blockers that mean we should NOT proceed (e.g., no visa sponsorship, citizenship-only roles, relocation constraints, unpaid roles).
- Summarize the job description text clearly for downstream agents.
- Identify any applicant questionnaire questions that require free-form answers.

Guidelines:
- Only set block_application=true when the posting explicitly states a hard blocker.
- If sponsorship is not mentioned, treat it as safe to proceed (sponsorship_status="Not Specified") and keep block_application=false.
- If the job requires on-site US work (non-remote) but otherwise has no blockers, do not block; simply note the location expectations.
- Treat any requirement for an active security clearance (e.g., "Active Security Clearance - Secret") as a hard blocker and set block_application=true.
- Use notes to highlight uncertainties without stopping the workflow unless the blocker is explicit."""
    ,
    required_params=[]
)

SCREENING_USER_PROMPT = PromptTemplate(
    template="""Analyze the following job posting content.

KNOWN JOB DATA:
- Title: {job_title}
- Company: {company}
- Source URL: {job_url}

RAW JOB CONTENT:
{job_content}

Extract:
1. Whether we should block the application before proceeding.
   - Consider explicit "no sponsorship", "US citizens only", security clearance (e.g., "Active Security Clearance - Secret"), relocation impossible, unpaid internships, or other hard blockers.
2. Sponsorship status (Yes, No, Not Specified) based on the posting.
3. Reasons for blocking, if any (each reason as a short sentence).
4. Cleaned job description text suitable for downstream analysis (remove navigation, unrelated fluff).
5. A list of application questions that the employer asks the candidate to answer (exact question text).
6. Optional notes for the human operator.

Return strict JSON:
{{
  "block_application": true,
  "block_reasons": ["reason1", "reason2"],
  "sponsorship_status": "Yes/No/Not Specified",
  "clean_job_description": "cleaned description text",
  "application_questions": ["question one", "question two"],
  "notes": "optional additional context or empty string"
}}

If sponsorship is not mentioned, set block_application=false and sponsorship_status="Not Specified" and capture any uncertainties in notes.
If the posting requires on-site US work (non-remote) but otherwise has no blockers, keep block_application=false and document the location expectations in notes.
If any field is unknown, provide a sensible default (e.g., empty list, empty string, or "Not Specified").""",
    required_params=["job_title", "company", "job_url", "job_content"]
)

# Job Description Analyzer Prompts
JD_ANALYZER_SYSTEM_PROMPT = PromptTemplate(
    template="""You are an expert job description analyzer. Extract key requirements, skills,
        and keywords from job descriptions to help match candidates effectively.

        Focus on:
        - Distinguishing required vs preferred skills
        - Identifying ATS keywords
        - Extracting quantifiable requirements (years of experience, education)
        - Noting domain-specific knowledge needs

        Be comprehensive but precise.""",
    required_params=[]
)

JD_ANALYZER_USER_PROMPT = PromptTemplate(
    template="""Analyze this job description and extract all relevant information:

Job Title: {job_title}
Company: {company}

Job Description:
{job_description}

Return a JSON object with the following structure:
{{
    "required_skills": ["skill1", "skill2"],
    "preferred_skills": ["skill1", "skill2"],
    "soft_skills": ["skill1", "skill2"],
    "key_responsibilities": ["responsibility1", "responsibility2"],
    "must_have_experience": ["experience1", "experience2"],
    "nice_to_have": ["item1", "item2"],
    "domain_knowledge": ["domain1", "domain2"],
    "years_experience_required": 5,
    "education_requirements": "Bachelor's degree or equivalent",
    "certifications": ["cert1", "cert2"],
    "keywords_for_ats": ["keyword1", "keyword2"]
}}""",
    required_params=["job_title", "company", "job_description"]
)

# Job Metadata Extractor Prompts
METADATA_EXTRACTOR_SYSTEM_PROMPT = PromptTemplate(
    template="""Extract structured metadata from job descriptions.
        Be precise and only include information explicitly stated.""",
    required_params=[]
)

METADATA_EXTRACTOR_USER_PROMPT = PromptTemplate(
    template="""Extract metadata from this job description:

{job_description}

Already provided:
- Title: {provided_title}
- Company: {provided_company}
- URL: {provided_url}

Return JSON:
{{
    "title": "extracted or use provided",
    "company": "extracted or use provided",
    "role_level": "one of: Entry, Mid, Senior, Staff, Principal, Lead, Manager, Director, VP, C-Level, Not Specified",
    "sponsorship": "Yes/No/Not Specified - Look for phrases like 'must be authorized to work', 'no sponsorship', 'unable to sponsor', 'H1B', 'visa sponsorship'",
    "posted_date_raw": "e.g., 'Posted 3 days ago' or empty string '' if not found",
    "job_type": "Full-time/Part-time/Contract/Internship or null",
    "job_url": "{provided_url}"
}}""",
    required_params=[
        "job_description", "provided_title", 
        "provided_company", "provided_url"
    ]
)

# Complete Resume Validator Prompts with Enhanced Scoring
COMPLETE_RESUME_VALIDATOR_SYSTEM_PROMPT = PromptTemplate(
    template="""You are the final validator in a multi-agent resume optimization system.

Your role: Validate the complete resume document using requirements from the JD Analyzer.

SCORING APPROACH (for internal use - include in feedback):
- Relevance to JD (35%): exact keywords, mirrors responsibilities, seniority fit
- Impact & Metrics (20%): quantified outcomes (%, #, time, cost), action verbs
- Clarity & Structure (15%): 1-2 line bullets, scannable, logical sections
- ATS Compliance (15%): single column, no tables/images, standard headings
- Skills Section (10%): grouped, prioritized, no duplicates
- Contact/Links (5%): email required, phone optional, LinkedIn, GitHub/portfolio

Critical failure conditions that MUST result in is_valid=false:
- Repetitive or duplicate bullet points (same content repeated)
- Keyword coverage below 60%
- Major grammar/spelling errors
- Missing critical sections (email contact, experience, education)

Provide DETAILED feedback for rewrites:
- Specific bullets that need metrics
- Missing keywords that should be incorporated
- Suggestions for using TAR format (action + tech + result with metric)

Only be strict with repetitive content if it is too repetitive or there are exact duplicates.""",
    required_params=[]
)

COMPLETE_RESUME_VALIDATOR_USER_PROMPT = PromptTemplate(
    template="""Validate this transformed resume:

TRANSFORMED RESUME CONTENT:
{resume_content}

{job_context_section}

Think step-by-step:
1. Scan for repetitive/duplicate bullet points (critical check)
2. Check ATS compatibility (formatting, structure)
3. Count keyword matches from provided requirements
4. Evaluate content quality and professionalism
5. Calculate keyword coverage score
6. Determine if any critical failure conditions exist
7. Calculate approximate total score (for your own assessment)

Return only valid JSON in the following format:
{{
    "is_valid": true,
    "keyword_coverage_score": 85,
    "issues_found": ["issue1", "issue2"],
    "suggestions": ["suggestion1", "suggestion2"],
    "feedback_for_rewrite": "Detailed, specific feedback for improvements including which bullets need metrics, which keywords are missing, and how to improve using TAR format"
}}

IMPORTANT for feedback_for_rewrite:
- Be specific about which bullets lack metrics (e.g., "LEAFICIENT bullet 2 needs user scale metric")
- List exact missing keywords that should be incorporated
- Suggest TAR format improvements (e.g., "Change 'Responsible for X' to 'Built X using Y; achieved Z metric'")
- Include approximate scoring breakdown in feedback to guide improvements

Example output:
{{
    "is_valid": false,
    "keyword_coverage_score": 45,
    "issues_found": ["Repetitive bullet points in experience section", "Low keyword coverage", "Missing email address", "Bullets lack quantifiable metrics"],
    "suggestions": ["Add keywords: Docker, Kubernetes, CI/CD", "Use past tense for previous roles", "Add metrics to all bullets"],
    "feedback_for_rewrite": "Score breakdown: Relevance 15/35, Impact 5/20, Clarity 10/15, ATS 12/15, Skills 5/10, Contact 0/5. Total ~47/100. SPECIFIC IMPROVEMENTS: 1) LEAFICIENT bullets need metrics - add user count, latency improvements, cost savings. 2) Missing critical keywords: Kubernetes, Docker, CI/CD, REST APIs. 3) Rewrite duty-based bullets using TAR format: Instead of 'Responsible for backend services', use 'Built scalable REST APIs using Django and PostgreSQL; reduced response time by 40% serving 10K daily users'. 4) Add email to contact section immediately."
}}

Validation criteria for is_valid determination:
CRITICAL FAILURES (any of these = is_valid false):
- Repetitive or duplicate bullet points across resume
- keyword_coverage_score < 60%
- Major grammar/spelling errors
- Missing email address (phone is optional)

Additional quality checks:
- ATS compatibility (no headers/footers, tables, graphics)
- Standard sections present (contact, experience, education)
- Consistent verb tenses throughout
- Quantifiable achievements included

Scoring: keyword_coverage_score = (matched_keywords / total_required_keywords) * 100

{job_specific_criteria}

Do not include any text outside the JSON structure.""",
    required_params=[
        "resume_content", "job_context_section", "job_specific_criteria"
    ]
)


# Resume Rewriter Prompts with TAR/STAR Format
RESUME_REWRITER_SYSTEM_PROMPT = PromptTemplate(
    template="""You are an expert resume writer specializing in TAR/STAR-mini format for ATS optimization.

TAR/STAR-mini FORMAT RULES:
- Task/Action with specific tech, then Result with metric
- Format: Action verb + what you built/improved + tech/tools + outcome with metric
- Keep each bullet 1-2 lines (≈16-28 words)
- Avoid duties ("responsible for...")
- First mention full form then acronym (e.g., "Key Performance Indicators (KPIs)")
- Quantify with %, #, time, cost, latency, users
- Use a safe guestimate for unknown metrics, these will be reviewed later

BULLET EXAMPLES:
- "Built real-time anomaly detection system using PyTorch and AWS SageMaker; reduced false positives by 67% while processing 2M daily events"
- "Optimized PostgreSQL queries and implemented Redis caching layer; decreased API response time from 800ms to 120ms (85% improvement)"
- "Led migration from monolith to microservices architecture using Docker and Kubernetes; improved deployment frequency by 4x and reduced downtime by 90%"

ROLE CONTEXTS:
- LEAFICIENT (Machine Learning Engineer, Apr 2024-Present): Early-stage agricultural tech startup. Small team environment, hands-on technical work, rapid prototyping, direct impact on product. Focus on technical achievements, metrics, and direct contributions.
- DHS (Data Scientist Intern, Jun-Aug 2023): Government organization focused on public service. Emphasize data analysis for policy impact, statistical rigor, civic responsibility, and measurable public benefit.
- EDUCATIVE_PM (Technical Product Manager, Oct 2020-Dec 2022): EdTech platform with established teams. Focus on product strategy, user research, feature launches, metrics-driven decisions, and cross-functional collaboration.
- EDUCATIVE_SWE (Software Engineer, Jun 2018-Sep 2020): Full-stack development role. Focus on technical implementation, code quality, system design, and engineering best practices.

Guidelines for each role:
1. Match the company culture and role level
2. Use appropriate terminology for the organization type
3. Highlight achievements relevant to that specific position
4. Incorporate job requirements while staying true to each role's context
5. Quantify impact where possible
6. Each bullet should be 1-2 lines long

CRITICAL GUIDANCE:
1. As you write bullets, identify and naturally mention specific technologies, tools, and skills
2. Use exact technology names (e.g., "PyTorch" not "ML framework", "Kubernetes" not "containers")
3. After writing bullets, create a SKILLS section with 10-15 of the most relevant skills
4. Mirror JD language naturally (use exact keywords where applicable)

SKILLS SECTION REQUIREMENTS:
- Extract ONLY skills the candidate actually has based on their base pointers
- Prioritize skills that match job requirements BUT only if candidate has them
- Order by importance: most relevant/recent skills first
- Include: programming languages, frameworks, tools, platforms, methodologies
- Format: Simple comma-separated list (e.g., "Python, PyTorch, AWS, Docker, ...")
- Make it ATS-friendly: use standard technology names and common abbreviations

Format: Return a JSON object:
{{
  "skills": "Python, PyTorch, Machine Learning, Computer Vision, AWS, Docker, ...",
  "LEAFICIENT": ["bullet1", "bullet2", ...],
  "DHS": ["bullet1", "bullet2", "bullet3"],
  "EDUCATIVE_PM": ["bullet1", "bullet2", ...],
  "EDUCATIVE_SWE": ["bullet1", "bullet2", ...]
}}""",
    required_params=[]
)

RESUME_REWRITER_USER_PROMPT = PromptTemplate(
    template="""Transform these base experience pointers into tailored resume bullets for the target job.

TARGET JOB REQUIREMENTS (pre-analyzed):
{analyzed_requirements}

BASE EXPERIENCE POINTERS TO TRANSFORM:
{base_resume_pointers}

{validation_feedback_section}

Transform each pointer into polished TAR format bullets that directly address the job requirements. Focus on:
1. Incorporating exact keywords from requirements
2. Highlighting relevant technologies and skills
3. Adding quantifiable metrics where appropriate
4. Emphasizing experiences that match what this role needs

Remember: These are raw pointers, not final content. Rewrite them completely to match this specific job.""",
    required_params=[
        "analyzed_requirements", "base_resume_pointers", "validation_feedback_section"
    ]
)

def format_complete_resume_validator_prompt(
    resume_content: str,
    job_description: Optional[str] = None,
    job_metadata: Optional[Dict[str, Any]] = None,
    requirements: Optional[Dict[str, Any]] = None
) -> str:
    """Helper function to format complete resume validator prompt with optional job context."""
    
    job_context_parts = []
    job_specific_criteria = ""
    
    if job_description or requirements:
        job_context_parts.append("\nJOB CONTEXT:")
        
    if job_description:
        job_context_parts.append(f"\nJob Description:\n{job_description[:1500]}...")
        
    if job_metadata:
        job_context_parts.append(f"\nTarget Position: {job_metadata.get('title', '')} at {job_metadata.get('company', '')}")
        job_context_parts.append(f"Role Level: {job_metadata.get('role_level', '')}")
        
    if requirements:
        job_context_parts.append(f"\nKey Requirements:")
        job_context_parts.append(f"- Required Skills: {', '.join(requirements.get('required_skills', [])[:10])}")
        job_context_parts.append(f"- Keywords: {', '.join(requirements.get('keywords_for_ats', [])[:10])}")
    
    if job_description or requirements:
        job_specific_criteria = "- If job provided: keyword coverage >= 60% for is_valid = true\n- If no job: general quality check for is_valid = true"
    else:
        job_specific_criteria = "- General quality check for is_valid = true"
    
    job_context_section = "".join(job_context_parts)
    
    return COMPLETE_RESUME_VALIDATOR_USER_PROMPT.format(
        resume_content=resume_content,
        job_context_section=job_context_section,
        job_specific_criteria=job_specific_criteria
    )