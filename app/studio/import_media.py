"""Validated, non-overwriting imports into permanent channel libraries."""
import hashlib
import os
import shutil
import tempfile
from pathlib import Path
from werkzeug.utils import secure_filename
from app.providers.local_music import LocalMusicProvider
from app.providers.media_history import validate_background
from app.youtube.state import publishing_lock


def import_file(upload, folder, kind):
    folder = Path(folder).resolve()
    project = Path.cwd().resolve()
    if not folder.is_relative_to(project) or folder == project or folder.is_relative_to(project / 'jobs'):
        raise ValueError('Choose a permanent media folder inside this project, outside jobs')
    suffix = Path(upload.filename or '').suffix.lower()
    allowed = LocalMusicProvider.SUPPORTED_FORMATS if kind == 'music' else {'.png', '.jpg', '.jpeg', '.webp'}
    if kind not in ('music', 'image') or suffix not in allowed:
        raise ValueError('Unsupported media type')
    name = secure_filename(Path(upload.filename.replace('\\', '/')).name)
    if not name:
        raise ValueError('File must have a valid name')
    folder.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='import_', dir=Path('jobs')) as temporary:
        staged = Path(temporary) / name
        upload.save(staged)
        if staged.stat().st_size == 0:
            raise ValueError('Uploaded file is empty')
        if kind == 'image':
            dimensions = validate_background(staged)
            details = {'dimensions': dimensions}
        else:
            import subprocess
            from app.utils.ffmpeg import find_ffmpeg
            duration = LocalMusicProvider()._get_audio_duration(staged)
            if duration < 10:
                raise ValueError('Music must be at least 10 seconds long')
            subprocess.run([str(find_ffmpeg()), '-v', 'error', '-xerror', '-i', str(staged),
                            '-t', '2', '-vn', '-f', 'null', '-'], capture_output=True, check=True, timeout=30)
            details = {'duration': duration}
        from app.youtube.publishing import file_hash
        digest = file_hash(staged)
        with publishing_lock(Path('jobs/media_import')):
            output = folder / name
            if output.exists():
                if file_hash(output) == digest:
                    return {'name': output.name, 'path': str(output), 'status': 'already_imported', **details}
                output = folder / f'{Path(name).stem}_{digest[:12]}{suffix}'
            if output.exists():
                if file_hash(output) != digest:
                    raise ValueError('Import name conflict; rename the source file')
            else:
                # Exclusive creation ensures originals are never overwritten.
                created = False
                try:
                    with output.open('xb') as stream, staged.open('rb') as source:
                        created = True
                        shutil.copyfileobj(source, stream, 1024*1024)
                except Exception:
                    if created and output.is_file():
                        output.unlink()
                    raise
        return {'name': output.name, 'path': str(output), 'status': 'imported', **details}
