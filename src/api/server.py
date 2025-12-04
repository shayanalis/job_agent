"""Flask API server for resume generation."""

import hashlib
import logging
import time
import mlflow
from flask import Flask, request, jsonify, send_file
from flask_cors import CORS
import io

from src.graph.workflow import create_workflow
from config.settings import FLASK_PORT, FLASK_DEBUG, LOG_LEVEL
from src.services.status_service import status_service

# Configure logging
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Create Flask app
app = Flask(__name__)
CORS(app)  # Enable CORS for Chrome extension

# Initialize workflow (singleton)
workflow = None


def get_workflow():
    """Get or create workflow instance."""
    global workflow
    if workflow is None:
        logger.info("Initializing LangGraph workflow")
        workflow = create_workflow()
    return workflow


@app.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint.

    Returns:
        JSON response with status
    """
    return jsonify({
        "status": "healthy",
        "service": "resume-agent"
    }), 200


@app.route('/generate-resume', methods=['POST'])
def generate_resume():
    """Generate tailored resume from job description.

    Request JSON:
        {
            "job_description": "Full job description text",
            "job_metadata": {
                "job_url": "https://example.com/jobs/12345"
            }
        }
    
    Note: Title, company, and other metadata will be extracted from the job description.

    Returns:
        JSON response with resume URL or error
    """
    status_id = None
    status_snapshot = None

    try:
        # Validate request
        data = request.get_json()
        if not data:
            return jsonify({
                "error": "No JSON data provided"
            }), 400

        job_description = data.get('job_description')
        if not job_description:
            return jsonify({
                "error": "job_description is required"
            }), 400

        job_metadata = data.get('job_metadata', {})
        job_url = job_metadata.get('job_url')
        
        if not job_url:
            return jsonify({
                "error": "job_url is required in job_metadata"
            }), 400

        logger.info(f"Received resume generation request for URL: {job_url}")

        job_hash = _derive_job_hash(job_url, job_description)

        status_snapshot = status_service.create_status(
            job_url=job_url,
            status="processing",
            step="received",
            message="Request received",
            metadata={
                "job_title": job_metadata.get("title"),
                "company": job_metadata.get("company"),
                "job_hash": job_hash,
            },
            job_hash=job_hash,
        )
        status_id = status_snapshot.status_id

        # Initialize workflow state
        initial_state = {
            "job_description": job_description,
            "job_metadata": job_metadata,
            "status_id": status_id,
            "job_hash": job_hash,
            "base_resume_pointers": None,
            "analyzed_requirements": None,
            "resume_sections": None,
            "validation_result": None,
            "generated_doc_path": "",
            "resume_url": "",
            "retry_count": 0,
            "error_message": "",
            "status": "processing"
        }

        # Run workflow
        workflow_instance = get_workflow()
        
        # Set experiment name for better organization
        mlflow.set_experiment("resume-generation")
        
        with mlflow.start_run(run_name=f"resume_{job_metadata.get('company', 'unknown')}"):
            with mlflow.start_span(name="resume_generation_workflow") as span:
                span.set_inputs({
                    "job_url": job_url,
                    "company": job_metadata.get("company", "unknown"),
                    "job_title": job_metadata.get("title", "unknown")
                })
                result = workflow_instance.invoke(initial_state)
                
                # Check if workflow returned a result
                if result is not None:
                    validation_result = result.get("validation_result")
                    validation_score = 0
                    if validation_result and isinstance(validation_result, dict):
                        validation_score = validation_result.get("keyword_coverage_score", 0)
                    
                    # Count bullets across all roles
                    resume_sections = result.get("resume_sections", {})
                    total_bullets = sum(len(bullets) for role, bullets in resume_sections.items() if role != "skills" and isinstance(bullets, list)) if resume_sections else 0
                    
                    span.set_outputs({
                        "status": result.get("status"),
                        "bullets_count": total_bullets,
                        "validation_score": validation_score
                    })
                else:
                    span.set_outputs({
                        "status": "failed",
                        "error": "Workflow returned no result"
                    })

        # Handle null result
        if result is None:
            logger.error("Workflow returned None - likely an early exit or crash")
            status_service.update_status(
                status_id=status_id,
                status="failed",
                step="workflow_error",
                message="Workflow returned no result",
            )
            return jsonify({
                "error": "Resume processing failed - workflow returned no result",
                "status": "failed",
                "status_id": status_id,
            }), 500

        # Check for errors
        if result.get("status") == "failed":
            error_msg = result.get("error_message", "Unknown error")
            logger.error(f"Workflow failed: {error_msg}")
            status_service.update_status(
                status_id=status_id,
                status="failed",
                step="workflow_failed",
                message=error_msg,
            )
            return jsonify({
                "error": error_msg,
                "status": "failed",
                "status_id": status_id,
            }), 500
        
        # Check for no sponsorship
        if result.get("status") == "no_sponsorship":
            error_msg = "cancelled: no visa sponsorship"
            job_metadata = result.get("job_metadata", {})
            logger.warning(f"Workflow ended: No H1B sponsorship for {job_metadata.get('title')} at {job_metadata.get('company')}")
            status_service.update_status(
                status_id=status_id,
                status="no_sponsorship",
                step="screened_out",
                message=error_msg,
                metadata={
                    "job_metadata": job_metadata,
                },
            )
            return jsonify({
                "error": error_msg,
                "status": "no_sponsorship",
                "status_id": status_id,
                "metadata": {
                    "job_title": job_metadata.get("title"),
                    "company": job_metadata.get("company"),
                    "sponsorship": job_metadata.get("sponsorship", "No")
                }
            }), 400

        # Success response
        resume_url = result.get("resume_url")
        validation_result = result.get("validation_result") or {}

        logger.info(f"Resume generated successfully: {resume_url}")
        status_service.update_status(
            status_id=status_id,
            status="completed",
            step="uploaded",
            message="Resume generated successfully",
            resume_url=resume_url or "",
            metadata={
                "job_metadata": result.get("job_metadata", {}),
                "validation_result": validation_result,
            },
        )

        resume_sections = result.get("resume_sections") or {}
        bullets_count = 0
        if isinstance(resume_sections, dict):
            bullets_count = sum(
                len(bullets)
                for role, bullets in resume_sections.items()
                if role != "skills" and isinstance(bullets, list)
            )

        job_metadata = result.get("job_metadata") or {}

        return jsonify({
            "status": "success",
            "status_id": status_id,
            "resume_url": resume_url,
            "metadata": {
                "job_title": job_metadata.get("title"),
                "company": job_metadata.get("company"),
                "bullets_count": bullets_count,
                "keyword_coverage": validation_result.get("keyword_coverage_score", 0),
                "retry_count": result.get("retry_count", 0)
            }
        }), 200

    except Exception as error:
        logger.error(f"Error in generate_resume endpoint: {error}", exc_info=True)
        if status_id:
            status_service.update_status(
                status_id=status_id,
                status="failed",
                step="exception",
                message=str(error),
            )
        return jsonify({
            "error": f"Internal server error: {str(error)}",
            "status": "failed",
            "status_id": status_id,
        }), 500


@app.route('/status', methods=['GET'])
def get_status():
    """Fetch latest workflow status for a job URL, base URL, or status ID."""

    job_url = request.args.get('job_url')
    base_url = request.args.get('base_url')
    status_id = request.args.get('status_id')

    if not any([job_url, base_url, status_id]):
        return jsonify({
            "error": "status_id, job_url, or base_url query parameter is required",
            "status": "failed"
        }), 400

    snapshot = status_service.get_status(
        job_url=job_url,
        base_url=base_url,
        status_id=status_id,
    )

    if snapshot:
        return jsonify({
            "status": "success",
            "snapshot": snapshot.to_dict()
        }), 200

    normalized_job_url = status_service.normalize_job_url(job_url) if job_url else ""
    normalized_base_url = status_service.normalize_base_url(base_url or job_url or "") if (base_url or job_url) else ""

    return jsonify({
        "status": "not_found",
        "snapshot": {
            "job_url": normalized_job_url,
            "base_url": normalized_base_url,
            "status": "not_started",
            "step": "idle",
            "message": "",
            "resume_url": "",
            "metadata": {},
            "status_id": status_id or "",
            "updated_at": time.time(),
        }
    }), 200


@app.route('/statuses', methods=['GET'])
def list_statuses():
    """Return all tracked resume statuses."""

    include_applied_raw = request.args.get('include_applied', 'true').strip().lower()
    include_applied = include_applied_raw not in ('false', '0', 'no')

    snapshots = status_service.list_all(include_applied=include_applied)
    return jsonify({
        "status": "success",
        "snapshots": [snap.to_dict() for snap in snapshots]
    }), 200


@app.route('/statuses/<status_id>/applied', methods=['POST'])
def set_status_applied(status_id: str):
    """Mark a workflow status as applied or not applied."""

    body = request.get_json(silent=True) or {}
    applied_raw = body.get('applied', True)
    applied = bool(applied_raw)

    snapshot = status_service.mark_applied(status_id, applied=applied)
    if snapshot is None:
        return jsonify({
            "status": "failed",
            "error": "status_id not found"
        }), 404

    return jsonify({
        "status": "success",
        "snapshot": snapshot.to_dict()
    }), 200


@app.route('/download-resume', methods=['GET'])
def download_resume():
    """Download a resume file from Google Drive.

    Query parameters:
        status_id: Status ID to get resume URL from (preferred)
        resume_url: Direct Google Drive URL (alternative)

    Returns:
        File download response

    Raises:
        400: If neither status_id nor resume_url provided
        404: If status_id not found or resume URL missing
        500: If download fails
    """
    try:
        from src.services.drive_service import DriveService

        status_id = request.args.get('status_id')
        resume_url = request.args.get('resume_url')

        # Get resume URL from status_id if provided
        if status_id:
            snapshot = status_service.get_status(status_id=status_id)
            if not snapshot:
                return jsonify({
                    "status": "failed",
                    "error": "status_id not found"
                }), 404
            
            resume_url = snapshot.resume_url or (snapshot.metadata and snapshot.metadata.get('resume_url'))
            if not resume_url:
                return jsonify({
                    "status": "failed",
                    "error": "No resume URL found for this status_id"
                }), 404

        if not resume_url:
            return jsonify({
                "status": "failed",
                "error": "Either status_id or resume_url query parameter is required"
            }), 400

        # Extract file ID from URL
        drive_service = DriveService()
        file_id = drive_service.extract_file_id_from_url(resume_url)
        
        if not file_id:
            return jsonify({
                "status": "failed",
                "error": f"Could not extract file ID from URL: {resume_url}"
            }), 400

        # Download file as PDF
        content, mime_type, file_name = drive_service.download_file_binary_content(file_id, export_as_pdf=True)

        # Create BytesIO object for Flask send_file
        file_stream = io.BytesIO(content)
        file_stream.seek(0)

        logger.info(f"Downloading resume: {file_name} ({len(content)} bytes)")

        return send_file(
            file_stream,
            mimetype=mime_type,
            as_attachment=True,
            download_name=file_name
        ), 200

    except Exception as error:
        logger.error(f"Error downloading resume: {error}", exc_info=True)
        return jsonify({
            "status": "failed",
            "error": str(error)
        }), 500


@app.route('/test-drive', methods=['GET'])
def test_drive():
    """Test Google Drive connection.

    Returns:
        JSON response with Drive connection status
    """
    try:
        from src.services.drive_service import DriveService

        drive_service = DriveService()
        files = drive_service.list_pointer_documents()

        return jsonify({
            "status": "success",
            "files_found": len(files),
            "files": [f['name'] for f in files]
        }), 200

    except Exception as error:
        logger.error(f"Drive test failed: {error}")
        return jsonify({
            "status": "failed",
            "error": str(error)
        }), 500


@app.route('/test-llm', methods=['POST'])
def test_llm():
    """Test LLM service connection.

    Request JSON:
        {
            "text": "Sample job description"
        }

    Returns:
        JSON response with LLM test result
    """
    try:
        from src.services.llm_service import LLMService

        data = request.get_json()
        text = data.get('text', 'Test job description for a Software Engineer position.')

        llm_service = LLMService()
        requirements = llm_service.analyze_job_description(
            job_description=text,
            job_metadata={"title": "Test", "company": "Test"}
        )

        return jsonify({
            "status": "success",
            "requirements": requirements.model_dump()
        }), 200

    except Exception as error:
        logger.error(f"LLM test failed: {error}")
        return jsonify({
            "status": "failed",
            "error": str(error)
        }), 500




@app.errorhandler(404)
def not_found(error):
    """Handle 404 errors."""
    return jsonify({
        "error": "Endpoint not found",
        "status": "failed"
    }), 404


@app.errorhandler(500)
def internal_error(error):
    """Handle 500 errors."""
    logger.error(f"Internal server error: {error}")
    return jsonify({
        "error": "Internal server error",
        "status": "failed"
    }), 500


def _derive_job_hash(job_url: str, job_description: str, snippet_length: int = 200) -> str:
    normalized_url = status_service.normalize_job_url(job_url)
    snippet = (job_description or "")[:snippet_length].strip()
    digest = hashlib.sha256(f"{normalized_url}::{snippet}".encode("utf-8")).hexdigest()
    return digest


def run_server():
    """Run the Flask server."""
    # Check critical configuration
    from config.settings import OPENAI_API_KEY, GOOGLE_DRIVE_POINTERS_FOLDER_ID, GOOGLE_DRIVE_OUTPUT_FOLDER_ID, RESUME_TEMPLATE_DRIVE_ID
    
    logger.info("=" * 60)
    logger.info("Configuration Check:")
    logger.info(f"OpenAI API Key: {'✓ Configured' if OPENAI_API_KEY else '✗ MISSING'}")
    logger.info(f"Google Drive Pointers Folder: {'✓ Configured' if GOOGLE_DRIVE_POINTERS_FOLDER_ID else '✗ MISSING'}")
    logger.info(f"Google Drive Output Folder: {'✓ Configured' if GOOGLE_DRIVE_OUTPUT_FOLDER_ID else '✗ MISSING'}")
    logger.info(f"Resume Template Drive ID: {'✓ Configured' if RESUME_TEMPLATE_DRIVE_ID else '✗ MISSING'}")
    logger.info("=" * 60)
    
    if not OPENAI_API_KEY:
        logger.warning("OpenAI API key is not configured! Metadata extraction may fail.")
    
    # Log registered routes for debugging
    logger.info("=" * 60)
    logger.info("Registered Routes:")
    for rule in app.url_map.iter_rules():
        methods = ','.join(sorted(rule.methods - {'HEAD', 'OPTIONS'}))
        logger.info(f"  {rule.rule:50s} [{methods}]")
    logger.info("=" * 60)
    
    logger.info(f"Starting Flask server on port {FLASK_PORT}")
    app.run(
        host='0.0.0.0',
        port=FLASK_PORT,
        debug=FLASK_DEBUG,
        threaded=True
    )


if __name__ == '__main__':
    run_server()
