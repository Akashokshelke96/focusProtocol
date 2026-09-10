"""
Logging utilities
"""
import logging
import sys
import atexit
import signal
from datetime import datetime
from pathlib import Path
from collections import deque


RECENT_LOGS = deque(maxlen=1000)
_LIFECYCLE_REGISTERED = False


class RecentLogHandler(logging.Handler):
    """Keep recent server events available to the dashboard."""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            RECENT_LOGS.append({
                "timestamp": datetime.fromtimestamp(record.created).isoformat(timespec="seconds"),
                "level": record.levelname,
                "logger": record.name,
                "message": record.getMessage(),
            })
        except Exception:
            pass


def setup_logging(level: str = "INFO", log_dir: Path = None) -> logging.Logger:
    """Configure structured logging."""
    if log_dir is None:
        log_dir = Path("jobs")

    log_dir.mkdir(parents=True, exist_ok=True)

    global _LIFECYCLE_REGISTERED
    logger = logging.getLogger("youtube_automation")
    logger.setLevel(getattr(logging, level.upper(), logging.INFO))

    if not any(isinstance(handler, RecentLogHandler) for handler in logger.handlers):
        logger.addHandler(RecentLogHandler())

    # Console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(getattr(logging, level.upper(), logging.INFO))
    formatter = logging.Formatter(
        '[%(levelname)s] %(name)s - %(message)s'
    )
    console_handler.setFormatter(formatter)

    # File handler
    log_file = log_dir / f"app_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
    file_handler = logging.FileHandler(log_file)
    file_handler.setFormatter(formatter)

    if not any(type(handler) is logging.StreamHandler for handler in logger.handlers):
        logger.addHandler(console_handler)
    if not any(isinstance(handler, logging.FileHandler) for handler in logger.handlers):
        logger.addHandler(file_handler)

    if not _LIFECYCLE_REGISTERED:
        def log_exit() -> None:
            # Pytest and some launchers close stdout before Python runs atexit.
            # Keep lifecycle logging in the file/recent handlers without writing
            # through a closed console stream.
            for handler in logger.handlers:
                if type(handler) is logging.StreamHandler and getattr(handler, "stream", None) is not None:
                    if getattr(handler.stream, "closed", False):
                        continue
                try:
                    handler.handle(logger.makeRecord(
                        logger.name, logging.CRITICAL, __file__, 0,
                        "Application shutdown: process exit", (), None
                    ))
                except (ValueError, OSError):
                    pass

        def log_signal(signum, _frame) -> None:
            logger.critical("Application received termination signal: %s", signum)
            raise SystemExit(128 + signum)

        atexit.register(log_exit)
        for signal_name in ("SIGINT", "SIGTERM"):
            signal_value = getattr(signal, signal_name, None)
            if signal_value is not None:
                signal.signal(signal_value, log_signal)
        _LIFECYCLE_REGISTERED = True

    return logger


def get_logger(name: str) -> logging.Logger:
    """Get logger for a module."""
    return logging.getLogger(f"youtube_automation.{name}")


def get_recent_logs(limit: int = 200) -> list[dict]:
    """Return the newest captured server events for the UI."""
    return list(RECENT_LOGS)[-limit:]
