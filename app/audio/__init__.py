"""
Audio mixing and normalization
"""
from pathlib import Path
from typing import Optional
import subprocess
from app.config.settings import Settings
from app.config.logging_config import get_logger
from app.audio.collection_manager import MasterAudioCollection

logger = get_logger("audio.mixer")


class AudioMixer:
    """Handles audio mixing, normalization, and crossfading."""

    def __init__(self, settings: Settings):
        """Initialize audio mixer."""
        self.settings = settings
        self.master_collection = MasterAudioCollection(Path("media/audio"))
        logger.info("Audio mixer initialized with master collection")

    def mix_narration_and_music(
        self,
        narration_path: Path,
        music_path: Path,
        output_path: Path,
    ) -> bool:
        """Mix narration with background music."""
        logger.info(f"Mixing narration and music")

        try:
            # Use FFmpeg to mix audio with proper levels
            cmd = [
                "ffmpeg",
                "-i", str(narration_path),
                "-i", str(music_path),
                "-filter_complex",
                f"[0:a]volume={self.settings.narration_volume}[narration];"
                f"[1:a]volume={self.settings.music_volume}[music];"
                f"[narration][music]amix=inputs=2:duration=longest[a]",
                "-map", "[a]",
                "-y",
                str(output_path),
            ]

            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode != 0:
                logger.error(f"FFmpeg error: {result.stderr}")
                return False

            logger.info(f"Audio mixed successfully: {output_path}")
            return True

        except Exception as e:
            logger.error(f"Audio mixing failed: {e}")
            return False

    def normalize_audio(self, input_path: Path, output_path: Path) -> bool:
        """Normalize audio levels."""
        logger.info(f"Normalizing audio: {input_path}")

        try:
            cmd = [
                "ffmpeg",
                "-i", str(input_path),
                "-af", "loudnorm=I=-16:TP=-1.5:LRA=11",
                "-y",
                str(output_path),
            ]

            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode != 0:
                logger.error(f"FFmpeg error: {result.stderr}")
                return False

            logger.info(f"Audio normalized: {output_path}")
            return True

        except Exception as e:
            logger.error(f"Normalization failed: {e}")
            return False

    def crossfade_tracks(
        self,
        track1_path: Path,
        track2_path: Path,
        output_path: Path,
        crossfade_duration: Optional[float] = None,
    ) -> bool:
        """Create crossfade between two audio tracks."""
        if crossfade_duration is None:
            crossfade_duration = self.settings.audio_crossfade_seconds

        logger.info(f"Crossfading audio tracks ({crossfade_duration}s)")

        try:
            # Calculate offset for crossfade
            overlap_start = str(int(crossfade_duration))

            cmd = [
                "ffmpeg",
                "-i", str(track1_path),
                "-i", str(track2_path),
                "-filter_complex",
                f"[0:a]aformat=sample_rates=44100:channel_layouts=stereo[a0];"
                f"[1:a]aformat=sample_rates=44100:channel_layouts=stereo[a1];"
                f"[a0][a1]acrossfade=d={crossfade_duration}[a]",
                "-map", "[a]",
                "-y",
                str(output_path),
            ]

            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode != 0:
                logger.error(f"FFmpeg error: {result.stderr}")
                return False

            logger.info(f"Crossfade created: {output_path}")
            return True

        except Exception as e:
            logger.error(f"Crossfade failed: {e}")
            return False
