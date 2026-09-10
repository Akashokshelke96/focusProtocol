#!/usr/bin/env python
"""
Direct Dark Blues Video Generator & YouTube Uploader
Generates 2x 30-minute hypnotic dark blues videos and uploads to YouTube
NO WEB UI - DIRECT EXECUTION
"""
import os
import sys
from pathlib import Path
from datetime import datetime, timedelta
from dotenv import load_dotenv

# Load environment
load_dotenv(Path(__file__).parent / '.env')

sys.path.insert(0, str(Path(__file__).parent))

from app.config.logging_config import setup_logging, get_logger
from app.providers.treblo import TrebloProvider, create_dark_blues_prompt
from app.youtube.scheduler import YouTubeUploadScheduler
from app.youtube.metadata_generator import YouTubeMetadataGenerator
from app.youtube.thumbnail_generator import ThumbnailGenerator

logger = setup_logging()
log = get_logger("direct_uploader")


def generate_dark_blues_track(treblo: TrebloProvider, variation: int, duration_minutes: int = 30):
    """Generate a single 30-minute dark blues track."""
    log.info("")
    log.info("=" * 80)
    log.info(f"[STEP] GENERATING VARIATION {variation} ({duration_minutes} minutes)")
    log.info("=" * 80)

    prompt = f"""
SLOW 76–80 BPM. Dark, smoky, sophisticated, masculine and calm. 2 AM atmosphere — rain outside, dim room, black coffee, one person working alone with complete focus.

INSTRUMENTS: ONLY 1–3. Warm, breathy tenor saxophone as the main instrument, with a very subtle upright bass underneath. Extremely sparse arrangement.

VOCALS: Occasional deep male baritone, quietly spoken and intimate, with long instrumental gaps. Short, intelligent phrases about discipline, focus, patience and working alone. Never theatrical or motivational.

Create a {duration_minutes}-minute hypnotic dark blues composition. Variation {variation}: {"Emphasize saxophone with minimal drums" if variation == 1 else "Deep baritone vocals focus, intimate spoken delivery" if variation == 2 else "Late-night noir blues, hypnotic groove, minimal movement"}
"""

    result = treblo.generate_music(
        prompt=prompt,
        duration_seconds=duration_minutes * 60,
        title=f"Deep Focus - {duration_minutes}min (Variation {variation})",
        style="dark_blues"
    )

    if result.get("status") == "queued":
        log.info(f"✓ Generation queued: {result['generation_id']}")
        return result["generation_id"]
    else:
        log.error(f"✗ Generation failed: {result.get('message')}")
        return None


def wait_for_music(treblo: TrebloProvider, gen_id: str, max_wait_minutes: int = 30):
    """Wait for music generation to complete."""
    log.info(f"Waiting for generation {gen_id[:20]}... (max {max_wait_minutes} min)")

    import time
    start = time.time()
    max_seconds = max_wait_minutes * 60

    while time.time() - start < max_seconds:
        status = treblo.get_generation_status(gen_id)

        if status.get("status") == "completed":
            log.info(f"✓ COMPLETED: {status.get('progress')}%")
            return status

        elif status.get("status") == "failed":
            log.error(f"✗ FAILED: {status.get('error')}")
            return None

        progress = status.get("progress", 0)
        log.info(f"  Status: {status.get('status')} ({progress}%)")
        time.sleep(30)  # Check every 30 seconds

    log.error("✗ TIMEOUT")
    return None


def download_and_save(treblo: TrebloProvider, status: dict, episode: int):
    """Download completed music and save to episode folder."""
    file_url = status.get("file_url")
    if not file_url:
        log.error("No file URL in completion status")
        return None

    output_path = Path("output") / "EPISODES" / f"episode_{episode:03d}" / "music.mp3"
    output_path.parent.mkdir(parents=True, exist_ok=True)

    log.info(f"Downloading to {output_path}")
    if treblo.download_music(file_url, output_path):
        log.info(f"✓ Saved: {output_path}")
        return output_path
    else:
        log.error("✗ Download failed")
        return None


def generate_metadata_and_thumbnail(episode: int, duration_minutes: int):
    """Generate YouTube metadata and thumbnail."""
    log.info("")
    log.info("Generating metadata & thumbnail...")

    gen = YouTubeMetadataGenerator()
    metadata = gen.generate_metadata(
        compilation_id=f"ep_{episode}",
        song_titles=[f"Deep Focus - Part {episode}"],
        total_duration_minutes=duration_minutes,
        episode_number=episode
    )

    thumb_gen = ThumbnailGenerator()
    thumbnail = thumb_gen.generate_thumbnail(
        episode_number=episode,
        duration_minutes=duration_minutes,
        title_text=metadata.get("title", "")[:40]
    )

    log.info(f"✓ Metadata: {metadata.get('title')}")
    log.info(f"✓ Thumbnail: {thumbnail}")

    return metadata, thumbnail


def upload_to_youtube(episode: int, duration_minutes: int):
    """Queue video for YouTube upload."""
    log.info("")
    log.info("=" * 80)
    log.info(f"UPLOADING EPISODE {episode} TO YOUTUBE ({duration_minutes} min)")
    log.info("=" * 80)

    scheduler = YouTubeUploadScheduler()

    # Generate metadata & thumbnail
    metadata, thumbnail = generate_metadata_and_thumbnail(episode, duration_minutes)

    # Queue for upload
    job = scheduler.queue_compilation(
        episode_number=episode,
        upload_datetime=datetime.utcnow() + timedelta(hours=1),  # Upload in 1 hour
        priority="high"
    )

    # Update job with metadata
    job["metadata"] = metadata
    job["thumbnail_path"] = str(thumbnail)
    job["status"] = "ready_for_upload"

    log.info(f"✓ Queued episode {episode} for upload")
    log.info(f"  Title: {metadata.get('title')}")
    log.info(f"  YouTube URL: https://youtube.com/watch?v=pending_{episode}")

    return job


def main():
    """Main execution: Generate 2x 30-min videos and upload to YouTube."""
    log.info("")
    log.info("=" * 80)
    log.info("SILENT DARK BLUES - DIRECT VIDEO GENERATOR & YOUTUBE UPLOADER")
    log.info("=" * 80)
    log.info("")

    # Check API key
    api_key = os.getenv("TREBLO_API_KEY")
    if not api_key:
        log.error("[ERROR] TREBLO_API_KEY not found in .env")
        log.error("  Add: TREBLO_API_KEY=your_key_here")
        return False

    log.info("[OK] Treblo API key found")
    log.info("")

    treblo = TrebloProvider()

    # Generate 2 variations (2x 30-minute videos)
    variations = []

    for var_num in [1, 2]:
        log.info(f"[STEP {var_num}] Generate variation {var_num}...")
        gen_id = generate_dark_blues_track(treblo, var_num, duration_minutes=30)

        if not gen_id:
            log.error(f"✗ Failed to queue variation {var_num}")
            return False

        # Wait for completion
        status = wait_for_music(treblo, gen_id, max_wait_minutes=60)

        if not status:
            log.error(f"✗ Music generation failed for variation {var_num}")
            return False

        # Download
        music_path = download_and_save(treblo, status, var_num)

        if not music_path:
            log.error(f"✗ Download failed for variation {var_num}")
            return False

        variations.append({
            "episode": var_num,
            "music_path": music_path,
            "duration_minutes": 30
        })

    log.info("")
    log.info("=" * 80)
    log.info("BOTH VARIATIONS GENERATED SUCCESSFULLY!")
    log.info("=" * 80)
    log.info("")

    # Upload both to YouTube
    for var in variations:
        log.info(f"[UPLOAD {var['episode']}] Queuing for YouTube...")
        upload_to_youtube(var["episode"], var["duration_minutes"])

    log.info("")
    log.info("╔" + "=" * 78 + "╗")
    log.info("║" + "SUCCESS! 2x 30-MINUTE VIDEOS GENERATED & QUEUED FOR UPLOAD".center(78) + "║")
    log.info("╚" + "=" * 78 + "╝")
    log.info("")
    log.info("Episodes queued:")
    log.info("  • Episode 1: 30 minutes (Saxophone-focused)")
    log.info("  • Episode 2: 30 minutes (Vocals-focused)")
    log.info("")
    log.info("Videos will auto-upload with YouTube metadata & thumbnails")
    log.info("")

    return True


if __name__ == "__main__":
    try:
        success = main()
        sys.exit(0 if success else 1)
    except Exception as e:
        log.error(f"✗ Fatal error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
