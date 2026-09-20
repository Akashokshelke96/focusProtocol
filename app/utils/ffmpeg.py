"""
FFmpeg utilities - Find and manage FFmpeg executable path
"""
import subprocess
import os
import json
from functools import lru_cache
from copy import deepcopy
from pathlib import Path
from typing import Optional
from app.config.logging_config import get_logger

logger = get_logger("utils.ffmpeg")

# Global FFmpeg path cache
_ffmpeg_path = None
_ffprobe_path = None


def no_window_flags():
    """Suppress child console windows without changing streams or commands."""
    return {'creationflags': getattr(subprocess, 'CREATE_NO_WINDOW', 0)} if os.name == 'nt' else {}


def probe_media(path, executable=None):
    """Reuse successful probes only while the file identity and timestamps agree."""
    path = Path(path).resolve()
    stat = path.stat()
    return deepcopy(_probe_cached(str(path), stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns,
                                  str(executable or find_ffprobe())))


@lru_cache(maxsize=256)
def _probe_cached(path, size, modified, created, executable):
    result = subprocess.run([executable, '-v', 'error', '-show_streams', '-show_format',
                             '-of', 'json', path], capture_output=True, text=True,
                            check=True, timeout=60, **no_window_flags())
    return json.loads(result.stdout)


def find_ffmpeg() -> Optional[Path]:
    """Find FFmpeg executable in common locations.

    Returns:
        Path to FFmpeg executable, or None if not found
    """
    global _ffmpeg_path

    if _ffmpeg_path:
        return _ffmpeg_path

    # Check common locations (use both forward and backslash for Windows compatibility)
    common_paths = [
        Path(__file__).resolve().parents[2] / "ffmpeg" / "bin" / "ffmpeg.exe",
        Path(r"d:\Stocker Video Project\ffmpeg\bin\ffmpeg.exe"),
        Path("D:\\ffmpeg\\bin\\ffmpeg.exe"),
        Path("C:\\ffmpeg\\bin\\ffmpeg.exe"),
        Path("/d/Stocker Video Project/ffmpeg/bin/ffmpeg.exe"),
        Path("C:/ffmpeg/bin/ffmpeg.exe"),
        Path("D:/ffmpeg/bin/ffmpeg.exe"),
        Path("/usr/bin/ffmpeg"),
        Path("/usr/local/bin/ffmpeg"),
    ]

    for path in common_paths:
        try:
            if path.exists():
                logger.info(f"Found FFmpeg at: {path}")
                _ffmpeg_path = path
                return _ffmpeg_path
        except Exception as e:
            logger.debug(f"Failed to check path {path}: {e}")

    # Try to find in PATH
    try:
        result = subprocess.run(
            ["where", "ffmpeg"] if Path("C:\\Windows").exists() else ["which", "ffmpeg"],
            capture_output=True,
            text=True,
            timeout=5
        , **no_window_flags())
        if result.returncode == 0:
            ffmpeg_path = Path(result.stdout.strip().split('\n')[0])
            if ffmpeg_path.exists():
                logger.info(f"Found FFmpeg in PATH: {ffmpeg_path}")
                _ffmpeg_path = ffmpeg_path
                return _ffmpeg_path
    except Exception as e:
        logger.debug(f"Failed to find FFmpeg in PATH: {e}")

    logger.error("FFmpeg not found in any common location")
    return None


def get_ffmpeg_path() -> Path:
    """Get FFmpeg path, raising error if not found.

    Returns:
        Path to FFmpeg executable

    Raises:
        RuntimeError if FFmpeg is not found
    """
    path = find_ffmpeg()
    if not path:
        raise RuntimeError("FFmpeg not found. Please install FFmpeg from https://ffmpeg.org/download.html")
    return path


def find_ffprobe() -> Optional[Path]:
    """Find the ffprobe executable next to FFmpeg or on PATH."""
    global _ffprobe_path
    if _ffprobe_path:
        return _ffprobe_path

    ffmpeg_path = find_ffmpeg()
    if ffmpeg_path:
        sibling = ffmpeg_path.with_name("ffprobe.exe" if ffmpeg_path.suffix.lower() == ".exe" else "ffprobe")
        if sibling.exists():
            _ffprobe_path = sibling
            return _ffprobe_path

    try:
        result = subprocess.run(
            ["where", "ffprobe"] if Path("C:\\Windows").exists() else ["which", "ffprobe"],
            capture_output=True,
            text=True,
            timeout=5,
         **no_window_flags())
        if result.returncode == 0:
            candidate = Path(result.stdout.strip().split("\n")[0])
            if candidate.exists():
                _ffprobe_path = candidate
                return _ffprobe_path
    except Exception as error:
        logger.debug("Failed to find ffprobe in PATH: %s", error)
    return None
