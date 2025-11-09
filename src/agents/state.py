"""State definitions for LangGraph agents."""

from typing import TypedDict, List, Optional, Literal
from datetime import datetime
from pydantic import BaseModel, Field


class JobMetadata(BaseModel):
    """Structured metadata about the job posting."""

    title: str = Field(description="Job title")
    company: str = Field(description="Company name")
    role_level: Literal[
        "Entry", "Mid", "Senior", "Staff", "Principal",
        "Lead", "Manager", "Director", "VP", "C-Level", "Not Specified"
    ] = Field(default="Not Specified", description="Role seniority level")
    sponsorship: str = Field(default="Not Specified", description="Sponsorship availability")
    posted_date: Optional[datetime] = Field(default=None, description="When the job was posted")
    posted_date_raw: str = Field(default="", description="Raw posted date text from JD")
    job_type: Optional[Literal["Full-time", "Part-time", "Contract", "Internship"]] = Field(
        default=None, description="Employment type"
    )
    job_url: str = Field(default="", description="Original job posting URL")


class AnalyzedRequirements(BaseModel):
    """Structured output from JD Analyzer agent."""

    required_skills: List[str] = Field(
        default_factory=list,
        description="Must-have technical skills"
    )
    preferred_skills: List[str] = Field(
        default_factory=list,
        description="Nice-to-have technical skills"
    )
    soft_skills: List[str] = Field(
        default_factory=list,
        description="Soft skills and competencies"
    )
    key_responsibilities: List[str] = Field(
        default_factory=list,
        description="Main job duties"
    )
    must_have_experience: List[str] = Field(
        default_factory=list,
        description="Non-negotiable experience requirements"
    )
    nice_to_have: List[str] = Field(
        default_factory=list,
        description="Bonus qualifications"
    )
    domain_knowledge: List[str] = Field(
        default_factory=list,
        description="Industry/domain expertise needed"
    )
    years_experience_required: Optional[int] = Field(
        default=None,
        description="Years of experience required"
    )
    education_requirements: Optional[str] = Field(
        default=None,
        description="Educational requirements"
    )
    certifications: List[str] = Field(
        default_factory=list,
        description="Required or preferred certifications"
    )
    keywords_for_ats: List[str] = Field(
        default_factory=list,
        description="Critical ATS keywords to include"
    )


class ValidationResult(BaseModel):
    """Result from Quality Validator agent."""

    is_valid: bool = Field(description="Whether the resume passes validation")
    keyword_coverage_score: float = Field(
        description="Percentage of JD keywords covered (0-100)"
    )
    issues_found: List[str] = Field(
        default_factory=list,
        description="List of issues identified"
    )
    suggestions: List[str] = Field(
        default_factory=list,
        description="Improvement suggestions"
    )
    feedback_for_rewrite: str = Field(
        default="",
        description="Specific feedback for Resume Writer if retry needed"
    )


class AgentState(TypedDict):
    """Main state object shared across all LangGraph nodes."""

    # Input from API
    job_description: str
    job_metadata: dict  # Will be converted to JobMetadata

    # Loaded resume data
    base_resume_pointers: Optional[str]  # Raw experience pointers from markdown file to be transformed

    # Agent outputs
    analyzed_requirements: Optional[dict]  # AnalyzedRequirements as dict
    resume_sections: Optional[dict]  # Dict containing role bullets + skills
    validation_result: Optional[dict]  # ValidationResult as dict

    # Document generation
    generated_doc_path: str
    resume_url: str  # Final Google Drive link

    # Workflow control
    retry_count: int
    error_message: str
    status: str  # "processing", "completed", "failed"
