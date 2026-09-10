"""Small time-domain overlay; no browser, spectral data, or PNG frame sequence.

Astrofox references: CanvasAudio (window peaks), WaveParser (temporal EMA),
CanvasBars (bounded height and spacing). RMS and percentile scaling retain
the backend's existing approach; they are not claimed as Astrofox algorithms.
"""
import math
import subprocess
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image, ImageColor, ImageDraw

from app.utils.ffmpeg import find_ffmpeg


def process_amplitudes(values, previous, filtered):
    """Bound both modes; optionally average neighbours and smooth over time."""
    values = np.clip(values, 0, 1)
    if filtered:
        values = np.convolve(np.pad(values, (1, 1), mode="edge"), [0.25, 0.5, 0.25], mode="valid")
        # WaveParser's buffer * smoothing + current * (1 - smoothing).
        values = previous * 0.55 + values * 0.45
    return values


def draw_waveform(values, width, height, bar_width, color):
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
    return image


def create_waveform(audio_path: Path, job_dir: Path, settings, duration: float):
    """Stream 10 small RGBA frames/sec to lossless FFV1; save one PNG preview.

    PCM is disk-backed and reduced in chunks, keeping 90-minute jobs bounded
    in memory. Each frame displays the preceding 160 ms of real audio.
    """
    ffmpeg = str(find_ffmpeg())
    width = max(2, round(settings.video_width * settings.waveform_width_ratio))
    height = max(3, round(settings.video_height * settings.waveform_height_ratio))
    bar_width = min(settings.waveform_bar_width, max(1, width // 4))
    count = min(160, max(2, width // (bar_width + 3)))
    rgb = ImageColor.getrgb(settings.waveform_color.replace("0x", "#"))
    color = (*rgb[:3], round(255 * settings.waveform_opacity * (rgb[3] / 255 if len(rgb) == 4 else 1)))
    output = job_dir / "waveform.mkv"
    preview = job_dir / "waveform.png"
    fps = 10
    with tempfile.TemporaryDirectory(dir=job_dir, prefix="waveform_") as temporary:
        pcm = Path(temporary) / "audio.pcm"
        subprocess.run([ffmpeg, "-v", "error", "-y", "-i", str(audio_path),
                        "-t", str(duration), "-ac", "1", "-ar", "8000", "-f", "s16le", str(pcm)],
                       capture_output=True, check=True, timeout=max(60, duration / 5))
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
                "-i", "pipe:0", "-an", "-c:v", "ffv1", "-pix_fmt", "bgra", str(output)],
                stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=errors)
            try:
                for frame in range(math.ceil(duration * fps)):
                    indices = np.linspace(frame / fps * 1000 - 159, frame / fps * 1000, count).astype(int)
                    values = envelope[np.clip(indices, 0, len(envelope) - 1)].copy()
                    values[indices < 0] = 0
                    previous = process_amplitudes(values, previous, settings.waveform_filter_enabled)
                    image = draw_waveform(previous, width, height, bar_width, color)
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
    y = round(settings.video_height * settings.waveform_vertical_position_ratio - height / 2)
    with Image.open(preview) as image:
        preview_bbox = image.getchannel("A").getbbox()
    return output, {
        "waveform_engine": "native_amplitude", "waveform_animated": True,
        "waveform_filter_enabled": settings.waveform_filter_enabled,
        "waveform_asset_dimensions": [width, height], "waveform_overlay_xy": [x, y],
        "waveform_visible_bbox": list(union) if union else None,
        "waveform_preview_bbox": list(preview_bbox) if preview_bbox else None,
        "waveform_bar_count": count, "waveform_bar_width": bar_width,
        "waveform_opacity": settings.waveform_opacity, "waveform_color": settings.waveform_color,
        "waveform_fps": fps, "waveform_preview_seconds": preview_frame / fps,
    }
