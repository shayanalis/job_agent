"""Prompts package for centralized prompt management."""

from .prompt_templates import (
    # Classes
    PromptTemplate,
    
    # JD Analyzer Prompts
    JD_ANALYZER_SYSTEM_PROMPT,
    JD_ANALYZER_USER_PROMPT,
    
    
    # Resume Rewriter Prompts
    RESUME_REWRITER_SYSTEM_PROMPT,
    RESUME_REWRITER_USER_PROMPT,
    
    # Validator Prompts
    COMPLETE_RESUME_VALIDATOR_SYSTEM_PROMPT,
    COMPLETE_RESUME_VALIDATOR_USER_PROMPT,
    
    # Metadata Extractor Prompts
    METADATA_EXTRACTOR_SYSTEM_PROMPT,
    METADATA_EXTRACTOR_USER_PROMPT,
    
    
    # Helper functions
    format_complete_resume_validator_prompt,
)

__all__ = [
    'PromptTemplate',
    'JD_ANALYZER_SYSTEM_PROMPT',
    'JD_ANALYZER_USER_PROMPT',
    'RESUME_REWRITER_SYSTEM_PROMPT',
    'RESUME_REWRITER_USER_PROMPT',
    'COMPLETE_RESUME_VALIDATOR_SYSTEM_PROMPT',
    'COMPLETE_RESUME_VALIDATOR_USER_PROMPT',
    'METADATA_EXTRACTOR_SYSTEM_PROMPT',
    'METADATA_EXTRACTOR_USER_PROMPT',
    'format_complete_resume_validator_prompt',
]