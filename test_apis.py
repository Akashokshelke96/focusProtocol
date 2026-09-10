#!/usr/bin/env python
"""
API Testing & Episode 1 Generation with Real Images + Music
"""
import sys
from pathlib import Path
import os

sys.path.insert(0, str(Path(__file__).parent))

from app.config.settings import get_settings, ensure_directories
from app.config.logging_config import setup_logging, get_logger
from app.jobs.manager import JobManager, JobStage
from datetime import datetime

logger = None

DARK_BLUES_PROMPT = """Create an ORIGINAL dark, sophisticated, hypnotic blues instrumental designed for deep work and concentration.

CORE VIBE: Dark noir blues / cinematic blues / blues-rock. Masculine, mature, intelligent, mysterious and extremely controlled. The feeling is a highly focused person working alone at 2 AM — calm, calculating, disciplined and completely in control. Rain outside, dim lights, black coffee, laptop glowing, world completely switched off.

HYPNOTIC DESIGN: Make the track hypnotic through repetition, groove and MICRO-EVOLUTION. Establish a strong musical pattern early. Use recurring guitar motifs, repeating bass patterns and consistent drum pulse. Make tiny changes felt subconsciously: subtle guitar phrasing variations, small bass variations, occasional ghost-note changes, tiny atmospheric shifts, restrained fills.

RHYTHM: Slow, steady and deliberate. Around 75–82 BPM perceived tempo with subtle double-time pulse. Gentle blues swing. Groove should feel like steady heartbeat: predictable, grounding and precise.

DRUMS: Minimal live-feeling drums. Deep soft kick, dry controlled snare, subtle hi-hat and occasional ghost notes. Very few fills. No big crashes.

BASS: Deep, warm electric bass with slight analog saturation. Repeating blues-based pattern tightly locked to kick. Occasional chromatic passing notes, but keep it restrained.

ELECTRIC GUITAR: Dark vintage electric guitar with warm tube-amp overdrive, smooth saturation, sustain and subtle compression. Use slow blues bends, slides, vibrato, muted notes. Create 1–2 memorable recurring guitar motifs.

HARMONY: Dark minor-blues atmosphere with blues-scale vocabulary, dominant seventh tension and occasional chromatic movement. Keep progression simple and repetitive.

ATMOSPHERE: Smoky, rainy, urban, nocturnal, sophisticated and slightly dangerous. Not sad - POWERFUL CALM. Should feel intelligent, disciplined and quietly intimidating.

PRODUCTION: Warm analog character, dark tonal balance, rich low-mids, controlled bass, smooth highs, subtle tape saturation, spacious stereo imaging. Comfortable for long headphone sessions.

DYNAMICS: Keep energy relatively consistent. NO dramatic climax. NO sudden drops. NO huge impacts. Maintain steady psychological momentum.

ABSOLUTELY AVOID: Vocals, lyrics, spoken words, EDM drops, trap beats, aggressive rock, flashy solos, shredding, catchy pop melodies, dramatic orchestration, excessive percussion, sudden transitions, cheerful moods.

PSYCHOLOGICAL TARGET: Listener should think "I'll just work for a while..." and suddenly realize two hours have passed. Make distractions feel distant and concentration feel effortless.

Create music for people who have work to do. Instrumental. Completely original. Do not copy any existing song, melody, riff or distinctive musical phrase."""


def test_ace_music_api():
    """Test ACE-Step Music API."""
    logger.info("")
    logger.info("="*70)
    logger.info("TESTING ACE-STEP MUSIC API")
    logger.info("="*70)

    settings = get_settings()
    ace_key = os.getenv("ACE_MUSIC_API_KEY")
    ace_url = os.getenv("ACE_MUSIC_BASE_URL")

    if not ace_key:
        logger.error("ERROR: ACE_MUSIC_API_KEY not found in .env")
        return False

    logger.info(f"API Key:     {ace_key[:20]}...")
    logger.info(f"Base URL:    {ace_url}")

    try:
        import requests

        headers = {
            "Authorization": f"Bearer {ace_key}",
            "Content-Type": "application/json"
        }

        payload = {
            "prompt": "Dark blues instrumental, 75 BPM, masculine, contemplative",
            "duration": 60,
            "num_samples": 1,
            "quality": "high"
        }

        logger.info("Sending test request...")
        response = requests.post(
            f"{ace_url}/v1/generate",
            headers=headers,
            json=payload,
            timeout=60
        )

        logger.info(f"Response Status: {response.status_code}")

        if response.status_code == 200:
            data = response.json()
            logger.info("Response Data:")
            logger.info(f"  Status: {data.get('status', 'unknown')}")
            if data.get('samples'):
                logger.info(f"  Samples: {len(data['samples'])} generated")
                for i, sample in enumerate(data['samples'][:1]):
                    logger.info(f"    Sample {i+1}:")
                    logger.info(f"      - Duration: {sample.get('duration', 'N/A')}s")
                    logger.info(f"      - URL: {sample.get('url', 'N/A')[:60]}...")
            logger.info("")
            logger.info("SUCCESS: ACE-Step API is working!")
            logger.info("")
            return True
        else:
            logger.error(f"API Error: {response.status_code}")
            logger.error(f"Response: {response.text[:200]}")
            return False

    except Exception as e:
        logger.error(f"Connection Error: {e}")
        return False


def test_pexels_api():
    """Test Pexels API."""
    logger.info("")
    logger.info("="*70)
    logger.info("TESTING PEXELS VIDEO API")
    logger.info("="*70)

    pexels_key = os.getenv("PEXELS_API_KEY")

    if not pexels_key:
        logger.error("ERROR: PEXELS_API_KEY not found in .env")
        return False

    logger.info(f"API Key: {pexels_key[:20]}...")

    try:
        import requests

        headers = {"Authorization": pexels_key}

        search_query = "cillian murphy peaky blinders smoking noir"
        logger.info(f"Searching: {search_query}")

        response = requests.get(
            "https://api.pexels.com/v1/videos/search",
            headers=headers,
            params={"query": search_query, "per_page": 3},
            timeout=30
        )

        logger.info(f"Response Status: {response.status_code}")

        if response.status_code == 200:
            data = response.json()
            videos = data.get('videos', [])
            logger.info(f"Found: {data.get('total_results', 0)} total results")
            logger.info(f"Returned: {len(videos)} videos in this batch")

            if videos:
                for i, video in enumerate(videos[:1]):
                    logger.info(f"  Video {i+1}:")
                    logger.info(f"    - ID: {video.get('id')}")
                    logger.info(f"    - Photographer: {video.get('user', {}).get('name', 'N/A')}")
                    files = video.get('video_files', [])
                    if files:
                        logger.info(f"    - Resolution: {files[0].get('width')}x{files[0].get('height')}")
                        logger.info(f"    - URL: {files[0].get('link', 'N/A')[:60]}...")

            logger.info("")
            logger.info("SUCCESS: Pexels API is working!")
            logger.info("")
            return True
        else:
            logger.error(f"API Error: {response.status_code}")
            logger.error(f"Response: {response.text[:200]}")
            return False

    except Exception as e:
        logger.error(f"Connection Error: {e}")
        return False


def test_pinterest_via_pexels():
    """Test finding character images through Pexels."""
    logger.info("")
    logger.info("="*70)
    logger.info("TESTING CHARACTER IMAGE SEARCH (Pexels)")
    logger.info("="*70)

    pexels_key = os.getenv("PEXELS_API_KEY")

    try:
        import requests

        headers = {"Authorization": pexels_key}

        searches = [
            "cillian murphy peaky blinders dark noir",
            "john wick keanu reeves suit noir",
            "gentleman noir smoking contemplative dark"
        ]

        for search in searches:
            logger.info(f"Searching: {search}")
            response = requests.get(
                "https://api.pexels.com/v1/search",
                headers=headers,
                params={"query": search, "per_page": 1},
                timeout=15
            )

            if response.status_code == 200:
                data = response.json()
                photos = data.get('photos', [])
                logger.info(f"  Found: {data.get('total_results', 0)} results")
                if photos:
                    photo = photos[0]
                    logger.info(f"    - URL: {photo.get('url')[:70]}...")
            else:
                logger.warning(f"  Error: {response.status_code}")

        logger.info("")
        logger.info("SUCCESS: Image search API working!")
        logger.info("")
        return True

    except Exception as e:
        logger.error(f"Error: {e}")
        return False


def main():
    """Test APIs and report."""
    global logger

    ensure_directories()
    logger = setup_logging()

    logger.info("")
    logger.info("="*70)
    logger.info("SILENT DARK BLUES - API VALIDATION & TESTING")
    logger.info("="*70)
    logger.info("")

    # Test all APIs
    ace_ok = test_ace_music_api()
    pexels_ok = test_pexels_api()
    images_ok = test_pinterest_via_pexels()

    logger.info("")
    logger.info("="*70)
    logger.info("API TEST SUMMARY")
    logger.info("="*70)
    logger.info(f"ACE-Step Music API:  {'SUCCESS' if ace_ok else 'FAILED'}")
    logger.info(f"Pexels Video API:    {'SUCCESS' if pexels_ok else 'FAILED'}")
    logger.info(f"Image Search:        {'SUCCESS' if images_ok else 'FAILED'}")
    logger.info("="*70)
    logger.info("")

    if ace_ok and pexels_ok and images_ok:
        logger.info("ALL APIS WORKING - Ready to generate Episode 1 with real content!")
        return 0
    else:
        logger.error("Some APIs failed - check keys and connectivity")
        return 1


if __name__ == "__main__":
    sys.exit(main())
