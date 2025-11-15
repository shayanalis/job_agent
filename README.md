# Resume Agent System

LangGraph-based automation that turns a highlighted job description into a tailored Word resume and tracks progress across browser sessions.

## Feature Highlights

- **Multi-stage LangGraph flow**: Initial screening → pointer ingestion → JD analysis → resume rewrite → document generation → LLM validation with retries
- **Sponsorship guard rails**: Lightweight screening service flags “no visa sponsorship” jobs before expensive calls
- **Google Drive integration**: Pointer markdown pulled from Drive, final `.docx` uploaded back with shareable links
- **Structured LLM services**: Single OpenAI client handles analysis, rewriting, and validation with pydantic-validated outputs
- **Realtime status service**: `/status` endpoint plus Chrome extension UI retain progress per job URL/status id
- **Observability via MLflow**: Every workflow run is logged under the `resume-generation` experiment (see `mlruns/`)

## System Architecture

```
Browser (Chrome Extension)
        │
        ▼
 Flask API (`/generate-resume`)
        │
        ▼
 LangGraph Workflow
   ├─ Initial screening (visa / blockers)
   ├─ Load base pointers from Drive
   ├─ Analyze JD & extract metadata
   ├─ Rewrite role bullets + skills
   ├─ Generate DOCX from Drive template
   └─ Validate + retry → upload to Drive
        │
        ▼
Google Drive + Status Service
```

See `Agent_architecture.md` for a deeper dive into each node.

## 1. Prerequisites

- Python 3.11
- An OpenAI API key (configured for `gpt-5`/`gpt-5-mini` variants used in `config/settings.py`)
- Google Cloud project with Drive API enabled and OAuth desktop credentials
- `mlflow` installed (required by the API to log runs)

## 2. Environment Setup

### Option A – Conda (recommended)

```bash
conda env create -f /Users/shayan/Documents/Job_Assistant/environment.yml
conda activate resume-agent
```

### Option B – venv + pip

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r /Users/shayan/Documents/Job_Assistant/requirements.txt
pip install mlflow  # required for server telemetry
```

### Environment variables

Create `/Users/shayan/Documents/Job_Assistant/.env` and populate:

```
OPENAI_API_KEY=sk-your-key
OPENAI_MODEL=gpt-5                    # optional override
SCREENING_MODEL=gpt-5-mini            # optional override
GOOGLE_DRIVE_POINTERS_FOLDER_ID=xxx
GOOGLE_DRIVE_OUTPUT_FOLDER_ID=yyy
RESUME_TEMPLATE_DRIVE_ID=zzz
FLASK_PORT=8000                       # match the Chrome extension default
LOG_LEVEL=INFO
VALIDATION_RETRIES=2
LLM_TEMPERATURE=0.0
```

Place your Google OAuth `credentials.json` in the repository root; the first run will create `token.json`.

## 3. Google Drive Preparation

1. Create two folders: one for **resume pointers** (markdown or text bullet banks) and one for **generated resumes**.
2. Upload your Word template with placeholders such as `{{CANDIDATE_NAME}}`, `{{LEAFICIENT_EXPERIENCE_BULLET_1}}`, `{{TECHNICAL_SKILLS}}`, etc. The `DocumentService` will clear any unused placeholders automatically.
3. Record the folder IDs and template file ID from the Drive URLs and copy them into `.env`.
4. Share the folders/files with the Google account used during OAuth if you hit 403 errors.

## 4. Running the Backend

```bash
python /Users/shayan/Documents/Job_Assistant/run.py
```

Key endpoints (replace `8000` with your configured `FLASK_PORT`, default is `8002` in code):

- `GET /health` – service heartbeat
- `POST /generate-resume` – main workflow (requires `job_description` + `job_metadata.job_url`)
- `GET /status` – latest snapshot by `status_id`, `job_url`, or `base_url`
- `GET /test-drive` – verifies Drive connectivity/listing
- `POST /test-llm` – smoke test for OpenAI access

The server prints a configuration summary on startup and will warn if critical IDs or API keys are missing.

### Workflow status persistence

Statuses live in-memory via `StatusService`. They are keyed by normalized job URL and expire after one hour. The Chrome extension and `/status` endpoint both use that service (`src/services/status_service.py`, `tests/test_status_service.py`).

## 5. Observability

- Runs are logged to `./mlruns/` under the `resume-generation` experiment.
- Launch a local UI with the provided Makefile target:

```bash
make -C /Users/shayan/Documents/Job_Assistant mlflow
```

## 6. Chrome Extension

Path: `/Users/shayan/Documents/Job_Assistant/chrome-extension`

1. Update `SERVER_BASE_URL` in `popup.js` if your backend is not on `http://localhost:8000`.
2. Load the directory as an unpacked extension in Chrome.
3. Highlight a job description, click “Create Resume,” and the popup will poll `/status` until a terminal state is reached.
4. History for the last five runs is cached per job/base URL to survive popup closes.

## 7. Tests & Tooling

- Unit tests: `pytest /Users/shayan/Documents/Job_Assistant/tests`
- Example ad-hoc script for sponsorship handling: `python /Users/shayan/Documents/Job_Assistant/test_sponsorship.py` (update the URL/port to match your server)
- Code style: `black src/ tests/`

## 8. Project Structure

```
Job_Assistant/
├── config/
│   └── settings.py           # loads .env, centralizes configuration defaults
├── src/
│   ├── api/server.py         # Flask app + endpoints
│   ├── agents/
│   │   ├── state.py          # Typed dict & pydantic models for workflow data
│   │   ├── jd_analyzer.py    # LangGraph node for JD + metadata extraction
│   │   └── resume_writer.py  # LangGraph node for TAR-style bullet rewriting
│   ├── graph/workflow.py     # LangGraph definition incl. screening + validation loop
│   └── services/
│       ├── document_service.py  # Downloads template, fills placeholders, uploads
│       ├── drive_service.py     # Google Drive OAuth + file helpers
│       ├── llm_service.py       # Shared OpenAI client (analysis, rewrite, validation)
│       ├── screening_service.py # Sponsorship / blocker detection
│       └── status_service.py    # In-memory status tracking
├── chrome-extension/           # Browser UI to trigger and monitor runs
├── generated_resumes/          # Local output cache (also uploaded to Drive)
├── mlruns/                     # MLflow traces and runs
├── requirements.txt
├── environment.yml
├── run.py
└── tests/
```

## 9. Troubleshooting

- **`OPENAI_API_KEY` errors**: ensure the key has access to the specified models; adjust `OPENAI_MODEL`/`SCREENING_MODEL` if needed.
- **`mlflow` import failures**: install `mlflow>=2.14` (or run `pip install mlflow`) inside your environment.
- **Drive pointer folder empty**: confirm the folder ID and that the OAuth account has read access; `DriveService.list_pointer_documents` logs everything it finds.
- **Sponsorship rejection**: when the screening node detects “no sponsorship,” `/generate-resume` returns a 400 with status `no_sponsorship`.
- **Template placeholder mismatches**: add placeholders matching the role keys returned by the resume writer (`LEAFICIENT_EXPERIENCE_BULLET_1`, etc.) or they will be cleared.
- **Port mismatch with Chrome extension**: either set `FLASK_PORT=8000` in `.env` before starting the server or edit `chrome-extension/popup.js`.

## License

MIT
