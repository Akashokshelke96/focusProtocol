#!/usr/bin/env python
"""
Silent Dark Blues - Demo Mode with Mock Audio
Tests complete pipeline with existing audio files
"""
import sys
from pathlib import Path
from dotenv import load_dotenv
import json
from datetime import datetime
import librosa
import numpy as np
from PIL import Image, ImageDraw
from moviepy.editor import (
    VideoFileClip,
    VideoClip,
    concatenate_videoclips,
    AudioFileClip,
    ImageClip,
)

load_dotenv(Path(__file__).parent / '.env')
sys.path.insert(0, str(Path(__file__).parent))

from app.config.logging_config import setup_logging, get_logger
from app.providers.local_images import LocalImageProvider

logger = None


def create_demo_audio(duration_seconds: int = 60, output_path: Path = None) -> Path:
    """Create demo dark blues audio."""
    if output_path is None:
        output_path = Path(__file__).parent / "temp_demo_audio.wav"

    logger.info(f"Creating demo audio ({duration_seconds}s)...")

    import wave
    sample_rate = 44100
    chunk_duration = 10

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
    logger.info(f"Demo audio created: {size_mb:.1f} MB ({duration_seconds}s)")
    return output_path


def extract_audio_features(audio_path: str, fps: int = 30) -> tuple:
    """Extract audio features for visualizer."""
    logger.info("Extracting audio features...")

    y, sr = librosa.load(audio_path, sr=None)
    duration = librosa.get_duration(y=y, sr=sr)

    D = librosa.stft(y)
    S = np.abs(D) ** 2
    mel_S = librosa.feature.melspectrogram(S=S, sr=sr, n_mels=7)
    mel_S_db = librosa.power_to_db(mel_S, ref=np.max)
    mel_S_normalized = (mel_S_db - mel_S_db.min()) / (mel_S_db.max() - mel_S_db.min() + 1e-6)

    num_frames = int(duration * fps)
    time_frames = np.linspace(0, mel_S_normalized.shape[1] - 1, num_frames)

    features = np.zeros((num_frames, 7))
    for i in range(7):
        features[:, i] = np.interp(time_frames, np.arange(mel_S_normalized.shape[1]), mel_S_normalized[i])

    logger.info(f"Extracted {num_frames} frames with 7 frequency bands")
    return features, sr


def create_soundbar_frame(amplitudes: np.ndarray, frame_width: int = 1920, frame_height: int = 1080) -> np.ndarray:
    """Create soundbar visualizer frame."""
    img = Image.new('RGBA', (frame_width, frame_height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    num_bars = 7
    bar_width = 40
    max_bar_height = 200
    gap = 20

    total_width = num_bars * bar_width + (num_bars - 1) * gap
    start_x = (frame_width - total_width) // 2
    bar_bottom_y = int(frame_height * 0.7)

    for i, amplitude in enumerate(amplitudes):
        x = start_x + i * (bar_width + gap)
        bar_height = int(amplitude * max_bar_height)
        y_top = bar_bottom_y - bar_height
        y_bottom = bar_bottom_y

        r = int(0 + amplitude * 100)
        g = int(200 + amplitude * 55)
        b = int(255)

        draw.rectangle(
            [x, y_top, x + bar_width, y_bottom],
            fill=(r, g, b, 200),
            outline=(255, 255, 255, 150),
            width=2
        )

    return np.array(img)


def create_demo_video() -> dict:
    """Create complete demo video with visualizer."""
    logger.info("")
    logger.info("=" * 80)
    logger.info("SILENT DARK BLUES - DEMO MODE (Complete Pipeline Test)")
    logger.info("=" * 80)
    logger.info("")

    try:
        run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
        root_dir = Path(__file__).parent
        output_dir = root_dir / "output" / f"demo_{run_id}"
        output_dir.mkdir(parents=True, exist_ok=True)

        logger.info("[1/5] Creating demo audio")
        audio_path = create_demo_audio(duration_seconds=60)
        logger.info("")

        logger.info("[2/5] Selecting background images")
        images = LocalImageProvider().select_images(count=1)
        if not images:
            logger.error("No images available")
            return {"status": "failed", "reason": "No images"}
        logger.info("")

        logger.info("[3/5] Creating base video with image and audio")
        prepared_img = LocalImageProvider().prepare_image(images[0], 1920, 1080)
        if prepared_img is None:
            logger.error("Failed to prepare image")
            return {"status": "failed", "reason": "Image prep failed"}

        img_array = np.array(prepared_img)
        image_clip = ImageClip(img_array).set_duration(60)
        audio_clip = AudioFileClip(str(audio_path))

        base_video = image_clip.set_audio(audio_clip)
        base_video_path = output_dir / "base_video.mp4"

        base_video.write_videofile(
            str(base_video_path),
            fps=30,
            codec="libx264",
            audio_codec="aac",
            verbose=False,
            logger=None,
        )
        logger.info("")

        logger.info("[4/5] Extracting audio features for visualizer")
        features, sr = extract_audio_features(str(audio_path), fps=30)
        logger.info("")

        logger.info("[5/5] Adding audio-reactive visualizer")
        base_video = VideoFileClip(str(base_video_path))
        fps = base_video.fps
        duration = base_video.duration

        frame_idx = [0]

        def make_frame_with_visualizer(t):
            """Generate frame with visualizer overlay."""
            frame_num = int(t * fps)
            if frame_num >= len(features):
                frame_num = len(features) - 1

            original_frame = base_video.get_frame(t)
            amplitudes = features[frame_num]

            viz_frame = create_soundbar_frame(amplitudes, base_video.w, base_video.h)

            orig_img = Image.fromarray((original_frame * 255).astype(np.uint8))
            viz_img = Image.fromarray(viz_frame, 'RGBA')
            orig_img.paste(viz_img, (0, 0), viz_img)

            frame_idx[0] += 1
            if frame_idx[0] % int(fps * 10) == 0:
                logger.info(f"  Frame {frame_idx[0]}/{int(duration * fps)}")

            return np.array(orig_img).astype(np.uint8)

        final_video = VideoClip(make_frame_with_visualizer, duration=duration)
        final_video = final_video.set_fps(fps)
        final_video = final_video.set_audio(base_video.audio)

        output_video = output_dir / "demo_with_visualizer.mp4"
        logger.info("Rendering final video with visualizer...")

        final_video.write_videofile(
            str(output_video),
            fps=fps,
            codec="libx264",
            audio_codec="aac",
            verbose=False,
            logger=None,
        )

        logger.info("")
        logger.info("=" * 80)
        logger.info("DEMO COMPLETE")
        logger.info("=" * 80)
        logger.info("")
        logger.info(f"Output directory: {output_dir}")
        logger.info(f"Final video: {output_video.name}")
        logger.info(f"Duration: 1 minute")
        logger.info(f"Visualizer: Audio-reactive soundbars (centered, 70% from top)")
        logger.info("")

        return {
            "status": "success",
            "output_dir": str(output_dir),
            "final_video": str(output_video),
            "duration": "1 minute",
            "visualizer": "ACTIVE",
        }

    except Exception as e:
        logger.error(f"Demo failed: {e}")
        import traceback
        traceback.print_exc()
        return {"status": "failed", "error": str(e)}


def main():
    """Run demo."""
    global logger
    logger = setup_logging()

    result = create_demo_video()

    if result["status"] == "success":
        logger.info("SUCCESS - Pipeline verified with working visualizer")
        logger.info(f"Output: {result['final_video']}")
        return 0
    else:
        logger.error(f"FAILED: {result.get('error', result.get('reason', 'Unknown'))}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
