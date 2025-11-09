"""Job Description Analyzer agent."""

import logging
from typing import Dict

from src.agents.state import AgentState, AnalyzedRequirements, JobMetadata
from src.services.llm_service import LLMService

logger = logging.getLogger(__name__)


def analyze_jd_node(state: AgentState) -> Dict:
    """Analyze job description and extract requirements.

    This is a LangGraph node that:
    1. Takes job description from state
    2. Calls LLM to extract structured requirements
    3. Updates state with analyzed requirements

    Args:
        state: Current agent state

    Returns:
        Dict with updated state keys
    """
    logger.info("Starting JD analysis")

    try:
        llm_service = LLMService()

        # Get provided metadata
        job_metadata_dict = state.get("job_metadata", {})
        
        # Single combined call to analyze job and extract metadata
        job_metadata, requirements = llm_service.analyze_job_complete(
            job_description=state["job_description"],
            provided_metadata=job_metadata_dict
        )

        logger.info(
            f"JD analysis complete: {len(requirements.required_skills)} required skills, "
            f"{len(requirements.keywords_for_ats)} ATS keywords"
        )

        return {
            "job_metadata": job_metadata.model_dump(),
            "analyzed_requirements": requirements.model_dump(),
            "status": "analyzed"
        }

    except Exception as error:
        logger.error(f"Error in JD analysis: {error}")
        return {
            "error_message": f"JD analysis failed: {str(error)}",
            "status": "failed"
        }
