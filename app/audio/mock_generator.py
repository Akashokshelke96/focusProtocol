from __future__ import annotations
"""
Mock Music Generator - Creates placeholder audio for Episode 1
"""
import numpy as np
from pathlib import Path
from app.config.logging_config import get_logger

logger = get_logger("music.mock_generator")


def generate_mock_music(output_path: Path, duration_seconds: int = 300) -> bool:
    """Generate a simple dark blues mock audio file."""
    try:
        import wave
        import struct

        logger.info(f"Generating mock dark blues audio ({duration_seconds}s)...")

        output_path.parent.mkdir(parents=True, exist_ok=True)

        # Audio parameters
        sample_rate = 44100
        num_samples = duration_seconds * sample_rate
        channels = 2
        sample_width = 2

        # Generate simple dark blues pattern
        t = np.linspace(0, duration_seconds, num_samples)

        # Base frequencies for dark blues (low, melancholic)
        freq1 = 100  # Low bass
        freq2 = 150  # Mid bass
        freq3 = 220  # Low note

        # Create signal
        signal1 = 0.1 * np.sin(2 * np.pi * freq1 * t)
        signal2 = 0.05 * np.sin(2 * np.pi * freq2 * t)
        signal3 = 0.08 * np.sin(2 * np.pi * freq3 * t)

        # Add envelope (gradually fades in and out)
        envelope = np.ones_like(t)
        fade_in = min(2.0, duration_seconds / 10)  # 2 second fade in
        fade_in_samples = int(fade_in * sample_rate)
        envelope[:fade_in_samples] = np.linspace(0, 1, fade_in_samples)

        fade_out = min(2.0, duration_seconds / 10)  # 2 second fade out
        fade_out_samples = int(fade_out * sample_rate)
        envelope[-fade_out_samples:] = np.linspace(1, 0, fade_out_samples)

        # Combine signals
        mono_signal = (signal1 + signal2 + signal3) * envelope

        # Convert to stereo
        mono_signal = np.clip(mono_signal, -1.0, 1.0)
        stereo_signal = np.repeat(mono_signal[:, np.newaxis], 2, axis=1)

        # Convert to int16
        audio_data = (stereo_signal * 32767).astype(np.int16)

        # Write WAV file
        with wave.open(str(output_path), "wb") as wav_file:
            wav_file.setnchannels(channels)
            wav_file.setsampwidth(sample_width)
            wav_file.setframerate(sample_rate)
            wav_file.writeframes(audio_data.tobytes())

        logger.info(f"✓ Mock audio created: {output_path}")
        return True

    except Exception as e:
        logger.error(f"Failed to generate mock music: {e}")
        return False
