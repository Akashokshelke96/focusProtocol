"""Reconcile abandoned work only while no pipeline owns the generation lock."""
from pathlib import Path
from datetime import datetime, timezone
from app.youtube.state import publishing_lock, write_json
from app.studio.store import read_json
from app.studio.assets import qc_job


def process_alive(owner):
    if not owner or not owner.get('pid'):
        return False
    import psutil
    try:
        process = psutil.Process(owner['pid'])
        return abs(process.create_time() - owner['created']) < .1 and process.is_running()
    except psutil.NoSuchProcess:
        return False
    except psutil.AccessDenied:
        return True  # Do not race an owner we cannot inspect.


def reconcile(service):
    try:
        with publishing_lock(service.root / 'generation'):
            for path in service.root.glob('*/job.json'):
                record = read_json(path, {})
                if record.get('status') != 'running':
                    continue
                directory = path.parent
                metadata = {**record.get('metadata', {}), **read_json(directory / 'metadata.json', {})}
                progress = read_json(directory / 'render_progress.json', {})
                if progress.get('status') not in ('complete', 'failed') and process_alive(progress.get('owner')):
                    continue
                video = Path(metadata.get('video_path') or directory / 'output/rendering.mp4')
                # A file by itself is not a completion signal. Run full application QC
                # only after a persisted encoder success or a finalization checkpoint.
                can_validate = progress.get('status') == 'complete' or record.get('stage') in ('APPLY_MOTION_RENDER', 'VALIDATE_OUTPUT') or metadata.get('generation_status') in ('completed', 'completed_with_fallback')
                status, error = 'interrupted', 'Worker stopped before completion. Retry reuses prepared audio and artwork when available.'
                if can_validate and video.is_file():
                    row = dict(video_path=str(video), thumbnail_path=metadata.get('thumbnail_path'),
                               title=metadata.get('youtube_title', ''), description=metadata.get('youtube_description', ''))
                    result = qc_job(directory, row, metadata)
                    if result['status'] == 'pass':
                        status, error = ('completed_with_fallback' if metadata.get('fallback_used') else 'completed'), None
                        metadata['video_path'] = str(video.resolve())
                        metadata['qc_status'] = 'pass'
                    else:
                        status = 'failed'
                        error = 'Recovery QC failed: ' + ', '.join(c['name'] for c in result['checks'] if c['status'] == 'fail')
                ended = datetime.now(timezone.utc)
                metadata.update(generation_status=status, completed_at=ended.isoformat(), recovery_checked_at=ended.isoformat())
                if metadata.get('started_at'):
                    start = datetime.fromisoformat(metadata['started_at'])
                    if start.tzinfo is None:
                        start = start.astimezone()
                    metadata['total_elapsed_seconds'] = round((ended-start).total_seconds(), 3)
                record.update(status=status, error_message=error, metadata=metadata, updated_at=ended.isoformat())
                write_json(directory / 'metadata.json', metadata)
                write_json(path, record)
                # Keep the pre-existing compatibility registry aligned, without creating one.
                import sqlite3
                from app.config.settings import get_settings
                database = Path(get_settings().database_path)
                if database.is_file():
                    import json
                    with sqlite3.connect(database) as connection:
                        connection.execute('UPDATE jobs SET status=?, error_message=?, metadata=?, updated_at=? WHERE id=?',
                                           (status, error, json.dumps(metadata), ended.isoformat(), record['id']))
                with service.store.transaction() as state:
                    for item in state['content']:
                        if item.get('job_id') == directory.name and item['stage'] != 'planned':
                            item.update(stage='ready' if status.startswith('completed') else status, error=error)
    except RuntimeError as error:
        if 'Another YouTube publishing operation' not in str(error):
            raise
