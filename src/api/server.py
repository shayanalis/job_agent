"""Flask API server for resume generation."""

import logging
import mlflow
from flask import Flask, request, jsonify
from flask_cors import CORS

from src.graph.workflow import create_workflow
from config.settings import FLASK_PORT, FLASK_DEBUG, LOG_LEVEL

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

        # Initialize workflow state
        initial_state = {
            "job_description": job_description,
            "job_metadata": job_metadata,
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
            return jsonify({
                "error": "Resume processing failed - workflow returned no result",
                "status": "failed"
            }), 500

        # Check for errors
        if result.get("status") == "failed":
            error_msg = result.get("error_message", "Unknown error")
            logger.error(f"Workflow failed: {error_msg}")
            return jsonify({
                "error": error_msg,
                "status": "failed"
            }), 500
        
        # Check for no sponsorship
        if result.get("status") == "no_sponsorship":
            error_msg = result.get("error_message", "This position does not offer H1B visa sponsorship")
            job_metadata = result.get("job_metadata", {})
            logger.warning(f"Workflow ended: No H1B sponsorship for {job_metadata.get('title')} at {job_metadata.get('company')}")
            return jsonify({
                "error": error_msg,
                "status": "no_sponsorship",
                "metadata": {
                    "job_title": job_metadata.get("title"),
                    "company": job_metadata.get("company"),
                    "sponsorship": job_metadata.get("sponsorship", "No")
                }
            }), 400

        # Success response
        resume_url = result.get("resume_url")
        validation_result = result.get("validation_result", {})

        logger.info(f"Resume generated successfully: {resume_url}")

        return jsonify({
            "status": "success",
            "resume_url": resume_url,
            "metadata": {
                "job_title": result["job_metadata"].get("title"),
                "company": result["job_metadata"].get("company"),
                "bullets_count": sum(len(bullets) for role, bullets in result.get("resume_sections", {}).items() if role != "skills" and isinstance(bullets, list)),
                "keyword_coverage": validation_result.get("keyword_coverage_score", 0),
                "retry_count": result.get("retry_count", 0)
            }
        }), 200

    except Exception as error:
        logger.error(f"Error in generate_resume endpoint: {error}", exc_info=True)
        return jsonify({
            "error": f"Internal server error: {str(error)}",
            "status": "failed"
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
    
    logger.info(f"Starting Flask server on port {FLASK_PORT}")
    app.run(
        host='0.0.0.0',
        port=FLASK_PORT,
        debug=FLASK_DEBUG,
        threaded=True
    )


if __name__ == '__main__':
    run_server()
