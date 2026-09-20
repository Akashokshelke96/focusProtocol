"""Cached six-second decorative animation. No audio input or analysis."""
from app.utils.ffmpeg import no_window_flags
import math
import subprocess
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw
from app.utils.ffmpeg import find_ffmpeg


def animation_frame(index, fps, width=420, height=110):
    """Integer temporal harmonics make motion periodic across the seam."""
    phase = math.tau * index / (6 * fps)
    image = Image.new('RGBA', (width, height))
    draw = ImageDraw.Draw(image)
    count = 48
    step = width / count
    bar_width = max(3, round(step * .46))
    for bar in range(count):
        x = round((bar + .5) * step - bar_width / 2)
        envelope = .4 + .6 * math.sin(math.pi * (bar + .5) / count)
        motion = .5 + .27 * math.sin(phase + bar * .43) + .18 * math.sin(2 * phase - bar * .27)
        size = max(bar_width, round((height - 8) * envelope * (.14 + .82 * motion)))
        top = (height - size) // 2
        draw.rounded_rectangle((x-1, top-1, x+bar_width, top+size), radius=bar_width/2+1, fill=(0, 0, 0, 85))
        draw.rounded_rectangle((x, top, x+bar_width-1, top+size-1), radius=bar_width/2, fill=(255, 255, 255, 235))
    return image


def prepare_visualizer(settings, cache=None):
    """Generate only six seconds, once per FPS/version; retain true alpha."""
    if not settings.visualizer_enabled:
        return None
    fps = settings.video_fps
    folder = Path(cache) if cache is not None else Path(__file__).resolve().parents[2] / 'asset' / 'generated'
    folder.mkdir(parents=True, exist_ok=True)
    asset = folder / f'waveform_6s_v1_{fps}fps.mov'
    if not asset.is_file() or asset.stat().st_size == 0:
        with tempfile.NamedTemporaryFile(dir=folder, suffix='.mov', delete=False) as temp:
            temporary = Path(temp.name)
        try:
            command = [str(find_ffmpeg()), '-v', 'error', '-y', '-f', 'rawvideo',
                       '-pix_fmt', 'rgba', '-s', '420x110', '-r', str(fps), '-i', '-',
                       '-an', '-frames:v', str(6*fps), '-c:v', 'qtrle', '-pix_fmt', 'argb', str(temporary)]
            # One small frame in memory. No PNG sequence or audio subprocess.
            with tempfile.TemporaryFile() as errors:
                process = subprocess.Popen(command, stdin=subprocess.PIPE, stderr=errors, **no_window_flags())
                try:
                    for frame in range(6 * fps):
                        process.stdin.write(animation_frame(frame, fps).tobytes())
                    process.stdin.close()
                    if process.wait(timeout=120):
                        errors.seek(0)
                        raise RuntimeError(errors.read().decode(errors='replace'))
                finally:
                    if process.poll() is None:
                        process.kill()
                        process.wait()
            temporary.replace(asset)
        finally:
            temporary.unlink(missing_ok=True)
    width = max(2, round(settings.video_width * settings.visualizer_loop_width_ratio))
    height = max(2, round(width * 110 / 420))
    return dict(path=str(asset.resolve()), width=width, height=height,
                x=round(settings.video_width * settings.visualizer_left_padding_ratio),
                bottom=round(settings.video_height * settings.visualizer_loop_bottom_padding_ratio),
                opacity=settings.visualizer_opacity, duration_seconds=6, fps=fps,
                transparent=True, audio_reactive=False, music_disc_enabled=False)


def add_visualizer(cmd, filters, label, group, input_index, offset):
    """Loop only the overlay independently of the background timeline."""
    if group is None:
        return label
    cmd.extend(['-stream_loop', '-1', '-ss', str(round(offset % 6, 6)), '-i', group['path']])
    filters.append(f'[{input_index}:v]setpts=PTS-STARTPTS,format=rgba,'
                   f"scale={group['width']}:{group['height']},colorchannelmixer=aa={group['opacity']}[soundwave]")
    filters.append(f"[{label}][soundwave]overlay=x={group['x']}:y=H-h-{group['bottom']}:"
                   'shortest=1:format=auto[with_vis]')
    return 'with_vis'
