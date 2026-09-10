"""
Local music file provider for long-form jazz videos.
Scans local music directory and provides file selection.
"""
import random
import subprocess
import json
from pathlib import Path
from typing import Optional, List, Dict, Any
from app.config.logging_config import get_logger
from app.utils.ffmpeg import find_ffmpeg

logger = get_logger("providers.local_music")


class LocalMusicProvider:
    """Manages local music files for jazz video generation."""

    SUPPORTED_FORMATS = {".mp3", ".wav", ".aac", ".flac", ".m4a"}

    def __init__(self, music_dir: Optional[Path] = None):
        """Initialize local music provider.

        Args:
            music_dir: Directory containing music files. Defaults to project root/music
        """
        if music_dir is None:
            # Get absolute path to music directory
            project_root = Path(__file__).parent.parent.parent
            music_dir = project_root / "music"
        else:
            music_dir = Path(music_dir)

        self.music_dir = music_dir.absolute()
        self.music_dir.mkdir(parents=True, exist_ok=True)
        logger.info(f"Local music provider initialized: {self.music_dir}")

    def get_available_music_files(self) -> List[Dict[str, Any]]:
        """Scan music directory and return list of valid audio files.

        Returns:
            List of dicts with file info: {path, filename, duration}
        """
        files = []

        if not self.music_dir.exists():
            logger.warning(f"Music directory does not exist: {self.music_dir}")
            return files

        for file_path in self.music_dir.iterdir():
            if file_path.is_file() and file_path.suffix.lower() in self.SUPPORTED_FORMATS:
                try:
                    duration = self._get_audio_duration(file_path)
                    if duration > 0:
                        files.append({
                            "path": str(file_path.absolute()),
                            "filename": file_path.name,
                            "duration": duration,
                        })
                        logger.debug(f"Found music file: {file_path.name} ({duration:.1f}s)")
                except Exception as e:
                    logger.warning(f"Failed to inspect {file_path.name}: {e}")

        logger.info(f"Found {len(files)} valid music files in {self.music_dir}")
        return sorted(files, key=lambda x: x["filename"])

    def _get_audio_duration(self, file_path: Path) -> float:
        """Get audio file duration using available methods.

        Args:
            file_path: Path to audio file

        Returns:
            Duration in seconds
        """
        try:
            # Method 1: Use wave module for WAV files (most reliable for our WAV files)
            if file_path.suffix.lower() == ".wav":
                try:
                    import wave
                    with wave.open(str(file_path), 'rb') as wav_file:
                        frames = wav_file.getnframes()
                        rate = wav_file.getframerate()
                        duration = frames / rate
                        logger.info(f"WAV duration (wave module): {file_path.name} = {duration:.1f}s ({duration/60:.2f}m)")
                        return duration
                except Exception as e:
                    logger.error(f"WAV parsing failed: {e}. Will try FFprobe.")

            # Method 2: Use FFprobe via subprocess (most reliable for all formats)
            try:
                ffmpeg_path = find_ffmpeg()
                if ffmpeg_path:
                    ffprobe_path = ffmpeg_path.parent / "ffprobe.exe"
                    if not ffprobe_path.exists():
                        ffprobe_path = ffmpeg_path.parent / "ffprobe"

                    if ffprobe_path.exists():
                        result = subprocess.run(
                            [str(ffprobe_path), "-v", "error", "-show_entries",
                             "format=duration", "-of", "default=noprint_wrappers=1:nokey=1",
                             str(file_path)],
                            capture_output=True,
                            text=True,
                            timeout=10
                        )
                        if result.returncode == 0 and result.stdout.strip():
                            duration = float(result.stdout.strip())
                            logger.info(f"FFprobe duration: {file_path.name} = {duration:.1f}s ({duration/60:.2f}m)")
                            return duration
            except Exception as e:
                logger.debug(f"FFprobe method failed: {e}")

            # Method 3: Try using pydub with ffmpeg (if available)
            try:
                from pydub.utils import mediainfo
                info = mediainfo(str(file_path))
                if info and "duration" in info:
                    duration_ms = int(float(info.get("duration", 0)))
                    duration = duration_ms / 1000.0
                    logger.info(f"Pydub duration: {file_path.name} = {duration:.1f}s ({duration/60:.2f}m)")
                    return duration
            except Exception as e:
                logger.debug(f"Pydub method failed: {e}")

            # Method 4: Try mutagen for MP3/FLAC/M4A
            try:
                from mutagen.mp3 import MP3
                from mutagen.flac import FLAC
                from mutagen.mp4 import MP4

                if file_path.suffix.lower() == ".mp3":
                    audio = MP3(str(file_path))
                    duration = audio.info.length
                    logger.info(f"Mutagen MP3 duration: {file_path.name} = {duration:.1f}s ({duration/60:.2f}m)")
                    return duration
                elif file_path.suffix.lower() == ".flac":
                    audio = FLAC(str(file_path))
                    duration = audio.info.length
                    logger.info(f"Mutagen FLAC duration: {file_path.name} = {duration:.1f}s ({duration/60:.2f}m)")
                    return duration
                elif file_path.suffix.lower() in [".m4a", ".aac"]:
                    audio = MP4(str(file_path))
                    duration = audio.info.length
                    logger.info(f"Mutagen M4A duration: {file_path.name} = {duration:.1f}s ({duration/60:.2f}m)")
                    return duration
            except Exception as e:
                logger.debug(f"Mutagen method failed: {e}")

            logger.error(f"All duration detection methods failed for {file_path.name}")
            raise RuntimeError(f"Cannot determine duration for {file_path.name}")

        except Exception as e:
            logger.error(f"Failed to get duration for {file_path.name}: {e}")
            logger.error(f"SKIPPING FILE: Duration detection failed. Not assuming a default.")
            raise

    def select_random_tracks(
        self,
        count: int = 3,
        exclude_combinations: Optional[List[List[str]]] = None,
    ) -> List[Dict[str, Any]]:
        """Randomly select N music files.

        Args:
            count: Number of tracks to select (default 3)
            exclude_combinations: List of previously used combinations to avoid

        Returns:
            List of selected track dicts
        """
        available_files = self.get_available_music_files()

        if len(available_files) < count:
            logger.warning(
                f"Requested {count} tracks but only {len(available_files)} available. "
                f"Using all available files."
            )
            return available_files

        # Simple random selection for first implementation
        # Future: implement duplicate combination prevention
        selected = random.sample(available_files, count)

        selected_names = [f["filename"] for f in selected]
        logger.info(f"Selected {count} random tracks: {selected_names}")

        return selected

    def concatenate_tracks(
        self,
        track_paths: List[str],
        output_path: Path,
        crossfade_duration: float = 2.0,
    ) -> bool:
        """Concatenate multiple audio tracks with crossfade transitions.

        Args:
            track_paths: List of paths to audio files
            output_path: Path to save concatenated audio
            crossfade_duration: Duration of crossfade between tracks in seconds

        Returns:
            True if successful, False otherwise
        """
        if len(track_paths) < 2:
            logger.error("Need at least 2 tracks to concatenate")
            return False

        output_path.parent.mkdir(parents=True, exist_ok=True)

        try:
            # Find FFmpeg using utility function
            ffmpeg_path = find_ffmpeg()
            if not ffmpeg_path:
                logger.error("FFmpeg not found in system PATH or common locations")
                return False

            logger.info(f"Using FFmpeg from: {ffmpeg_path}")

            # Build FFmpeg filter for concatenation with crossfade
            filter_parts = []

            for i, track_path in enumerate(track_paths):
                filter_parts.append(f"[{i}:a]")

            # Build FFmpeg filter for audio concatenation with crossfade
            if len(track_paths) == 2:
                concat_filter = f"[0:a][1:a]acrossfade=d={crossfade_duration}[a]"
                output_label = "[a]"
            elif len(track_paths) == 3:
                # For 3 tracks: [0:a][1:a]acrossfade -> [a0]; [a0][2:a]acrossfade -> [a]
                concat_filter = (
                    f"[0:a][1:a]acrossfade=d={crossfade_duration}[a0];"
                    f"[a0][2:a]acrossfade=d={crossfade_duration}[a]"
                )
                output_label = "[a]"
            else:
                # For 4+ tracks, chain crossfades
                concat_parts = []
                for i in range(len(track_paths) - 1):
                    if i == 0:
                        concat_parts.append(
                            f"[0:a][1:a]acrossfade=d={crossfade_duration}[a{i}]"
                        )
                    elif i == len(track_paths) - 2:
                        # Last crossfade outputs to [a]
                        concat_parts.append(
                            f"[a{i-1}][{i+1}:a]acrossfade=d={crossfade_duration}[a]"
                        )
                    else:
                        concat_parts.append(
                            f"[a{i-1}][{i+1}:a]acrossfade=d={crossfade_duration}[a{i}]"
                        )

                concat_filter = ";".join(concat_parts)
                output_label = "[a]"

            # Build FFmpeg command
            cmd = [str(ffmpeg_path)]

            # Add all input files
            for track_path in track_paths:
                cmd.extend(["-i", str(track_path)])

            # Add filter and output
            cmd.extend([
                "-filter_complex", concat_filter,
                "-map", output_label,
                "-c:a", "aac",
                "-b:a", "192k",
                "-y",
                str(output_path),
            ])

            logger.info(f"Concatenating {len(track_paths)} tracks with {crossfade_duration}s crossfade")
            logger.debug(f"FFmpeg command: {' '.join(cmd)}")
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)

            if result.returncode != 0:
                logger.error(f"FFmpeg concatenation error: {result.stderr}")
                return False

            # Verify output
            output_duration = self._get_audio_duration(output_path)
            logger.info(f"Concatenation successful: {output_path} ({output_duration:.1f}s)")

            return True

        except Exception as e:
            logger.error(f"Concatenation failed: {e}")
            return False

    def _find_ffmpeg(self) -> Optional[Path]:
        """Find FFmpeg executable in common locations.

        Returns:
            Path to FFmpeg executable, or None if not found
        """
        # Check common locations
        common_paths = [
            Path("/d/Stocker Video Project/ffmpeg/bin/ffmpeg.exe"),
            Path("C:/ffmpeg/bin/ffmpeg.exe"),
            Path("D:/ffmpeg/bin/ffmpeg.exe"),
        ]

        for path in common_paths:
            if path.exists():
                logger.info(f"Found FFmpeg at: {path}")
                return path

        # Try to find in PATH
        try:
            result = subprocess.run(
                ["where", "ffmpeg"],
                capture_output=True,
                text=True,
                timeout=5
            )
            if result.returncode == 0:
                ffmpeg_path = Path(result.stdout.strip().split('\n')[0])
                if ffmpeg_path.exists():
                    logger.info(f"Found FFmpeg in PATH: {ffmpeg_path}")
                    return ffmpeg_path
        except:
            pass

        return None

    def get_total_duration(self, track_paths: List[str]) -> float:
        """Calculate total duration of tracks accounting for crossfade overlaps.

        Args:
            track_paths: List of audio file paths

        Returns:
            Total duration in seconds
        """
        durations = []
        for path in track_paths:
            duration = self._get_audio_duration(Path(path))
            durations.append(duration)

        # Account for crossfade overlaps (each crossfade reduces total by its duration)
        total = sum(durations)
        if len(durations) > 1:
            total -= (len(durations) - 1) * 2.0  # Assume 2s crossfade per overlap

        return total
