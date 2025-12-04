# Resume Agent System

LangGraph-based automation that turns a highlighted job description into a tailored Word resume and tracks progress across browser sessions.

## Feature Highlights

- **Multi-stage LangGraph flow**: Initial screening → pointer ingestion → JD analysis → resume rewrite → document generation → LLM validation with retries
- **Sponsorship guard rails**: Lightweight screening service flags "no visa sponsorship" jobs before expensive calls
- **Google Drive integration**: Pointer markdown pulled from Drive, final `.docx` uploaded back with shareable links
- **Structured LLM services**: Single OpenAI client handles analysis, rewriting, and validation with pydantic-validated outputs
- **Persistent status tracking**: SQLite-backed status service tracks all resume generations with URL normalization and job hashing
- **Chrome extension UI**: Highlight job descriptions to generate resumes, track active jobs, view history, and manage applied positions
- **Applied jobs management**: Mark positions as applied and filter them in a separate collapsible section in the extension
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
Google Drive + SQLite Status Store
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
conda env create -f environment.yml
conda activate resume-agent
```

### Option B – venv + pip

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
pip install mlflow  # required for server telemetry
```

### Environment variables

Create `.env` in the project root and populate:

```
OPENAI_API_KEY=sk-your-key
OPENAI_MODEL=gpt-5                    # optional override
SCREENING_MODEL=gpt-5-mini            # optional override
GOOGLE_DRIVE_POINTERS_FOLDER_ID=xxx
GOOGLE_DRIVE_OUTPUT_FOLDER_ID=yyy
RESUME_TEMPLATE_DRIVE_ID=zzz
FLASK_PORT=8002                       # default is 8002; Chrome extension defaults to 8000
LOG_LEVEL=INFO
VALIDATION_RETRIES=2
LLM_TEMPERATURE=0.0
DATABASE_URL=sqlite:///data/status_snapshots.db
```

Place your Google OAuth `credentials.json` in the repository root; the first run will create `token.json`.

## 3. Google Drive Preparation

1. Create two folders: one for **resume pointers** (markdown or text bullet banks) and one for **generated resumes**.
2. Upload your Word template with placeholders such as `{{CANDIDATE_NAME}}`, `{{LEAFICIENT_EXPERIENCE_BULLET_1}}`, `{{TECHNICAL_SKILLS}}`, etc. The `DocumentService` will clear any unused placeholders automatically.
3. Record the folder IDs and template file ID from the Drive URLs and copy them into `.env`.
4. Share the folders/files with the Google account used during OAuth if you hit 403 errors.

## 4. Running the Backend

First initialize the status database (creates the SQLite file defined by `DATABASE_URL`):

```bash
make migrate-db
```

```bash
python run.py
```

The server defaults to port `8002` (configurable via `FLASK_PORT`). **Note**: The Chrome extension defaults to `http://localhost:8000`, so either:
- Set `FLASK_PORT=8000` in your `.env` file, or
- Update `SERVER_BASE_URL` in `chrome-extension/popup.js` to match your port

Key endpoints:

- `GET /health` – service heartbeat
- `POST /generate-resume` – main workflow (requires `job_description` + `job_metadata.job_url`)
- `GET /status` – latest snapshot by `status_id`, `job_url`, or `base_url` query parameter
- `GET /statuses` – list all tracked statuses (supports `include_applied` query parameter, default `true`)
- `POST /statuses/<status_id>/applied` – mark a status as applied or not applied (body: `{"applied": true/false}`)
- `GET /test-drive` – verifies Drive connectivity/listing
- `POST /test-llm` – smoke test for OpenAI access

The server prints a configuration summary on startup and will warn if critical IDs or API keys are missing.

### Workflow status persistence

Statuses now persist exclusively to SQLite via `StatusService` + `StatusRepository`. By default the database lives at `data/status_snapshots.db` (override with `DATABASE_URL`). The service reads and writes directly to the database—there is no TTL or in-memory cache—so runs survive server restarts. Run `make migrate-db` whenever new tables or columns are introduced.

## 5. Observability

- Runs are logged to `./mlruns/` under the `resume-generation` experiment.
- Launch a local UI with the provided Makefile target:

```bash
make mlflow
```

## 6. Chrome Extension

Path: `chrome-extension/`

1. Update `SERVER_BASE_URL` in `popup.js` if your backend is not on `http://localhost:8000` (default backend port is `8002`, so you'll likely need to change this).
2. Load the directory as an unpacked extension in Chrome:
   - Open Chrome and navigate to `chrome://extensions/`
   - Enable "Developer mode" (toggle in top right)
   - Click "Load unpacked" and select the `chrome-extension` directory
3. **Usage**:
   - Navigate to a job posting page
   - Highlight/select the job description text
   - Click the extension icon and then "Create Resume"
   - The popup will show progress and poll `/status` until completion
   - View active jobs and history in the extension UI
4. **Applied Jobs**: 
   - Click the "Applied" toggle to expand/collapse a section showing all positions you've marked as applied
   - Use the applied icon (✓) on any completed resume card to mark it as applied
   - Applied jobs are filtered from the main history but can be viewed in the applied section
5. The extension fetches `/status` and `/statuses` fresh every time (no Chrome storage caching), so the SQLite database is the single source of truth.

## 7. Tests & Tooling

- Unit tests: `pytest tests/`
- Example ad-hoc script for sponsorship handling: `python test_sponsorship.py` (update the URL/port to match your server)
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
│   ├── db/
│   │   ├── base.py           # SQLAlchemy engine/session helpers
│   │   └── models.py         # ORM models (status snapshots)
│   ├── graph/workflow.py     # LangGraph definition incl. screening + validation loop
│   └── services/
│       ├── document_service.py  # Downloads template, fills placeholders, uploads
│       ├── drive_service.py     # Google Drive OAuth + file helpers
│       ├── llm_service.py       # Shared OpenAI client (analysis, rewrite, validation)
│       ├── screening_service.py # Sponsorship / blocker detection
│       ├── status_repository.py # SQLite persistence for workflow statuses
│       └── status_service.py    # Thin wrapper over the SQLite repository
├── scripts/
│   └── migrate_status_db.py  # Creates the status SQLite tables
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
- **Port mismatch with Chrome extension**: The backend defaults to port `8002`, but the extension defaults to `8000`. Either set `FLASK_PORT=8000` in `.env` before starting the server, or update `SERVER_BASE_URL` in `chrome-extension/popup.js` to `http://localhost:8002`.
- **Applied jobs not showing**: Make sure you're expanding the "Applied" section in the Chrome extension popup. Applied jobs are hidden from the main history by default but appear in the collapsible applied section.

## License

MIT
