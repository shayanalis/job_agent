"""LangGraph workflow orchestration."""

import logging
from typing import Dict, Literal, Optional

import mlflow
from langgraph.graph import StateGraph, END

from src.agents.state import AgentState, AnalyzedRequirements

mlflow.langchain.autolog(log_traces=True)
from src.agents.jd_analyzer import analyze_jd_node
from src.agents.resume_writer import write_resume_node
from src.services.drive_service import DriveService
from src.services.document_service import DocumentService
from src.services.llm_service import LLMService
from src.services.screening_service import ScreeningService
from src.services.status_service import status_service
def initial_screening_node(state: AgentState) -> Dict:
    """Run lightweight screening before the main workflow.

    Args:
        state: Current agent state containing raw job content.

    Returns:
        Dict with screening information and control status.
    """
    logger.info("Starting initial screening for job posting")

    try:
        screening_service = ScreeningService()
        job_metadata = state.get("job_metadata", {})

        screening = screening_service.screen_job_posting(
            job_content=state["job_description"],
            provided_metadata=job_metadata if isinstance(job_metadata, dict) else {},
        )

        # Prepare updates for downstream nodes.
        cleaned_description = screening.clean_job_description.strip()
        cleaned_description = cleaned_description or state["job_description"]

        updated_metadata = dict(job_metadata) if isinstance(job_metadata, dict) else {}
        if screening.sponsorship_status:
            updated_metadata["sponsorship"] = screening.sponsorship_status

        updates: Dict = {
            "job_description": cleaned_description,
            "screened_job_description": cleaned_description,
            "screening_result": screening.model_dump(),
            "application_questions": screening.application_questions,
            "job_metadata": updated_metadata,
            "status": "screened",
        }

        if screening.block_application:
            reason = "; ".join(screening.block_reasons) or "Screening blocked due to identified issues."
            updates["status"] = "screening_blocked"
            updates["error_message"] = reason
            logger.warning("Screening blocked workflow: %s", reason)
            _record_status(
                state,
                status="screening_blocked",
                step="screening_blocked",
                message=reason,
                metadata={"reasons": screening.block_reasons},
            )
        else:
            logger.info("Screening passed; continuing workflow")
            _record_status(
                state,
                status="processing",
                step="screened",
                message="Screening completed",
            )

        if screening.notes:
            logger.info("Screening notes: %s", screening.notes)

        return updates

    except Exception as error:
        logger.error(f"Error during initial screening: {error}")
        _record_status(
            state,
            status="failed",
            step="screening_failed",
            message=str(error),
        )
        return {
            "error_message": f"Screening failed: {str(error)}",
            "status": "failed"
        }
def should_continue_after_screening(state: AgentState) -> Literal["continue", "end"]:
    """Determine if workflow should continue after screening."""
    status = state.get("status", "")

    if status in {"failed", "screening_blocked"}:
        logger.error("Screening stage blocked workflow (status=%s)", status)
        return "end"

    return "continue"
from config.settings import VALIDATION_RETRIES

logger = logging.getLogger(__name__)


def _record_status(
    state: AgentState,
    *,
    status: str,
    step: str,
    message: str = "",
    resume_url: str = "",
    metadata: Optional[Dict] = None,
) -> None:
    status_id = state.get("status_id")

    if not status_id:
        return

    metadata_payload = metadata or {}

    try:
        status_service.update_status(
            status_id=status_id,
            status=status,
            step=step,
            message=message,
            resume_url=resume_url,
            metadata=metadata_payload,
        )
    except Exception as error:
        logger.debug(f"Failed to update status (step={step}): {error}")


def load_pointers_node(state: AgentState) -> Dict:
    """Load base resume pointers from Google Drive.

    This is a LangGraph node that:
    1. Connects to Google Drive
    2. Downloads markdown file containing base experience pointers
    3. Returns raw pointers to be transformed for specific jobs

    Args:
        state: Current agent state

    Returns:
        Dict with updated state keys
    """
    logger.info("Loading base resume pointers from Google Drive")
    _record_status(
        state,
        status="processing",
        step="loading_pointers",
        message="Loading base resume pointers from Google Drive",
    )

    try:
        drive_service = DriveService()

        # List pointer documents from Google Drive
        files = drive_service.list_pointer_documents()

        if not files:
            logger.warning("No pointer files found in Google Drive")
            _record_status(
                state,
                status="failed",
                step="pointers_missing",
                message="No pointer files found",
            )
            return {
                "base_resume_pointers": None,
                "error_message": "No pointer files found",
                "status": "failed"
            }

        # For now, assume single resume file (can be extended to handle multiple)
        file = files[0]
        logger.info(f"Loading pointer file: {file['name']}")
        
        # Download file content
        content = drive_service.download_file_content(file['id'])
        
        logger.info(f"Loaded base resume pointers: {len(content)} characters")

        _record_status(
            state,
            status="processing",
            step="pointers_loaded",
            message=f"Loaded pointers from {file['name']}",
        )

        return {
            "base_resume_pointers": content,
            "status": "pointers_loaded"
        }

    except Exception as error:
        logger.error(f"Error loading pointers: {error}")
        _record_status(
            state,
            status="failed",
            step="pointers_failed",
            message=str(error),
        )
        return {
            "base_resume_pointers": None,
            "error_message": f"Failed to load pointers: {str(error)}",
            "status": "failed"
        }


def generate_document_node(state: AgentState) -> Dict:
    """Generate final document without uploading.

    This is a LangGraph node that:
    1. Creates Word document from template
    2. Returns local path for validation

    Args:
        state: Current agent state

    Returns:
        Dict with updated state keys
    """
    logger.info("Generating final document")
    _record_status(
        state,
        status="processing",
        step="generating_document",
        message="Generating DOCX resume from template",
    )

    try:
        doc_service = DocumentService()

        # Generate Word document
        docx_path = doc_service.generate_resume(
            resume_sections=state["resume_sections"],
            job_metadata=state["job_metadata"]
        )

        logger.info(f"Document generated: {docx_path}")

        _record_status(
            state,
            status="processing",
            step="document_generated",
            message="DOCX resume generated",
            metadata={"docx_path": docx_path},
        )

        # Keep the local file for validation
        return {
            "generated_doc_path": docx_path,
            "status": "generated"
        }

    except Exception as error:
        logger.error(f"Error generating document: {error}")
        _record_status(
            state,
            status="failed",
            step="document_generation_failed",
            message=str(error),
        )
        return {
            "error_message": f"Document generation failed: {str(error)}",
            "status": "failed"
        }


def validate_complete_resume_node(state: AgentState) -> Dict:
    """Validate the complete generated resume.

    This is a LangGraph node that:
    1. Takes the generated DOCX path from state
    2. Validates the complete resume using validate_complete_resume
    3. Updates state with validation result
    4. Only uploads to Drive if valid or max retries reached
    5. Cleans up the local file only after successful upload

    Args:
        state: Current agent state

    Returns:
        Dict with updated state keys
    """
    logger.info("Validating the resume")
    retry_count = state.get("retry_count", 0)
    _record_status(
        state,
        status="processing",
        step="validating_resume",
        message=f"Validating resume (attempt {retry_count + 1})",
        metadata={"retry_count": retry_count},
    )

    try:
        llm_service = LLMService()
        
        # Parse requirements
        requirements = AnalyzedRequirements(**state["analyzed_requirements"])

        # Validate complete resume
        validation = llm_service.validate_complete_resume(
            docx_file_path=state["generated_doc_path"],
            job_description=state["job_description"],
            job_metadata=state["job_metadata"],
            requirements=requirements
        )

        logger.info(
            f"Complete resume validation: is_valid={validation.is_valid}, "
            f"score={validation.keyword_coverage_score}, "
            f"issues={len(validation.issues_found)}"
        )
        
        # Log detailed validation feedback
        if validation.issues_found:
            logger.warning("Validation issues found:")
            for issue in validation.issues_found:
                logger.warning(f"  - {issue}")
        
        if validation.suggestions:
            logger.info("Validation suggestions:")
            for suggestion in validation.suggestions:
                logger.info(f"  - {suggestion}")
                
        if validation.feedback_for_rewrite:
            logger.info(f"Validation feedback: {validation.feedback_for_rewrite}")

        # Check if we should upload or retry
        if validation.is_valid or retry_count >= VALIDATION_RETRIES:
            if not validation.is_valid:
                logger.warning(f"Validation failed but max retries ({VALIDATION_RETRIES}) reached. Uploading anyway.")
            
            # Upload to Drive
            drive_service = DriveService()
            resume_url = drive_service.upload_file(state["generated_doc_path"])
            logger.info(f"Document uploaded to Google Drive: {resume_url}")

            # Clean up local file after upload
            from pathlib import Path
            try:
                Path(state["generated_doc_path"]).unlink()
                logger.info("Cleaned up local resume file")
            except Exception as e:
                logger.warning(f"Failed to clean up file: {e}")

            _record_status(
                state,
                status="completed",
                step="resume_uploaded",
                message="Resume uploaded to Google Drive",
                resume_url=resume_url,
                metadata={
                    "validation_score": validation.keyword_coverage_score,
                    "issues_found": len(validation.issues_found),
                },
            )

            return {
                "validation_result": validation.model_dump(),
                "resume_url": resume_url,
                "status": "completed"
            }
        else:
            # Validation failed and we have retries left
            logger.info(f"Validation failed. Will retry (attempt {retry_count + 1}/{VALIDATION_RETRIES})")
            
            # Clean up the failed document
            from pathlib import Path
            try:
                Path(state["generated_doc_path"]).unlink()
                logger.info("Cleaned up failed resume file")
            except Exception as e:
                logger.warning(f"Failed to clean up file: {e}")

            _record_status(
                state,
                status="processing",
                step="validation_failed",
                message="Validation failed - retrying",
                metadata={
                    "validation_score": validation.keyword_coverage_score,
                    "issues_found": len(validation.issues_found),
                },
            )
            
            return {
                "validation_result": validation.model_dump(),
                "status": "validation_failed"
            }

    except Exception as error:
        logger.error(f"Error in complete resume validation: {error}")
        _record_status(
            state,
            status="failed",
            step="validation_failed",
            message=str(error),
        )
        return {
            "error_message": f"Complete resume validation failed: {str(error)}",
            "status": "failed"
        }


def should_retry_after_validation(state: AgentState) -> Literal["retry", "finish"]:
    """Determine if validation failed and we should retry.

    Args:
        state: Current agent state

    Returns:
        "retry" if should retry writing, "finish" if validation passed or max retries reached
    """
    status = state.get("status", "")
    
    if status == "completed":
        return "finish"
    elif status == "validation_failed":
        _record_status(
            state,
            status="processing",
            step="retrying_after_validation",
            message="Preparing to retry resume writing after validation feedback",
            metadata={"retry_count": state.get("retry_count", 0)},
        )
        return "retry"
    else:
        # Failed status or other
        return "finish"


def increment_retry_count(state: AgentState) -> Dict:
    """Increment retry counter before retry loop.

    Args:
        state: Current agent state

    Returns:
        Dict with incremented retry_count
    """
    new_retry_count = state.get("retry_count", 0) + 1

    _record_status(
        state,
        status="processing",
        step="retrying",
        message=f"Retry attempt {new_retry_count}",
        metadata={"retry_count": new_retry_count},
    )

    return {
        "retry_count": new_retry_count
    }


def should_continue_after_load(state: AgentState) -> Literal["continue", "end"]:
    """Check if workflow should continue after loading pointers.

    Args:
        state: Current agent state

    Returns:
        "continue" if pointers loaded successfully, "end" if failed
    """
    status = state.get("status", "processing")
    
    if status == "failed":
        logger.error("Pointer loading failed, ending workflow")
        return "end"
    
    base_resume_pointers = state.get("base_resume_pointers")
    if not base_resume_pointers:
        logger.error("No base resume pointers loaded, ending workflow")
        return "end"
    
    logger.info(f"Successfully loaded base resume pointers: {len(base_resume_pointers)} characters")
    return "continue"


def should_continue_after_analyze(state: AgentState) -> Literal["continue", "end"]:
    """Check if workflow should continue after analyzing JD.

    Args:
        state: Current agent state

    Returns:
        "continue" if JD analyzed successfully, "end" if failed
    """
    status = state.get("status", "processing")
    
    if status == "failed":
        logger.error("JD analysis failed, ending workflow")
        return "end"
    
    analyzed_requirements = state.get("analyzed_requirements")
    if not analyzed_requirements:
        logger.error("No analyzed requirements found, ending workflow")
        return "end"
    
    # Check sponsorship status
    job_metadata = state.get("job_metadata", {})
    sponsorship = job_metadata.get("sponsorship", "Not Specified")
    
    # Check if sponsorship is explicitly "No" (case-insensitive)
    if sponsorship and sponsorship.strip().lower() == "no":
        logger.warning(f"Job does not offer H1B sponsorship (sponsorship={sponsorship}), ending workflow")
        # Update state to indicate why we're stopping
        state["status"] = "no_sponsorship"
        state["error_message"] = "This position does not offer H1B visa sponsorship"
        metadata_payload = job_metadata
        if not isinstance(metadata_payload, dict) and hasattr(metadata_payload, "model_dump"):
            metadata_payload = metadata_payload.model_dump()
        _record_status(
            state,
            status="no_sponsorship",
            step="no_sponsorship",
            message="cancelled: no visa sponsorship",
            metadata=metadata_payload,
        )
        return "end"
    
    logger.info(f"JD analysis completed successfully, sponsorship status: {sponsorship}")
    return "continue"


def should_continue_after_write(state: AgentState) -> Literal["continue", "end"]:
    """Check if workflow should continue after writing resume.

    Args:
        state: Current agent state

    Returns:
        "continue" if resume written successfully, "end" if failed
    """
    status = state.get("status", "processing")
    
    if status == "failed":
        logger.error("Resume writing failed, ending workflow")
        return "end"
    
    resume_sections = state.get("resume_sections")
    if not resume_sections:
        logger.error("No resume sections found, ending workflow")
        return "end"
    
    logger.info("Resume writing completed successfully")
    return "continue"


def create_workflow() -> StateGraph:
    """Create and compile the LangGraph workflow.

    Returns:
        Compiled StateGraph
    """
    logger.info("Creating LangGraph workflow")

    # Create state graph
    workflow = StateGraph(AgentState)

    # Add nodes
    workflow.add_node("initial_screening", initial_screening_node)
    workflow.add_node("load_pointers", load_pointers_node)
    workflow.add_node("analyze_jd", analyze_jd_node)
    workflow.add_node("write_resume", write_resume_node)
    workflow.add_node("generate_doc", generate_document_node)
    workflow.add_node("validate_complete", validate_complete_resume_node)
    workflow.add_node("increment_retry", increment_retry_count)

    # Define edges
    workflow.set_entry_point("initial_screening")

    workflow.add_conditional_edges(
        "initial_screening",
        should_continue_after_screening,
        {
            "continue": "load_pointers",
            "end": END
        }
    )
    
    # Conditional edge after loading pointers
    workflow.add_conditional_edges(
        "load_pointers",
        should_continue_after_load,
        {
            "continue": "analyze_jd",
            "end": END
        }
    )
    
    # Conditional edge after analyzing JD
    workflow.add_conditional_edges(
        "analyze_jd",
        should_continue_after_analyze,
        {
            "continue": "write_resume",
            "end": END
        }
    )
    # Conditional edge after writing resume
    workflow.add_conditional_edges(
        "write_resume",
        should_continue_after_write,
        {
            "continue": "generate_doc",
            "end": END
        }
    )
    workflow.add_edge("generate_doc", "validate_complete")
    
    # Conditional edge after validation
    workflow.add_conditional_edges(
        "validate_complete",
        should_retry_after_validation,
        {
            "retry": "increment_retry",
            "finish": END
        }
    )
    
    # Retry loop back to write_resume
    workflow.add_edge("increment_retry", "write_resume")

    logger.info("Workflow created with 6 nodes including validation retry loop")

    return workflow.compile()
