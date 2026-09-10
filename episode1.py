#!/usr/bin/env python
"""
Episode 1 Generator - Direct execution
"""
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

from app.config.settings import get_settings, ensure_directories
from app.config.logging_config import setup_logging
from app.pipeline.music_first_orchestrator import MusicFirstOrchestrator


def main():
    """Run Episode 1 generation."""
    ensure_directories()
    setup_logging()

    settings = get_settings()

    # Check required API keys
    missing = settings.validate_required_keys()
    if missing:
        print(f"ERROR: Missing required API keys: {', '.join(missing)}")
        print("Please set these in .env file")
        return 1

    try:
        orchestrator = MusicFirstOrchestrator(settings)
        success = orchestrator.run(duration_minutes=5)  # 5-minute Episode 1
        return 0 if success else 1

    except Exception as e:
        print(f"FAILED: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
