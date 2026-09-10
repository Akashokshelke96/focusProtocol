#!/usr/bin/env python
"""
Jazz Video Generator - Web UI Launcher
Run this to start the dashboard and begin generating videos
"""
import sys
import os
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

from app.config.settings import ensure_directories
from app.config.logging_config import setup_logging, get_logger
from app.api.jazz_api import app

logger = None

def main():
    """Start the Jazz Video Generator web UI."""
    global logger

    # Setup
    ensure_directories()
    from app.studio.api import service
    service.start()
    logger = setup_logging()

    print("\n" + "="*70)
    print("JAZZ VIDEO GENERATOR - WEB UI")
    print("="*70)
    port = int(os.getenv("JAZZ_PORT", "5001"))
    print("\n[OK] Starting web server...")
    print(f"[OK] Dashboard available at: http://localhost:{port}")
    print("[OK] Press Ctrl+C to stop\n")

    # Start a small production WSGI server when installed. This avoids the
    # development-server warning and remains lightweight on Windows.
    try:
        try:
            from waitress import serve
            serve(app, host='127.0.0.1', port=port, threads=8)
        except ImportError:
            logger.warning("Waitress is unavailable; using Flask's local server")
            app.run(debug=False, host='127.0.0.1', port=port, use_reloader=False)
    except KeyboardInterrupt:
        print("\n\nShutting down...")
        sys.exit(0)
    except Exception as e:
        logger.error(f"Failed to start web UI: {e}", exc_info=True)
        sys.exit(1)

if __name__ == "__main__":
    main()
