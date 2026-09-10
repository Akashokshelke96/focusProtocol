#!/usr/bin/env python
"""
API Testing - Direct .env reading
"""
import sys
from pathlib import Path
import os
from dotenv import load_dotenv

# Load .env directly
load_dotenv(Path(__file__).parent / '.env')

sys.path.insert(0, str(Path(__file__).parent))

from app.config.logging_config import setup_logging, get_logger

logger = None

DARK_BLUES_PROMPT = """Create an ORIGINAL dark, sophisticated, hypnotic blues instrumental designed for deep work and concentration.

CORE VIBE: Dark noir blues / cinematic blues / blues-rock. Masculine, mature, intelligent, mysterious and extremely controlled.

RHYTHM: Slow, steady and deliberate. Around 75–82 BPM perceived tempo with subtle double-time pulse.

DRUMS: Minimal live-feeling drums. Deep soft kick, dry controlled snare, subtle hi-hat.

BASS: Deep, warm electric bass with analog saturation. Repeating blues-based pattern.

ELECTRIC GUITAR: Dark vintage electric guitar with warm tube-amp overdrive, smooth saturation.

HARMONY: Dark minor-blues atmosphere with blues-scale vocabulary.

PRODUCTION: Warm analog character, dark tonal balance, rich low-mids, smooth highs, subtle tape saturation.

NO: Vocals, EDM drops, aggressive rock, flashy solos, dramatic orchestration.

PSYCHOLOGICAL TARGET: Make distractions feel distant and concentration feel effortless.

Create music for people who have work to do. Instrumental. Completely original."""


def test_ace_music_api():
    """Test ACE-Step Music API."""
    logger.info("")
    logger.info("="*70)
    logger.info("TESTING ACE-STEP MUSIC API")
    logger.info("="*70)

    ace_key = os.getenv("ACE_MUSIC_API_KEY")
    ace_url = os.getenv("ACE_MUSIC_BASE_URL")

    if not ace_key:
        logger.error("ERROR: ACE_MUSIC_API_KEY not found")
        return False

    logger.info(f"API Key: {ace_key[:30]}...")
    logger.info(f"Base URL: {ace_url}")
    logger.info("")

    try:
        import requests

        headers = {
            "Authorization": f"Bearer {ace_key}",
            "Content-Type": "application/json"
        }

        payload = {
            "prompt": "Dark blues instrumental, 75 BPM, 60 seconds",
            "duration": 60,
            "num_samples": 1,
            "quality": "high"
        }

        logger.info("Sending test request to ACE-Step...")
        response = requests.post(
            f"{ace_url}/v1/generate",
            headers=headers,
            json=payload,
            timeout=120
        )

        logger.info(f"Response Status: {response.status_code}")

        if response.status_code in [200, 201]:
            data = response.json()
            logger.info("SUCCESS! ACE-Step API Response:")
            logger.info(f"  Status: {data.get('status', 'processing')}")
            if data.get('samples'):
                logger.info(f"  Samples Generated: {len(data['samples'])}")
                for i, sample in enumerate(data['samples'][:1]):
                    logger.info(f"    Sample {i+1}:")
                    logger.info(f"      Duration: {sample.get('duration', 'N/A')}s")
                    logger.info(f"      ID: {sample.get('id', 'N/A')}")
            if data.get('url'):
                logger.info(f"  Download URL: {data.get('url')[:60]}...")
            logger.info("")
            return True
        else:
            logger.error(f"API Error: {response.status_code}")
            try:
                logger.error(f"Response: {response.json()}")
            except:
                logger.error(f"Response: {response.text[:300]}")
            return False

    except Exception as e:
        logger.error(f"Connection Error: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_pexels_api():
    """Test Pexels API."""
    logger.info("")
    logger.info("="*70)
    logger.info("TESTING PEXELS API")
    logger.info("="*70)

    pexels_key = os.getenv("PEXELS_API_KEY")

    if not pexels_key:
        logger.error("ERROR: PEXELS_API_KEY not found")
        return False

    logger.info(f"API Key: {pexels_key[:30]}...")
    logger.info("")

    try:
        import requests

        headers = {"Authorization": pexels_key}

        # Test with simple search first
        search_query = "cillian murphy peaky blinders"
        logger.info(f"Searching Pexels for: {search_query}")

        response = requests.get(
            "https://api.pexels.com/v1/search",
            headers=headers,
            params={"query": search_query, "per_page": 3},
            timeout=30
        )

        logger.info(f"Response Status: {response.status_code}")

        if response.status_code == 200:
            data = response.json()
            photos = data.get('photos', [])
            logger.info(f"SUCCESS! Found {data.get('total_results', 0)} total results")
            logger.info(f"Returned: {len(photos)} photos")

            if photos:
                for i, photo in enumerate(photos[:1]):
                    logger.info(f"  Photo {i+1}:")
                    logger.info(f"    Photographer: {photo.get('photographer', 'N/A')}")
                    logger.info(f"    Dimensions: {photo.get('width')}x{photo.get('height')}")
                    logger.info(f"    URL: {photo.get('url')[:70]}...")
            logger.info("")
            return True
        else:
            logger.error(f"API Error: {response.status_code}")
            logger.error(f"Response: {response.text[:300]}")
            return False

    except Exception as e:
        logger.error(f"Connection Error: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    """Test APIs and report."""
    global logger

    logger = setup_logging()

    logger.info("")
    logger.info("="*70)
    logger.info("SILENT DARK BLUES - API VALIDATION")
    logger.info("="*70)

    # Print loaded environment
    logger.info("")
    logger.info("Environment Variables Loaded:")
    logger.info(f"  ACE_MUSIC_API_KEY: {'SET' if os.getenv('ACE_MUSIC_API_KEY') else 'NOT SET'}")
    logger.info(f"  ACE_MUSIC_BASE_URL: {'SET' if os.getenv('ACE_MUSIC_BASE_URL') else 'NOT SET'}")
    logger.info(f"  PEXELS_API_KEY: {'SET' if os.getenv('PEXELS_API_KEY') else 'NOT SET'}")
    logger.info("")

    # Test APIs
    ace_ok = test_ace_music_api()
    pexels_ok = test_pexels_api()

    logger.info("")
    logger.info("="*70)
    logger.info("API TEST RESULTS")
    logger.info("="*70)
    logger.info(f"ACE-Step Music API: {'✓ WORKING' if ace_ok else '✗ FAILED'}")
    logger.info(f"Pexels API:         {'✓ WORKING' if pexels_ok else '✗ FAILED'}")
    logger.info("="*70)
    logger.info("")

    if ace_ok and pexels_ok:
        logger.info("SUCCESS! All APIs are working. Ready to generate Episode 1!")
        return 0
    else:
        logger.error("Some APIs failed. Please check your API keys.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
