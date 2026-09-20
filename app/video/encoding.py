"""Small encoder capability probe and progress watchdog for the existing FFmpeg render."""
from app.utils.ffmpeg import no_window_flags
import json
import logging
import subprocess
import time
import os
import importlib.util
from pathlib import Path
from app.youtube.state import write_json

logger = logging.getLogger(__name__)
_backend_cache = {}


def encoder_args(encoder, settings):
    quality = str(settings.video_encoder_quality)
    if encoder == 'h264_nvenc':
        return ['-c:v', encoder, '-preset', 'p4', '-tune', 'hq', '-rc', 'vbr', '-cq', quality, '-b:v', '0']
    if encoder == 'h264_amf':
        return ['-c:v', encoder, '-quality', 'quality', '-rc', 'cqp', '-qp_i', quality, '-qp_p', quality]
    if encoder == 'h264_qsv':
        return ['-c:v', encoder, '-preset', 'veryfast', '-global_quality', quality]
    return ['-c:v', 'libx264', '-threads', str(settings.render_cpu_threads), '-preset', settings.ffmpeg_preset, '-crf', str(settings.ffmpeg_crf), '-tune', 'stillimage']


def choose_render_backend(ffmpeg, settings):
    """Try a packaged compatible NVENC build before falling back to other hardware."""
    key = (str(ffmpeg), settings.video_encoder, settings.video_width, settings.video_height,
           settings.video_fps, settings.video_encoder_quality)
    cached = _backend_cache.get(key)
    if cached and time.monotonic() - cached[0] < 300:
        return cached[1]
    result = _choose_render_backend(ffmpeg, settings)
    _backend_cache[key] = (time.monotonic(), result)
    return result


def _choose_render_backend(ffmpeg, settings):
    if settings.video_encoder in ('auto', 'h264_nvenc'):
        try:
            # Locate the packaged executable without the library's extra
            # platform/version subprocesses; our real encoder probe validates it.
            spec = importlib.util.find_spec('imageio_ffmpeg')
            if not spec or not spec.origin:
                raise ImportError('Optional bundled FFmpeg is not installed')
            candidates = sorted((Path(spec.origin).parent / 'binaries').glob('ffmpeg-win*.exe')) if os.name == 'nt' else []
            if not candidates:
                raise ImportError('No bundled Windows executable')
            candidate = str(candidates[-1])
            encoder, failures = choose_encoder(candidate, settings.model_copy(update={'video_encoder': 'h264_nvenc'}))
            if encoder == 'h264_nvenc':
                return candidate, encoder, failures
        except ImportError:
            pass
    encoder, failures = choose_encoder(ffmpeg, settings)
    if settings.video_encoder != 'auto' and settings.video_encoder != encoder:
        raise RuntimeError(f'Requested encoder {settings.video_encoder} could not initialize: {failures}')
    return ffmpeg, encoder, failures


def choose_encoder(ffmpeg, settings):
    """An actual encode detects unavailable GPU/driver support, not just compiled codecs."""
    requested = settings.video_encoder
    candidates = ['h264_nvenc', 'h264_amf', 'h264_qsv'] if requested == 'auto' else [requested]
    failures = {}
    for encoder in candidates:
        if encoder == 'libx264':
            return encoder, failures
        cmd = [str(ffmpeg), '-v', 'error', '-f', 'lavfi', '-i',
               f'color=c=black:s={settings.video_width}x{settings.video_height}:r={settings.video_fps}',
               '-frames:v', '3', *encoder_args(encoder, settings), '-pix_fmt', 'yuv420p', '-f', 'null', '-']
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=20, **no_window_flags())
            if result.returncode == 0:
                return encoder, failures
            failures[encoder] = result.stderr[-1200:]
        except (OSError, subprocess.TimeoutExpired) as error:
            failures[encoder] = str(error)
    logger.warning('Hardware encoding unavailable; using %s CPU preset. Details: %s', settings.ffmpeg_preset, failures)
    return 'libx264', failures


def _render_with_progress(cmd, directory, duration, settings):
    directory = Path(directory)
    timeout = max(3600, duration * settings.render_timeout_multiplier + 600)
    progress_path = directory / 'ffmpeg-progress.log'
    errors_path = directory / 'ffmpeg-render.log'
    command = [cmd[0], '-nostdin', '-nostats', '-stats_period', '2', '-progress', str(progress_path), *cmd[1:]]
    progress_path.write_text('')
    started = last_change = last_report = last_log = time.monotonic()
    last_frame = -1
    current = {}
    reason = None
    with errors_path.open('w+b') as errors, progress_path.open('r', encoding='utf-8', errors='replace') as progress:
        process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=errors, **no_window_flags())
        try:
            from app.video.resources import ResourceMonitor
            monitor = None
            owner = None
            if isinstance(process.pid, int):
                import psutil
                try:
                    monitor = ResourceMonitor(process.pid, settings)
                    owner = dict(pid=process.pid, created=psutil.Process(process.pid).create_time())
                except psutil.NoSuchProcess:
                    pass
            write_json(directory / 'render_progress.json', dict(status='running', owner=owner))
            while process.poll() is None:
                time.sleep(.5)
                for line in progress.readlines():
                    key, separator, value = line.strip().partition('=')
                    if separator:
                        current[key] = value
                now = time.monotonic()
                if (directory / 'cancel.request').exists():
                    reason = 'Cancelled by user'
                frame = int(current.get('frame', -1))
                if frame > last_frame:
                    last_frame, last_change = frame, now
                # Faststart may copy the completed MP4 before emitting the last update.
                near_end = frame >= max(1, int(duration * settings.video_fps) - 2 * settings.video_fps)
                stall_limit = max(settings.render_stall_timeout_seconds, duration * .1) if near_end or current.get('progress') == 'end' else settings.render_stall_timeout_seconds
                if now - started > timeout:
                    reason = f'Render exceeded its {timeout:.0f}s duration-based time limit'
                elif now - last_change > stall_limit:
                    reason = f'FFmpeg made no frame progress for {stall_limit:.0f}s'
                if reason:
                    process.kill()
                    break
                if now - last_report >= 5:
                    resources = monitor.sample() if monitor else {}
                    write_json(directory / 'render_progress.json', dict(current, status='running', owner=owner, resources=resources, elapsed_seconds=round(now-started, 1), timeout_seconds=timeout))
                    write_json(directory / 'render_resources.json', monitor.summary() if monitor else {})
                    if resources.get('gpu', {}).get('temperature_c', 0) >= settings.render_gpu_max_temperature or resources.get('ram_percent', 0) >= 98:
                        reason = 'Resource protection stopped this render: temperature or memory exceeded its limit. Prepared media is retained; retry after the machine cools down.'
                        process.kill()
                        break
                    last_report = now
                if now - last_log >= 30:
                    logger.info('Render progress: %s, speed %s', current.get('out_time', 'starting'), current.get('speed', 'pending'))
                    last_log = now
            code = process.wait()
        finally:
            if process.poll() is None:
                process.kill()
                process.wait()
        errors.seek(0, 2)
        errors.seek(max(0, errors.tell() - 6000))
        detail = errors.read().decode(errors='replace')
    write_json(directory / 'render_progress.json', dict(current, owner=owner, elapsed_seconds=round(time.monotonic()-started, 1), timeout_seconds=timeout, status='failed' if reason or code else 'complete', error=reason or (detail if code else None)))
    if reason or code:
        _backend_cache.clear()
        raise RuntimeError(f'{reason or "FFmpeg exited with code " + str(code)}. {detail}')
    return timeout


def render_with_progress(cmd, directory, duration, settings):
    """Cross-process render slots; queued work waits without changing output quality."""
    from contextlib import ExitStack
    from app.youtube.state import publishing_lock
    import psutil
    from app.video.resources import gpu_sample
    directory = Path(directory)
    while True:
        if (directory / 'cancel.request').exists():
            raise RuntimeError('Cancelled by user while queued')
        if psutil.virtual_memory().percent < 95 and gpu_sample().get('temperature_c', 0) < settings.render_gpu_max_temperature:
            for slot in range(settings.render_max_concurrent):
                with ExitStack() as stack:
                    try:
                        stack.enter_context(publishing_lock(Path('jobs/render_slots') / str(slot)))
                    except RuntimeError as error:
                        if 'Another YouTube publishing operation' not in str(error):
                            raise
                        continue
                    return _render_with_progress(cmd, directory, duration, settings)
        write_json(directory / 'render_progress.json', dict(status='queued', reason='Waiting for a render slot or lower resource pressure'))
        time.sleep(2)
