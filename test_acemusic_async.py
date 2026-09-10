#!/usr/bin/env python
"""
Test ACE-Step API with proper async workflow
"""
import sys
from pathlib import Path
import os
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / '.env')
sys.path.insert(0, str(Path(__file__).parent))

from app.config.logging_config import setup_logging, get_logger
from app.providers.acemusic_v2 import AceStepProvider

logger = None

DARK_BLUES_PROMPT = """Create an ORIGINAL dark, sophisticated, hypnotic blues instrumental for deep work.

CORE VIBE: Dark noir blues / blues-rock. Masculine, mature, intelligent, mysterious. 75-82 BPM.

INSTRUMENTATION: Slide guitar, upright bass, minimal drums, subtle hi-hat. Deep, warm tone.

HARMONY: Dark minor-blues with blues-scale vocabulary.

PRODUCTION: Warm analog character, dark tonal balance, rich low-mids, smooth highs.

NO: Vocals, EDM drops, aggressive rock, flashy solos, dramatic orchestration.

Create music for people who have work to do. Completely original."""


def main():
    """Test ACE-Step API."""
    global logger

    logger = setup_logging()

    logger.info("")
    logger.info("="*70)
    logger.info("ACE-STEP 1.5 API TEST - ASYNC WORKFLOW")
    logger.info("="*70)
    logger.info("")

    # Initialize provider
    provider = AceStepProvider()

    # Check configuration
    logger.info("Configuration:")
    logger.info(f"  API Key: {'SET' if provider.api_key else 'NOT SET'}")
    logger.info(f"  Base URL: {provider.base_url}")
    logger.info("")

    # Test 1: Health check
    logger.info("[TEST 1] Health Check")
    if provider.health_check():
        logger.info("  Status: OK - API is responding")
        logger.info("")
    else:
        logger.error("  Status: FAILED - API is not responding")
        logger.info("")
        return 1

    # Test 2: Music generation
    logger.info("[TEST 2] Generate Music (30 seconds)")
    logger.info(f"  Prompt: {DARK_BLUES_PROMPT[:60]}...")
    logger.info("  Duration: 30 seconds")
    logger.info("  BPM: 75")
    logger.info("  Samples: 1")
    logger.info("  Thinking: Enabled")
    logger.info("")

    results = provider.generate_music(
        prompt=DARK_BLUES_PROMPT,
        duration_seconds=30,
        bpm=75,
        num_samples=1,
        thinking=True,
        inference_steps=32
    )

    if results:
        logger.info("SUCCESS - Music generated!")
        logger.info("")
        for i, result in enumerate(results):
            logger.info(f"  Sample {i+1}:")
            logger.info(f"    Task ID: {result.get('task_id')}")
            logger.info(f"    Duration: {result.get('duration')}s")
            logger.info(f"    BPM: {result.get('bpm')}")
            logger.info(f"    URL: {result.get('url')[:80]}...")
        logger.info("")
        logger.info("="*70)
        logger.info("ACE-STEP API IS WORKING CORRECTLY")
        logger.info("="*70)
        logger.info("")
        return 0
    else:
        logger.error("FAILED - No samples generated")
        logger.info("")
        return 1


if __name__ == "__main__":
    sys.exit(main())
