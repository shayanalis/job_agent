#!/usr/bin/env python3
"""Main entry point for Resume Agent System."""

import sys
import os

# Add src to Python path
sys.path.insert(0, os.path.join(os.path.dirname(__file__)))

from src.api.server import run_server

if __name__ == '__main__':
    print("=" * 60)
    print("Resume Agent System - Starting Server")
    print("=" * 60)
    print("\nEndpoints:")
    print("  POST /generate-resume - Generate tailored resume")
    print("  GET  /health         - Health check")
    print("  GET  /test-drive     - Test Google Drive connection")
    print("  POST /test-llm       - Test LLM service")
    print("\n" + "=" * 60)

    run_server()
