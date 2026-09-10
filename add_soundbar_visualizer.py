#!/usr/bin/env python
"""
Add animated soundbar visualizer to Painted Soul videos
Centered horizontally, 70% from top, audio-reactive bars
"""
import sys
from pathlib import Path
import numpy as np
from PIL import Image, ImageDraw
import librosa
import soundfile as sf
from moviepy.editor import VideoFileClip, VideoClip, concatenate_videoclips
import os

sys.path.insert(0, str(Path(__file__).parent))
from app.config.logging_config import setup_logging, get_logger

logger = None


def extract_audio_features(audio_path: str, fps: int = 30) -> tuple[np.ndarray, int]:
    """
    Extract frequency features from audio.
    Returns: (features_per_frame, sample_rate)
    features_per_frame shape: (num_frames, num_bands)
    """
    logger.info(f"Extracting audio features from {Path(audio_path).name}...")

    y, sr = librosa.load(audio_path, sr=None)
    duration = librosa.get_duration(y=y, sr=sr)

    # Compute STFT
    D = librosa.stft(y)
    S = np.abs(D) ** 2

    # Convert to mel scale (better for music)
    mel_S = librosa.feature.melspectrogram(S=S, sr=sr, n_mels=7)

    # Convert to dB scale
    mel_S_db = librosa.power_to_db(mel_S, ref=np.max)

    # Normalize to 0-1 range
    mel_S_normalized = (mel_S_db - mel_S_db.min()) / (mel_S_db.max() - mel_S_db.min() + 1e-6)

    # Resample to match video fps
    num_frames = int(duration * fps)
    time_frames = np.linspace(0, mel_S_normalized.shape[1] - 1, num_frames)

    features = np.zeros((num_frames, 7))
    for i in range(7):
        features[:, i] = np.interp(time_frames, np.arange(mel_S_normalized.shape[1]), mel_S_normalized[i])

    logger.info(f"Extracted {num_frames} frames with 7 frequency bands")
    return features, sr


def create_soundbar_frame(amplitudes: np.ndarray, frame_width: int = 1920, frame_height: int = 1080) -> np.ndarray:
    """
    Create a single frame with animated soundbars.
    amplitudes: array of 7 values (0-1) representing bar heights
    """
    # Create transparent background
    img = Image.new('RGBA', (frame_width, frame_height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Soundbar parameters
    num_bars = 7
    bar_width = 40
    max_bar_height = 200
    gap = 20

    # Center horizontally
    total_width = num_bars * bar_width + (num_bars - 1) * gap
    start_x = (frame_width - total_width) // 2

    # 70% from top
    bar_bottom_y = int(frame_height * 0.7)

    # Draw bars with gradient color (cyan to blue)
    for i, amplitude in enumerate(amplitudes):
        x = start_x + i * (bar_width + gap)
        bar_height = int(amplitude * max_bar_height)
        y_top = bar_bottom_y - bar_height
        y_bottom = bar_bottom_y

        # Gradient color based on amplitude (cyan to blue)
        r = int(0 + amplitude * 100)
        g = int(200 + amplitude * 55)
        b = int(255)

        # Draw bar with semi-transparency
        draw.rectangle(
            [x, y_top, x + bar_width, y_bottom],
            fill=(r, g, b, 200),
            outline=(255, 255, 255, 150),
            width=2
        )

        # Add glow effect with smaller inner rectangle
        glow_x1 = x + 2
        glow_y1 = y_top + 2
        glow_x2 = x + bar_width - 2
        glow_y2 = y_bottom - 2
        if glow_y2 > glow_y1:
            draw.rectangle(
                [glow_x1, glow_y1, glow_x2, glow_y2],
                fill=(r, g, b, 100),
                outline=None
            )

    return np.array(img)


def add_visualizer_to_video(video_path: str, audio_path: str, output_path: str) -> bool:
    """
    Add animated soundbar visualizer to video.
    """
    try:
        logger.info(f"Loading video: {Path(video_path).name}...")
        video = VideoFileClip(video_path)
        fps = video.fps
        duration = video.duration

        logger.info(f"Video: {video.w}x{video.h} @ {fps}fps, {duration:.1f}s")

        # Extract audio features
        features, sr = extract_audio_features(audio_path, fps=int(fps))

        frame_idx = [0]

        def make_frame_with_visualizer(t):
            """Generate frame with original video + visualizer overlay."""
            frame_num = int(t * fps)
            if frame_num >= len(features):
                frame_num = len(features) - 1

            # Get original video frame
            original_frame = video.get_frame(t)

            # Get audio amplitudes for this frame
            amplitudes = features[frame_num]

            # Create visualizer frame
            viz_frame = create_soundbar_frame(amplitudes, video.w, video.h)

            # Convert original frame to PIL Image for compositing
            orig_img = Image.fromarray((original_frame * 255).astype(np.uint8))
            viz_img = Image.fromarray(viz_frame, 'RGBA')

            # Composite visualizer on top of video
            orig_img.paste(viz_img, (0, 0), viz_img)

            frame_idx[0] += 1
            if frame_idx[0] % int(fps * 5) == 0:
                logger.info(f"Processing frame {frame_idx[0]}/{int(duration * fps)}")

            return np.array(orig_img).astype(np.uint8)

        # Create final video clip
        logger.info("Creating composite video with visualizer...")
        final_video = VideoClip(make_frame_with_visualizer, duration=duration)
        final_video = final_video.set_fps(fps)
        final_video = final_video.set_audio(video.audio)

        # Export
        logger.info(f"Rendering to {Path(output_path).name}...")
        final_video.write_videofile(
            output_path,
            fps=fps,
            codec='libx264',
            audio_codec='aac',
            verbose=False,
            logger=None,
        )

        logger.info("Visualizer added successfully!")
        return True

    except Exception as e:
        logger.error(f"Failed to add visualizer: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    """Add visualizer to latest Painted Soul episode."""
    global logger
    logger = setup_logging()

    try:
        # Find latest episode
        output_base = Path("output")
        episodes = sorted(output_base.glob("painted_soul_episode_*"))

        if not episodes:
            logger.error("No episodes found in output/")
            return 1

        latest_episode = episodes[-1]
        logger.info(f"Latest episode: {latest_episode.name}")

        video_path = latest_episode / f"{latest_episode.name}.mp4"
        audio_path = latest_episode / "audio" / "soundtrack.wav"

        if not video_path.exists():
            logger.error(f"Video not found: {video_path}")
            return 1

        if not audio_path.exists():
            logger.error(f"Audio not found: {audio_path}")
            return 1

        output_path = latest_episode / f"{latest_episode.name}_with_viz.mp4"

        logger.info("")
        logger.info("=" * 80)
        logger.info("ADDING SOUNDBAR VISUALIZER")
        logger.info("=" * 80)
        logger.info("")

        if add_visualizer_to_video(str(video_path), str(audio_path), str(output_path)):
            logger.info("")
            logger.info("=" * 80)
            logger.info("COMPLETE")
            logger.info("=" * 80)
            logger.info("")
            logger.info(f"Output: {output_path.resolve()}")
            logger.info("")
            return 0
        else:
            return 1

    except Exception as e:
        logger.error(f"Failed: {e}", exc_info=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
