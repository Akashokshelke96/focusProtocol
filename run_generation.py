#!/usr/bin/env python
"""
Direct video generation + YouTube upload
No UI, no complexity. Just works.
"""
import os
import sys
import time
import json
import requests
from pathlib import Path
from datetime import datetime, timedelta
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / '.env')

sys.path.insert(0, str(Path(__file__).parent))

from app.config.logging_config import get_logger
from app.youtube.scheduler import YouTubeUploadScheduler
from app.youtube.metadata_generator import YouTubeMetadataGenerator
from app.youtube.thumbnail_generator import ThumbnailGenerator

log = get_logger("video_generator")

API_KEY = os.getenv("TREBLO_API_KEY")
API_BASE = "https://api.treblo.com/v1"

def log_step(msg):
    print(f"\n>>> {msg}")
    log.info(msg)

def generate_music(variation, duration_minutes=30):
    """Generate a single music track using Treblo v3 API"""
    log_step(f"VARIATION {variation}: Generating {duration_minutes}min track...")

    prompt = f"""SLOW 76-80 BPM. Dark, smoky, sophisticated. 2 AM atmosphere.
INSTRUMENTS: Warm tenor saxophone (main) + subtle upright bass. Sparse arrangement.
VOCALS: Occasional deep male baritone, intimate, quietly spoken. Long gaps between vocals.
Phrases: discipline, focus, patience, working alone. Never theatrical.
Create a {duration_minutes}-minute hypnotic dark blues track.
Variation {variation}: {"Saxophone focused" if variation == 1 else "Baritone vocals focused"}"""

    payload = {
        "prompt": prompt,
        "duration": duration_minutes * 60,
        "title": f"Dark Blues - {duration_minutes}min (Var {variation})",
    }

    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json"
    }

    try:
        print(f"  POST {API_BASE}/generations/v3")
        response = requests.post(
            f"{API_BASE}/generations/v3",
            json=payload,
            headers=headers,
            timeout=30
        )
        print(f"  Response: {response.status_code}")

        if response.status_code in [200, 201]:
            data = response.json()
            task_id = data.get("task_id")
            print(f"  Task ID: {task_id}")
            return task_id
        else:
            print(f"  ERROR: {response.text[:200]}")
            return None
    except Exception as e:
        print(f"  Exception: {e}")
        return None


def poll_status(task_id, max_wait_minutes=120):
    """Poll Treblo API until generation completes"""
    log_step(f"Waiting for generation {task_id[:16]}... (max {max_wait_minutes}min)")

    headers = {"Authorization": f"Bearer {API_KEY}"}
    start = time.time()
    max_seconds = max_wait_minutes * 60
    poll_count = 0

    while time.time() - start < max_seconds:
        try:
            print(f"  Poll #{poll_count+1}...", end=" ", flush=True)
            response = requests.get(
                f"{API_BASE}/generations/{task_id}",
                headers=headers,
                timeout=10
            )

            if response.status_code == 200:
                data = response.json()
                status = data.get("status")
                progress = data.get("progress", 0)
                print(f"Status: {status} ({progress}%)")

                if status == "completed":
                    print("  GENERATION COMPLETE!")
                    return data
                elif status == "failed":
                    print(f"  FAILED: {data.get('error_message', 'Unknown error')}")
                    return None

            poll_count += 1
            time.sleep(10)

        except Exception as e:
            print(f"Error: {e}")
            time.sleep(10)

    print("  TIMEOUT!")
    return None


def download_music(status_data, episode):
    """Download completed music file"""
    log_step(f"Downloading music for episode {episode}...")

    file_url = status_data.get("audio_url") or status_data.get("file_url")
    if not file_url:
        print("  No file URL in response")
        return None

    output_path = Path("output") / "EPISODES" / f"episode_{episode:03d}" / "music.mp3"
    output_path.parent.mkdir(parents=True, exist_ok=True)

    headers = {"Authorization": f"Bearer {API_KEY}"}

    try:
        print(f"  URL: {file_url[:60]}...")
        response = requests.get(file_url, headers=headers, timeout=60, stream=True)

        if response.status_code == 200:
            with open(output_path, "wb") as f:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
            print(f"  Downloaded: {output_path}")
            return output_path
        else:
            print(f"  Download failed: {response.status_code}")
            return None
    except Exception as e:
        print(f"  Exception: {e}")
        return None


def create_metadata_and_thumbnail(episode, duration_minutes):
    """Generate YouTube metadata and thumbnail"""
    log_step(f"Creating metadata & thumbnail for episode {episode}...")

    try:
        gen = YouTubeMetadataGenerator()
        metadata = gen.generate_metadata(
            compilation_id=f"ep_{episode}",
            song_titles=[f"Deep Focus - {duration_minutes}min"],
            total_duration_minutes=duration_minutes,
            episode_number=episode
        )
        print(f"  Title: {metadata.get('title')[:60]}...")

        thumb_gen = ThumbnailGenerator()
        thumbnail = thumb_gen.generate_thumbnail(
            episode_number=episode,
            duration_minutes=duration_minutes,
            title_text=metadata.get("title", "")[:40]
        )
        print(f"  Thumbnail: {thumbnail.name}")

        return metadata, thumbnail
    except Exception as e:
        print(f"  Exception: {e}")
        return None, None


def queue_youtube_upload(episode, duration_minutes):
    """Queue video for YouTube upload"""
    log_step(f"Queueing episode {episode} for YouTube upload...")

    try:
        scheduler = YouTubeUploadScheduler()

        metadata, thumbnail = create_metadata_and_thumbnail(episode, duration_minutes)
        if not metadata:
            print("  Failed to create metadata")
            return None

        job = scheduler.queue_compilation(
            episode_number=episode,
            upload_datetime=datetime.utcnow() + timedelta(hours=1),
            priority="high"
        )

        job["metadata"] = metadata
        job["thumbnail_path"] = str(thumbnail) if thumbnail else None
        job["status"] = "ready_for_upload"

        print(f"  Queued: {metadata.get('title')}")
        print(f"  YouTube: https://youtube.com/watch?v=PENDING_{episode}")

        return job
    except Exception as e:
        print(f"  Exception: {e}")
        return None


def main():
    print("\n" + "="*80)
    print("SILENT DARK BLUES - VIDEO GENERATION & YOUTUBE UPLOAD")
    print("="*80)

    if not API_KEY:
        print("\nERROR: TREBLO_API_KEY not found in .env")
        return False

    print(f"\nAPI Key: {API_KEY[:20]}...")
    print(f"API Base: {API_BASE}")

    # Generate 2 variations (2x 30-minute videos)
    episodes = []

    for var in [1, 2]:
        # Queue generation
        task_id = generate_music(var, duration_minutes=30)
        if not task_id:
            print(f"\nFailed to queue variation {var}")
            continue

        # Wait for completion
        status_data = poll_status(task_id, max_wait_minutes=120)
        if not status_data:
            print(f"\nGeneration failed for variation {var}")
            continue

        # Download
        music_path = download_music(status_data, var)
        if not music_path:
            print(f"\nDownload failed for variation {var}")
            continue

        episodes.append({
            "episode": var,
            "music_path": music_path,
            "duration": 30
        })

    if not episodes:
        print("\nNo episodes generated successfully")
        return False

    print("\n" + "="*80)
    print(f"GENERATED {len(episodes)} EPISODES")
    print("="*80)

    # Upload to YouTube
    uploads = []
    for ep in episodes:
        job = queue_youtube_upload(ep["episode"], ep["duration"])
        if job:
            uploads.append(job)

    print("\n" + "="*80)
    print(f"SUCCESS: {len(uploads)} VIDEOS QUEUED FOR YOUTUBE UPLOAD")
    print("="*80)
    print("\nEpisodes:")
    for ep in episodes:
        print(f"  - Episode {ep['episode']}: {ep['duration']}min")
    print("\nFiles saved in: output/EPISODES/")
    print("YouTube upload scheduled in: 1 hour")

    return True


if __name__ == "__main__":
    try:
        success = main()
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        print("\n\nCancelled by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n\nFATAL ERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
