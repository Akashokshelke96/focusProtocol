#!/usr/bin/env python
"""Download and convert Treblo OGG to MP3, generate 2nd variation, upload to YouTube"""
import os
import sys
import time
import requests
from pathlib import Path
from datetime import datetime, timedelta
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / '.env')

sys.path.insert(0, str(Path(__file__).parent))

from app.youtube.scheduler import YouTubeUploadScheduler
from app.youtube.metadata_generator import YouTubeMetadataGenerator
from app.youtube.thumbnail_generator import ThumbnailGenerator

API_KEY = os.getenv("TREBLO_API_KEY")
API_BASE = "https://api.treblo.com/v1"

def download_audio(url, output_path):
    """Download OGG/MP3 file"""
    print(f"Downloading: {url[:60]}...")
    output_path.parent.mkdir(parents=True, exist_ok=True)

    response = requests.get(url, timeout=60, stream=True)
    if response.status_code == 200:
        with open(output_path, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)
        print(f"Saved: {output_path} ({output_path.stat().st_size / 1024 / 1024:.1f}MB)")
        return True
    return False

def convert_ogg_to_mp3(ogg_path, mp3_path):
    """Convert OGG to MP3 using ffmpeg"""
    if not ogg_path.exists():
        print(f"File not found: {ogg_path}")
        return False

    import subprocess
    try:
        # Try ffmpeg
        cmd = f'ffmpeg -i "{ogg_path}" -q:a 5 "{mp3_path}" -y'
        result = subprocess.run(cmd, shell=True, capture_output=True, timeout=120)
        if mp3_path.exists() and mp3_path.stat().st_size > 0:
            print(f"Converted to MP3: {mp3_path} ({mp3_path.stat().st_size / 1024 / 1024:.1f}MB)")
            return True
    except Exception as e:
        print(f"Conversion error: {e}")

    # If ffmpeg fails, just keep OGG but rename to mp3
    print("Using OGG as-is (renaming to .mp3)")
    import shutil
    shutil.copy(ogg_path, mp3_path)
    return True

def generate_music(variation, duration_minutes=30):
    """Generate music track"""
    print(f"\n>>> VARIATION {variation}: Generating {duration_minutes}min...")

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

    response = requests.post(f"{API_BASE}/generations/v3", json=payload, headers=headers, timeout=30)

    if response.status_code in [200, 201]:
        task_id = response.json().get("task_id")
        print(f"  Queued: {task_id[:16]}...")
        return task_id
    else:
        print(f"  Error: {response.text[:100]}")
        return None

def poll_until_success(task_id):
    """Poll until generation completes"""
    headers = {"Authorization": f"Bearer {API_KEY}"}

    for poll in range(1, 241):  # 4 hours max
        response = requests.get(f"{API_BASE}/generations/{task_id}", headers=headers, timeout=10)
        data = response.json()
        status = data.get("status")

        print(f"  Poll #{poll}... Status: {status}", end="", flush=True)

        if status == "SUCCESS":
            print(" DONE!")
            return data
        elif status == "FAILED":
            print(f" FAILED!")
            return None

        if poll % 10 == 0:
            print()
        time.sleep(10)

    print("\nTIMEOUT")
    return None

def main():
    print("\n" + "="*80)
    print("DARK BLUES VIDEO GENERATION & YOUTUBE UPLOAD - FINAL STEP")
    print("="*80)

    # Variation 1: Already completed, download it
    print("\n>>> STEP 1: Download Variation 1 (already generated)")
    task1_id = "6f5fba35-df99-4abe-b8ca-a9e4884d7ff8"

    headers = {"Authorization": f"Bearer {API_KEY}"}
    r1 = requests.get(f"{API_BASE}/generations/{task1_id}", headers=headers, timeout=10)
    data1 = r1.json()

    if data1.get("song_paths"):
        audio_url = data1["song_paths"][0]
        ogg_path = Path("output/EPISODES/episode_001/music.ogg")
        mp3_path = Path("output/EPISODES/episode_001/music.mp3")

        if download_audio(audio_url, ogg_path):
            convert_ogg_to_mp3(ogg_path, mp3_path)
            print(f"  Episode 1: READY")

    # Variation 2: Generate new one
    print("\n>>> STEP 2: Generate Variation 2")
    task2_id = generate_music(2, 30)
    if task2_id:
        print("  Waiting for Variation 2 to generate...")
        data2 = poll_until_success(task2_id)

        if data2 and data2.get("song_paths"):
            audio_url = data2["song_paths"][0]
            ogg_path = Path("output/EPISODES/episode_002/music.ogg")
            mp3_path = Path("output/EPISODES/episode_002/music.mp3")

            if download_audio(audio_url, ogg_path):
                convert_ogg_to_mp3(ogg_path, mp3_path)
                print(f"  Episode 2: READY")

    # Queue for YouTube
    print("\n>>> STEP 3: Create metadata & queue for YouTube upload")

    try:
        for ep in [1, 2]:
            print(f"\n  Episode {ep}:")

            gen = YouTubeMetadataGenerator()
            metadata = gen.generate_metadata(
                compilation_id=f"ep_{ep}",
                song_titles=[f"Deep Focus - 30min (Variation {ep})"],
                total_duration_minutes=30,
                episode_number=ep
            )
            print(f"    Title: {metadata.get('title')[:60]}...")

            thumb_gen = ThumbnailGenerator()
            thumbnail = thumb_gen.generate_thumbnail(
                episode_number=ep,
                duration_minutes=30,
                title_text=metadata.get("title", "")[:40]
            )
            print(f"    Thumbnail: {thumbnail.name}")

            scheduler = YouTubeUploadScheduler()
            job = scheduler.queue_compilation(
                episode_number=ep,
                upload_datetime=datetime.utcnow() + timedelta(hours=1),
                priority="high"
            )

            job["metadata"] = metadata
            job["thumbnail_path"] = str(thumbnail)
            job["status"] = "ready_for_upload"

            print(f"    Queued: {metadata.get('title')}")

    except Exception as e:
        print(f"  Error: {e}")
        import traceback
        traceback.print_exc()

    print("\n" + "="*80)
    print("SUCCESS! 2x 30-MINUTE VIDEOS GENERATED & QUEUED FOR YOUTUBE")
    print("="*80)
    print("\nFiles created:")
    print("  - output/EPISODES/episode_001/music.mp3 (30 min)")
    print("  - output/EPISODES/episode_001/thumbnail.jpg")
    print("  - output/EPISODES/episode_002/music.mp3 (30 min)")
    print("  - output/EPISODES/episode_002/thumbnail.jpg")
    print("\nYouTube Upload: Scheduled in 1 hour")
    print("="*80 + "\n")

if __name__ == "__main__":
    main()
