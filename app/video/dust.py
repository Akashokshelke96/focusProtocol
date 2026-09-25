"""Small cached, periodic transparent dust asset; baked into the short clip."""
import math
import random
import subprocess
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter
from app.utils.ffmpeg import find_ffmpeg, no_window_flags


def dust_frame(index, fps=30, width=640, height=360):
    rng = random.Random(7319)
    phase = math.tau * (index % (6 * fps)) / (6 * fps)
    image = Image.new('RGBA', (width, height))
    draw = ImageDraw.Draw(image)
    for _ in range(45):
        x, y = rng.uniform(10, width-10), rng.uniform(10, height-10)
        offset = rng.uniform(0, math.tau)
        x += 5 * math.sin(phase+offset)
        y += 3 * math.cos(phase+offset)
        radius = rng.uniform(.8, 2.2)
        draw.ellipse((x-radius, y-radius, x+radius, y+radius),
                     fill=(255, 255, 255, rng.randint(100, 210)))
    # Blur alpha only: keep white RGB to avoid dark fringes when compositing.
    alpha = image.getchannel('A').filter(ImageFilter.GaussianBlur(.8))
    image.paste((255, 255, 255), (0, 0, width, height))
    image.putalpha(alpha)
    return image


def prepare_dust(settings):
    if not settings.dust_enabled:
        return None
    asset = Path(__file__).resolve().parents[2] / 'asset' / 'dust_6s.mov'
    asset.parent.mkdir(parents=True, exist_ok=True)
    if not asset.is_file() or not asset.stat().st_size:
        with tempfile.NamedTemporaryFile(dir=asset.parent, suffix='.mov', delete=False) as temp:
            temporary = Path(temp.name)
        try:
            command = [str(find_ffmpeg()), '-v', 'error', '-y', '-f', 'rawvideo',
                       '-pix_fmt', 'rgba', '-s', '640x360', '-r', '30', '-i', '-',
                       '-an', '-frames:v', '180', '-c:v', 'qtrle', '-pix_fmt', 'argb', str(temporary)]
            with tempfile.TemporaryFile() as errors:
                process = subprocess.Popen(command, stdin=subprocess.PIPE, stderr=errors, **no_window_flags())
                try:
                    for index in range(180):
                        process.stdin.write(dust_frame(index).tobytes())
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
    return dict(path=str(asset), opacity=settings.dust_opacity, duration_seconds=6)
