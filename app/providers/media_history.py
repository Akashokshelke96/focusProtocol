"""Content-aware media rotation using the existing atomic JSON state helpers."""
import hashlib
import json
import random
import logging
import subprocess
from pathlib import Path
from app.youtube.state import publishing_lock, write_json


def fingerprint(path, state, kind="file"):
    path = Path(path).resolve()
    stat = path.stat()
    stamp = [stat.st_size, stat.st_mtime_ns]
    cache = state.setdefault('files', {})
    entry = cache.get(str(path), {})
    if entry.get('stamp') != stamp or entry.get('kind') != kind:
        digest = hashlib.sha256()
        with path.open('rb') as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b''):
                digest.update(block)
        digest_value = digest.hexdigest()
        entry = {'stamp': stamp, 'digest': digest_value, 'kind': kind}
        cache[str(path)] = entry
    return entry['digest']


def rotate(candidates, kind, job_id, target=None, crossfade=4, history_path=Path('jobs/media_usage.json')):
    """Reserve an image or a shuffled, at-most-twice music timeline atomically."""
    history_path = Path(history_path)
    with publishing_lock(history_path.parent / 'media_rotation'):
        state = json.loads(history_path.read_text('utf-8')) if history_path.exists() else {}
        usage = state.setdefault(kind, {})
        unique = {}
        for item in candidates:
            try:
                digest = fingerprint(item['path'], state, kind)
            except (OSError, subprocess.SubprocessError) as error:
                logging.getLogger(__name__).warning('Skipping unreadable media %s: %s', item['path'], error)
                continue
            unique.setdefault(digest, {**item, 'source_id': digest})
        if kind == 'images' and not usage:
            legacy = history_path.parent / 'background_rotation.json'
            if legacy.exists():
                for order, value in enumerate(json.loads(legacy.read_text('utf-8')), 1):
                    if Path(value).is_file():
                        digest = fingerprint(value, state, kind)
                        usage[digest] = {'sequence': order, 'path': value, 'uses': 1}
                state['sequence'] = max([state.get('sequence', 0)] + [entry['sequence'] for entry in usage.values()])
        pool = list(unique.values())
        random.SystemRandom().shuffle(pool)
        pool.sort(key=lambda item: usage.get(item['source_id'], {}).get('sequence', 0))
        selected, duration = [], 0.0
        if kind in ('images', 'thumbnail_images'):
            latest = max(usage, key=lambda key: usage[key].get('sequence', 0), default=None)
            if len(pool) == 1 and pool[0]['source_id'] == latest:
                raise ValueError('Only one distinct usable image remains and it was used last. Add another image to prevent a consecutive repeat.')
            selected = pool[:1]
        else:
            pool = [item for item in pool if item['duration'] > crossfade * 2]
            for occurrence in range(2):
                sequence = list(pool)
                if occurrence:
                    random.SystemRandom().shuffle(sequence)
                while sequence and duration < target:
                    options = [item for item in sequence if not selected or item['source_id'] != selected[-1]['source_id']]
                    if not options:
                        break
                    item = options[0]
                    sequence.remove(item)
                    duration += item['duration'] - (crossfade if selected else 0)
                    selected.append(item)
                if duration >= target:
                    break
        if not selected:
            raise ValueError(f'No valid {kind} available; add files to the permanent library')
        sequence_number = state.get('sequence', 0) + 1
        state['sequence'] = sequence_number
        for item in selected:
            old = usage.get(item['source_id'], {})
            usage[item['source_id']] = {'sequence': sequence_number, 'job_id': job_id,
                                       'path': item['path'], 'uses': old.get('uses', 0) + 1}
        write_json(history_path, state)
        return selected, min(duration, target) if target else None


def validate_background(path, minimum=(1920, 1080)):
    from PIL import Image, ImageOps, ImageStat
    with Image.open(path) as source:
        source.load()
        image = ImageOps.exif_transpose(source)
        width, height = image.size
        if width < minimum[0] or height < minimum[1]:
            raise ValueError(f'Background must be at least {minimum[0]}×{minimum[1]}; got {width}×{height}')
        if abs(width / height - 16 / 9) > .10:
            raise ValueError(f'Background must be landscape 16:9; got {width}×{height}')
        # Reject blank/washed-out images; subject/genre matching remains a library curation concern.
        sample = image.convert('L').resize((128, 72))
        stats = ImageStat.Stat(sample)
        if stats.stddev[0] < 2 or stats.mean[0] > 235:
            raise ValueError('Background is blank or washed out')
        return width, height
