"""Small time-domain overlay; no browser, spectral data, or PNG frame sequence.

Astrofox references: CanvasAudio (window peaks), WaveParser (temporal EMA),
CanvasBars (bounded height and spacing). RMS and percentile scaling retain
the backend's existing approach; they are not claimed as Astrofox algorithms.
"""
from app.utils.ffmpeg import no_window_flags
import math
import subprocess
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image, ImageColor, ImageDraw, ImageFilter

from app.utils.ffmpeg import find_ffmpeg


def process_amplitudes(values, previous, filtered):
    """Bound both modes; optionally average neighbours and smooth over time."""
    values = np.clip(values, 0, 1)
    if filtered:
        values = np.convolve(np.pad(values, (1, 1), mode="edge"), [0.25, 0.5, 0.25], mode="valid")
        # WaveParser's buffer * smoothing + current * (1 - smoothing).
        # Quick response to notes, slower release avoids flicker between beats.
        weight = np.where(values > previous, .45, .22)
        values = previous * (1 - weight) + values * weight
    return values


def draw_waveform(values, width, height, bar_width, color, outline=None):
    image = Image.new("RGBA", (width, height))
    draw = ImageDraw.Draw(image)
    for x, amplitude in zip(np.linspace(0, width - bar_width, len(values)), values):
        bar_height = max(1, round(float(amplitude) * (height - 2)))
        top = (height - bar_height) // 2
        box = (round(x), top, round(x) + bar_width - 1, top + bar_height - 1)
        if bar_width == 1 or bar_height == 1:
            draw.rectangle(box, fill=color)
        else:
            draw.rounded_rectangle(box, radius=bar_width / 2, fill=color)
    if outline:
        edge = Image.new("RGBA", image.size)
        pen = ImageDraw.Draw(edge)
        for x, amplitude in zip(np.linspace(0, width - bar_width, len(values)), values):
            bar_height = max(1, round(float(amplitude) * (height - 2)))
            top = (height - bar_height) // 2
            pen.rounded_rectangle((round(x)-1, top-1, round(x)+bar_width, top+bar_height), radius=bar_width/2+1, fill=outline)
        image = Image.alpha_composite(edge, image)
    return image


def draw_radial(values, width, height, bar_width, color, outline=None):
    """Adapt Astrofox CanvasRadial's mirrored outward bars (MIT; see licenses).

    Shares the existing amplitude renderer/encoder; no browser or spectrum engine.
    """
    image = Image.new('RGBA', (width, height))
    draw = ImageDraw.Draw(image)
    center = width / 2
    inner = height * .20
    radius = height * .28
    count = len(values)
    step = math.tau / (count * 2)
    for i in range(count * 2):
        val = float(values[i if i < count else count * 2 - 1 - i])
        length = val * radius
        if length < .5:
            continue
        angle = step * (i + .3) - math.pi / 2
        c, s = math.cos(angle), math.sin(angle)
        draw.line((center+c*inner, height/2+s*inner,
                   center+c*(inner+length), height/2+s*(inner+length)), fill=color, width=bar_width)
    if outline:
        edge = Image.new("RGBA", image.size)
        pen = ImageDraw.Draw(edge)
        for i in range(count * 2):
            val = float(values[i if i < count else count * 2 - 1 - i])
            length = val * radius
            if length < .5:
                continue
            angle = step * (i + .3) - math.pi / 2
            c, s = math.cos(angle), math.sin(angle)
            pen.line((center+c*inner, height/2+s*inner, center+c*(inner+length), height/2+s*(inner+length)), fill=outline, width=bar_width+2)
        image = Image.alpha_composite(edge, image)
    return image


def create_waveform(audio_path: Path, job_dir: Path, settings, duration: float):
    """Stream 10 small RGBA frames/sec to lossless FFV1; save one PNG preview.

    PCM is disk-backed and reduced in chunks, keeping 90-minute jobs bounded
    in memory. Each frame displays the preceding 160 ms of real audio.
    """
    ffmpeg = str(find_ffmpeg())
    width = max(2, round(settings.video_width * min(.94, settings.waveform_width_ratio * settings.waveform_scale)))
    height = max(3, round(settings.video_height * settings.waveform_visual_height_ratio))
    if settings.waveform_style == "circular":
        width = height
    bar_width = min(settings.waveform_bar_width, max(1, width // 4))
    count = 32 if settings.waveform_style == "circular" else min(160, max(2, width // (bar_width + 3)))
    rgb = ImageColor.getrgb(settings.waveform_color.replace("0x", "#"))
    color = (*rgb[:3], round(255 * settings.waveform_opacity * (rgb[3] / 255 if len(rgb) == 4 else 1)))
    if not settings.waveform_animated:
        return create_static_waveform(audio_path, job_dir, settings, duration,
                                      width, height, bar_width, count, color, rgb)
    output = job_dir / "waveform.mkv"
    preview = job_dir / "waveform.png"
    fps = 10
    with tempfile.TemporaryDirectory(dir=job_dir, prefix="waveform_") as temporary:
        pcm = Path(temporary) / "audio.pcm"
        subprocess.run([ffmpeg, "-v", "error", "-y", "-i", str(audio_path),
                        "-t", str(duration), "-ac", "1", "-ar", "8000", "-f", "s16le", str(pcm)],
                       capture_output=True, check=True, timeout=max(60, duration / 5), **no_window_flags())
        if pcm.stat().st_size < 2:
            raise ValueError("No audio samples for waveform")
        samples = np.memmap(pcm, dtype="<i2", mode="r")
        envelopes = []
        # 1 ms RMS windows retain the time-domain shape of musical notes.
        # Long windows flatten sustained jazz notes into a volume meter.
        for start in range(0, len(samples), 800000):
            chunk = samples[start:start + 800000].astype(np.float32) / 32768
            chunk = np.pad(chunk, (0, (-len(chunk)) % 8)).reshape(-1, 8)
            envelopes.append(np.sqrt(np.mean(chunk * chunk, axis=1)))
        del samples
        envelope = np.concatenate(envelopes)
        # A fixed whole-track reference avoids frame-by-frame pumping and
        # refuses to amplify near-silence. Gentle compression, hard ceiling.
        reference = max(0.05, float(np.percentile(envelope, 98)))
        envelope = np.clip(envelope / reference, 0, 1) ** 0.8
        previous = np.zeros(count)
        preview_frame = min(math.ceil(duration * fps) - 1, 2 * fps)
        union = None
        with open(Path(temporary) / "encoder.log", "w+b") as errors:
            encoder = subprocess.Popen([ffmpeg, "-v", "error", "-y", "-f", "rawvideo",
                "-pixel_format", "rgba", "-video_size", f"{width}x{height}", "-framerate", str(fps),
                "-i", "pipe:0", "-an", "-c:v", "ffv1", '-threads', str(settings.render_cpu_threads), "-pix_fmt", "bgra", str(output)],
                stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=errors, **no_window_flags())
            try:
                for frame in range(math.ceil(duration * fps)):
                    if frame % fps == 0 and (job_dir / 'cancel.request').exists():
                        raise RuntimeError('Cancelled by user')
                    indices = np.linspace(frame / fps * 1000 - 159, frame / fps * 1000, count).astype(int)
                    values = envelope[np.clip(indices, 0, len(envelope) - 1)].copy()
                    values[indices < 0] = 0
                    previous = process_amplitudes(values, previous, settings.waveform_filter_enabled)
                    draw = draw_radial if settings.waveform_style == "circular" else draw_waveform
                    outline = (255, 255, 255, round(color[3] * .45)) if max(rgb[:3]) < 32 else None
                    image = draw(np.maximum(previous, settings.waveform_min_amplitude), width, height, bar_width, color, outline=outline)
                    bbox = image.getchannel("A").getbbox()
                    if bbox:
                        union = bbox if union is None else (min(union[0], bbox[0]), min(union[1], bbox[1]), max(union[2], bbox[2]), max(union[3], bbox[3]))
                    if frame == preview_frame:
                        image.save(preview)
                    encoder.stdin.write(image.tobytes())
                encoder.stdin.close()
                if encoder.wait(timeout=60):
                    errors.seek(0)
                    raise RuntimeError(errors.read().decode(errors="replace"))
            finally:
                if encoder.poll() is None:
                    encoder.kill()
                    encoder.wait()
                if not encoder.stdin.closed:
                    encoder.stdin.close()
    x = (settings.video_width - width) // 2
    y = max(0, min(settings.video_height - height, round(settings.video_height * settings.waveform_vertical_position_ratio - height / 2)))
    with Image.open(preview) as image:
        preview_bbox = image.getchannel("A").getbbox()
    return output, {
        "waveform_preview_path": str(preview.resolve()), "waveform_engine": "native_amplitude", "waveform_style": settings.waveform_style,
        "waveform_min_amplitude": settings.waveform_min_amplitude,
        "waveform_visual_height_ratio": settings.waveform_visual_height_ratio, "waveform_animated": True,
        "waveform_filter_enabled": settings.waveform_filter_enabled,
        "waveform_asset_dimensions": [width, height], "waveform_overlay_xy": [x, y],
        "waveform_visible_bbox": list(union) if union else None,
        "waveform_preview_bbox": list(preview_bbox) if preview_bbox else None,
        "waveform_bar_count": count, "waveform_bar_width": bar_width,
        "waveform_opacity": settings.waveform_opacity, "waveform_color": settings.waveform_color,
        "waveform_fps": fps, "waveform_preview_seconds": preview_frame / fps,
    }


def create_static_waveform(audio_path, job_dir, settings, duration, width, height, bar_width, count, color, rgb):
    """Aggregate bounded PCM chunks into one whole-track PNG, never Python video frames."""
    ffmpeg = str(find_ffmpeg())
    output = job_dir / 'waveform.png'
    with tempfile.TemporaryDirectory(dir=job_dir, prefix='waveform_') as temporary:
        pcm = Path(temporary) / 'audio.pcm'
        subprocess.run([ffmpeg, '-v', 'error', '-y', '-i', str(audio_path), '-t', str(duration),
                        '-ac', '1', '-ar', '8000', '-f', 's16le', str(pcm)],
                       capture_output=True, check=True, timeout=max(60, duration / 5), **no_window_flags())
        samples = np.memmap(pcm, dtype='<i2', mode='r')
        bounds = np.linspace(0, len(samples), count + 1).astype(int)
        amplitudes = []
        for start, end in zip(bounds, bounds[1:]):
            total = 0.0
            for offset in range(start, end, 800000):
                chunk = samples[offset:min(end, offset + 800000)].astype(np.float32) / 32768
                total += float(np.sum(chunk * chunk))
            amplitudes.append(math.sqrt(total / max(1, end-start)))
        del samples
    values = np.asarray(amplitudes)
    if settings.waveform_filter_enabled:
        values = np.convolve(np.pad(values, (1,1), mode='edge'), [.25,.5,.25], mode='valid')
    values = np.clip(values / max(.05, float(np.percentile(values,98))), settings.waveform_min_amplitude, 1)
    draw = draw_radial if settings.waveform_style == 'circular' else draw_waveform
    outline = (255,255,255,round(color[3]*.45)) if max(rgb[:3]) < 32 else None
    image = draw(values, width, height, bar_width, color, outline=outline)
    image.save(output)
    bbox = image.getchannel('A').getbbox()
    x = (settings.video_width-width)//2
    y = max(0, min(settings.video_height-height, round(settings.video_height*settings.waveform_vertical_position_ratio-height/2)))
    return output, dict(waveform_preview_path=str(output.resolve()), waveform_engine='whole_track_rms',
        waveform_style=settings.waveform_style, waveform_animated=False,
        waveform_filter_enabled=settings.waveform_filter_enabled, waveform_asset_dimensions=[width,height],
        waveform_overlay_xy=[x,y], waveform_visible_bbox=list(bbox) if bbox else None,
        waveform_preview_bbox=list(bbox) if bbox else None, waveform_bar_count=count,
        waveform_bar_width=bar_width, waveform_color=settings.waveform_color,
        waveform_opacity=settings.waveform_opacity, waveform_fps=0, waveform_preview_seconds=0)
