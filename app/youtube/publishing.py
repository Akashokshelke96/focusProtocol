"""File-based publishing layered on existing job directories; no queue database."""
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
    path = Path(path)
    if not path.is_file() or path.stat().st_size == 0:
        raise ValueError(f'Video is missing or empty: {path}')
    probe = subprocess.run([str(find_ffprobe()), '-v', 'error', '-show_format', '-show_streams', '-of', 'json', str(path)], capture_output=True, text=True, check=True, timeout=60)
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
        if not thumbnail.is_file() or thumbnail.stat().st_size > 2 * 1024 * 1024:
            raise ValueError('Thumbnail must exist and be under 2 MB')
        with Image.open(thumbnail) as image:
            image.verify()
    return duration


class PublishingQueue:
    def __init__(self, settings, root='jobs', service=None, channel_id=None):
        self.settings, self.root = settings, Path(root)
        self.service = service or YouTubeService(settings)
        self.channel_id = channel_id

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
                if self.channel_id and data.get('channel_id', 'focus-protocol') != self.channel_id:
                    continue
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
        write_json(self.root / row['job_id'] / 'youtube.json', row)

    def reconcile(self):
        """Refresh known local upload states without creating or updating videos."""
        with publishing_lock(self.root):
            rows = self.scan()
            for row in rows:
                if not row.get('youtube_video_id'):
                    continue
                video = self.service.video_details(row['youtube_video_id'])
                if observe(row, video) and row.get('publishing_verified_at'):
                    status = video.get('status', {})
                    row['youtube_status'] = 'scheduled' if status.get('publishAt') else ('published' if status.get('privacyStatus') == 'public' else status.get('privacyStatus', 'processing_complete'))
                self.save(row)
            return rows

    def add_manual(self, video, **metadata):
        path = Path(video).resolve()
        digest = file_hash(path)
        row = {'job_id': 'manual_' + digest, 'generation_status': 'completed', 'video_path': str(path),
               'youtube_status': 'pending', 'retry_count': 0, 'sha256': digest, **metadata}
        with publishing_lock(self.root):
            for previous in self.scan():
                if previous.get('sha256') == digest or Path(previous['video_path']).resolve() == path:
                    return previous['job_id']
            validate_video(path, row)
            self.save(row)
        return row['job_id']

    def publish(self, dry_run=False, job_id=None, wait=True):
        if not dry_run and not self.settings.youtube_upload_enabled:
            raise RuntimeError('Set YOUTUBE_UPLOAD_ENABLED=true to enable publishing')
        with publishing_lock(self.root):
            rows = self.scan()
            if job_id and not any(row['job_id'] == job_id for row in rows):
                raise ValueError('Unknown publishing job ID')
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
                marker = 'engine-sha256-' + row.get('sha256', '')
                if row['youtube_status'] in ('uploading', 'needs_review'):
                    match = next((v for v in remote if marker in v.get('snippet', {}).get('tags', [])), None)
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
                    marker = 'engine-sha256-' + row['sha256']
                    remote_match = next((v for v in remote if marker in v.get('snippet', {}).get('tags', [])), None)
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
                    if dry_run:
                        row['youtube_status'] = 'ready'
                        known[row['sha256']] = row
                        results.append(row.copy())
                        continue
                    row.update(youtube_status='uploading', upload_started_at=datetime.now(UTC).isoformat(), last_error=None, retry_count=row.get('retry_count', 0) + 1)
                    self.save(row)  # durable intent BEFORE any remote mutation
                    known[row['sha256']] = row
                    def completed(result):
                        row.update(youtube_video_id=result['video_id'], youtube_status='uploaded', upload_timestamp=datetime.now(UTC).isoformat())
                        row['upload_elapsed_seconds'] = round((datetime.now(UTC) - datetime.fromisoformat(row['upload_started_at'])).total_seconds(), 3)
                        row['metadata_dirty'] = False
                        self.save(row)  # persist ID BEFORE optional thumbnail upload
                    metadata = {**row, 'tags': list(row.get('tags', [])) + ['engine-sha256-' + row['sha256']]}
                    result = self.service.upload(Path(row['video_path']), metadata, uploaded_callback=completed)
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
