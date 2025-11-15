"""Centralized configuration management."""

import os
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Base paths
BASE_DIR = Path(__file__).parent.parent
SRC_DIR = BASE_DIR / "src"
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

# API Keys
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

# Google Drive Configuration
GOOGLE_DRIVE_POINTERS_FOLDER_ID = os.getenv("GOOGLE_DRIVE_POINTERS_FOLDER_ID")
GOOGLE_DRIVE_OUTPUT_FOLDER_ID = os.getenv("GOOGLE_DRIVE_OUTPUT_FOLDER_ID")
GOOGLE_CREDENTIALS_PATH = BASE_DIR / "credentials.json"
GOOGLE_TOKEN_PATH = BASE_DIR / "token.json"

# Resume Template - Google Drive Configuration
RESUME_TEMPLATE_DRIVE_ID = os.getenv("RESUME_TEMPLATE_DRIVE_ID")

# Agent Settings
VALIDATION_RETRIES = int(os.getenv("VALIDATION_RETRIES", "2"))
LLM_TEMPERATURE = float(os.getenv("LLM_TEMPERATURE", "0.0"))
# LLM Models
OPENAI_MODEL = "gpt-5"
SCREENING_MODEL = os.getenv("SCREENING_MODEL", "gpt-5-mini")

# Flask Settings
FLASK_PORT = int(os.getenv("FLASK_PORT", "8002"))
FLASK_DEBUG = os.getenv("FLASK_DEBUG", "false").lower() == "true"

# Logging
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

# Database
DEFAULT_DB_PATH = DATA_DIR / "status_snapshots.db"
DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{DEFAULT_DB_PATH}")
