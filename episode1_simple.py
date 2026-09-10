#!/usr/bin/env python
"""
Episode 1 Generator - Simplified Direct Execution
"""
import sys
from pathlib import Path
import numpy as np

sys.path.insert(0, str(Path(__file__).parent))

from app.config.settings import get_settings, ensure_directories
from app.config.logging_config import setup_logging, get_logger
from app.jobs.manager import JobManager, JobStage
from datetime import datetime

logger = None


def generate_mock_music(output_path: Path, duration_seconds: int = 300) -> bool:
    """Generate dark blues mock audio."""
    try:
        import wave

        logger.info(f"  Generating mock audio ({duration_seconds}s)...")
        output_path.parent.mkdir(parents=True, exist_ok=True)

        sample_rate = 44100
        num_samples = duration_seconds * sample_rate
        t = np.linspace(0, duration_seconds, num_samples)

        freq1, freq2, freq3 = 100, 150, 220
        signal1 = 0.1 * np.sin(2 * np.pi * freq1 * t)
        signal2 = 0.05 * np.sin(2 * np.pi * freq2 * t)
        signal3 = 0.08 * np.sin(2 * np.pi * freq3 * t)

        envelope = np.ones_like(t)
        fade_in_samples = int(2.0 * sample_rate)
        envelope[:fade_in_samples] = np.linspace(0, 1, fade_in_samples)
        fade_out_samples = int(2.0 * sample_rate)
        envelope[-fade_out_samples:] = np.linspace(1, 0, fade_out_samples)

        mono_signal = (signal1 + signal2 + signal3) * envelope
        mono_signal = np.clip(mono_signal, -1.0, 1.0)
        stereo_signal = np.repeat(mono_signal[:, np.newaxis], 2, axis=1)
        audio_data = (stereo_signal * 32767).astype(np.int16)

        with wave.open(str(output_path), "wb") as wav_file:
            wav_file.setnchannels(2)
            wav_file.setsampwidth(2)
            wav_file.setframerate(sample_rate)
            wav_file.writeframes(audio_data.tobytes())

        logger.info(f"  ✓ Mock audio created")
        return True
    except Exception as e:
        logger.error(f"Mock audio failed: {e}")
        return False


def create_placeholder_image(output_path: Path, width: int = 1920, height: int = 1080) -> bool:
    """Create dark noir placeholder image."""
    try:
        from PIL import Image, ImageDraw

        output_path.parent.mkdir(parents=True, exist_ok=True)

        img = Image.new("RGB", (width, height), color=(20, 20, 30))
        draw = ImageDraw.Draw(img)

        for y in range(height):
            shade = int(20 + (y / height) * 40)
            draw.line([(0, y), (width, y)], fill=(shade, shade, shade + 20))

        img.save(output_path, "JPEG", quality=95)
        return True
    except Exception as e:
        logger.error(f"Placeholder creation failed: {e}")
        return False


def create_silent_video(
    hero_images: list[str],
    output_path: Path,
    audio_path: Path,
    duration_seconds: float,
) -> bool:
    """Create video using FFmpeg."""
    try:
        import ffmpeg
        import subprocess

        output_path.parent.mkdir(parents=True, exist_ok=True)
        logger.info(f"  Rendering video with FFmpeg...")

        # Calculate shot duration
        shot_duration = duration_seconds / len(hero_images)

        # Create concat demuxer input file
        concat_file = output_path.parent / "concat.txt"
        with open(concat_file, "w") as f:
            for image in hero_images:
                f.write(f"file '{image}'\n")
                f.write(f"duration {shot_duration}\n")

        # Build FFmpeg command
        cmd = [
            "ffmpeg",
            "-y",
            "-f", "concat",
            "-safe", "0",
            "-i", str(concat_file),
            "-i", str(audio_path),
            "-c:v", "libx264",
            "-pix_fmt", "yuv420p",
            "-c:a", "aac",
            "-b:a", "192k",
            "-shortest",
            str(output_path),
        ]

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)

        if result.returncode == 0:
            logger.info(f"  ✓ Video rendered")
            return True
        else:
            logger.error(f"FFmpeg error: {result.stderr}")
            return False

    except Exception as e:
        logger.error(f"Video creation failed: {e}")
        return False


def main():
    """Run Episode 1."""
    global logger

    ensure_directories()
    logger = setup_logging()

    settings = get_settings()

    missing = settings.validate_required_keys()
    if missing:
        logger.error(f"Missing API keys: {', '.join(missing)}")
        return 1

    try:
        job_id = datetime.now().strftime("%Y%m%d_%H%M%S") + "_episode_1"
        job_manager = JobManager()
        job = job_manager.create_job(job_id, "Silent Dark Blues Episode 1", 5)
        job_dir = Path("jobs") / job_id

        logger.info(f"\n{'='*60}")
        logger.info("SILENT DARK BLUES - EPISODE 1")
        logger.info(f"{'='*60}\n")

        # Stage 1: Create mock music
        logger.info("[STAGE 1/4] MUSIC GENERATION")
        music_path = job_dir / "music" / "episode_1.wav"
        if not generate_mock_music(music_path, 300):
            raise Exception("Music generation failed")
        job.stage = JobStage.AUDIO_READY.value
        job_manager.update_job(job)
        logger.info("")

        # Stage 2: Create hero images
        logger.info("[STAGE 2/4] HERO IMAGES")
        hero_images = []
        for i in range(1, 7):
            img_path = job_dir / "images" / f"hero_{i}.jpg"
            logger.info(f"  Creating hero image {i}...")
            if create_placeholder_image(img_path):
                hero_images.append(str(img_path))
        logger.info(f"  ✓ {len(hero_images)} hero images created\n")

        # Stage 3: Build timeline
        logger.info("[STAGE 3/4] BUILD TIMELINE")
        total_duration = 300
        shot_duration = total_duration / len(hero_images)
        logger.info(f"  Timeline: {len(hero_images)} shots × {shot_duration:.0f}s")
        logger.info("")

        # Stage 4: Render video
        logger.info("[STAGE 4/4] RENDER VIDEO")
        output_path = job_dir / "output" / "episode_1.mp4"

        if create_silent_video(hero_images, output_path, music_path, total_duration):
            job.stage = JobStage.VIDEO_COMPLETE.value
            job_manager.update_job(job)

            logger.info(f"\n{'='*60}")
            logger.info("EPISODE 1 COMPLETE")
            logger.info(f"{'='*60}")
            logger.info(f"Output: {output_path}")
            logger.info(f"Duration: 5 minutes")
            logger.info(f"Shots: {len(hero_images)}")
            logger.info(f"Status: SUCCESS")
            logger.info(f"{'='*60}\n")

            job.status = "completed"
            job_manager.update_job(job)

            # Print path for easy access
            logger.info(f"VIDEO PATH: {output_path.resolve()}")
            return 0
        else:
            raise Exception("Video rendering failed")

    except Exception as e:
        logger.error(f"\nEPISODE 1 FAILED: {e}", exc_info=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
