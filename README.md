# Resume Agent System

Production-quality LangGraph agent system for generating tailored resumes from job descriptions.

## Features

- **LangGraph Multi-Agent System**: Orchestrated workflow with JD Analyzer, Resume Writer, and Quality Validator agents
- **Google Drive Integration**: Dynamically loads resume pointers from Google Drive, uploads generated PDFs
- **LLM-Powered**: Uses GPT-4 for intelligent analysis and content generation
- **Quality Validation**: Automatic validation with retry logic for optimal results
- **Chrome Extension Ready**: Flask API designed to work with browser extensions

## Architecture

```
Browser → Chrome Extension → Flask API → LangGraph Orchestrator
         (sends URL + JD)                     ↓
                                        [Load Pointers]
                                              ↓
                                        [Extract Metadata]
                                              ↓
                                        [Analyze JD]
                                              ↓
                                        [Write Resume]
                                              ↓
                                        [Validate] → (retry if needed)
                                              ↓
                                        [Generate Doc]
                                              ↓
                                        Google Drive Upload
```

## Setup

### 1. Install Dependencies

**Option A: Using Conda (Recommended - Stable Versions)**

```bash
# Quick setup with script
./setup_conda.sh

# Or manually
conda env create -f environment.yml
conda activate resume-agent
```

**Option B: Using pip/venv**

```bash
# For stable versions
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
pip install -r requirements-stable.txt

# For latest versions (may have compatibility issues)
pip install -r requirements.txt
```

📖 **See [SETUP.md](SETUP.md) for detailed installation instructions and troubleshooting.**

### 2. Configure Environment Variables

Copy `.env.example` to `.env` and fill in your credentials:

```bash
cp .env.example .env
```

Required variables:
- `OPENAI_API_KEY`: Your OpenAI API key
- `GOOGLE_DRIVE_POINTERS_FOLDER_ID`: Folder ID containing base experience pointer markdown files (raw descriptions to be transformed)
- `GOOGLE_DRIVE_OUTPUT_FOLDER_ID`: Folder ID for generated resumes  
- `RESUME_TEMPLATE_DRIVE_ID`: Google Drive file ID of your resume template (.docx file)

### 3. Google Drive Setup

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create a new project or select existing
3. Enable Google Drive API
4. Create OAuth 2.0 credentials (Desktop app)
5. Download `credentials.json` to project root
6. **Add yourself as a test user:**
   - Navigate to your project in Google Cloud Console
   - Go to "APIs & Services" → "OAuth consent screen"
   - Scroll down to "Test users" section
   - Click "+ ADD USERS"
   - Add your email address
   - Click "SAVE"
7. Create folders and upload resume template in Google Drive:
   - **Resume Pointers** folder (for markdown files with bullet points)
   - **Generated Resumes** folder (for output .docx files)  
   - **Upload your resume template** (.docx file) to Google Drive
8. Get IDs from Google Drive URLs:
   - **Folder IDs**: `https://drive.google.com/drive/folders/FOLDER_ID_HERE`
   - **File ID**: `https://drive.google.com/file/d/FILE_ID_HERE/view`

### 4. Prepare Resume Pointers

Create markdown files in your Resume Pointers folder:

**Example: `job1_experience.md`**
```markdown
- Architected microservices platform handling 1M+ requests/day
- Reduced deployment time by 60% through CI/CD automation
- Led team of 5 engineers in delivering critical features
```

**Example: `projects.md`**
```markdown
- Built real-time analytics dashboard using React and WebSockets
- Implemented ML pipeline for customer churn prediction (85% accuracy)
```

### 5. Create Resume Template

1. Create a Word document (`resume_template.docx`) with placeholders:
   ```
   {{CANDIDATE_NAME}}
   {{CONTACT_INFO}}

   PROFESSIONAL SUMMARY
   {{SUMMARY}}

   EXPERIENCE
   Current Role
   {{EXPERIENCE_BULLET_1}}
   {{EXPERIENCE_BULLET_2}}
   {{EXPERIENCE_BULLET_3}}
   {{EXPERIENCE_BULLET_4}}

   SKILLS
   {{TECHNICAL_SKILLS}}
   ```

   Note: Use individual bullet placeholders ({{EXPERIENCE_BULLET_1}}, {{EXPERIENCE_BULLET_2}}, etc.) not {{EXPERIENCE_BULLETS_1}}

2. Upload the .docx file to Google Drive and copy the file ID from the URL
3. Add the file ID to your `.env` file as `RESUME_TEMPLATE_DRIVE_ID`

## Usage

### Chrome Extension

1. Load the extension from the `chrome-extension` directory
2. Navigate to any job posting page
3. Select the job description text
4. Click the extension icon and press "Extract & Send to Server"
5. The system will:
   - Extract the selected job description
   - Send it with the page URL to the backend
   - Extract job metadata (title, company, etc.) using AI
   - Generate a tailored resume
   - Upload to Google Drive and return the link

### Start the Server

```bash
python run.py
```

Server runs on `http://localhost:8000`

### Test Endpoints

**Health Check:**
```bash
curl http://localhost:8000/health
```

**Test Google Drive:**
```bash
curl http://localhost:8000/test-drive
```

**Test LLM:**
```bash
curl -X POST http://localhost:8000/test-llm \
  -H "Content-Type: application/json" \
  -d '{"text": "Sample job description"}'
```

**Generate Resume:**
```bash
curl -X POST http://localhost:8000/generate-resume \
  -H "Content-Type: application/json" \
  -d '{
    "job_description": "Full job description text here...",
    "job_metadata": {
      "job_url": "https://example.com/jobs/12345"
    }
  }'
```

Note: The system will automatically extract job title, company, and other metadata from the job description using AI.

Response:
```json
{
  "status": "success",
  "resume_url": "https://docs.google.com/document/d/.../edit",
  "metadata": {
    "job_title": "Senior Software Engineer", 
    "company": "Google",
    "bullets_count": 10,
    "keyword_coverage": 85.5,
    "retry_count": 0
  }
}
```

**Note**: The system now generates .docx files only (no PDF conversion) for optimal ATS compatibility.

## Project Structure

```
resume-agent/
├── config/
│   └── settings.py          # Centralized configuration
├── src/
│   ├── agents/              # LangGraph agent nodes
│   │   ├── state.py         # State schemas
│   │   ├── jd_analyzer.py   # Job description analysis
│   │   ├── resume_writer.py # Resume bullet rewriting
│   │   └── quality_validator.py # Quality validation
│   ├── graph/
│   │   └── workflow.py      # LangGraph orchestration
│   ├── services/
│   │   ├── drive_service.py # Google Drive API
│   │   ├── llm_service.py   # OpenAI wrapper
│   │   └── document_service.py # Word document generation
│   └── api/
│       └── server.py        # Flask API
├── tests/
├── .env
├── requirements.txt
└── run.py
```

## Configuration

Edit `.env` to customize:
- `VALIDATION_RETRIES`: Max retries if validation fails (default: 2)
- `LLM_TEMPERATURE`: LLM temperature setting (default: 0.3)

**Server Settings:**
- `FLASK_PORT`: Server port (default: 8000)

## Development

### Run Tests

```bash
pytest tests/
```

### Code Formatting

```bash
black src/ tests/
```

## Troubleshooting

**Google Drive Authentication:**
- Delete `token.json` and re-authenticate if you get permission errors
- Ensure correct scopes in `drive_service.py`

**LLM API Errors:**
- Check API key is valid and has credits
- Verify `OPENAI_API_KEY` in `.env`

**Template Issues:**
- Verify `RESUME_TEMPLATE_DRIVE_ID` is correct
- Check file permissions in Google Drive
- Ensure template is a .docx file with proper placeholders

**Document Conversion:**
- On Linux, install `libreoffice`: `sudo apt-get install libreoffice`
- On Windows/Mac, ensure Microsoft Word is installed

## License

MIT
