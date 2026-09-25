"""Optional, silent WebM instances on the final video timeline."""
import math
import re
import subprocess
from pathlib import Path

from app.config.logging_config import get_logger
from app.utils.ffmpeg import no_window_flags, probe_media
from app.video.encoding import encoder_args

logger = get_logger('video.subscribe_overlay')


def files(settings):
    path = Path(settings.subscribe_overlay_path)
    if path.is_file():
        return [path] if path.suffix.lower() == '.webm' else []
    return sorted((p for p in path.iterdir() if p.is_file() and p.suffix.lower() == '.webm'),
                  key=lambda p: p.name.lower()) if path.is_dir() else []


def schedule(target, interval, start=None):
    start = interval if start is None else start
    return [start + i * interval for i in range(max(0, math.ceil((target-start)/interval)))]


def record_fallback(metadata, reason):
    logger.warning('Subscribe overlay file not found or could not be processed. Rendering video without subscribe overlay. %s', reason)
    metadata.update(subscribe_overlay_enabled=False, subscribe_overlay_fallback=str(reason)[-2000:])


def prepare(settings, target, ffmpeg, ffprobe, metadata):
    metadata['subscribe_overlay_enabled'] = False
    if not settings.subscribe_overlay_enabled:
        return None
    starts = schedule(target, settings.subscribe_overlay_interval_seconds,
                      settings.subscribe_overlay_start_after_seconds)
    if not starts:
        return None
    try:
        candidates = files(settings)
        selected = settings.subscribe_overlay_file
        path = next((p for p in candidates if p.name == selected), None) if selected else next(iter(candidates), None)
        if path is None:
            raise ValueError('Subscribe overlay file not found')
        info = probe_media(path, ffprobe)
        stream = next(s for s in info['streams'] if s['codec_type'] == 'video')
        duration = float(stream.get('duration') or info['format']['duration'])
        if not math.isfinite(duration) or duration <= 0:
            raise ValueError('Invalid WebM duration')
        decoder = {'vp8': 'libvpx', 'vp9': 'libvpx-vp9'}[stream['codec_name']]
        # Native VP8/VP9 decoders can discard alpha; explicitly use libvpx.
        alpha = any(k.lower() == 'alpha_mode' and str(v) == '1' for k, v in stream.get('tags', {}).items())
        check = subprocess.run([str(ffmpeg), '-hide_banner', '-v', 'info' if alpha else 'error',
                                '-c:v', decoder, '-i', str(path), '-map', '0:v:0', '-an',
                                *(['-vf', 'alphaextract,cropdetect=limit=0.001:round=2:reset=0:skip=0'] if alpha else []),
                                '-f', 'null', '-'], capture_output=True, text=True,
                               check=True, timeout=60, **no_window_flags())
        crop = None
        source_w, source_h = stream['width'], stream['height']
        bounds = re.findall(r'x1:(\d+) x2:(\d+) y1:(\d+) y2:(\d+)', check.stderr) if alpha else []
        if bounds:
            x1, x2, y1, y2 = map(int, bounds[-1])
            if x2 >= x1 and y2 >= y1:
                # Expand to even boundaries so chroma rounding never clips alpha edges.
                x, y = (x1//2)*2, (y1//2)*2
                source_w = min(stream['width'], ((x2+2)//2)*2)-x
                source_h = min(stream['height'], ((y2+2)//2)*2)-y
                crop = f'{source_w}:{source_h}:{x}:{y}'
        w, h = settings.video_width, settings.video_height
        right, bottom = round(w*settings.subscribe_overlay_right_padding_ratio), round(h*settings.subscribe_overlay_bottom_padding_ratio)
        factor = min(w*settings.subscribe_overlay_width_ratio/source_w,
                     (h-bottom)/source_h, (w-right)/source_w)
        ow, oh = max(1, round(source_w*factor)), max(1, round(source_h*factor))
        result = dict(path=str(path), decoder=decoder, starts=starts, crop=crop,
                      duration=min(duration, settings.subscribe_overlay_interval_seconds),
                      width=ow, height=oh, x=w-ow-right, y=h-oh-bottom)
        metadata.update(subscribe_overlay_enabled=True, subscribe_overlay_file=str(path),
                        subscribe_overlay_starts=starts, subscribe_animation_duration=duration,
                        subscribe_overlay_interval_seconds=settings.subscribe_overlay_interval_seconds,
                        subscribe_overlay_alpha_crop=crop,
                        subscribe_overlay_bounds=[result['x'], result['y'], ow, oh],
                        subscribe_overlay_position='bottom_right', subscribe_overlay_audio_muted=True)
        return result
    except (OSError, ValueError, KeyError, StopIteration, subprocess.SubprocessError) as error:
        record_fallback(metadata, error)
        return None


def overlay_command(backend, settings, video, audio, output, target, encoder, overlay):
    cmd = [str(backend), '-y', '-filter_complex_threads', str(settings.render_cpu_threads),
           '-i', str(video), '-i', str(audio)]
    filters, previous = [], '0:v'
    for i, start in enumerate(overlay['starts']):
        cmd += ['-threads', '1', '-c:v', overlay['decoder'], '-i', overlay['path']]
        duration = min(overlay['duration'], target-start)
        crop = f"crop={overlay['crop']}," if overlay.get('crop') else ''
        filters.append(f"[{i+2}:v]setpts=PTS-STARTPTS,trim=duration={duration},"
                       f"{crop}scale={overlay['width']}:{overlay['height']},format=yuva420p,"
                       f"setpts=PTS+{start}/TB[sub{i}]")
        filters.append(f"[{previous}][sub{i}]overlay=x={overlay['x']}:y={overlay['y']}:"
                       f"eof_action=pass:repeatlast=0:enable='gte(t,{start})*lt(t,{start+duration})'[v{i}]")
        previous = f'v{i}'
    return cmd + ['-filter_complex', ';'.join(filters), '-map', f'[{previous}]',
                  '-map', '1:a:0', *encoder_args(encoder, settings), '-pix_fmt', 'yuv420p',
                  '-c:a', 'copy', '-t', str(target), '-movflags', '+faststart', str(output)]
