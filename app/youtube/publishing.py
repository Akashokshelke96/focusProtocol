"""File-based publishing layered on existing job directories; no queue database."""
from app.utils.ffmpeg import no_window_flags
import hashlib
import json
import math
import sqlite3
import subprocess
from datetime import datetime, timedelta, timezone, time
from pathlib import Path
from zoneinfo import ZoneInfo

from app.youtube.oauth import YouTubeService
from app.youtube.lifecycle import finish, observe
from app.youtube.state import write_json, publishing_lock
from app.utils.ffmpeg import find_ffprobe

UTC = timezone.utc
DONE = {'scheduled', 'published', 'private', 'unlisted'}


def instant(value):
    result = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if result.tzinfo is None:
        raise ValueError('Publish times must include a timezone offset')
    return result.astimezone(UTC)


def file_hash(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def next_slot(settings, reserved, now=None):
    zone = ZoneInfo(settings.youtube_timezone)
    now = now or datetime.now(UTC)
    names = settings.youtube_schedule_times.split(',') if settings.youtube_schedule_times else [settings.youtube_schedule_time_1, settings.youtube_schedule_time_2]
    times = sorted({time.fromisoformat(name.strip()) for name in names})
    if len(times) < settings.youtube_videos_per_day or any(t.tzinfo for t in times):
        raise ValueError('Set distinct local YOUTUBE_SCHEDULE_TIMES for every daily slot')
    times = times[:settings.youtube_videos_per_day]
    occupied = {instant(v) for v in reserved if v}
    day = now.astimezone(zone).date()
    for offset in range(3660):
        date = day + timedelta(days=offset)
        if sum(value.astimezone(zone).date() == date for value in occupied) >= settings.youtube_videos_per_day:
            continue
        for clock in times:
            local = datetime.combine(date, clock, zone)
            candidate = local.astimezone(UTC)
            if candidate.astimezone(zone).replace(tzinfo=None) != local.replace(tzinfo=None):
                continue  # nonexistent DST wall time
            if candidate > now + timedelta(minutes=15) and candidate not in occupied:
                return candidate.isoformat()
    raise ValueError('No available publishing slot')


def validate_video(path, metadata):
    if metadata.get('assets'):
        from app.studio.assets import verify_job_assets
        verify_job_assets(metadata)
    path = Path(path)
    if not path.is_file() or path.stat().st_size == 0:
        raise ValueError(f'Video is missing or empty: {path}')
    probe = subprocess.run([str(find_ffprobe()), '-v', 'error', '-show_format', '-show_streams', '-of', 'json', str(path)], capture_output=True, text=True, check=True, timeout=60, **no_window_flags())
    data = json.loads(probe.stdout)
    duration = float(data['format'].get('duration', 0))
    kinds = [s.get('codec_type') for s in data['streams']]
    if not math.isfinite(duration) or duration <= 0 or kinds.count('video') != 1 or kinds.count('audio') != 1:
        raise ValueError('Video must have valid duration, one video stream and one audio stream')
    if not any(name in data['format']['format_name'].split(',') for name in ('mp4', 'mov')):
        raise ValueError('Publishing currently requires an MP4/MOV container')
    target = metadata.get('target_duration_seconds')
    if target and abs(duration - float(target)) > 5:
        raise ValueError('Video duration does not match the job target')
    title = metadata.get('title', '')
    if not isinstance(title, str) or not title.strip() or len(title) > 100 or any(c in title for c in '<>'):
        raise ValueError('Provide a title of 1-100 characters without angle brackets')
    description = metadata.get('description', '')
    if not isinstance(description, str) or len(description.encode('utf-8')) > 5000 or any(c in description for c in '<>'):
        raise ValueError('Description is invalid or exceeds 5000 UTF-8 bytes')
    tags = metadata.get('tags', [])
    if not isinstance(tags, list) or any(not isinstance(t, str) or not t for t in tags) or sum(len(t) + (2 if ' ' in t else 0) + 1 for t in tags) > 415:
        raise ValueError('Tags must be nonempty strings within YouTube limits')
    if metadata.get('privacy_status', 'private') not in ('private', 'unlisted', 'public'):
        raise ValueError('Invalid privacy status')
    if metadata.get('thumbnail_path'):
        from PIL import Image
        thumbnail = Path(metadata['thumbnail_path'])
        if not thumbnail.is_file():
            raise ValueError(f'Thumbnail is missing: {thumbnail}')
        if thumbnail.stat().st_size > 2 * 1024 * 1024:
            from app.studio.assets import ensure_uploadable_thumbnail
            metadata['thumbnail_path'] = str(ensure_uploadable_thumbnail(thumbnail))
            thumbnail = Path(metadata['thumbnail_path'])
        with Image.open(thumbnail) as image:
            image.verify()
    return duration


class PublishingQueue:
    def __init__(self, settings, root='jobs', service=None, channel_id=None):
        self.settings, self.root = settings, Path(root)
        self.service = service or YouTubeService(settings, channel_id=channel_id or 'focus-protocol')
        self.channel_id = channel_id
        self.injected_service = service is not None

    def for_channel(self, channel_id):
        from app.studio.store import StudioStore
        from app.studio.profiles import channel_settings
        settings = self.settings
        if channel_id != 'focus-protocol':
            settings = channel_settings(settings, StudioStore(self.root / 'studio').channel(channel_id))
        return PublishingQueue(settings, self.root, channel_id=channel_id)

    def scan(self):
        legacy = {}
        database = Path(self.settings.database_path)
        if database.is_file():
            with sqlite3.connect(database.resolve().as_uri() + '?mode=ro', uri=True) as db:
                legacy = {row[0]: (row[1], json.loads(row[2] or '{}')) for row in db.execute('SELECT id,status,metadata FROM jobs')}
        rows = []
        for directory in sorted(self.root.iterdir()) if self.root.exists() else []:
            if not directory.is_dir():
                continue
            source, state_path = directory / 'metadata.json', directory / 'youtube.json'
            if not source.exists() and not state_path.exists():
                continue
            try:
                data = json.loads(source.read_text(encoding='utf-8')) if source.exists() else {}
                old_status, old_metadata = legacy.get(directory.name, ('', {}))
                data = {**old_metadata, **data}
                if data.get('youtube_exclude'):
                    continue
                status = data.get('generation_status') or old_status
                state = json.loads(state_path.read_text(encoding='utf-8')) if state_path.exists() else {}
                if status in ('failed', 'running') or (status not in ('completed', 'completed_with_fallback', 'uploaded') and not state):
                    continue
                row = {'job_id': directory.name, 'generation_status': status, 'channel_id': data.get('channel_id', 'focus-protocol'),
                       'video_path': data.get('video_path', str(directory / 'output/final_video.mp4')),
                       'title': data.get('youtube_title', data.get('title', '')),
                       'description': data.get('youtube_description', data.get('description', '')),
                       'tags': data.get('youtube_tags', data.get('tags', [])),
                       'thumbnail_path': data.get('thumbnail_path'),
                       'category': data.get('category', self.settings.youtube_category),
                       'target_duration_seconds': data.get('target_duration_seconds'),
                       'youtube_status': 'uploaded' if data.get('youtube_video_id') else 'pending',
                       'youtube_video_id': data.get('youtube_video_id'), 'retry_count': 0,
                       **state}
                row['channel_id'] = data.get('channel_id', state.get('channel_id', 'focus-protocol'))
                if data.get('assets'):
                    row['assets'] = data['assets']
                    from app.studio.assets import ensure_uploadable_thumbnail
                    row['thumbnail_path'] = str(ensure_uploadable_thumbnail(data['assets']['thumbnail']['path']))
                if self.channel_id and row['channel_id'] != self.channel_id:
                    continue
                # Repair old jazz jobs affected by the metadata f-string bug.
                # Derive only factual copy from the existing job, never arbitrary manual files.
                if not row['title'] and data.get('background_prompt') and data.get('target_duration_seconds'):
                    minutes = round(float(data['target_duration_seconds']) / 60)
                    scene = data['background_prompt'].get('title', 'Focus Protocol')
                    row.update(title=f'{scene} | {minutes} Min Jazz for Focus & Study'[:100],
                               description=f'{minutes} minutes of instrumental jazz for working, studying and relaxing. A single cinematic background accompanies the music.',
                               tags=['jazz', 'focus music', 'study music'], metadata_source='local_legacy_repair')
                rows.append(row)
            except (ValueError, OSError) as error:
                raise RuntimeError(f'Cannot read {directory.name} publishing state; repair the JSON before publishing') from error
        return rows

    def save(self, row):
        from app.youtube.display_status import publishing_state
        display = publishing_state(row)
        row.update(upload_status='uploaded' if display['uploaded'] else display['state'],
                   thumbnail_status='uploaded' if row.get('thumbnail_uploaded') else ('failed' if row.get('youtube_status') in ('thumbnail_retry', 'thumbnail_blocked') else ('pending' if row.get('thumbnail_path') else 'not_requested')),
                   metadata_status='verified' if row.get('metadata_verified') and not row.get('metadata_dirty') else 'pending',
                   last_checked=display['last_checked'], upload_error=row.get('last_error'))
        if display['state'] == 'published':
            row.setdefault('published_time', row.get('publishing_verified_at'))
        write_json(self.root / row['job_id'] / 'youtube.json', row)

    def reconcile(self):
        """Refresh known local upload states without creating or updating videos."""
        with publishing_lock(self.root):
            rows = self.scan()
            for row in rows:
                if not row.get('youtube_video_id'):
                    continue
                service = self.service if self.injected_service else self.for_channel(row['channel_id']).service
                video = service.video_details(row['youtube_video_id'])
                if observe(row, video) and row.get('publishing_verified_at'):
                    status = video.get('status', {})
                    row['youtube_status'] = 'scheduled' if status.get('publishAt') else ('published' if status.get('privacyStatus') == 'public' else status.get('privacyStatus', 'processing_complete'))
                self.save(row)
            return rows

    def add_manual(self, video, **metadata):
        path = Path(video).resolve()
        digest = file_hash(path)
        row = {'job_id': 'manual_' + digest, 'generation_status': 'completed', 'video_path': str(path),
               'youtube_status': 'pending', 'retry_count': 0, 'sha256': digest, 'channel_id': self.channel_id or 'focus-protocol', **metadata}
        with publishing_lock(self.root):
            for previous in self.scan():
                if previous.get('sha256') == digest or Path(previous['video_path']).resolve() == path:
                    return previous['job_id']
            validate_video(path, row)
            self.save(row)
        return row['job_id']

    def publish(self, dry_run=False, job_id=None, wait=True):
        if self.channel_id and self.channel_id != 'focus-protocol' and not self.injected_service:
            resolved = self.for_channel(self.channel_id)
            self.settings, self.service = resolved.settings, resolved.service
        if not self.channel_id and not self.injected_service:
            rows = [r for r in self.scan() if not job_id or r['job_id'] == job_id]
            if job_id and not rows:
                raise ValueError('Unknown publishing job ID')
            results = []
            for channel_id in dict.fromkeys(r['channel_id'] for r in rows):
                results.extend(self.for_channel(channel_id).publish(dry_run=dry_run, job_id=job_id, wait=wait))
            return results
        from app.config.logging_config import get_logger
        get_logger('youtube.publishing').info('Publish action channel=%s job=%s dry_run=%s', self.channel_id or 'focus-protocol', job_id or 'batch', dry_run)
        if not dry_run and not self.settings.youtube_upload_enabled:
            raise RuntimeError('Set YOUTUBE_UPLOAD_ENABLED=true to enable publishing')
        with publishing_lock(self.root):
            rows = self.scan()
            if job_id and not any(row['job_id'] == job_id for row in rows):
                raise ValueError('Unknown publishing job ID')
            if not dry_run and self.channel_id and not self.injected_service:
                from app.studio.store import StudioStore
                channel = StudioStore(self.root / 'studio').channel(self.channel_id)
                connection = self.service.connection_status()
                if not connection.get('connected'):
                    raise ValueError(channel['name'] + ' is not connected — click Connect YouTube')
                if channel.get('youtube_channel_id') and connection.get('channel_id') != channel['youtube_channel_id']:
                    raise ValueError('Connected account does not match ' + channel['name'])
            remote = [] if dry_run else self.service.channel_videos()
            reserved = [r.get('scheduled_publish_time') for r in rows
                        if r.get('scheduled_publish_time')]
            reserved += [v.get('status', {}).get('publishAt') for v in remote]
            known = {r.get('sha256'): r for r in rows if r.get('sha256') and (r.get('youtube_video_id') or r['youtube_status'] in ('uploading', 'needs_review'))}
            results = []
            for row in rows:
                if job_id and row['job_id'] != job_id:
                    continue
                if row.get('youtube_video_id'):
                    if not dry_run and (job_id or not row.get('publishing_verified_at') or row['youtube_status'] not in DONE):
                        finish(self.service, self.settings, row, self.save, wait=wait)
                        results.append(row.copy())
                        if row['youtube_status'] not in DONE:
                            break
                    continue
                if row['youtube_status'] == 'duplicate':
                    continue
                if row['youtube_status'] in ('uploading', 'needs_review'):
                    match = next((v for v in remote if v.get('snippet', {}).get('title') == row.get('title')), None)
                    if match:
                        row.update(youtube_video_id=match['id'], youtube_status='uploaded', last_error=None)
                    else:
                        row.update(youtube_status='needs_review', last_error='Previous upload outcome is uncertain. Check YouTube Studio; automatic re-upload is blocked.')
                    if not dry_run:
                        self.save(row)
                        if row.get('youtube_video_id'):
                            finish(self.service, self.settings, row, self.save, wait=wait)
                    results.append(row.copy())
                    continue
                try:
                    validate_video(row['video_path'], row)
                    row['sha256'] = file_hash(row['video_path'])
                    remote_match = next((v for v in remote if v.get('snippet', {}).get('title') == row.get('title')), None)
                    if remote_match:
                        row.update(youtube_video_id=remote_match['id'], youtube_status='uploaded')
                        if not dry_run:
                            self.save(row)
                            finish(self.service, self.settings, row, self.save, wait=wait)
                        results.append(row.copy())
                        continue
                    previous = known.get(row['sha256'])
                    if previous and previous['job_id'] != row['job_id']:
                        row.update(youtube_status='duplicate', duplicate_of=previous['job_id'])
                        if not dry_run:
                            self.save(row)
                        results.append(row.copy())
                        continue
                    scheduled = row.get('scheduled_publish_time')
                    if scheduled and instant(scheduled) <= datetime.now(UTC):
                        if row.get('schedule_source') == 'automatic':
                            scheduled = next_slot(self.settings, reserved)
                        else:
                            raise ValueError('Explicit schedule is in the past; choose a future time')
                    if scheduled:
                        other_slots = [r.get('scheduled_publish_time') for r in rows if r['job_id'] != row['job_id']]
                        other_slots += [v.get('status', {}).get('publishAt') for v in remote]
                        if instant(scheduled) in {instant(v) for v in other_slots if v}:
                            if row.get('schedule_source') == 'automatic':
                                scheduled = next_slot(self.settings, reserved)
                            else:
                                raise ValueError('Explicit schedule conflicts with an existing reservation')
                    if not scheduled and self.settings.youtube_auto_schedule_enabled:
                        scheduled = next_slot(self.settings, reserved)
                    row['scheduled_publish_time'] = scheduled
                    row.setdefault('privacy_status', self.settings.youtube_privacy_status)
                    if scheduled:
                        row['privacy_status'] = 'private'
                    reserved.append(scheduled)
                    import re as _re
                    if _re.search(r'\bVol\.?\s*\d+', row.get('title') or '') and not row.get('playlist_vol'):
                        try:
                            from app.studio.store import StudioStore as _VolumeStore
                            _vol_channel = _VolumeStore(self.root / 'studio').channel(row.get('channel_id', 'focus-protocol'))
                            row['playlist_vol'] = int(_vol_channel.get('playlist_volume') or 0) + 1
                        except (ValueError, TypeError):
                            row['playlist_vol'] = 1
                    if row.get('playlist_vol'):
                        row['title'] = _re.sub(r'\bVol\.?\s*\d+', 'Vol. %02d' % int(row['playlist_vol']), row.get('title'), count=1)
                    if dry_run:
                        row['youtube_status'] = 'ready'
                        known[row['sha256']] = row
                        results.append(row.copy())
                        continue
                    row.update(youtube_status='uploading', upload_started_at=datetime.now(UTC).isoformat(), last_error=None, retry_count=row.get('retry_count', 0) + 1)
                    self.save(row)  # durable intent BEFORE any remote mutation
                    known[row['sha256']] = row
                    def completed(result):
                        row.update(youtube_video_id=result['video_id'], youtube_status='uploaded', upload_percent=100, upload_timestamp=datetime.now(UTC).isoformat())
                        row['upload_elapsed_seconds'] = round((datetime.now(UTC) - datetime.fromisoformat(row['upload_started_at'])).total_seconds(), 3)
                        row['metadata_dirty'] = False
                        if row.get('playlist_vol'):
                            try:
                                from app.studio.store import StudioStore as _BumpStore
                                _bump = _BumpStore(self.root / 'studio')
                                with _bump.transaction() as _state:
                                    for _c in _state['channels']:
                                        if _c['id'] == row.get('channel_id', 'focus-protocol'):
                                            _c['playlist_volume'] = max(int(_c.get('playlist_volume') or 0), int(row['playlist_vol']))
                            except Exception:
                                pass
                        self.save(row)  # persist ID BEFORE optional thumbnail upload
                    metadata = {**row, 'tags': list(row.get('tags', []))}
                    last_percent = [-1]
                    def progress(percent):
                        # One durable update per percentage point; the video ID remains authoritative.
                        value = min(100, max(0, int(percent)))
                        if value != last_percent[0]:
                            last_percent[0] = value
                            row.update(upload_percent=value, upload_progress_at=datetime.now(UTC).isoformat())
                            self.save(row)
                    result = self.service.upload(Path(row['video_path']), metadata, progress_callback=progress, uploaded_callback=completed)
                    finish(self.service, self.settings, row, self.save, wait=wait)
                except Exception as error:
                    row['last_error'] = str(error)
                    if not row.get('youtube_video_id'):
                        row['youtube_status'] = 'needs_review' if row['youtube_status'] == 'uploading' else 'failed'
                    if not dry_run:
                        self.save(row)
                results.append(row.copy())
                if not dry_run and row.get('youtube_video_id') and row['youtube_status'] not in DONE:
                    break
            return results
