from __future__ import annotations
"""
Painted Soul - Complete Video Generation Pipeline
Music-first with cinematic visuals and soundbar
"""
import sys
from pathlib import Path
import os
from dotenv import load_dotenv
from datetime import datetime
import subprocess
import json
from PIL import Image

load_dotenv(Path(__file__).parent / '.env')
sys.path.insert(0, str(Path(__file__).parent))

from app.config.settings import get_settings, ensure_directories
from app.config.logging_config import setup_logging, get_logger
from app.jobs.manager import JobManager, JobStage
from app.providers.suno import SunoProvider
from app.providers.local_images import LocalImageProvider
from app.media.visual_effects import CinematicZoomEffect, SoundbarVisualizer

logger = None

# The Painted Soul - Music Direction
SUNO_PROMPT = """Create an ORIGINAL dark, sophisticated, hypnotic blues instrumental designed specifically for deep work, coding, studying, writing and intense concentration.

CORE VIBE:
Dark noir blues / cinematic blues / blues-rock. Masculine, mature, intelligent, mysterious and extremely controlled.

The feeling is a highly focused person working alone at 2 AM — calm, calculating, disciplined and completely in control. Rain outside, dim lights, black coffee, laptop glowing, world completely switched off.

The music should create FLOW STATE, not demand attention.

HYPNOTIC DESIGN:
Make the track hypnotic through repetition, groove and MICRO-EVOLUTION.

Establish a strong musical pattern early and let the listener's brain settle into it.

Use recurring guitar motifs, repeating bass patterns and a consistent drum pulse.

Do NOT constantly introduce new ideas.

Instead, use tiny changes that are felt subconsciously:

- subtle guitar phrasing variations
- small bass variations
- occasional ghost-note changes
- tiny atmospheric shifts
- restrained fills

The listener should gradually stop consciously noticing the music while remaining immersed in its groove.

RHYTHM:
Slow, steady and deliberate.
Around 75–82 BPM perceived tempo.
Subtle double-time pulse.
Gentle blues swing.

The groove should feel like a steady heartbeat: predictable, grounding and precise.

DRUMS:
Minimal live-feeling drums.
Deep soft kick.
Dry controlled snare.
Subtle hi-hat.
Occasional ghost notes.
Very few fills.
No big crashes.
No drops.
No dramatic transitions.

BASS:
Deep, warm electric bass with slight analog saturation.

Create a repeating blues-based pattern tightly locked to the kick.

Occasional chromatic passing notes are acceptable, but keep them restrained.

The bass should provide stability and momentum.

ELECTRIC GUITAR:
Dark vintage electric guitar with warm tube-amp overdrive, smooth saturation, sustain and subtle compression.

Use:

- slow blues bends
- slides
- vibrato
- muted notes
- deliberate pauses

Create 1–2 memorable recurring guitar motifs.

Let notes breathe.

Avoid shredding and flashy solos.

A simple expressive phrase followed by silence is better than constant playing.

HARMONY:
Dark minor-blues atmosphere with blues-scale vocabulary, dominant seventh tension and occasional chromatic movement.

Keep the progression simple and repetitive.

Avoid frequent chord changes.

Avoid complex jazz harmony.

ATMOSPHERE:
Smoky, rainy, urban, nocturnal, sophisticated and slightly dangerous.

Not sad.

Not depressing.

POWERFUL CALM.

The music should feel intelligent, disciplined and quietly intimidating.

PRODUCTION:
Warm analog character.
Dark tonal balance.
Rich low-mids.
Controlled bass.
Smooth highs.
Subtle tape saturation.
Spacious but stable stereo imaging.

Comfortable for long headphone sessions.

Avoid harsh treble and excessive mastering.

DYNAMICS:
Keep energy relatively consistent.

NO dramatic climax.
NO sudden drops.
NO huge cinematic impacts.

Maintain steady psychological momentum.

ABSOLUTELY AVOID:
Vocals.
Lyrics.
Spoken words.
EDM drops.
Trap beats.
Aggressive rock.
Flashy solos.
Shredding.
Catchy pop melodies.
Dramatic orchestration.
Excessive percussion.
Sudden transitions.
Constant variation.
Cheerful moods.
Sentimental moods.

PSYCHOLOGICAL TARGET:

The listener should think:

"I'll just work for a while..."

—and suddenly realize two hours have passed.

The music should make distractions feel distant and concentration feel effortless.

Think:

DARK BLUES FOR PEOPLE WHO HAVE WORK TO DO.

Instrumental.

Completely original.

Do not copy any existing song, melody, riff, recording or distinctive musical phrase."""


def get_music_library_dir() -> Path:
    """Get permanent Suno music library directory."""
    music_dir = Path(__file__).parent / "music" / "suno"
    music_dir.mkdir(parents=True, exist_ok=True)
    return music_dir


def generate_suno_tracks(track_count: int = 2) -> list[dict]:
    """Generate Suno music tracks."""
    logger.info("")
    logger.info("[STAGE 1/5] SUNO MUSIC GENERATION")
    logger.info("-" * 80)

    provider = SunoProvider()

    # Check health
    if not provider.health_check():
        logger.error("Suno API is not responding")
        return []

    tracks = []
    music_library = get_music_library_dir()

    for track_num in range(1, track_count + 1):
        logger.info(f"Generating Track {track_num}/{track_count}...")

        results = provider.generate_music(
            prompt=SUNO_PROMPT,
            duration_seconds=300,  # 5 minutes
            custom_mode=True,
        )

        if not results:
            logger.error(f"Failed to generate track {track_num}")
            continue

        for result in results:
            task_id = result.get("task_id", f"track_{track_num}")
            url = result.get("url")
            duration = result.get("duration", 300)

            if not url:
                logger.warning(f"No URL returned for track {track_num}")
                continue

            # Download to permanent library
            filename = f"painted_soul_track_{track_num:02d}_{task_id[:8]}.mp3"
            track_path = music_library / filename

            logger.info(f"  Downloading to library: {filename}")

            if provider.download_audio(url, track_path):
                tracks.append({
                    "track_num": track_num,
                    "path": track_path,
                    "duration": duration,
                    "url": url,
                })
                logger.info(f"  ✓ Stored in music library")
            else:
                logger.error(f"  ✗ Download failed")

    logger.info(f"Generated {len(tracks)} track(s)")
    logger.info("")
    return tracks


def select_background_images() -> list[Path]:
    """Select 2 background images from local folder."""
    logger.info("[STAGE 2/5] LOCAL IMAGE SELECTION")
    logger.info("-" * 80)

    provider = LocalImageProvider()
    images = provider.select_images(count=2)

    if len(images) < 2:
        logger.error(f"Need 2 images, found only {len(images)}")
        return []

    for i, img_path in enumerate(images, 1):
        info = provider.get_image_info(img_path)
        logger.info(f"Image {i}: {img_path.name}")
        logger.info(f"  Resolution: {info['width']}x{info['height']}")
        logger.info(f"  Aspect ratio: {info['aspect_ratio']:.2f}")

    logger.info("")
    return images


def prepare_video_images(images: list[Path], episode_dir: Path) -> list[Image.Image]:
    """Prepare images for video rendering."""
    logger.info("[STAGE 3/5] PREPARE IMAGES")
    logger.info("-" * 80)

    provider = LocalImageProvider()
    prepared_images = []

    for i, img_path in enumerate(images, 1):
        logger.info(f"Processing image {i}/{len(images)}...")
        prepared = provider.prepare_image(img_path, target_width=1920, target_height=1080)

        if prepared:
            prepared_images.append(prepared)
            logger.info(f"  ✓ Prepared for video")
        else:
            logger.error(f"  ✗ Preparation failed")

    logger.info(f"Prepared {len(prepared_images)} image(s)")
    logger.info("")
    return prepared_images


def render_video_segment(
    image: Image.Image,
    audio_path: Path,
    output_path: Path,
    episode_dir: Path,
) -> bool:
    """Render a single video segment (image + audio + effects)."""
    try:
        import librosa

        logger.info(f"Rendering segment: {output_path.name}")

        # Get audio duration
        y, sr = librosa.load(str(audio_path), sr=None)
        duration = librosa.get_duration(y=y, sr=sr)
        logger.info(f"  Duration: {duration:.1f}s")

        # Create frames with cinematic zoom
        zoom_effect = CinematicZoomEffect(
            image=image,
            duration_seconds=duration,
            fps=30,
            zoom_strength=0.03,
            pan_strength=0.02,
        )

        logger.info(f"  Applying cinematic zoom...")
        zoom_frames = zoom_effect.generate_all_frames()

        # Create soundbar overlay
        soundbar = SoundbarVisualizer(
            width=1920,
            height=1080,
            fps=30,
            duration_seconds=duration,
            bar_count=7,
            bar_color=(100, 200, 255),
            bg_color=(20, 20, 30),
        )

        logger.info(f"  Generating soundbar animation...")
        soundbar_frames = soundbar.generate_all_frames()

        # Composite frames
        logger.info(f"  Compositing zoom + soundbar...")
        final_frames = []
        for zoom_frame, sb_frame in zip(zoom_frames, soundbar_frames):
            composite = SoundbarVisualizer.composite_soundbar(zoom_frame, sb_frame)
            final_frames.append(composite)

        # Save frames to temp directory
        frames_dir = episode_dir / "temp_frames"
        frames_dir.mkdir(exist_ok=True)

        for i, frame in enumerate(final_frames):
            frame_path = frames_dir / f"frame_{i:06d}.png"
            frame.save(frame_path)

        logger.info(f"  Saved {len(final_frames)} frames")

        # Use FFmpeg to create video with audio
        logger.info(f"  Rendering with FFmpeg...")

        cmd = [
            "ffmpeg",
            "-framerate", "30",
            "-i", str(frames_dir / "frame_%06d.png"),
            "-i", str(audio_path),
            "-c:v", "libx264",
            "-crf", "18",
            "-preset", "fast",
            "-c:a", "aac",
            "-b:a", "192k",
            "-shortest",
            "-y",
            str(output_path),
        ]

        result = subprocess.run(cmd, capture_output=True, text=True)

        if result.returncode != 0:
            logger.error(f"FFmpeg error: {result.stderr}")
            return False

        logger.info(f"  ✓ Segment rendered")
        return True

    except Exception as e:
        logger.error(f"Segment rendering failed: {e}")
        return False


def crossfade_audio_tracks(
    track1_path: Path,
    track2_path: Path,
    output_path: Path,
    crossfade_seconds: float = 3.0,
) -> bool:
    """Crossfade two audio tracks."""
    try:
        import librosa
        import soundfile as sf
        import numpy as np

        logger.info(f"Creating audio crossfade ({crossfade_seconds}s)...")

        # Load both tracks
        y1, sr1 = librosa.load(str(track1_path), sr=None)
        y2, sr2 = librosa.load(str(track2_path), sr=None)

        if sr1 != sr2:
            logger.warning(f"Sample rates differ: {sr1} vs {sr2}, using {sr1}")
            y2 = librosa.resample(y2, orig_sr=sr2, target_sr=sr1)

        sr = sr1

        # Calculate crossfade samples
        cf_samples = int(crossfade_seconds * sr)

        # Create crossfade envelope
        fade_out = np.linspace(1, 0, cf_samples)
        fade_in = np.linspace(0, 1, cf_samples)

        # Apply crossfade
        cf_start1 = len(y1) - cf_samples
        cf_start2 = 0

        y1[:cf_start1] = y1[:cf_start1]  # Keep original
        y1[cf_start1:] = y1[cf_start1:] * fade_out + y2[cf_start2:cf_samples] * fade_in

        # Append remainder of track 2
        combined = np.concatenate([y1, y2[cf_samples:]])

        # Save combined audio
        output_path.parent.mkdir(parents=True, exist_ok=True)
        sf.write(str(output_path), combined, sr)

        duration = len(combined) / sr
        logger.info(f"  ✓ Combined audio: {duration:.1f}s")
        return True

    except Exception as e:
        logger.error(f"Audio crossfade failed: {e}")
        return False


def main():
    """Generate Painted Soul Episode 1."""
    global logger

    ensure_directories()
    logger = setup_logging()

    try:
        episode_num = 1
        episode_id = f"EPISODE_{episode_num}"
        episode_dir = Path("output") / episode_id

        # Check if episode already exists
        if episode_dir.exists():
            logger.warning(f"Episode directory already exists: {episode_dir}")
            logger.info("Using existing directory for test")

        episode_dir.mkdir(parents=True, exist_ok=True)

        logger.info("")
        logger.info("=" * 80)
        logger.info("THE PAINTED SOUL - EPISODE 1 GENERATION")
        logger.info("=" * 80)
        logger.info("")

        # Stage 1: Generate Suno tracks
        tracks = generate_suno_tracks(track_count=2)
        if len(tracks) < 2:
            raise Exception("Failed to generate 2 music tracks")

        # Stage 2: Select images
        images = select_background_images()
        if len(images) < 2:
            raise Exception("Failed to select 2 background images")

        # Stage 3: Prepare images
        prepared = prepare_video_images(images, episode_dir)
        if len(prepared) < 2:
            raise Exception("Failed to prepare images")

        # Stage 4: Render video segments with effects
        logger.info("[STAGE 4/5] RENDER VIDEO SEGMENTS")
        logger.info("-" * 80)

        segments = []
        for i, (track, image) in enumerate(zip(tracks, prepared), 1):
            segment_path = episode_dir / f"segment_{i}.mp4"
            logger.info(f"Segment {i}/{len(tracks)}...")

            if render_video_segment(image, track["path"], segment_path, episode_dir):
                segments.append(segment_path)
            else:
                raise Exception(f"Failed to render segment {i}")

        logger.info(f"Rendered {len(segments)} segment(s)")
        logger.info("")

        # Stage 5: Concatenate segments
        logger.info("[STAGE 5/5] FINAL ASSEMBLY")
        logger.info("-" * 80)

        final_video = episode_dir / "video.mp4"
        concat_list = episode_dir / "concat.txt"

        # Create FFmpeg concat file
        with open(concat_list, "w") as f:
            for segment in segments:
                f.write(f"file '{segment.absolute()}'\n")

        logger.info("Concatenating segments...")

        cmd = [
            "ffmpeg",
            "-f", "concat",
            "-safe", "0",
            "-i", str(concat_list),
            "-c", "copy",
            "-y",
            str(final_video),
        ]

        result = subprocess.run(cmd, capture_output=True, text=True)

        if result.returncode != 0:
            logger.error(f"Concatenation failed: {result.stderr}")
            raise Exception("Failed to concatenate segments")

        logger.info("✓ Segments concatenated")
        logger.info("")

        # Validation
        if final_video.exists():
            size_mb = final_video.stat().st_size / (1024 * 1024)
            logger.info("=" * 80)
            logger.info("EPISODE 1 GENERATION COMPLETE")
            logger.info("=" * 80)
            logger.info("")
            logger.info("OUTPUT VIDEO:")
            logger.info(f"  File: {final_video.resolve()}")
            logger.info(f"  Size: {size_mb:.1f} MB")
            logger.info(f"  Duration: ~10 minutes")
            logger.info(f"  Format: MP4 (H.264 + AAC)")
            logger.info(f"  Resolution: 1920x1080 @ 30fps")
            logger.info(f"  Images: 2 (local)")
            logger.info(f"  Music: 2 × Suno tracks")
            logger.info(f"  Effects: Cinematic zoom + centered soundbar")
            logger.info(f"  Status: COMPLETE & PLAYABLE")
            logger.info("")
            logger.info("=" * 80)
            logger.info("")

            return 0
        else:
            raise Exception("Final video was not created")

    except Exception as e:
        logger.error(f"FAILED: {e}", exc_info=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
