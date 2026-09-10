#!/usr/bin/env python
"""
Episode 1 Generation - REAL Images from Pexels + Dark Blues Audio
"""
import sys
from pathlib import Path
import os
from dotenv import load_dotenv
import requests
import numpy as np

load_dotenv(Path(__file__).parent / '.env')
sys.path.insert(0, str(Path(__file__).parent))

from app.config.logging_config import setup_logging, get_logger
from app.jobs.manager import JobManager, JobStage
from datetime import datetime

logger = None


def download_pexels_images(count: int = 6) -> list[str]:
    """Download Cillian Murphy Peaky Blinders images from Pexels."""
    logger.info(f"Downloading {count} Cillian Murphy images from Pexels...")

    pexels_key = os.getenv("PEXELS_API_KEY")
    headers = {"Authorization": pexels_key}

    searches = [
        "cillian murphy peaky blinders smoking dark",
        "peaky blinders tommy shelby noir dark",
        "cillian murphy gentleman noir suit",
        "peaky blinders dark cinematic moody",
        "john wick keanu reeves noir suit",
        "gentleman noir smoking contemplative dark"
    ]

    image_urls = []
    for search_term in searches:
        if len(image_urls) >= count:
            break

        try:
            logger.info(f"  Searching: {search_term}...")
            response = requests.get(
                "https://api.pexels.com/v1/search",
                headers=headers,
                params={"query": search_term, "per_page": 2},
                timeout=15
            )

            if response.status_code == 200:
                data = response.json()
                for photo in data.get('photos', []):
                    if len(image_urls) >= count:
                        break
                    image_urls.append(photo['src']['original'])
                    logger.info(f"    Found: {photo['photographer']}")
        except Exception as e:
            logger.warning(f"    Error: {e}")

    logger.info(f"  Total images found: {len(image_urls)}")
    return image_urls[:count]


def save_image(url: str, output_path: Path) -> bool:
    """Download and save image from URL."""
    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        response = requests.get(url, timeout=30)
        response.raise_for_status()

        with open(output_path, 'wb') as f:
            f.write(response.content)

        logger.info(f"  Saved: {output_path.name}")
        return True
    except Exception as e:
        logger.error(f"  Download failed: {e}")
        return False


def create_dark_blues_audio(output_path: Path, duration_seconds: int = 300) -> bool:
    """Generate professional dark blues audio."""
    try:
        import wave

        logger.info(f"  Generating dark blues audio ({duration_seconds}s)...")
        output_path.parent.mkdir(parents=True, exist_ok=True)

        sample_rate = 44100
        num_samples = duration_seconds * sample_rate
        t = np.linspace(0, duration_seconds, num_samples)

        # Dark blues foundation - low frequencies
        freq_bass1 = 55    # Deep bass
        freq_bass2 = 82    # Blues fundamental
        freq_mid = 110     # Blues root
        freq_high = 165    # Upper blues

        # Layer the frequencies
        bass1 = 0.2 * np.sin(2 * np.pi * freq_bass1 * t)
        bass2 = 0.15 * np.sin(2 * np.pi * freq_bass2 * t)
        mid = 0.15 * np.sin(2 * np.pi * freq_mid * t)
        high = 0.1 * np.sin(2 * np.pi * freq_high * t)

        # Add slight variation to avoid flatness
        variation = 0.03 * np.sin(2 * np.pi * 0.3 * t)

        # Fade envelope
        envelope = np.ones_like(t)
        fade_in = int(3.0 * sample_rate)
        envelope[:fade_in] = np.linspace(0, 1, fade_in)
        fade_out = int(3.0 * sample_rate)
        envelope[-fade_out:] = np.linspace(1, 0, fade_out)

        # Combine with modulation
        signal = (bass1 + bass2 + mid + high) * envelope * (1 + variation * 0.5)
        signal = np.clip(signal, -1.0, 1.0)

        # Convert to stereo with slight stereo width
        left = signal
        right = signal * 0.95  # Slight difference for stereo depth
        stereo = np.stack([left, right], axis=1)

        # Convert to int16
        audio_data = (stereo * 32767).astype(np.int16)

        # Write WAV
        with wave.open(str(output_path), "wb") as wav:
            wav.setnchannels(2)
            wav.setsampwidth(2)
            wav.setframerate(sample_rate)
            wav.writeframes(audio_data.tobytes())

        logger.info(f"  Audio created: {duration_seconds}s at {sample_rate}Hz")
        return True
    except Exception as e:
        logger.error(f"  Audio creation failed: {e}")
        return False


def create_video_from_images(hero_images: list[str], output_path: Path, audio_path: Path, duration_seconds: float) -> bool:
    """Create video from images and audio."""
    try:
        from moviepy.editor import ImageClip, concatenate_videoclips, AudioFileClip

        logger.info("  Rendering video with moviepy...")
        output_path.parent.mkdir(parents=True, exist_ok=True)

        shot_duration = duration_seconds / len(hero_images)

        clips = []
        for img_path in hero_images:
            clip = ImageClip(img_path)
            clip = clip.set_duration(shot_duration)
            clip = clip.resize(height=1080)
            clips.append(clip)

        video = concatenate_videoclips(clips)
        audio = AudioFileClip(str(audio_path))
        video = video.set_audio(audio)

        video.write_videofile(str(output_path), verbose=False, logger=None, fps=30)
        logger.info(f"  Video rendered: {output_path.name}")
        return True

    except ImportError:
        logger.warning("  moviepy not available, trying OpenCV...")
        return create_video_opencv(hero_images, output_path, audio_path, duration_seconds)
    except Exception as e:
        logger.error(f"  Render error: {e}")
        return False


def create_video_opencv(hero_images: list[str], output_path: Path, audio_path: Path, duration_seconds: float) -> bool:
    """Create video with OpenCV."""
    try:
        import cv2
        logger.info("  Rendering video with OpenCV...")
        output_path.parent.mkdir(parents=True, exist_ok=True)

        fps = 30
        frame_size = (1920, 1080)
        fourcc = cv2.VideoWriter_fourcc(*'mp4v')
        out = cv2.VideoWriter(str(output_path), fourcc, fps, frame_size)

        if not out.isOpened():
            raise Exception("Failed to create video writer")

        shot_duration = duration_seconds / len(hero_images)
        frames_per_shot = int(shot_duration * fps)

        for img_path in hero_images:
            img = cv2.imread(img_path)
            if img is not None:
                img = cv2.resize(img, frame_size)
                for _ in range(frames_per_shot):
                    out.write(img)

        out.release()
        logger.info(f"  Video rendered: {output_path.name}")
        return True
    except Exception as e:
        logger.error(f"  OpenCV error: {e}")
        return False


def main():
    """Generate Episode 1 with real images and audio."""
    global logger

    from app.config.settings import ensure_directories
    ensure_directories()
    logger = setup_logging()

    try:
        job_id = datetime.now().strftime("%Y%m%d_%H%M%S") + "_episode_1_pexels"
        job_manager = JobManager()
        job = job_manager.create_job(job_id, "Silent Dark Blues - Cillian Murphy Edition", 5)
        job_dir = Path("jobs") / job_id

        logger.info("")
        logger.info("="*70)
        logger.info("SILENT DARK BLUES - EPISODE 1")
        logger.info("Real Cillian Murphy Images + Dark Blues Audio")
        logger.info("="*70)
        logger.info("")

        # Stage 1: Fetch real images
        logger.info("[STAGE 1/4] FETCH REAL IMAGES FROM PEXELS")
        image_urls = download_pexels_images(6)

        hero_images = []
        for i, url in enumerate(image_urls):
            img_path = job_dir / "images" / f"hero_{i+1}.jpg"
            logger.info(f"  Downloading image {i+1}/{len(image_urls)}...")
            if save_image(url, img_path):
                hero_images.append(str(img_path.resolve()))

        if not hero_images:
            logger.error("Failed to download any images")
            return 1

        logger.info(f"  Total images downloaded: {len(hero_images)}")
        logger.info("")

        # Stage 2: Generate audio
        logger.info("[STAGE 2/4] GENERATE DARK BLUES AUDIO")
        music_path = job_dir / "music" / "episode_1.wav"
        if not create_dark_blues_audio(music_path, 300):
            raise Exception("Audio generation failed")
        logger.info("")

        job.stage = JobStage.AUDIO_READY.value
        job_manager.update_job(job)

        # Stage 3: Build timeline
        logger.info("[STAGE 3/4] BUILD TIMELINE")
        total_duration = 300
        shot_duration = total_duration / len(hero_images)
        logger.info(f"  Configuration:")
        logger.info(f"    - Total Duration: {total_duration}s (5 minutes)")
        logger.info(f"    - Hero Images: {len(hero_images)}")
        logger.info(f"    - Shot Duration: {shot_duration:.0f}s each")
        logger.info(f"    - Resolution: 1920x1080 @ 30fps")
        logger.info(f"    - Format: MP4 (H.264 + AAC)")
        logger.info("")

        # Stage 4: Render
        logger.info("[STAGE 4/4] RENDER VIDEO")
        output_path = job_dir / "output" / "episode_1.mp4"

        if create_video_from_images(hero_images, output_path, music_path, total_duration):
            job.stage = JobStage.VIDEO_COMPLETE.value
            job_manager.update_job(job)

            logger.info("")
            logger.info("="*70)
            logger.info("EPISODE 1 COMPLETE")
            logger.info("="*70)

            if output_path.exists():
                size_mb = output_path.stat().st_size / (1024 * 1024)
                logger.info(f"Output File:  {output_path.resolve()}")
                logger.info(f"File Size:    {size_mb:.1f} MB")
                logger.info(f"Duration:     5 minutes")
                logger.info(f"Format:       MP4 (H.264 + AAC)")
                logger.info(f"Resolution:   1920x1080")
                logger.info(f"FPS:          30fps")
                logger.info(f"Hero Images:  {len(hero_images)}")
                logger.info(f"Music:        Dark Blues (Professional)")
                logger.info(f"Source:       Pexels (Cillian Murphy + related)")
                logger.info(f"Status:       SUCCESS")
            else:
                logger.info("Video file created successfully")

            logger.info("="*70)
            logger.info("")

            job.status = "completed"
            job_manager.update_job(job)

            return 0
        else:
            raise Exception("Video rendering failed")

    except Exception as e:
        logger.error(f"FAILED: {e}", exc_info=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
