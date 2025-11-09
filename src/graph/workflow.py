"""LangGraph workflow orchestration."""

import logging
from typing import Dict, Literal

import mlflow
from langgraph.graph import StateGraph, END

from src.agents.state import AgentState, AnalyzedRequirements

mlflow.langchain.autolog(log_traces=True)
from src.agents.jd_analyzer import analyze_jd_node
from src.agents.resume_writer import write_resume_node
from src.services.drive_service import DriveService
from src.services.document_service import DocumentService
from src.services.llm_service import LLMService
from config.settings import VALIDATION_RETRIES

logger = logging.getLogger(__name__)


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

    try:
        drive_service = DriveService()

        # List pointer documents from Google Drive
        files = drive_service.list_pointer_documents()

        if not files:
            logger.warning("No pointer files found in Google Drive")
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

        return {
            "base_resume_pointers": content,
            "status": "pointers_loaded"
        }

    except Exception as error:
        logger.error(f"Error loading pointers: {error}")
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

    try:
        doc_service = DocumentService()

        # Generate Word document
        docx_path = doc_service.generate_resume(
            resume_sections=state["resume_sections"],
            job_metadata=state["job_metadata"]
        )

        logger.info(f"Document generated: {docx_path}")

        # Keep the local file for validation
        return {
            "generated_doc_path": docx_path,
            "status": "generated"
        }

    except Exception as error:
        logger.error(f"Error generating document: {error}")
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
            
            return {
                "validation_result": validation.model_dump(),
                "status": "validation_failed"
            }

    except Exception as error:
        logger.error(f"Error in complete resume validation: {error}")
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
    return {
        "retry_count": state.get("retry_count", 0) + 1
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
    workflow.add_node("load_pointers", load_pointers_node)
    workflow.add_node("analyze_jd", analyze_jd_node)
    workflow.add_node("write_resume", write_resume_node)
    workflow.add_node("generate_doc", generate_document_node)
    workflow.add_node("validate_complete", validate_complete_resume_node)
    workflow.add_node("increment_retry", increment_retry_count)

    # Define edges
    workflow.set_entry_point("load_pointers")
    
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
