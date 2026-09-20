"""Small local thumbnails and bounded QC. No network providers."""
from app.utils.ffmpeg import no_window_flags
import json
import subprocess
from datetime import datetime, timezone
from fractions import Fraction
from pathlib import Path
from PIL import Image, ImageOps, ImageDraw, ImageFont
from app.utils.ffmpeg import find_ffprobe, find_ffmpeg
from app.youtube.publishing import validate_video
from app.youtube.state import write_json


def asset_sha256(path):
    import hashlib
    with Path(path).open('rb') as stream:
        digest = hashlib.sha256()
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
        return digest.hexdigest()


def copy_thumbnail(source, output):
    """Atomically copy immutable artwork, preserving every byte."""
    import os, shutil, tempfile
    source, output = Path(source), Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    expected = asset_sha256(source)
    if source.resolve() == output.resolve():
        return expected
    fd, temporary = tempfile.mkstemp(dir=output.parent, suffix='.tmp')
    os.close(fd)
    try:
        shutil.copyfile(source, temporary)
        if asset_sha256(temporary) != expected:
            raise ValueError('Artwork copy SHA-256 mismatch')
        os.replace(temporary, output)
    finally:
        Path(temporary).unlink(missing_ok=True)
    return expected


def verify_job_assets(metadata):
    """Fail explicitly on missing/changed assigned artwork; never silently reselect."""
    assets = metadata.get('assets', {})
    if assets and set(assets) != {'background', 'thumbnail'}:
        raise ValueError('Job must have exactly one assigned background and thumbnail')
    for kind, record in assets.items():
        alias = 'thumbnail_path' if kind == 'thumbnail' else 'generated_background_path'
        if metadata.get(alias) and Path(metadata[alias]).resolve() != Path(record['path']).resolve():
            raise ValueError(f'Job {kind} reference differs from its immutable assignment')
        for key in ('source', 'path'):
            path = Path(record[key])
            if not path.is_file() or asset_sha256(path) != record['sha256']:
                raise ValueError(f'Assigned {kind} {key} is missing or changed: {path}')


def make_thumbnail(source, output, title, channel):
    with Image.open(source) as original:
        image = ImageOps.fit(ImageOps.exif_transpose(original).convert('RGB'), (1280, 720), method=Image.Resampling.LANCZOS)
    shade = Image.new('RGBA', image.size)
    draw = ImageDraw.Draw(shade)
    for y in range(720):
        draw.line((0, y, 1280, y), fill=(0, 0, 0, round(210 * (y / 720) ** 1.5)))
    image = Image.alpha_composite(image.convert('RGBA'), shade)
    draw = ImageDraw.Draw(image)
    font_path = Path('C:/Windows/Fonts/BOD_B.TTF')
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
    import io, os, tempfile
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    image = image.convert('RGB')
    content = io.BytesIO()
    fmt = 'PNG' if output.suffix.lower() == '.png' else 'JPEG'
    image.save(content, format=fmt, optimize=True, **({'quality': 95} if fmt == 'JPEG' else {}))
    if len(content.getvalue()) > 2 * 1024 * 1024 and fmt == 'PNG':
        content = io.BytesIO()
        image.quantize(colors=256).save(content, format='PNG', optimize=True)
    fd, temporary = tempfile.mkstemp(dir=output.parent, suffix='.tmp')
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(content.getvalue())
        os.replace(temporary, output)
    finally:
        Path(temporary).unlink(missing_ok=True)


def qc_job(directory, row, metadata):
    checks = []
    def check(name, condition, detail='', status=None):
        resolved = status or ('pass' if condition else 'fail')
        checks.append({'name': name, 'status': resolved, 'detail': detail})
    try:
        verify_job_assets(metadata)
        if metadata.get('assets'):
            check('Original asset SHA-256 integrity', True)
        elif (Path(directory) / 'prompt_assets.json').is_file():
            check('Original asset SHA-256 integrity', False, 'Assignment exists but is missing from job metadata')
    except Exception as error:
        check('Original asset SHA-256 integrity', False, str(error))
    try:
        validate_video(row['video_path'], {**row, 'thumbnail_path': None})
        check('Playable MP4 and metadata', True)
        from app.utils.ffmpeg import probe_media
        data = probe_media(row['video_path'])
        check('Exactly one video and audio stream', [s['codec_type'] for s in data['streams']].count('video') == 1 and [s['codec_type'] for s in data['streams']].count('audio') == 1)
        video = next(s for s in data['streams'] if s['codec_type'] == 'video')
        audio = next(s for s in data['streams'] if s['codec_type'] == 'audio')
        config = metadata.get('render_config', {})
        check('Resolution', video['width'] == config.get('video_width', video['width']) and video['height'] == config.get('video_height', video['height']), f"{video['width']} × {video['height']}")
        fps = float(Fraction(video['avg_frame_rate']))
        check('Square pixels', video.get('sample_aspect_ratio', '1:1') in ('1:1', 'N/A'))
        check('YouTube pixel format', video.get('pix_fmt') == 'yuv420p')
        check('Frame rate', abs(fps - config.get('video_fps', fps)) < .1, f'{fps:g} FPS')
        duration = float(data['format']['duration'])
        target = metadata.get('target_duration_seconds', duration)
        check('Target duration', abs(duration - target) <= 5, f'{duration:.2f} seconds')
        check('Audio duration', abs(float(audio.get('duration', duration)) - target) <= 5, f"{audio.get('codec_name')} · {audio.get('channels')} channels")
        if metadata.get('selected_images') is not None:
            check('One background', len(metadata['selected_images']) == 1)
        if metadata.get('render_architecture') == 'short_clip_copy_loop':
            regions = metadata.get('branding_regions', [])
            check('Two distinct branding locations', sorted(r.get('position', '') for r in regions) == ['bottom_right', 'top_right'])
            check('Channel branding text', len(regions) == 2 and all(r.get('text') == 'Camping With Blues' for r in regions))
            check('No production visualizer', not any(metadata.get(k) for k in ('waveform_enabled', 'visualizer_enabled', 'subscribe_overlay_enabled', 'song_panel_enabled')))
            check('Short video encoding only', 0 < metadata.get('short_clip_seconds', 0) <= 8 and not metadata.get('render_segmented'))
            command_file = Path(directory) / 'output' / 'render_commands.json'
            commands = json.loads(command_file.read_text(encoding='utf-8'))
            check('Long video uses stream copy', all('-c:v' in commands[k] and commands[k][commands[k].index('-c:v')+1] == 'copy' for k in ('loop', 'mux')))
        if 'visualizer_enabled' in metadata.get('visualization_config', {}):
            requested = metadata['visualization_config']['visualizer_enabled']
            check('GIF visualizer toggle', bool(metadata.get('visualizer_enabled')) == requested)
            check('Old waveform skipped', not metadata.get('waveform_enabled'))
            if requested:
                group = metadata.get('visualizer_group') or {}
                has_gif = bool(group.get('path') or group.get('soundwave'))
                check('GIF visualizer members', has_gif)
        elif metadata.get('visualization_config', {}).get('waveform_enabled'):
            check('Waveform', bool(metadata.get('waveform_enabled')))
        if metadata.get('music_source_ids'):
            from collections import Counter
            sources = metadata['music_source_ids']
            check('At most twice per music source', max(Counter(sources).values()) <= 2)
            check('No adjacent repeated music', all(a != b for a, b in zip(sources, sources[1:])))
        thumbnail = Path(row.get('thumbnail_path') or '')
        if thumbnail.is_file():
            size_ok = thumbnail.stat().st_size <= 2 * 1024 * 1024
            check('YouTube thumbnail upload size', size_ok,
                  f'{thumbnail.stat().st_size} bytes; API limit 2 MB. Original is preserved without resizing; add a smaller file to the thumbnail folder if upload is rejected.',
                  status='pass' if size_ok else 'warning')
            with Image.open(thumbnail) as image:
                check('Thumbnail dimensions', image.width >= 640 and abs(image.width / image.height - 16/9) < .1, f'{image.width} × {image.height}')
        else:
            check('Thumbnail exists', False)
        if metadata.get('video_fades_enabled'):
            for label, enabled, offset in (
                ('Intro fades from black', metadata.get('intro_fade_seconds', 0) > 0, 0),
                ('Outro fades to black', metadata.get('outro_fade_seconds', 0) > 0, max(0, duration-2/fps)),
            ):
                if not enabled:
                    continue
                frame = subprocess.run([str(find_ffmpeg()), '-v', 'error', '-ss', str(offset), '-i', row['video_path'],
                                        '-frames:v', '1', '-vf', 'scale=64:36,format=gray', '-f', 'rawvideo', '-'],
                                       capture_output=True, check=True, timeout=30, **no_window_flags()).stdout
                brightness = sum(frame)/len(frame) if frame else 255
                check(label, len(frame) == 64*36 and brightness < 5, f'Mean brightness {brightness:.2f}/255')
        # Decode three short samples, including the end, without scanning hours of frames.
        # Use -ss before -i for fast input seeking instead of slow decoder seeking.
        for offset in (0, max(0, duration / 2), max(0, duration - 2)):
            decode = subprocess.run([str(find_ffmpeg()), '-v', 'error', '-xerror', '-ss', str(offset), '-i', row['video_path'], '-t', '1', '-f', 'null', '-'], capture_output=True, timeout=30, **no_window_flags())
            check(f'Decode sample at {offset:.0f}s', decode.returncode == 0)
    except Exception as error:
        check('Media validation', False, str(error))
    fingerprint = []
    for value in (row.get('video_path'), row.get('thumbnail_path')):
        path = Path(value or '')
        fingerprint.append([str(path), path.stat().st_size, path.stat().st_mtime_ns] if path.is_file() else None)
    result = {'fingerprint': fingerprint, 'status': 'fail' if any(c['status'] == 'fail' for c in checks) else ('warning' if any(c['status'] == 'warning' for c in checks) else 'pass'),
              'checks': checks, 'checked_at': datetime.now(timezone.utc).isoformat(), 'scope': 'Stream checks and three decode samples; not a full-frame corruption or copyright scan.'}
    write_json(Path(directory) / 'qc.json', result)
    return result
