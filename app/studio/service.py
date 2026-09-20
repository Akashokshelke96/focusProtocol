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
from app.youtube.display_status import publishing_state, status_counts
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

    def jobs(self, include_excluded=False):
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
        identifiers = set(legacy) | set(published) | {p.parent.name for p in self.root.glob('*/job.json')} | {p.parent.name for p in self.root.glob('*/youtube.json')}
        rows = []
        deleted = set(self.store.read().get('deleted_jobs', []))
        for job_id in identifiers:
            if job_id in deleted:
                continue
            directory = self.root / job_id
            record = read_json(directory / 'job.json', legacy.get(job_id, {}))
            metadata = {**record.get('metadata', {}), **read_json(directory / 'metadata.json', {})}
            if metadata.get('youtube_exclude') and not include_excluded:
                continue
            yt = {**published.get(job_id, {}), **read_json(directory / 'youtube.json', {})}
            qc = read_json(directory / 'qc.json', {})
            status = record.get('status') or metadata.get('generation_status', 'unknown')
            stage = 'rendering' if record.get('stage') == 'VIDEO_RENDERING' and status == 'running' else ('generating' if status == 'running' else status)
            if status == 'running' and record.get('stage') in ('APPLY_MOTION_RENDER', 'VALIDATE_OUTPUT'):
                stage = 'qc'
            if status in ('completed', 'completed_with_fallback', 'uploaded'):
                stage = 'ready_to_publish' if qc.get('status') in ('pass', 'warning') and (qc.get('status') == 'pass' or qc.get('approved')) else 'qc'
            if yt.get('youtube_status') not in (None, 'pending', 'ready'):
                stage = yt['youtube_status']
                if stage in ('private', 'unlisted'):
                    stage = 'uploaded'
                elif stage in ('uploaded', 'thumbnail_uploading', 'thumbnail_uploaded', 'processing_complete'):
                    stage = 'processing'
            if qc.get('status') == 'fail' and not yt.get('youtube_video_id'):
                stage = 'failed'
            rows.append({'job_id': job_id, 'title': yt.get('title') or metadata.get('youtube_title') or record.get('topic', job_id),
                         'channel_id': metadata.get('channel_id', yt.get('channel_id', 'focus-protocol')), 'stage': stage,
                         'publishing': publishing_state(yt), 'generation_status': status, 'created_at': record.get('created_at', metadata.get('started_at', '')),
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
        row['render_progress'] = read_json(self.root / job_id / 'render_progress.json', {})
        row['render_resources'] = read_json(self.root / job_id / 'render_resources.json', {})
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

    def add_content(self, channel_id, titles, duration=None, planned=False, waveform_style=None, waveform_enabled=None,
                      background_mode='image', lyrics_captions=False, visual_effect=None, visual_effect_opacity=None):
        channel = self.store.channel(channel_id)
        if waveform_enabled is None:
            waveform_enabled = channel.get('visualizer_enabled', True)
        from app.studio.profiles import Channel
        chosen_filter = Channel.model_validate({**channel,
            'visual_effect': visual_effect if visual_effect is not None else channel.get('visual_effect', 'old_film'),
            'visual_effect_opacity': visual_effect_opacity if visual_effect_opacity is not None else channel.get('visual_effect_opacity', .06)})
        waveform_style = waveform_style or channel.get('waveform_style', 'linear')
        if waveform_style not in ('linear', 'circular'):
            raise ValueError('Choose Linear or Circular visualizer')
        if type(waveform_enabled) is not bool:
            raise ValueError('waveform_enabled must be a boolean')
        if background_mode not in ('image', 'video'):
            raise ValueError('Choose image or looping video background')
        if type(lyrics_captions) is not bool:
            raise ValueError('lyrics_captions must be a boolean')
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
                           stage='planned' if planned else 'ideas', created_at=now(), job_id=None, attempts=0,
                           waveform_style=waveform_style, waveform_enabled=waveform_enabled, visualizer_enabled=waveform_enabled,
                           background_mode=background_mode, lyrics_captions=lyrics_captions,
                           visual_effect=chosen_filter.visual_effect, visual_effect_opacity=chosen_filter.visual_effect_opacity)
                state['content'].append(row); created.append(row)
            if planned:
                state['paused'] = False
        return created

    def create_videos(self, channel_id, count, request_id, duration=None, waveform_enabled=None, waveform_style=None,
                      background_mode='image', lyrics_captions=False, visual_effect=None, visual_effect_opacity=None):
        if type(count) is not int or not 1 <= count <= 100:
            raise ValueError('Choose 1–100 videos')
        if not isinstance(request_id, str) or not 8 <= len(request_id) <= 100:
            raise ValueError('A request ID is required to prevent duplicate batches')
        channel = self.store.channel(channel_id)
        if waveform_enabled is None:
            waveform_enabled = channel.get('visualizer_enabled', True)
        if type(waveform_enabled) is not bool:
            raise ValueError('waveform_enabled must be a boolean')
        from app.studio.profiles import Channel
        chosen_filter = Channel.model_validate({**channel,
            'visual_effect': visual_effect if visual_effect is not None else channel.get('visual_effect', 'old_film'),
            'visual_effect_opacity': visual_effect_opacity if visual_effect_opacity is not None else channel.get('visual_effect_opacity', .06)})
        waveform_style = waveform_style or channel.get('waveform_style', 'linear')
        if waveform_style not in ('linear', 'circular'):
            raise ValueError('Choose Linear or Circular visualizer')
        if background_mode not in ('image', 'video'):
            raise ValueError('Choose image or looping video background')
        if type(lyrics_captions) is not bool:
            raise ValueError('lyrics_captions must be a boolean')
        minutes = int(duration or channel['duration_minutes'])
        if not 1 <= minutes <= 180:
            raise ValueError('Duration must be 1–180 minutes')
        with self.store.transaction() as state:
            previous = [c for c in state['content'] if c.get('request_id') == request_id]
            if previous:
                if len(previous) != count or any(c['channel_id'] != channel_id or c['duration_minutes'] != minutes for c in previous):
                    raise ValueError('Request ID was already used for a different batch')
                return previous
            profile = next(p for p in state['profiles'] if p['id'] == channel['profile_id'])
            created = []
            for index in range(count):
                identity = uuid.uuid4().hex
                row = dict(id=identity, job_id='studio_' + identity, request_id=request_id,
                           channel_id=channel_id, channel_snapshot=channel, profile_snapshot=profile,
                           title=f'Preparing video {index+1}', automatic=True, duration_minutes=minutes,
                           stage='planned', created_at=now(), attempts=0,
                           waveform_style=waveform_style, waveform_enabled=waveform_enabled, visualizer_enabled=waveform_enabled,
                           background_mode=background_mode, lyrics_captions=lyrics_captions,
                           visual_effect=chosen_filter.visual_effect, visual_effect_opacity=chosen_filter.visual_effect_opacity)
                state['content'].append(row)
                created.append(row)
            state['paused'] = False
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
            try:
                self._run_worker_once()
            except Exception as error:
                self.error = f'Coordinator recovery failed: {type(error).__name__}: {error}'
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
        from app.studio.recovery import reconcile
        reconcile(self)
        with self.store.transaction() as state:
            for item in state['content']:
                if item['stage'] == 'generating':
                    meta = read_json(self.root / item['job_id'] / 'metadata.json', {})
                    record = read_json(self.root / item['job_id'] / 'job.json', {})
                    if record.get('status') == 'running':
                        continue
                    if record.get('status') in ('completed', 'completed_with_fallback'):
                        item['stage'] = 'ready'
                    else:
                        item.update(stage='failed' if record.get('status') == 'failed' else 'interrupted', error=record.get('error_message') or 'Generation was interrupted. Retry only this item; completed items are retained.')
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
                raise ValueError('YouTube connection failed: ' + (connection.get('error') or 'Click Connect YouTube to sign in.'))
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
        from app.studio.recovery import reconcile
        reconcile(self)
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
        jobs = self.jobs()
        # Explicit production requests do not depend on unrelated publishing failures.
        item = next((c for c in state['content'] if c['stage'] == 'planned'), None)
        if item:
            channel = item.get('channel_snapshot') or self.store.channel(item['channel_id'])
            self._generate(item, channel, state)
            return
        if any(j['status'] == 'failed' for b in state['batches'] for j in b['jobs']):
            return
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
                with self.store.transaction() as latest:
                    next(c for c in latest['content'] if c['id'] == item['id']).update(
                        stage='planned', error='Another generator is running; this item keeps its queue position.')
                return
            import psutil
            from app.video.resources import gpu_sample
            if psutil.virtual_memory().percent >= 95 or gpu_sample().get('temperature_c', 0) >= get_settings().render_gpu_max_temperature:
                raise RuntimeError('Production is waiting for available memory or GPU cooling; queued videos are retained.')
            job_id = item.get('job_id') or 'studio_' + item['id'] + '_1'
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
                settings.waveform_enabled = False
                settings.visualizer_enabled = item.get('visualizer_enabled', item.get('waveform_enabled', channel.get('visualizer_enabled', True)))
                settings.waveform_style = item.get('waveform_style', channel.get('waveform_style', 'linear'))
                settings.channel_brand_name = channel['name']
                settings.song_panel_enabled = channel.get('song_panel_enabled', False)
                settings.visual_effect = item.get('visual_effect', channel.get('visual_effect', 'old_film'))
                settings.visual_effect_opacity = item.get('visual_effect_opacity', channel.get('visual_effect_opacity', .06))
                settings.studio_motion_mode = channel.get('motion_mode', 'static')
                profile = item.get('profile_snapshot') or next(p for p in state['profiles'] if p['id'] == channel['profile_id'])
                plan = item.get('content_plan')
                if item.get('automatic') and not plan:
                    from app.studio.content import create_plan
                    from app.llm.gemini import GeminiProvider
                    history = [c['title'] for c in state['content'] if c['channel_id'] == channel['id'] and c['id'] != item['id'] and not c['title'].startswith('Preparing video ')]
                    history += [j['title'] for j in self.jobs() if j['channel_id'] == channel['id']]
                    plan = create_plan(GeminiProvider(settings), profile, channel, item['duration_minutes'], history)
                    item = dict(item, title=plan['concept'], content_plan=plan)
                    with self.store.transaction() as latest:
                        next(c for c in latest['content'] if c['id'] == item['id']).update(title=item['title'], content_plan=plan)
                context = dict(channel=channel, profile=profile, content_id=item['id'], concept=item['title'], job_id=job_id, content_plan=plan,
                               background_mode=item.get('background_mode', 'image'), lyrics_captions=item.get('lyrics_captions', False))
                engine = LongFormJazzOrchestrator(settings, context=context)
                if (self.root / job_id / 'job.json').exists():
                    success = engine.resume(job_id)
                else:
                    success = engine.run(video_count=1, duration_minutes=item['duration_minutes'])
                if not success:
                    raise RuntimeError(read_json(self.root / job_id / 'job.json', {}).get('error_message') or 'Generation failed; inspect the job and logs')
                result = self.job(job_id).get('qc') or self.qc(job_id)
                if result['status'] == 'fail':
                    raise RuntimeError('QC failed; inspect the failed checks')
                changes = dict(stage='ready', completed_at=now(), error=None)
            except Exception as error:
                changes = dict(stage='planned' if 'Another YouTube publishing operation' in str(error) else 'failed', error=str(error), completed_at=now())
            with self.store.transaction() as latest:
                next(c for c in latest['content'] if c['id'] == item['id']).update(changes)

    def snapshot(self):
        state = self.store.read()
        jobs = self.jobs()
        by_id = {j['job_id']: j for j in jobs}
        for item in state['content']:
            if item.get('job_id') in by_id and item['stage'] == 'planned':
                by_id[item['job_id']]['stage'] = 'planned'
            if item.get('job_id') in by_id and item['stage'] != 'planned':
                job = by_id[item['job_id']]
                item['stage'] = 'ready' if job['stage'] == 'ready_to_publish' else job['stage']
                item['error'] = job['error'] or item.get('error')
        batches = []
        for batch in state['batches']:
            members = [by_id.get(item['job_id'], {'publishing': publishing_state({'youtube_status': 'failed' if item['status'] == 'failed' else 'pending'})}) for item in batch['jobs']]
            batches.append({**batch, 'publishing_counts': status_counts(members)})
        counts = Counter(r['stage'] for r in jobs)
        counts.update(c['stage'] for c in state['content'] if c.get('job_id') not in by_id)
        metrics = {}
        for key in ('render_elapsed_seconds', 'overlay_preparation_seconds', 'media_sourcing_seconds', 'audio_elapsed_seconds', 'total_elapsed_seconds'):
            values = [r['metadata'][key] for r in jobs if isinstance(r['metadata'].get(key), (float, int))]
            metrics[key] = {'average': sum(values) / len(values) if values else None, 'samples': len(values)}
        # Return only public channel/profile fields. No Settings dumps or credential content.
        return dict(channels=state['channels'], profiles=state['profiles'], content=state['content'], batches=batches, publishing_counts=status_counts(jobs),
                    paused=state['paused'], jobs=jobs, counts=counts, metrics=metrics, worker_error=self.error,
                    themes=THEMES, presets=list(PRESETS), server_time=now())
