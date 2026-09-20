"""Generated artifact naming and conservative, manifest-based local deletion."""
import hashlib
import json
import re
import shutil
import subprocess
from pathlib import Path
from app.youtube.state import publishing_lock, write_json


def name_final_video(path, metadata, channel, duration, job_id):
    path = Path(path)
    slug = re.sub(r'[^a-z0-9]+', '_', channel.lower()).strip('_')[:60] or 'the_painted_soul'
    ledger = Path('jobs/episodes.json')
    with publishing_lock(ledger.parent / 'episode_numbers'):
        state = json.loads(ledger.read_text('utf-8')) if ledger.exists() else {}
        series = state.setdefault(slug, {'next': 1, 'jobs': {}})
        episode = series['jobs'].get(job_id)
        if episode is None:
            episode = series['next']
            series['next'] += 1
            series['jobs'][job_id] = episode
        write_json(ledger, state)
    output = path.with_name(f'{slug}_ep_{episode:02d}_{round(duration/60)}min.mp4')
    if output != path:
        if output.exists():
            raise ValueError('Final output already exists; refusing to overwrite it')
        path.rename(output)
    metadata.update(video_path=str(output.resolve()), episode_number=episode,
                    actual_duration_seconds=duration, output_filename=output.name,
                    channel_title=channel)
    return output


def is_link(path):
    return path.is_symlink() or bool(getattr(path.lstat(), 'st_file_attributes', 0) & 0x400)


def contained_files(directory):
    """Reject junctions/symlinks before traversing any generated directory."""
    directory = Path(directory)
    if is_link(directory):
        raise ValueError('Linked job directories cannot be deleted')
    root = directory.resolve()
    files = []
    def visit(folder):
        for path in sorted(folder.iterdir()):
            if is_link(path) or not path.resolve().is_relative_to(root):
                raise ValueError('Linked or external artifacts cannot be deleted')
            if path.is_dir():
                visit(path)
            elif path.is_file():
                files.append(path)
    visit(directory)
    return files


TEMP_FILES = ('render_background.png', 'waveform.mkv', 'music/audio_base_block.aac',
              'music/audio_concatenated.aac', 'output/rendering.mp4', 'preview.mp4', 'benchmark.mp4',
              'subscribe_overlay.mov', 'concat.txt', 'output/preview.mp4')


def cleanup_job(directory, metadata):
    """Only known redundant outputs of a successfully QC'd job; keep retry sources."""
    directory = Path(directory).resolve()
    final = Path(metadata['video_path']).resolve()
    thumbnail = Path(metadata['thumbnail_path']).resolve()
    if not final.is_file() or not thumbnail.is_file():
        raise ValueError('Final video and thumbnail are required before cleanup')
    protected = {Path(record['path']).resolve() for record in metadata.get('assets', {}).values()}
    protected.add(Path(metadata.get('audio_path') or directory / 'music/audio_concatenated.aac').resolve())
    # The final audio master is referenced by metadata['audio_path'] even when that
    # pointer is stale/relative at cleanup time; never delete the job-local master.
    protected.add((directory / 'music' / 'audio_concatenated.aac').resolve())
    candidates = []
    for name in TEMP_FILES:
        path = directory / name
        if path.is_file() and not is_link(path) and path.resolve().is_relative_to(directory):
            if path.resolve() not in (final, thumbnail) and path.resolve() not in protected:
                candidates.append(path)
    # A local library source can replace its redundant per-job copy for future thumbnail edits.
    source = Path(metadata.get('background_source_path', ''))
    copied = directory / 'background_images/background.png'
    if not metadata.get('assets') and source.is_file() and not source.resolve().is_relative_to(directory) and source.resolve().is_relative_to(Path.cwd().resolve()):
        metadata['generated_background_path'] = str(source.resolve())
        thumbnail_source = Path(metadata.get('thumbnail_source', str(copied)))
        if thumbnail_source.resolve() == copied.resolve():
            metadata['thumbnail_source'] = str(source.resolve())
        assets_path = directory / 'prompt_assets.json'
        if assets_path.is_file() and not is_link(assets_path):
            assets = json.loads(assets_path.read_text('utf-8'))
            assets.update(background_path=str(source.resolve()), thumbnail_source=metadata.get('thumbnail_source', str(source.resolve())))
            write_json(assets_path, assets)
        if copied.is_file() and not is_link(copied):
            candidates.append(copied)
    removed = 0
    removed_files, warnings = [], []
    for path in candidates:
        try:
            size = path.stat().st_size
            path.unlink()
            removed += size
            removed_files.append(str(path.relative_to(directory)))
        except OSError as error:
            warnings.append(f'{path.name}: {error}')
    return {'removed_bytes': removed, 'removed_files': removed_files, 'warnings': warnings}


def deletion_plan(service, ids):
    root = service.root.resolve()
    state = service.store.read()
    all_jobs = service.jobs(include_excluded=True)
    if ids != 'all' and (not isinstance(ids, list) or any(not isinstance(i, str) for i in ids)):
        raise ValueError('Choose generated job IDs or all')
    requested = {j['job_id'] for j in all_jobs} if ids == 'all' else set(ids)
    if not requested:
        raise ValueError('No generated jobs to delete')
    known = {j['job_id']: j for j in all_jobs}
    if not requested.issubset(known):
        raise ValueError('Unknown generated job')
    generation_busy = {c.get('job_id') for c in state['content'] if c['stage'] == 'generating'}
    generation_busy |= {i for i in requested if known[i]['generation_status'] == 'running'}
    publishing_busy = {j['job_id'] for b in state['batches'] for j in b['jobs'] if j['status'] in ('queued', 'running', 'processing')}
    if requested & publishing_busy:
        raise ValueError('Wait for YouTube publishing to finish before deleting these jobs')
    protected = [Path.cwd().resolve() / name for name in ('music', 'backgroundImages', 'thumbnail', 'thumbnails', 'watermark')]
    protected += [Path(c[key]).resolve() for c in state['channels'] for key in ('music_dir', 'background_dir', 'thumbnail_dir')]
    files, directories, missing = [], [], []
    for job_id in sorted(requested):
        raw = root / job_id
        directory = raw.resolve()
        if directory.parent != root or job_id in ('studio', 'generation'):
            raise ValueError('Only direct generated job folders may be deleted')
        if not raw.exists() and not raw.is_symlink():
            missing.append(job_id)
            continue
        if is_link(raw):
            raise ValueError('Linked job directories cannot be deleted')
        if any(p == directory or p.is_relative_to(directory) or directory.is_relative_to(p) for p in protected):
            raise ValueError('A source library overlaps this job; deletion is blocked')
        if not (directory / 'metadata.json').is_file() and not (directory / 'job.json').is_file():
            raise ValueError('Job has no generation manifest')
        for path in contained_files(directory):
            stat = path.stat()
            files.append({'path': str(path), 'bytes': stat.st_size, 'modified': stat.st_mtime_ns})
        directories.append(str(directory))
    token = hashlib.sha256(json.dumps({'job_ids': sorted(requested), 'files': files}, sort_keys=True).encode()).hexdigest()
    message = 'Deletes these local generated job folders, final videos, thumbnails and job artifacts. Permanent music/images, settings, code and videos already on YouTube are kept.'
    if requested & generation_busy:
        message += ' Active generation jobs will be stopped before deletion.'
    return {'job_ids': sorted(requested), 'directories': directories, 'files': files,
            'bytes': sum(f['bytes'] for f in files), 'confirmation': token, 'missing_job_ids': missing,
            'generation_busy_job_ids': sorted(requested & generation_busy),
            'message': message}


def delete_generated(service, ids, confirmation):
    # Generation and publishing cannot mutate artifacts between confirmation and removal.
    with publishing_lock(service.root / 'generation'), publishing_lock(service.root):
        plan = deletion_plan(service, ids)
        if not confirmation or confirmation != plan['confirmation']:
            raise ValueError('Files changed or confirmation is missing. Review a fresh deletion preview.')
        if plan['generation_busy_job_ids']:
            for process_name in ('ffmpeg.exe', 'ffprobe.exe'):
                subprocess.run(['taskkill', '/F', '/T', '/IM', process_name],
                               capture_output=True, text=True, timeout=10, check=False)
            try:
                from app.api import jazz_api
                if jazz_api.current_job and jazz_api.current_job.get('status') == 'running':
                    jazz_api.current_job.update(status='cancelled', message='Generation deleted by user')
            except Exception:
                pass
        deleted = []
        for value in plan['directories']:
            directory = Path(value)
            contained_files(directory)  # Recheck reparse points immediately before native removal.
            shutil.rmtree(directory)
            deleted.append(directory.name)
            with service.store.transaction() as state:
                state.setdefault('deleted_jobs', []).append(directory.name)
                state['content'] = [c for c in state['content'] if c.get('job_id') != directory.name]
                for batch in state['batches']:
                    batch['jobs'] = [j for j in batch['jobs'] if j['job_id'] != directory.name]
                state['batches'] = [b for b in state['batches'] if b['jobs']]
        for job_id in plan['missing_job_ids']:
            if (service.root / job_id).exists():
                raise ValueError('A missing job folder reappeared. Review a fresh deletion preview.')
            with service.store.transaction() as state:
                state.setdefault('deleted_jobs', []).append(job_id)
                state['content'] = [c for c in state['content'] if c.get('job_id') != job_id]
                for batch in state['batches']:
                    batch['jobs'] = [j for j in batch['jobs'] if j['job_id'] != job_id]
                state['batches'] = [b for b in state['batches'] if b['jobs']]
            deleted.append(job_id)
        return {'deleted': deleted, 'bytes': plan['bytes']}
