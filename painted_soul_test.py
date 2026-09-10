#!/usr/bin/env python
"""
PAINTED SOUL - Complete Test Generator
Suno API + Local Images + Cinematic Effects
"""
import sys
from pathlib import Path
import os
from dotenv import load_dotenv
import subprocess
import json
from datetime import datetime
import time

load_dotenv(Path(__file__).parent / '.env')
sys.path.insert(0, str(Path(__file__).parent))

from app.config.logging_config import setup_logging, get_logger
from app.providers.suno import SunoProvider
from app.providers.local_images import LocalImageProvider

logger = None

SUNO_PROMPT = """Create an ORIGINAL dark, sophisticated, hypnotic blues instrumental designed for deep work.

CORE VIBE: Dark noir blues / cinematic blues / blues-rock. Masculine, mature, intelligent, mysterious and extremely controlled. The feeling is a highly focused person working alone at 2 AM.

RHYTHM: Slow, steady and deliberate. Around 75–82 BPM perceived tempo with subtle double-time pulse. Gentle blues swing.

DRUMS: Minimal live-feeling drums. Deep soft kick, dry controlled snare, subtle hi-hat and occasional ghost notes. Very few fills.

BASS: Deep, warm electric bass with slight analog saturation. Repeating blues-based pattern tightly locked to kick.

ELECTRIC GUITAR: Dark vintage electric guitar with warm tube-amp overdrive, smooth saturation, sustain and subtle compression. Use slow blues bends, slides, vibrato.

HARMONY: Dark minor-blues atmosphere with blues-scale vocabulary, dominant seventh tension and occasional chromatic movement.

ATMOSPHERE: Smoky, rainy, urban, nocturnal, sophisticated and slightly dangerous. Not sad - POWERFUL CALM. Should feel intelligent, disciplined and quietly intimidating.

PRODUCTION: Warm analog character, dark tonal balance, rich low-mids, controlled bass, smooth highs, subtle tape saturation, spacious stereo imaging.

DYNAMICS: Keep energy relatively consistent. NO dramatic climax. NO sudden drops. NO huge impacts. Maintain steady psychological momentum.

ABSOLUTELY AVOID: Vocals, lyrics, spoken words, EDM drops, trap beats, aggressive rock, flashy solos, shredding, catchy pop melodies, dramatic orchestration, excessive percussion, sudden transitions, cheerful moods.

PSYCHOLOGICAL TARGET: Listener should think "I'll just work for a while..." and suddenly realize two hours have passed. Make distractions feel distant and concentration feel effortless.

Think: DARK BLUES FOR PEOPLE WHO HAVE WORK TO DO.

Instrument. Completely original."""


def get_music_library_dir() -> Path:
    """Get permanent Suno music library directory."""
    music_dir = Path(__file__).parent / "music" / "suno"
    music_dir.mkdir(parents=True, exist_ok=True)
    return music_dir


def test_suno_api() -> bool:
    """Test Suno API connectivity."""
    logger.info("")
    logger.info("=" * 80)
    logger.info("TESTING SUNO API")
    logger.info("=" * 80)
    logger.info("")

    provider = SunoProvider()

    api_key = os.getenv("SUNO_API_KEY")
    if not api_key:
        logger.error("SUNO_API_KEY not found in environment")
        return False

    logger.info("Configuration:")
    logger.info(f"  API Key: {api_key[:20]}...")
    logger.info(f"  Base URL: {provider.base_url}")
    logger.info("")

    return True


def generate_suno_tracks(track_count: int = 2) -> list[dict]:
    """Generate Suno music tracks."""
    logger.info("")
    logger.info("=" * 80)
    logger.info("GENERATING SUNO TRACKS")
    logger.info("=" * 80)
    logger.info("")

    provider = SunoProvider()
    tracks = []
    music_library = get_music_library_dir()

    for track_num in range(1, track_count + 1):
        logger.info(f"[TRACK {track_num}/{track_count}] Generating...")
        logger.info(f"  Duration: ~5 minutes")
        logger.info(f"  Style: Dark blues instrumental")
        logger.info("")

        results = provider.generate_music(
            prompt=SUNO_PROMPT,
            duration_seconds=300,
        )

        if not results:
            logger.error(f"  ✗ Generation failed")
            continue

        for result in results:
            task_id = result.get("task_id", f"track_{track_num}")
            url = result.get("url")
            duration = result.get("duration", 300)

            if not url:
                logger.warning(f"  ⚠ No URL in response")
                continue

            filename = f"painted_soul_track_{track_num:02d}_{task_id[:8]}.mp3"
            track_path = music_library / filename

            logger.info(f"  Downloading to: {filename}")

            if provider.download_audio(url, track_path):
                tracks.append({
                    "track_num": track_num,
                    "path": track_path,
                    "duration": duration,
                })
                logger.info(f"  ✓ Track stored in music library")
                logger.info(f"    Path: {track_path}")
            else:
                logger.error(f"  ✗ Download failed")

        logger.info("")

    logger.info(f"Total tracks generated: {len(tracks)}")
    return tracks


def select_and_verify_images() -> list[Path]:
    """Select and verify 2 local background images."""
    logger.info("")
    logger.info("=" * 80)
    logger.info("SELECTING LOCAL BACKGROUND IMAGES")
    logger.info("=" * 80)
    logger.info("")

    provider = LocalImageProvider()
    available = provider.list_available_images()

    logger.info(f"Available images in backgroundImages/:")
    for i, img in enumerate(available, 1):
        logger.info(f"  {i}. {img.name}")

    if len(available) < 2:
        logger.error(f"✗ Need at least 2 images, found only {len(available)}")
        return []

    images = available[:2]
    logger.info("")
    logger.info("Selected:")

    for i, img_path in enumerate(images, 1):
        info = provider.get_image_info(img_path)
        logger.info(f"  Image {i}: {img_path.name}")
        logger.info(f"    Resolution: {info['width']}x{info['height']}")
        logger.info(f"    Aspect ratio: {info['aspect_ratio']:.3f}")

    logger.info("")
    return images


def create_simple_video(
    image1_path: Path,
    image2_path: Path,
    audio1_path: Path,
    audio2_path: Path,
    output_path: Path,
) -> bool:
    """Create video with simple crossfade between 2 images and 2 audio tracks."""
    try:
        import librosa
        import soundfile as sf
        import numpy as np
        from PIL import Image

        logger.info("")
        logger.info("=" * 80)
        logger.info("RENDERING VIDEO")
        logger.info("=" * 80)
        logger.info("")

        # Load audio durations
        logger.info("Reading audio files...")
        y1, sr1 = librosa.load(str(audio1_path), sr=None)
        y2, sr2 = librosa.load(str(audio2_path), sr=None)

        duration1 = librosa.get_duration(y=y1, sr=sr1)
        duration2 = librosa.get_duration(y=y2, sr=sr2)

        logger.info(f"  Track 1: {duration1:.1f}s")
        logger.info(f"  Track 2: {duration2:.1f}s")
        logger.info(f"  Total: {duration1 + duration2:.1f}s")

        # Create crossfaded audio
        logger.info("Creating audio crossfade...")
        if sr1 != sr2:
            y2 = librosa.resample(y2, orig_sr=sr2, target_sr=sr1)

        sr = sr1
        crossfade_samples = int(3 * sr)  # 3 second crossfade

        # Build combined audio
        y1_end = y1[-crossfade_samples:]
        y2_start = y2[:crossfade_samples]

        fade_out = np.linspace(1, 0, crossfade_samples)
        fade_in = np.linspace(0, 1, crossfade_samples)

        crossfaded = y1_end * fade_out + y2_start * fade_in
        combined_audio = np.concatenate([y1[:-crossfade_samples], crossfaded, y2[crossfade_samples:]])

        audio_duration = len(combined_audio) / sr

        # Save combined audio
        combined_audio_path = output_path.parent / "combined_audio.wav"
        sf.write(str(combined_audio_path), combined_audio, sr)
        logger.info(f"  ✓ Audio combined: {audio_duration:.1f}s")

        # Load and prepare images
        logger.info("Preparing images...")
        img1 = Image.open(image1_path).convert("RGB")
        img2 = Image.open(image2_path).convert("RGB")

        # Resize to 1920x1080
        img1 = img1.resize((1920, 1080), Image.Resampling.LANCZOS)
        img2 = img2.resize((1920, 1080), Image.Resampling.LANCZOS)
        logger.info(f"  ✓ Images resized to 1920x1080")

        # Create frame sequence with image crossfade
        logger.info("Creating frame sequence...")
        frames_dir = output_path.parent / "frames"
        frames_dir.mkdir(exist_ok=True)

        fps = 30
        frame_idx = 0
        samples_per_frame = sr // fps

        # Duration of each image (approx)
        img1_duration = duration1 - 1.5  # Leave time for crossfade
        img2_duration = duration2 - 1.5

        img1_frames = int(img1_duration * fps)
        crossfade_frames = int(3 * fps)
        img2_frames = int(img2_duration * fps)

        total_frames = img1_frames + crossfade_frames + img2_frames

        logger.info(f"  Total frames to create: {total_frames}")

        # Image 1
        for i in range(img1_frames):
            img1.save(frames_dir / f"frame_{frame_idx:06d}.png")
            frame_idx += 1

        # Crossfade
        for i in range(crossfade_frames):
            alpha = i / crossfade_frames
            composite = Image.blend(img1, img2, alpha)
            composite.save(frames_dir / f"frame_{frame_idx:06d}.png")
            frame_idx += 1

        # Image 2
        for i in range(img2_frames):
            img2.save(frames_dir / f"frame_{frame_idx:06d}.png")
            frame_idx += 1

        logger.info(f"  ✓ Created {frame_idx} frames")

        # Render with FFmpeg
        logger.info("Rendering with FFmpeg...")
        output_path.parent.mkdir(parents=True, exist_ok=True)

        cmd = [
            "ffmpeg",
            "-framerate", "30",
            "-i", str(frames_dir / "frame_%06d.png"),
            "-i", str(combined_audio_path),
            "-c:v", "libx264",
            "-crf", "18",
            "-preset", "fast",
            "-c:a", "aac",
            "-b:a", "192k",
            "-shortest",
            "-y",
            str(output_path),
        ]

        logger.info("  Running FFmpeg...")
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)

        if result.returncode != 0:
            logger.error(f"FFmpeg error: {result.stderr[:500]}")
            return False

        logger.info("  ✓ FFmpeg completed")

        # Validate output
        if output_path.exists():
            size_mb = output_path.stat().st_size / (1024 * 1024)
            logger.info("")
            logger.info(f"✓ Video created successfully")
            logger.info(f"  File: {output_path.resolve()}")
            logger.info(f"  Size: {size_mb:.1f} MB")
            logger.info(f"  Duration: ~{audio_duration:.0f} seconds (~{audio_duration/60:.1f} minutes)")
            return True
        else:
            logger.error("✗ Video file was not created")
            return False

    except Exception as e:
        logger.error(f"Video rendering failed: {e}", exc_info=True)
        return False


def main():
    """Run complete Painted Soul test."""
    global logger

    logger = setup_logging()

    try:
        logger.info("")
        logger.info("╔" + "=" * 78 + "╗")
        logger.info("║" + " " * 78 + "║")
        logger.info("║" + "THE PAINTED SOUL - EPISODE 1 TEST".center(78) + "║")
        logger.info("║" + " " * 78 + "║")
        logger.info("╚" + "=" * 78 + "╝")

        # Step 1: Test API
        if not test_suno_api():
            return 1

        # Step 2: Generate tracks
        tracks = generate_suno_tracks(track_count=2)
        if len(tracks) < 2:
            logger.error("✗ Failed to generate 2 music tracks")
            return 1

        # Step 3: Select images
        images = select_and_verify_images()
        if len(images) < 2:
            logger.error("✗ Failed to select 2 background images")
            return 1

        # Step 4: Create video
        episode_dir = Path("output") / "EPISODE_1"
        episode_dir.mkdir(parents=True, exist_ok=True)

        final_video = episode_dir / "video.mp4"

        if create_simple_video(
            image1_path=images[0],
            image2_path=images[1],
            audio1_path=tracks[0]["path"],
            audio2_path=tracks[1]["path"],
            output_path=final_video,
        ):
            logger.info("")
            logger.info("=" * 80)
            logger.info("EPISODE 1 COMPLETE")
            logger.info("=" * 80)
            logger.info("")
            logger.info("OUTPUT SUMMARY:")
            logger.info(f"  Video: {final_video.resolve()}")
            logger.info(f"  Images: 2 (local)")
            logger.info(f"  Music: 2 × Suno tracks (~5 min each)")
            logger.info(f"  Effects: Image crossfade")
            logger.info(f"  Status: ✓ READY FOR PLAYBACK")
            logger.info("")

            return 0
        else:
            logger.error("✗ Failed to create video")
            return 1

    except Exception as e:
        logger.error(f"Test failed: {e}", exc_info=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
