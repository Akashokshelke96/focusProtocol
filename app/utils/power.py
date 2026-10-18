"""Keep Windows awake during long renders (no-op elsewhere)."""
import logging
from contextlib import contextmanager

logger = logging.getLogger(__name__)


@contextmanager
def keep_awake(reason="video generation"):
    """Prevent system sleep while a generation runs.

    A sleeping PC freezes the pipeline mid-stage (file mtimes prove a
    ~20h stall with zero progress), inflates stage timers, and leaves the
    GPU in a state that stalls NVENC on wake. Screen may still turn off;
    only sleep/away-mode is blocked. Restored on exit, including on error.
    """
    requested = False
    try:
        import ctypes
        kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
        ES_CONTINUOUS = 0x80000000
        ES_SYSTEM_REQUIRED = 0x00000001
        previous = kernel32.SetThreadExecutionState(ES_CONTINUOUS | ES_SYSTEM_REQUIRED)
        requested = bool(previous)
        if not requested:
            logger.warning('Could not request execution state: %s', reason)
    except (OSError, AttributeError) as error:
        logger.debug('Stay-awake unavailable on this platform: %s', error)
    try:
        yield requested
    finally:
        try:
            import ctypes
            kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
            kernel32.SetThreadExecutionState(0x80000000)
        except (OSError, AttributeError):
            pass


def free_gb(path):
    """Free disk space in GB for the filesystem holding path."""
    import shutil
    return shutil.disk_usage(str(path)).free / (1024 ** 3)


def require_scratch_space(directory, target_minutes, per_minute_gb=0.15, floor_gb=5.0):
    """Fail fast before a render that cannot fit its temp files.

    An 83-minute render stages ~10 GB of intermediates; starting one with
    20 GB free on C: risks a mid-render crash. Raise with a clear message
    instead.
    """
    from pathlib import Path
    need = max(floor_gb, target_minutes * per_minute_gb)
    free = free_gb(Path(directory))
    if free < need:
        raise RuntimeError(
            f'Only {free:.1f} GB free for render scratch; need ~{need:.1f} GB. '
            'Free disk space or delete old jobs before generating.')
    return free
