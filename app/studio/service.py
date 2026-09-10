"""Persistent production/batch coordinator. One renderer and one publisher at a time."""
import sqlite3
import json
import threading
import uuid
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from app.config.settings import get_settings
from app.studio.store import StudioStore, read_json
from app.studio.profiles import Channel, ContentProfile, THEMES, PRESETS, channel_settings
from app.studio.assets import qc_job
from app.youtube.publishing import PublishingQueue, DONE, next_slot, validate_video, file_hash
from app.youtube.state import write_json, publishing_lock
from app.youtube.oauth import YouTubeService


def now():
    return datetime.now(timezone.utc).isoformat()


class StudioService:
    def __init__(self, root='jobs', store=None):
        self.root = Path(root)
        self.store = store or StudioStore(self.root / 'studio')
        self.stop = threading.Event()
        self.thread = None
        self.error = None
        self.boot_time = now()

    def queue(self, channel_id):
        channel = self.store.channel(channel_id)
        return PublishingQueue(channel_settings(get_settings(), channel), self.root, channel_id=channel_id)

    def jobs(self):
        # Legacy registry is read only; job.json is written by the existing job owner.
        legacy = {}
        database = Path(get_settings().database_path)
        if database.is_file():
            with sqlite3.connect(database.resolve().as_uri() + '?mode=ro', uri=True) as db:
                db.row_factory = sqlite3.Row
                for record in db.execute('SELECT * FROM jobs ORDER BY created_at DESC LIMIT 10000'):
                    record = dict(record)
                    record['metadata'] = json.loads(record.get('metadata') or '{}')
                    legacy[record['id']] = record
        published = {r['job_id']: r for r in PublishingQueue(get_settings(), self.root).scan()}
        identifiers = set(legacy) | set(published) | {p.parent.name for p in self.root.glob('*/job.json')}
        rows = []
        for job_id in identifiers:
            directory = self.root / job_id
            record = read_json(directory / 'job.json', legacy.get(job_id, {}))
            metadata = {**record.get('metadata', {}), **read_json(directory / 'metadata.json', {})}
            if metadata.get('youtube_exclude'):
                continue
            yt = published.get(job_id, {})
            qc = read_json(directory / 'qc.json', {})
            status = metadata.get('generation_status', record.get('status', 'unknown'))
            if status == 'running' and (record.get('updated_at') or '')[:19] < self.boot_time[:19]:
                # Previous process cannot still own a render after this server restarted.
                active_ids = {c.get('job_id') for c in self.store.read()['content'] if c['stage'] == 'generating'}
                if job_id not in active_ids:
                    status = 'interrupted'
            stage = 'rendering' if record.get('stage') == 'VIDEO_RENDERING' and status == 'running' else ('generating' if status == 'running' else status)
            if status in ('completed', 'completed_with_fallback', 'uploaded'):
                stage = 'ready_to_publish' if qc.get('status') in ('pass', 'warning') and (qc.get('status') == 'pass' or qc.get('approved')) else 'qc'
            if yt.get('youtube_status') not in (None, 'pending', 'ready'):
                stage = yt['youtube_status']
                if stage in ('uploaded', 'thumbnail_uploading', 'thumbnail_uploaded', 'processing_complete'):
                    stage = 'processing'
            if qc.get('status') == 'fail' and not yt.get('youtube_video_id'):
                stage = 'failed'
            rows.append({'job_id': job_id, 'title': yt.get('title') or metadata.get('youtube_title') or record.get('topic', job_id),
                         'channel_id': metadata.get('channel_id', yt.get('channel_id', 'focus-protocol')), 'stage': stage,
                         'generation_status': status, 'created_at': record.get('created_at', metadata.get('started_at', '')),
                         'duration_seconds': metadata.get('target_duration_seconds'), 'metadata': metadata, 'youtube': yt, 'qc': qc,
                         'error': yt.get('last_error') or record.get('error_message') or ('Interrupted before this server started; retry this item.' if status == 'interrupted' else None),
                         'video_exists': Path(yt.get('video_path') or metadata.get('video_path') or directory / 'output/final_90min_video.mp4').is_file()})
        return sorted(rows, key=lambda r: r['created_at'], reverse=True)

    def job(self, job_id):
        if not isinstance(job_id, str) or not job_id or Path(job_id).name != job_id or '/' in job_id or '\\' in job_id or job_id in ('.', '..'):
            raise ValueError('Invalid job ID')
        row = next((r for r in self.jobs() if r['job_id'] == job_id), None)
        if not row:
            raise ValueError('Job not found')
        return row

    def save_channel(self, data):
        channel = Channel.model_validate(data).model_dump()
        if len(channel['upload_times']) != channel['videos_per_day']:
            raise ValueError('Provide one preferred time per daily video')
        if channel['theme'] not in THEMES or channel['render_preset'] not in PRESETS:
            raise ValueError('Unknown theme or render preset')
        if channel['thumbnail_style'] not in ('branded', 'local'):
            raise ValueError('Choose branded or local thumbnails')
        from PIL import ImageColor
        ImageColor.getrgb(channel['thumbnail_color'])
        with self.store.transaction() as state:
            if not any(p['id'] == channel['profile_id'] for p in state['profiles']):
                raise ValueError('Unknown content profile')
            old = next((c for c in state['channels'] if c['id'] == channel['id']), None)
            # A verified account binding cannot be silently changed in a form.
            if old and old.get('youtube_channel_id') and channel['youtube_channel_id'] != old['youtube_channel_id']:
                raise ValueError('Reconnect YouTube to change its channel binding')
            state['channels'] = [c for c in state['channels'] if c['id'] != channel['id']] + [channel]
        return channel

    def add_content(self, channel_id, titles, duration=None, planned=False):
        channel = self.store.channel(channel_id)
        titles = [t.strip() for t in titles if isinstance(t, str) and t.strip()]
        if not 1 <= len(titles) <= 50 or any(len(t) > 160 for t in titles):
            raise ValueError('Provide 1–50 concepts, up to 160 characters each')
        duration = int(duration or channel['duration_minutes'])
        if not 1 <= duration <= 180:
            raise ValueError('Duration must be 1–180 minutes')
        created = []
        with self.store.transaction() as state:
            for title in titles:
                if any(c['channel_id'] == channel_id and c['title'].casefold() == title.casefold() for c in state['content']):
                    raise ValueError(f'Concept already exists: {title}')
                row = dict(id=uuid.uuid4().hex, channel_id=channel_id, title=title, duration_minutes=duration,
                           stage='planned' if planned else 'ideas', created_at=now(), job_id=None, attempts=0)
                state['content'].append(row); created.append(row)
        return created

    def plan(self, ids):
        with self.store.transaction() as state:
            rows = [c for c in state['content'] if c['id'] in ids]
            if len(rows) != len(set(ids)):
                raise ValueError('Unknown content item')
            for row in rows:
                if row['stage'] not in ('ideas', 'failed', 'interrupted'):
                    raise ValueError('Only ideas or failed items can be queued')
                row.update(stage='planned', error=None)
            state['paused'] = False

    def retry_generation(self, job_id):
        job = self.job(job_id)
        if job['generation_status'] not in ('failed', 'interrupted'):
            raise ValueError('Only failed or interrupted generation can be retried')
        item = next((c for c in self.store.read()['content'] if c.get('job_id') == job_id), None)
        if item:
            self.plan([item['id']])
        else:
            title = job['metadata'].get('background_prompt', {}).get('title') or job['title']
            item = self.add_content(job['channel_id'], [title + ' — retry ' + job_id[:8]], round((job['duration_seconds'] or 600) / 60))[0]
            self.plan([item['id']])
        return item

    def qc(self, job_id, approve=False):
        row = self.job(job_id)
        if not row['video_exists'] or row['generation_status'] not in ('completed', 'completed_with_fallback', 'uploaded'):
            raise ValueError('Wait for a completed render before QC')
        result = qc_job(self.root / job_id, row['youtube'], row['metadata'])
        if approve and result['status'] != 'fail':
            result.update(approved=True, approved_at=now())
            write_json(self.root / job_id / 'qc.json', result)
        return result

    def edit_metadata(self, job_id, data):
        row = self.job(job_id)
        queue = self.queue(row['channel_id'])
        with publishing_lock(self.root):
            yt = next(r for r in queue.scan() if r['job_id'] == job_id)
            if yt['youtube_status'] in ('uploading', 'needs_review'):
                raise ValueError('Resolve the upload outcome before editing metadata')
            yt.update({k: data[k] for k in ('title', 'description', 'tags') if k in data})
            validate_video(yt['video_path'], yt)
            yt['metadata_dirty'] = True
            yt['metadata_verified'] = False
            queue.save(yt)
        return yt

    def enqueue_publish(self, job_ids):
        if not isinstance(job_ids, list) or not 1 <= len(job_ids) <= 50:
            raise ValueError('Select 1–50 videos')
        rows = [self.job(j) for j in dict.fromkeys(job_ids)]
        for row in rows:
            if not row['youtube'].get('youtube_video_id'):
                result = self.qc(row['job_id'], approve=False)
                previous = row['qc']
                approved = previous.get('approved') and previous.get('fingerprint') == result.get('fingerprint')
                if result['status'] == 'fail' or (result['status'] == 'warning' and not approved):
                    raise ValueError(f"Review QC for {row['title']} before publishing")
                if approved:
                    result.update(approved=True, approved_at=previous.get('approved_at'))
                    write_json(self.root / row['job_id'] / 'qc.json', result)
        with publishing_lock(self.root):
            queues = {}
            reservations = {}
            for row in rows:
                cid = row['channel_id']
                if cid not in queues:
                    queues[cid] = self.queue(cid)
                    reservations[cid] = [r.get('scheduled_publish_time') for r in queues[cid].scan()]
                queue = queues[cid]
                yt = next(r for r in queue.scan() if r['job_id'] == row['job_id'])
                if not yt.get('scheduled_publish_time') and not yt.get('youtube_video_id'):
                    yt['scheduled_publish_time'] = next_slot(queue.settings, reservations[cid])
                    yt['schedule_source'] = 'automatic'
                    reservations[cid].append(yt['scheduled_publish_time'])
                    queue.save(yt)
        batch = dict(id=uuid.uuid4().hex, created_at=now(), status='queued', jobs=[dict(job_id=r['job_id'], channel_id=r['channel_id'], status='queued', attempts=0) for r in rows])
        with self.store.transaction() as state:
            busy = {j['job_id'] for b in state['batches'] for j in b['jobs'] if j['status'] in ('queued', 'running', 'processing')}
            if busy.intersection(job_ids):
                raise ValueError('One or more videos are already in a publishing batch')
            state['batches'].append(batch)
        return batch

    def start(self):
        if self.thread and self.thread.is_alive():
            return
        self.thread = threading.Thread(target=self._loop, daemon=True, name='studio-coordinator')
        self.thread.start()

    def _loop(self):
        while not self.stop.is_set():
            self._run_worker_once()
            self.stop.wait(5)

    def _run_worker_once(self):
        try:
            # This lock survives threads and is released by the OS after a crash.
            with publishing_lock(self.store.root / 'worker'):
                self._recover()
                while not self.stop.is_set():
                    try:
                        self.tick()
                        self.error = None
                    except Exception as error:
                        self.error = f'{type(error).__name__}: {error}'
                    self.stop.wait(5)
        except RuntimeError:
            self.error = 'Another studio coordinator is already running'

    def _recover(self):
        with self.store.transaction() as state:
            for item in state['content']:
                if item['stage'] == 'generating':
                    meta = read_json(self.root / item['job_id'] / 'metadata.json', {})
                    if meta.get('generation_status') in ('completed', 'completed_with_fallback'):
                        item['stage'] = 'ready'
                    else:
                        item.update(stage='interrupted', error='Generation was interrupted. Retry only this item; completed items are retained.')
            for batch in state['batches']:
                for item in batch['jobs']:
                    if item['status'] == 'running':
                        item['status'] = 'queued'  # PublishingQueue reconciles saved IDs / ambiguous uploads.

    def _batch_update(self, batch_id, job_id, **changes):
        with self.store.transaction() as state:
            batch = next(b for b in state['batches'] if b['id'] == batch_id)
            item = next(j for j in batch['jobs'] if j['job_id'] == job_id)
            item.update(changes)
            statuses = {j['status'] for j in batch['jobs']}
            batch['status'] = 'running' if statuses & {'queued', 'running', 'processing'} else ('needs_attention' if 'failed' in statuses else 'complete')

    def _publish_item(self, batch, item):
        self._batch_update(batch['id'], item['job_id'], status='running', attempts=item['attempts'] + 1)
        try:
            channel = self.store.channel(item['channel_id'])
            queue = self.queue(channel['id'])
            connection = queue.service.connection_status()
            if not connection.get('connected'):
                raise ValueError('Connect this channel to YouTube before publishing')
            if channel.get('youtube_channel_id') and connection.get('channel_id') != channel['youtube_channel_id']:
                raise ValueError('Connected YouTube account does not match the selected channel')
            yt = next(r for r in queue.scan() if r['job_id'] == item['job_id'])
            if yt.get('metadata_dirty') and yt.get('youtube_video_id'):
                with publishing_lock(self.root):
                    queue.service.update_metadata(yt['youtube_video_id'], yt)
                    yt['metadata_dirty'] = False
                    queue.save(yt)
            results = queue.publish(job_id=item['job_id'], wait=False)
            yt = results[-1] if results else next(r for r in queue.scan() if r['job_id'] == item['job_id'])
            stage = yt['youtube_status']
            status = 'complete' if stage in DONE and yt.get('publishing_verified_at') else ('processing' if stage == 'processing' else 'failed')
            if status == 'processing':
                started = yt.get('upload_timestamp') or now()
                if (datetime.now(timezone.utc) - datetime.fromisoformat(started)).total_seconds() > queue.settings.youtube_processing_timeout:
                    status = 'failed'
                    yt.update(youtube_status='processing_timeout', last_error='YouTube processing timed out. Retry verification using the saved video ID.')
                    queue.save(yt)
            self._batch_update(batch['id'], item['job_id'], status=status, checked_at=now(), error=yt.get('last_error'))
        except Exception as error:
            self._batch_update(batch['id'], item['job_id'], status='failed', error=str(error))

    def tick(self):
        state = self.store.read()
        # Explicit publishing requests run even when daily automation is paused.
        for batch in state['batches']:
            for item in batch['jobs']:
                due = not item.get('checked_at') or (datetime.now(timezone.utc) - datetime.fromisoformat(item['checked_at'])).total_seconds() >= 30
                if item['status'] == 'queued' or (item['status'] == 'processing' and due):
                    self._publish_item(batch, item)
                    return
        # Local schedules become published only after a fresh remote observation.
        publishing_rows = PublishingQueue(get_settings(), self.root).scan()
        for channel in state['channels']:
            due = next((r for r in publishing_rows if r['channel_id'] == channel['id'] and r['youtube_status'] == 'scheduled'
                        and r.get('scheduled_publish_time') and datetime.fromisoformat(r['scheduled_publish_time']) <= datetime.now(timezone.utc)
                        and (not r.get('processing_checked_at') or (datetime.now(timezone.utc) - datetime.fromisoformat(r['processing_checked_at'])).total_seconds() >= 300)), None)
            if due:
                from app.youtube.lifecycle import finish
                queue = self.queue(channel['id'])
                with publishing_lock(self.root):
                    finish(queue.service, queue.settings, due, queue.save, wait=False)
                return
        if state['paused']:
            return
        # Back pressure: publishing failures block new automatic production.
        if any(j['status'] == 'failed' for b in state['batches'] for j in b['jobs']):
            return
        jobs = self.jobs()
        for channel in state['channels']:
            ready = [r for r in jobs if r['channel_id'] == channel['id'] and r['stage'] == 'ready_to_publish']
            if channel['auto_publish'] and ready:
                self.enqueue_publish([r['job_id'] for r in ready[:channel['daily_target']]])
                return
            item = next((c for c in state['content'] if c['channel_id'] == channel['id'] and c['stage'] == 'planned'), None)
            pending = [r for r in jobs if r['channel_id'] == channel['id'] and r['stage'] in ('qc', 'ready_to_publish')]
            if not item and len(pending) >= channel['backlog_limit']:
                continue
            if not item and channel['auto_generate']:
                today = datetime.now(ZoneInfo(channel['timezone'])).date()
                produced = sum(c['channel_id'] == channel['id'] and c.get('started_at') and datetime.fromisoformat(c['started_at']).astimezone(ZoneInfo(channel['timezone'])).date() == today for c in state['content'])
                if produced < channel['daily_target']:
                    idea = next((c for c in state['content'] if c['channel_id'] == channel['id'] and c['stage'] == 'ideas'), None)
                    if idea:
                        self.plan([idea['id']]); return
            if item:
                self._generate(item, channel, state)
                return

    def _generate(self, item, channel, state):
        from app.pipeline.long_form_jazz_orchestrator import LongFormJazzOrchestrator
        with publishing_lock(self.root / 'studio_generation'):
            # Avoid overlapping the legacy UI's generation worker.
            from app.api import jazz_api
            if jazz_api.generation_thread and jazz_api.generation_thread.is_alive():
                return
            job_id = 'studio_' + item['id'] + '_' + str(item['attempts'] + 1)
            with self.store.transaction() as latest:
                saved = next(c for c in latest['content'] if c['id'] == item['id'])
                saved.update(stage='generating', job_id=job_id, attempts=item['attempts'] + 1, started_at=now())
            try:
                settings = get_settings().model_copy(deep=True)
                for key, value in PRESETS[channel['render_preset']].items():
                    setattr(settings, key, value)
                for key, value in THEMES[channel['theme']].items():
                    if key != 'name':
                        setattr(settings, key, value)
                settings.watermark_enabled = channel['watermark_enabled']
                settings.subscribe_overlay_enabled = channel['subscribe_enabled']
                settings.studio_motion_mode = channel.get('motion_mode', 'static')
                profile = next(p for p in state['profiles'] if p['id'] == channel['profile_id'])
                context = dict(channel=channel, profile=profile, content_id=item['id'], concept=item['title'], job_id=job_id)
                engine = LongFormJazzOrchestrator(settings, context=context)
                success = engine.run(video_count=1, duration_minutes=item['duration_minutes'])
                if not success:
                    raise RuntimeError('Generation failed; inspect the job and logs before retrying')
                self.qc(job_id)
                changes = dict(stage='ready', completed_at=now(), error=None)
            except Exception as error:
                changes = dict(stage='failed', error=str(error), completed_at=now())
            with self.store.transaction() as latest:
                next(c for c in latest['content'] if c['id'] == item['id']).update(changes)

    def snapshot(self):
        state = self.store.read()
        jobs = self.jobs()
        counts = Counter(r['stage'] for r in jobs)
        counts.update(c['stage'] for c in state['content'] if not c.get('job_id'))
        metrics = {}
        for key in ('render_elapsed_seconds', 'overlay_preparation_seconds', 'media_sourcing_seconds', 'audio_elapsed_seconds', 'total_elapsed_seconds'):
            values = [r['metadata'][key] for r in jobs if isinstance(r['metadata'].get(key), (float, int))]
            metrics[key] = {'average': sum(values) / len(values) if values else None, 'samples': len(values)}
        # Return only public channel/profile fields. No Settings dumps or credential content.
        return dict(channels=state['channels'], profiles=state['profiles'], content=state['content'], batches=state['batches'],
                    paused=state['paused'], jobs=jobs, counts=counts, metrics=metrics, worker_error=self.error,
                    themes=THEMES, presets=list(PRESETS), server_time=now())
