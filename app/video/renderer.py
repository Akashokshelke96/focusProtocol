"""
FFmpeg video renderer
"""
from app.utils.ffmpeg import no_window_flags
from pathlib import Path
from typing import Optional, List
import subprocess
import json
from app.config.settings import Settings
from app.config.logging_config import get_logger

logger = get_logger("video.renderer")


class FFmpegRenderer:
    """Handles video rendering with FFmpeg."""

    def __init__(self, settings: Settings):
        """Initialize renderer."""
        self.settings = settings
        logger.info("FFmpeg renderer initialized")

    def render_final_video(
        self,
        video_path: Path,
        audio_path: Path,
        subtitle_path: Optional[Path],
        output_path: Path,
    ) -> bool:
        """Render final video with audio and subtitles."""
        logger.info("Rendering final video")

        try:
            # Build FFmpeg command
            cmd = [
                "ffmpeg",
                "-i", str(video_path),
                "-i", str(audio_path),
                "-c:v", "libx264",
                "-preset", "medium",
                "-crf", "23",
                "-c:a", "aac",
                "-b:a", "192k",
                "-shortest",
            ]

            # Add subtitle filter if provided
            if subtitle_path and subtitle_path.exists():
                cmd.extend([
                    "-vf", f"subtitles={str(subtitle_path)}",
                ])

            cmd.extend(["-y", str(output_path)])

            logger.info(f"Running FFmpeg: {' '.join(cmd)}")
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=600, **no_window_flags())

            if result.returncode != 0:
                logger.error(f"FFmpeg error: {result.stderr}")
                return False

            logger.info(f"Video rendered: {output_path}")
            return True

        except subprocess.TimeoutExpired:
            logger.error("FFmpeg rendering timed out")
            return False
        except Exception as e:
            logger.error(f"Rendering failed: {e}")
            return False

    def probe_video(self, video_path: Path) -> Optional[dict]:
        """Get video information using ffprobe."""
        try:
            result = subprocess.run(
                [
                    "ffprobe",
                    "-v", "error",
                    "-select_streams", "v:0",
                    "-show_entries",
                    "stream=width,height,avg_frame_rate,duration",
                    "-show_entries",
                    "format=duration",
                    "-of", "json",
                    str(video_path),
                ],
                capture_output=True,
                text=True,
                timeout=10,
             **no_window_flags())

            if result.returncode != 0:
                logger.warning(f"ffprobe failed: {result.stderr}")
                return None

            data = json.loads(result.stdout)
            return data

        except Exception as e:
            logger.error(f"ffprobe error: {e}")
            return None

    def concatenate_videos(
        self,
        video_files: List[Path],
        output_path: Path,
    ) -> bool:
        """Concatenate multiple video files."""
        logger.info(f"Concatenating {len(video_files)} videos")

        try:
            # Create concat demuxer file
            concat_file = output_path.parent / "concat.txt"
            with open(concat_file, "w") as f:
                for vf in video_files:
                    f.write(f"file '{vf.absolute()}'\n")

            cmd = [
                "ffmpeg",
                "-f", "concat",
                "-safe", "0",
                "-i", str(concat_file),
                "-c", "copy",
                "-y",
                str(output_path),
            ]

            result = subprocess.run(cmd, capture_output=True, text=True, timeout=300, **no_window_flags())

            concat_file.unlink()

            if result.returncode != 0:
                logger.error(f"FFmpeg error: {result.stderr}")
                return False

            logger.info(f"Videos concatenated: {output_path}")
            return True

        except Exception as e:
            logger.error(f"Concatenation failed: {e}")
            return False
