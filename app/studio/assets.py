"""Small local thumbnails and bounded QC. No network providers."""
import json
import subprocess
from datetime import datetime, timezone
from fractions import Fraction
from pathlib import Path
from PIL import Image, ImageOps, ImageDraw, ImageFont
from app.utils.ffmpeg import find_ffprobe, find_ffmpeg
from app.youtube.publishing import validate_video
from app.youtube.state import write_json


def make_thumbnail(source, output, title, channel):
    image = ImageOps.fit(Image.open(source).convert('RGB'), (1280, 720))
    shade = Image.new('RGBA', image.size)
    draw = ImageDraw.Draw(shade)
    for y in range(720):
        draw.line((0, y, 1280, y), fill=(0, 0, 0, round(210 * (y / 720) ** 1.5)))
    image = Image.alpha_composite(image.convert('RGBA'), shade)
    draw = ImageDraw.Draw(image)
    font_path = Path('C:/Windows/Fonts/arialbd.ttf')
    font = ImageFont.truetype(str(font_path), 66) if font_path.exists() else ImageFont.load_default()
    small = ImageFont.truetype(str(font_path), 24) if font_path.exists() else font
    import textwrap
    title = ' '.join(title.split()[:6])
    words, lines, line = textwrap.wrap(title, 24, break_long_words=True), [], ''
    words = ' '.join(words).split()
    for word in words:
        candidate = (line + ' ' + word).strip()
        if draw.textlength(candidate, font=font) > 1120 and line:
            lines.append(line); line = word
        else:
            line = candidate
    lines.append(line)
    lines = lines[:3]
    y = 605 - 78 * len(lines)
    draw.rectangle((70, y - 32, 140, y - 26), fill=channel['thumbnail_color'])
    for line in lines:
        draw.text((65, y), line, fill='white', font=font, stroke_width=1)
        y += 78
    draw.text((70, 648), channel['name'].upper(), fill=channel['thumbnail_color'], font=small)
    image.convert('RGB').save(output, optimize=True)


def qc_job(directory, row, metadata):
    checks = []
    def check(name, condition, detail=''):
        checks.append({'name': name, 'status': 'pass' if condition else 'fail', 'detail': detail})
    try:
        validate_video(row['video_path'], row)
        check('Playable MP4 and metadata', True)
        probe = subprocess.run([str(find_ffprobe()), '-v', 'error', '-show_streams', '-show_format', '-of', 'json', row['video_path']], capture_output=True, text=True, check=True, timeout=60)
        data = json.loads(probe.stdout)
        video = next(s for s in data['streams'] if s['codec_type'] == 'video')
        audio = next(s for s in data['streams'] if s['codec_type'] == 'audio')
        config = metadata.get('render_config', {})
        check('Resolution', video['width'] == config.get('video_width', video['width']) and video['height'] == config.get('video_height', video['height']), f"{video['width']} × {video['height']}")
        fps = float(Fraction(video['avg_frame_rate']))
        check('Frame rate', abs(fps - config.get('video_fps', fps)) < .1, f'{fps:g} FPS')
        duration = float(data['format']['duration'])
        target = metadata.get('target_duration_seconds', duration)
        check('Target duration', abs(duration - target) <= 5, f'{duration:.2f} seconds')
        check('Audio duration', abs(float(audio.get('duration', duration)) - target) <= 5, f"{audio.get('codec_name')} · {audio.get('channels')} channels")
        if metadata.get('selected_images') is not None:
            check('One background', len(metadata['selected_images']) == 1)
        if metadata.get('visualization_config', {}).get('waveform_enabled'):
            check('Waveform', bool(metadata.get('waveform_enabled')))
        thumbnail = Path(row.get('thumbnail_path') or '')
        if thumbnail.is_file():
            with Image.open(thumbnail) as image:
                check('Thumbnail dimensions', image.width >= 640 and abs(image.width / image.height - 16/9) < .1, f'{image.width} × {image.height}')
        else:
            check('Thumbnail exists', False)
        # Decode three short samples, including the end, without scanning hours of frames.
        for offset in (0, max(0, duration / 2), max(0, duration - 2)):
            decode = subprocess.run([str(find_ffmpeg()), '-v', 'error', '-xerror', '-ss', str(offset), '-i', row['video_path'], '-t', '1', '-f', 'null', '-'], capture_output=True, timeout=30)
            check(f'Decode sample at {offset:.0f}s', decode.returncode == 0)
    except Exception as error:
        check('Media validation', False, str(error))
    if metadata.get('fallback_used'):
        checks.append({'name': 'Local image fallback', 'status': 'warning', 'detail': 'Review image and channel fit before publishing.'})
    fingerprint = []
    for value in (row.get('video_path'), row.get('thumbnail_path')):
        path = Path(value or '')
        fingerprint.append([str(path), path.stat().st_size, path.stat().st_mtime_ns] if path.is_file() else None)
    result = {'fingerprint': fingerprint, 'status': 'fail' if any(c['status'] == 'fail' for c in checks) else ('warning' if any(c['status'] == 'warning' for c in checks) else 'pass'),
              'checks': checks, 'checked_at': datetime.now(timezone.utc).isoformat(), 'scope': 'Stream checks and three decode samples; not a full-frame corruption or copyright scan.'}
    write_json(Path(directory) / 'qc.json', result)
    return result
