"""Resume Writer agent - rewrites bullets to align with JD."""

import logging
from typing import Dict, List

from src.agents.state import AgentState, AnalyzedRequirements, JobMetadata
from src.services.llm_service import LLMService

logger = logging.getLogger(__name__)


def write_resume_node(state: AgentState) -> Dict:
    """Resume Writer node - transforms base pointers into job-specific bullets.

    This is a LangGraph node that:
    1. Takes base experience pointers from markdown file
    2. Uses LLM to transform them into tailored, job-specific bullet points
    3. Returns transformed bullet points organized by role

    Args:
        state: Current agent state

    Returns:
        Dict with updated state keys
    """
    logger.info("Starting resume writing")

    try:
        # Parse requirements and metadata
        requirements = AnalyzedRequirements(**state["analyzed_requirements"])
        job_metadata = JobMetadata(**state["job_metadata"])
        base_resume_pointers = state.get("base_resume_pointers", "")
        
        # Get validation feedback if this is a retry
        validation_feedback = ""
        if state.get("validation_result"):
            validation_result = state["validation_result"]
            validation_feedback = validation_result.get("feedback_for_rewrite", "")
            if validation_feedback:
                logger.info(f"Using validation feedback for rewrite: {validation_feedback[:200]}...")

        llm_service = LLMService()
        
        # Transform base pointers into job-specific bullets
        try:
            rewritten_bullets = llm_service.rewrite_resume(
                base_resume_pointers=base_resume_pointers,
                requirements=requirements,
                validation_feedback=validation_feedback
            )
        except Exception as rewrite_error:
            logger.error(f"Error calling rewrite_resume: {rewrite_error}")
            logger.error(f"Error type: {type(rewrite_error)}")
            logger.error(f"Error args: {rewrite_error.args if hasattr(rewrite_error, 'args') else 'No args'}")
            raise
        
        # Process resume sections (role bullets + skills)
        resume_sections = rewritten_bullets
        
        # Count total bullets across all roles (excluding skills)
        total_bullets = sum(len(bullets) for role, bullets in resume_sections.items() if role != "skills" and isinstance(bullets, list))
        
        # Log role breakdown
        role_counts = []
        for role, content in resume_sections.items():
            if role == "skills":
                logger.info(f"Skills extracted: {content[:100]}...")
            elif isinstance(content, list):
                role_counts.append(f"{role}: {len(content)}")
        
        logger.info(f"Resume writing complete: {total_bullets} bullets generated across roles")
        if role_counts:
            logger.info(f"Role breakdown: {', '.join(role_counts)}")
        
        return {
            "resume_sections": resume_sections,
            "status": "written"
        }

    except Exception as error:
        logger.error(f"Error in resume writing: {error}")
        return {
            "error_message": f"Resume writing failed: {str(error)}",
            "status": "failed"
        }
