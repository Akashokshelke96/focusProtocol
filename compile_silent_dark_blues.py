#!/usr/bin/env python
"""
Silent Dark Blues - 20-Minute Compilation Pipeline
Full end-to-end execution
"""
import sys
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / '.env')
sys.path.insert(0, str(Path(__file__).parent))

from app.config.logging_config import setup_logging, get_logger
from app.pipeline.silent_dark_blues_compiler import SilentDarkBluesCompiler

logger = None


def main():
    """Run complete compilation pipeline."""
    global logger
    logger = setup_logging()

    try:
        compiler = SilentDarkBluesCompiler()
        result = compiler.run()

        if result["status"] == "success":
            logger.info("")
            logger.info("SUCCESS!")
            logger.info(f"Final video: {result['final_video']}")
            logger.info(f"Duration: {result['total_duration_minutes']:.1f} minutes")
            logger.info(f"Videos in mega library: {result['videos_generated']}")
            logger.info("")
            return 0
        else:
            logger.error(f"Pipeline failed: {result.get('reason', result.get('error', 'Unknown error'))}")
            return 1

    except Exception as e:
        logger.error(f"Failed: {e}", exc_info=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
