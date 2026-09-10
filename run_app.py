#!/usr/bin/env python
"""
Run Flask application with proper initialization
"""
import os
import sys
from pathlib import Path

# Fix encoding for Windows
os.environ['PYTHONIOENCODING'] = 'utf-8'

# Add project root to path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

# Set environment
os.environ['FLASK_ENV'] = 'production'
os.environ['FLASK_DEBUG'] = '0'

from app.api.web_app import app, init_app

if __name__ == '__main__':
    print("=" * 80)
    print("Silent Dark Blues - YouTube Automation System")
    print("=" * 80)
    print()
    print("Initializing application...")
    init_app()
    print("[OK] Application initialized")
    print()
    print("=" * 80)
    print("WEB APPLICATION RUNNING")
    print("=" * 80)
    print()
    print("Access the dashboard at:")
    print("  * http://localhost:5000")
    print("  * http://127.0.0.1:5000")
    print("  * http://192.168.1.8:5000 (network access)")
    print()
    print("Pages:")
    print("  * Dashboard:      http://localhost:5000/")
    print("  * Schedule:       http://localhost:5000/schedule")
    print("  * Metadata:       http://localhost:5000/metadata")
    print("  * Health Check:   http://localhost:5000/health")
    print()
    print("API Endpoints:")
    print("  * GET  /api/health           - Full health check")
    print("  * GET  /api/schedule/status  - Queue statistics")
    print("  * POST /api/metadata/generate - Generate metadata")
    print("  * POST /api/thumbnail/generate - Generate thumbnail")
    print()
    print("=" * 80)
    print()

    app.run(debug=False, host='0.0.0.0', port=5000, threaded=True)

