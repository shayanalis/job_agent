"""Job Description Analyzer agent."""

import logging
from typing import Dict, Optional

from src.agents.state import AgentState, AnalyzedRequirements, JobMetadata
from src.services.llm_service import LLMService
from src.services.status_service import status_service

logger = logging.getLogger(__name__)


def _record_status(
    state: AgentState,
    *,
    status: str,
    step: str,
    message: str = "",
    metadata: Optional[Dict] = None,
) -> None:
    status_id = state.get("status_id")

    if not status_id:
        return

    status_service.update_status(
        status_id=status_id,
        status=status,
        step=step,
        message=message,
        metadata=metadata or {},
    )


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

    _record_status(
        state,
        status="processing",
        step="analyzing_jd",
        message="Analyzing job description",
    )

    try:
        llm_service = LLMService()

        # Get provided metadata
        job_metadata_dict = state.get("job_metadata", {})
        
        job_description = (
            state.get("screened_job_description")
            or state.get("job_description")
            or ""
        )

        # Single combined call to analyze job and extract metadata
        job_metadata, requirements = llm_service.analyze_job_complete(
            job_description=job_description,
            provided_metadata=job_metadata_dict
        )

        logger.info(
            f"JD analysis complete: {len(requirements.required_skills)} required skills, "
            f"{len(requirements.keywords_for_ats)} ATS keywords"
        )

        _record_status(
            state,
            status="processing",
            step="jd_analyzed",
            message="Job description analyzed",
            metadata={
                "required_skills": len(requirements.required_skills),
                "ats_keywords": len(requirements.keywords_for_ats),
            },
        )

        return {
            "job_metadata": job_metadata.model_dump(),
            "analyzed_requirements": requirements.model_dump(),
            "status": "analyzed"
        }

    except Exception as error:
        logger.error(f"Error in JD analysis: {error}")
        _record_status(
            state,
            status="failed",
            step="jd_analysis_failed",
            message=str(error),
        )
        return {
            "error_message": f"JD analysis failed: {str(error)}",
            "status": "failed"
        }
