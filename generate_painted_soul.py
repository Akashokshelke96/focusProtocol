#!/usr/bin/env python
"""
THE PAINTED SOUL - Professional Video Generator
Clean naming conventions, proper structure
Output: output/painted_soul_episode_001/
"""
import sys
from pathlib import Path
import os
from dotenv import load_dotenv
from datetime import datetime
import json

load_dotenv(Path(__file__).parent / '.env')
sys.path.insert(0, str(Path(__file__).parent))

from app.config.logging_config import setup_logging, get_logger
from app.providers.local_images import LocalImageProvider

logger = None


def generate_dark_blues_audio(output_path: Path, duration_seconds: int = 300) -> bool:
    """Generate professional dark blues audio."""
    try:
        import wave
        import numpy as np

        logger.info(f"Generating dark blues audio ({duration_seconds}s)...")
        output_path.parent.mkdir(parents=True, exist_ok=True)

        sample_rate = 44100
        chunk_duration = 10
        chunk_samples = chunk_duration * sample_rate

        freq_sub = 40
        freq_bass = 55
        freq_root = 110
        freq_mid1 = 165
        freq_mid2 = 220

        with wave.open(str(output_path), "wb") as wav:
            wav.setnchannels(2)
            wav.setsampwidth(2)
            wav.setframerate(sample_rate)

            for chunk_idx in range(0, duration_seconds, chunk_duration):
                chunk_start = chunk_idx
                chunk_end = min(chunk_idx + chunk_duration, duration_seconds)
                chunk_len = chunk_end - chunk_start

                t = np.linspace(chunk_start, chunk_end, chunk_len * sample_rate, dtype=np.float32)

                sub_bass = 0.1 * np.sin(2 * np.pi * freq_sub * t, dtype=np.float32)
                deep_bass = 0.25 * np.sin(2 * np.pi * freq_bass * t, dtype=np.float32)
                root = 0.2 * np.sin(2 * np.pi * freq_root * t, dtype=np.float32)
                mid1 = 0.15 * np.sin(2 * np.pi * freq_mid1 * t, dtype=np.float32)
                mid2 = 0.1 * np.sin(2 * np.pi * freq_mid2 * t, dtype=np.float32)

                harmonic1 = 0.08 * np.sin(2 * np.pi * freq_bass * 1.5 * t, dtype=np.float32)
                harmonic2 = 0.06 * np.sin(2 * np.pi * freq_root * 1.5 * t, dtype=np.float32)

                variation1 = 0.02 * np.sin(2 * np.pi * 0.3 * t, dtype=np.float32)
                variation2 = 0.015 * np.sin(2 * np.pi * 0.7 * t, dtype=np.float32)
                variation3 = 0.01 * np.sin(2 * np.pi * 1.1 * t, dtype=np.float32)

                combined = (sub_bass + deep_bass + root + mid1 + mid2 + harmonic1 + harmonic2 + variation1 + variation2 + variation3)

                if chunk_idx == 0:
                    fade_in_samples = int(4.0 * sample_rate)
                    envelope = np.ones_like(combined, dtype=np.float32)
                    envelope[:fade_in_samples] = np.linspace(0, 1, fade_in_samples, dtype=np.float32)
                    combined = combined * envelope
                elif chunk_end >= duration_seconds:
                    fade_out_samples = int(5.0 * sample_rate)
                    envelope = np.ones_like(combined, dtype=np.float32)
                    envelope[-fade_out_samples:] = np.linspace(1, 0, fade_out_samples, dtype=np.float32)
                    combined = combined * envelope

                max_val = np.max(np.abs(combined))
                if max_val > 0:
                    combined = combined / max_val * 0.9

                left = combined
                right = combined * 0.98
                stereo = np.stack([left, right], axis=1)

                audio_data = (stereo * 32767).astype(np.int16)
                wav.writeframes(audio_data.tobytes())

        size_mb = output_path.stat().st_size / (1024 * 1024)
        logger.info(f"Audio created: {size_mb:.1f} MB")
        return True

    except Exception as e:
        logger.error(f"Audio generation failed: {e}")
        return False


def create_video_from_images(images: list[Path], audio_path: Path, output_path: Path) -> bool:
    """Create video from images and audio using moviepy."""
    try:
        from moviepy.editor import ImageClip, AudioFileClip, concatenate_videoclips
        from PIL import Image
        import numpy as np

        logger.info("Preparing images...")
        prepared_images = []
        for img_path in images:
            img = Image.open(img_path).convert("RGB")
            img = img.resize((1920, 1080), Image.Resampling.LANCZOS)
            prepared_images.append(img)

        # Load audio
        logger.info("Loading audio...")
        audio = AudioFileClip(str(audio_path))
        duration = audio.duration
        logger.info(f"Audio duration: {duration:.1f}s")

        # Create video clips
        logger.info("Creating video clips...")
        clips = []
        shot_duration = duration / len(prepared_images)

        for img in prepared_images:
            clip = ImageClip(np.array(img)).set_duration(shot_duration)
            clips.append(clip)

        # Concatenate clips
        logger.info("Concatenating clips...")
        video = concatenate_videoclips(clips)

        # Add audio
        logger.info("Adding audio...")
        video = video.set_audio(audio)

        # Render video
        logger.info("Rendering video...")
        output_path.parent.mkdir(parents=True, exist_ok=True)

        video.write_videofile(
            str(output_path),
            fps=30,
            codec="libx264",
            audio_codec="aac",
            verbose=False,
            logger=None,
        )

        logger.info("Video rendered successfully")
        return True

    except Exception as e:
        logger.error(f"Video creation failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    """Generate clean Painted Soul episode."""
    global logger

    logger = setup_logging()

    try:
        # Determine episode number
        output_base = Path("output")
        output_base.mkdir(exist_ok=True)

        existing_episodes = list(output_base.glob("painted_soul_episode_*"))
        episode_num = len(existing_episodes) + 1
        episode_id = f"painted_soul_episode_{episode_num:03d}"
        episode_dir = output_base / episode_id

        logger.info("")
        logger.info("=" * 80)
        logger.info(f"THE PAINTED SOUL - {episode_id.upper()}")
        logger.info("=" * 80)
        logger.info("")

        # Create episode directory structure
        assets_dir = episode_dir / "assets"
        audio_dir = episode_dir / "audio"
        assets_dir.mkdir(parents=True, exist_ok=True)
        audio_dir.mkdir(parents=True, exist_ok=True)

        # Step 1: Select images
        logger.info("[1/4] SELECTING BACKGROUND IMAGES")
        provider = LocalImageProvider()
        images = provider.select_images(count=2)

        if len(images) < 2:
            logger.error("Failed to select images")
            return 1

        for i, img in enumerate(images, 1):
            logger.info(f"  Image {i}: {img.name}")

        logger.info("")

        # Step 2: Generate audio
        logger.info("[2/4] GENERATING DARK BLUES AUDIO")
        music_path = audio_dir / "soundtrack.wav"

        if not generate_dark_blues_audio(music_path, duration_seconds=300):
            logger.error("Audio generation failed")
            return 1

        logger.info("")

        # Step 3: Create video
        logger.info("[3/4] RENDERING VIDEO")
        video_path = episode_dir / f"{episode_id}.mp4"

        if not create_video_from_images(images, music_path, video_path):
            logger.error("Video rendering failed")
            return 1

        logger.info("")

        # Step 4: Create metadata
        logger.info("[4/4] CREATING METADATA")
        metadata = {
            "episode_id": episode_id,
            "episode_number": episode_num,
            "title": f"The Painted Soul - Episode {episode_num}",
            "description": "Dark blues instrumental for deep work and concentration",
            "duration_minutes": 5,
            "resolution": "1920x1080",
            "fps": 30,
            "images_count": 2,
            "music_type": "dark_blues",
            "created_at": datetime.utcnow().isoformat(),
        }

        metadata_path = episode_dir / "metadata.json"
        with open(metadata_path, "w") as f:
            json.dump(metadata, f, indent=2)

        logger.info("")
        logger.info("=" * 80)
        logger.info("EPISODE COMPLETE")
        logger.info("=" * 80)
        logger.info("")

        if video_path.exists():
            size_mb = video_path.stat().st_size / (1024 * 1024)
            logger.info(f"OUTPUT VIDEO:")
            logger.info(f"  Episode ID: {episode_id}")
            logger.info(f"  File: {video_path.resolve()}")
            logger.info(f"  Size: {size_mb:.1f} MB")
            logger.info(f"  Duration: 5 minutes")
            logger.info(f"  Format: MP4 (H.264 + AAC)")
            logger.info(f"  Resolution: 1920x1080 @ 30fps")
            logger.info(f"  Status: READY FOR PLAYBACK")
            logger.info("")
            logger.info(f"Episode directory: {episode_dir.resolve()}")
            logger.info("")

            return 0
        else:
            logger.error("Video file was not created")
            return 1

    except Exception as e:
        logger.error(f"Failed: {e}", exc_info=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
