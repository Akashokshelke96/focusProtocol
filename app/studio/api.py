"""Studio HTTP interface. Local files are served only from approved media roots."""
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit, parse_qs
from flask import Blueprint, jsonify, request, send_file, redirect
from app.studio.service import StudioService
from app.studio.store import read_json
from app.studio.profiles import ContentProfile, channel_settings, metadata_for
from app.config.settings import get_settings
from app.youtube.oauth import YouTubeService
from app.youtube.state import publishing_lock, write_json
from app.youtube.publishing import file_hash, instant, next_slot

studio = Blueprint('studio', __name__, url_prefix='/api/studio')
service = StudioService()


@studio.before_request
def local_writes():
    if request.method not in ('GET', 'HEAD', 'OPTIONS'):
        origin = request.headers.get('Origin')
        if origin and urlsplit(origin).netloc != request.host:
            return jsonify(error='Use the local studio to change state'), 403
        if not isinstance(request.get_json(silent=True), dict):
            return jsonify(error='Send a JSON object'), 400


@studio.errorhandler(ValueError)
@studio.errorhandler(RuntimeError)
@studio.errorhandler(KeyError)
def invalid(error):
    return jsonify(error=str(error)), 400


@studio.get('/state')
def state():
    return jsonify(service.snapshot())


@studio.post('/channels')
def save_channel():
    return jsonify(service.save_channel(request.get_json()))


@studio.post('/profiles')
def save_profile():
    profile = ContentProfile.model_validate(request.get_json()).model_dump()
    # Validate placeholders now, before a render consumes the profile.
    metadata_for(profile, {'name': 'Channel'}, 'Concept', 10)
    with service.store.transaction() as state:
        state['profiles'] = [p for p in state['profiles'] if p['id'] != profile['id']] + [profile]
    return jsonify(profile)


@studio.post('/content')
def add_content():
    data = request.get_json()
    return jsonify(items=service.add_content(data['channel_id'], data['titles'], data.get('duration_minutes'), data.get('planned', False)))


@studio.post('/plan')
def plan():
    service.plan(request.get_json().get('ids', []))
    return jsonify(ok=True)


@studio.post('/automation')
def automation():
    paused = request.get_json().get('paused')
    if type(paused) is not bool:
        raise ValueError('paused must be a boolean')
    with service.store.transaction() as state:
        state['paused'] = paused
    return jsonify(paused=paused)


@studio.post('/publish')
def publish():
    return jsonify(service.enqueue_publish(request.get_json().get('job_ids'))), 202


@studio.post('/batches/<batch_id>/retry')
def retry_batch(batch_id):
    with service.store.transaction() as state:
        batch = next((b for b in state['batches'] if b['id'] == batch_id), None)
        if not batch:
            raise ValueError('Unknown batch')
        for item in batch['jobs']:
            if item['status'] == 'failed':
                item.update(status='queued', error=None)
        batch['status'] = 'queued'
    return jsonify(ok=True)


@studio.get('/jobs/<job_id>')
def detail(job_id):
    return jsonify(service.job(job_id))


@studio.post('/jobs/<job_id>/qc')
def qc(job_id):
    return jsonify(service.qc(job_id, bool((request.get_json() or {}).get('approve'))))


@studio.post('/jobs/<job_id>/retry-generation')
def retry_generation(job_id):
    return jsonify(service.retry_generation(job_id)), 202


@studio.post('/jobs/<job_id>/metadata')
def metadata(job_id):
    return jsonify(service.edit_metadata(job_id, request.get_json()))


@studio.post('/jobs/<job_id>/thumbnail')
def thumbnail(job_id):
    from app.studio.assets import make_thumbnail
    row = service.job(job_id)
    if row['generation_status'] not in ('completed', 'completed_with_fallback', 'uploaded'):
        raise ValueError('Wait for generation to finish')
    text = (request.get_json() or {}).get('text', '').strip()
    if not text or len(text) > 60:
        raise ValueError('Use a short thumbnail headline, up to 60 characters')
    source = safe_asset(row['metadata'].get('generated_background_path', ''))
    output = (service.root / job_id / 'thumbnail/studio_thumbnail.jpg').resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    channel = service.store.channel(row['channel_id'])
    with publishing_lock(service.root):
        make_thumbnail(source, output, text, channel)
        queue = service.queue(row['channel_id'])
        yt = next(r for r in queue.scan() if r['job_id'] == job_id)
        revision = datetime.now(timezone.utc).isoformat()
        yt.update(thumbnail_path=str(output), thumbnail_uploaded=False, thumbnail_revision=revision)
        queue.save(yt)
        meta = read_json(service.root / job_id / 'metadata.json', {})
        meta.update(thumbnail_path=str(output), thumbnail_text=text, thumbnail_revision=revision)
        write_json(service.root / job_id / 'metadata.json', meta)
        (service.root / job_id / 'qc.json').unlink(missing_ok=True)
    return jsonify(ok=True)


@studio.post('/jobs/<job_id>/schedule')
def schedule(job_id):
    row = service.job(job_id)
    queue = service.queue(row['channel_id'])
    data = request.get_json() or {}
    with publishing_lock(service.root):
        rows = queue.scan()
        yt = next(r for r in rows if r['job_id'] == job_id)
        reserved = [r.get('scheduled_publish_time') for r in rows if r['job_id'] != job_id]
        slot = data.get('scheduled_publish_time') or next_slot(queue.settings, reserved)
        if instant(slot) <= datetime.now(timezone.utc) or instant(slot) in {instant(v) for v in reserved if v}:
            raise ValueError('Choose an unoccupied future slot')
        if yt.get('youtube_video_id'):
            queue.service.update_schedule(yt['youtube_video_id'], slot)
            yt['youtube_status'] = 'processing_complete'
            yt.pop('publishing_verified_at', None)
        yt['scheduled_publish_time'] = slot
        yt['schedule_source'] = 'manual' if data.get('scheduled_publish_time') else 'automatic'
        queue.save(yt)
    return jsonify(yt)


@studio.post('/jobs/<job_id>/retry/<operation>')
def retry_operation(job_id, operation):
    row = service.job(job_id)
    queue = service.queue(row['channel_id'])
    if operation not in ('thumbnail', 'metadata', 'processing', 'upload'):
        raise ValueError('Unknown publishing operation')
    with publishing_lock(service.root):
        yt = next(r for r in queue.scan() if r['job_id'] == job_id)
        if operation == 'thumbnail':
            yt['thumbnail_uploaded'] = False
        if operation == 'metadata':
            yt['metadata_dirty'] = True
        queue.save(yt)
    return jsonify(service.enqueue_publish([job_id])), 202


def asset_roots():
    root = Path.cwd().resolve()
    folders = [root / name for name in ('jobs', 'music', 'backgroundImages', 'thumbnail', 'thumbnails', 'watermark')]
    for channel in service.store.read()['channels']:
        folders.extend(root / channel[key] for key in ('music_dir', 'background_dir', 'thumbnail_dir'))
    return folders


def safe_asset(value):
    path = Path(value).resolve()
    if not any(path.is_relative_to(root.resolve()) for root in asset_roots()) or not path.is_file():
        raise ValueError('Media file not found')
    if path.suffix.lower() not in ('.mp4', '.mp3', '.aac', '.m4a', '.flac', '.wav', '.png', '.jpg', '.jpeg', '.webp'):
        raise ValueError('Unsupported media type')
    if any(part.startswith('.') for part in path.relative_to(Path.cwd()).parts):
        raise ValueError('Hidden files cannot be served')
    return path


@studio.get('/jobs/<job_id>/asset/<kind>')
def job_asset(job_id, kind):
    row = service.job(job_id)
    key = {'video': 'video_path', 'thumbnail': 'thumbnail_path', 'background': 'generated_background_path'}.get(kind)
    if not key:
        raise ValueError('Unknown asset kind')
    value = row['youtube'].get(key) or row['metadata'].get(key)
    if not value:
        raise ValueError('This job has no asset of this type')
    return send_file(safe_asset(value), conditional=True)


@studio.get('/media')
def media():
    state = service.store.read()
    jobs = service.jobs()
    paths = set()
    for directory in asset_roots():
        if directory.name == 'jobs':
            continue
        if directory.exists():
            paths.update(p.resolve() for p in directory.iterdir() if p.is_file())
    usage = {}
    for job in jobs:
        meta = job['metadata']
        for key in ('video_path', 'audio_path', 'thumbnail_path', 'generated_background_path', 'thumbnail_source'):
            if meta.get(key):
                path = Path(meta[key]).resolve()
                paths.add(path)
                usage.setdefault(str(path), []).append({'job_id': job['job_id'], 'channel_id': job['channel_id']})
        channel = meta.get('channel_snapshot') or next((c for c in state['channels'] if c['id'] == job['channel_id']), state['channels'][0])
        for name in meta.get('selected_music', []):
            path = (Path(channel['music_dir']) / name).resolve()
            paths.add(path)
            usage.setdefault(str(path), []).append({'job_id': job['job_id'], 'channel_id': job['channel_id']})
    rows = []
    for path in sorted(paths):
        try:
            safe_asset(path)
        except ValueError:
            continue
        suffix = path.suffix.lower()
        kind = 'video' if suffix == '.mp4' else ('music' if suffix in ('.mp3', '.wav', '.aac', '.flac', '.m4a') else 'image')
        stat = path.stat()
        key = str(path)
        rows.append(dict(path=key, name=path.name, type=kind, bytes=stat.st_size, modified=datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
                         usage=usage.get(key, []), **state['assets'].get(key, {})))
    return jsonify(assets=rows, bytes=sum(r['bytes'] for r in rows))


@studio.get('/media/preview')
def media_preview():
    return send_file(safe_asset(request.args.get('path', '')), conditional=True)


@studio.post('/media/inspect')
def inspect_media():
    data = request.get_json()
    path = safe_asset(data.get('path', ''))
    stat = path.stat()
    existing = service.store.read()['assets'].get(str(path), {})
    values = dict(existing)
    if values.get('fingerprint') != [stat.st_size, stat.st_mtime_ns]:
        values.update(sha256=file_hash(path), fingerprint=[stat.st_size, stat.st_mtime_ns])
    if path.suffix.lower() in ('.mp3', '.wav', '.aac', '.m4a', '.flac'):
        from app.providers.local_music import LocalMusicProvider
        values['duration'] = LocalMusicProvider()._get_audio_duration(path)
    else:
        from PIL import Image
        if path.suffix.lower() != '.mp4':
            with Image.open(path) as image:
                values['dimensions'] = [image.width, image.height]
                gray = list(image.convert('L').resize((9, 8)).getdata())
                values['perceptual_hash'] = format(sum((gray[y*9+x] > gray[y*9+x+1]) << (y*8+x) for y in range(8) for x in range(8)), '016x')
    for key in ('genre', 'mood', 'source', 'assigned_channel', 'marked_used'):
        if key in data:
            values[key] = data[key]
    with service.store.transaction() as state:
        state['assets'][str(path)] = values
    return jsonify(values)


@studio.get('/settings')
def settings():
    settings = get_settings()
    allowed = ('video_width', 'video_height', 'video_fps', 'ffmpeg_preset', 'ffmpeg_crf', 'target_duration_minutes',
               'audio_loop_track_count', 'jazz_audio_crossfade_seconds', 'waveform_enabled', 'waveform_height_ratio', 'waveform_width_ratio',
               'watermark_enabled', 'subscribe_overlay_enabled', 'youtube_upload_enabled', 'youtube_timezone', 'youtube_processing_timeout')
    return jsonify(values={key: getattr(settings, key) for key in allowed}, credentials={'youtube_client_configured': bool(settings.youtube_client_id or Path(settings.youtube_client_secrets_file).is_file()), 'image_api_configured': bool(settings.colab_image_api_url)},
                   storage='Channel profiles and queues: jobs/studio/operations.json. Per-job publishing: youtube.json. Existing registry retained for compatibility.')


def cleanup_candidates():
    candidates = []
    for job in service.jobs():
        if job['generation_status'] not in ('completed', 'completed_with_fallback', 'uploaded') or not job['video_exists']:
            continue
        directory = (service.root / job['job_id']).resolve()
        # Explicit disposable outputs only. Keep audio, source images, thumbnails and final MP4s.
        for name in ('render_background.png', 'waveform.mkv'):
            raw_path = directory / name
            if raw_path.is_symlink():
                continue
            path = raw_path.resolve()
            if path.parent == directory and path.name == name and path.is_file():
                candidates.append({'path': str(path), 'bytes': path.stat().st_size})
    return candidates


@studio.route('/cleanup', methods=['GET', 'POST'])
def cleanup():
    candidates = cleanup_candidates()
    if request.method == 'POST':
        selected = set((request.get_json() or {}).get('paths', []))
        for item in candidates:
            if item['path'] in selected:
                Path(item['path']).unlink()
        return jsonify(removed=sum(c['path'] in selected for c in candidates))
    return jsonify(candidates=candidates, bytes=sum(c['bytes'] for c in candidates))


@studio.get('/channels/<channel_id>/connection')
def connection(channel_id):
    queue = service.queue(channel_id)
    result = queue.service.connection_status()
    channel = service.store.channel(channel_id)
    if result.get('connected') and channel.get('youtube_channel_id') and result.get('channel_id') != channel['youtube_channel_id']:
        result = dict(connected=False, error='Connected account does not match this channel')
    elif result.get('connected') and not channel.get('youtube_channel_id'):
        with service.store.transaction() as state:
            row = next(c for c in state['channels'] if c['id'] == channel_id)
            row.update(youtube_channel_id=result['channel_id'], youtube_account=result['channel_name'])
    return jsonify(result)


@studio.get('/channels/<channel_id>/connect')
def connect(channel_id):
    channel = service.store.channel(channel_id)
    youtube = YouTubeService(channel_settings(get_settings(), channel))
    url = youtube.authorization_url()
    nonce = parse_qs(urlsplit(url).query)['state'][0]
    with service.store.transaction() as state:
        state.setdefault('oauth_channels', {})[nonce] = channel_id
    return redirect(url)


def complete_channel_callback(url):
    nonce = parse_qs(urlsplit(url).query).get('state', [''])[0]
    channel_id = service.store.read().get('oauth_channels', {}).get(nonce)
    if not channel_id:
        return None
    channel = service.store.channel(channel_id)
    result = YouTubeService(channel_settings(get_settings(), channel)).complete_authorization(url)
    if result.get('connected'):
        with service.store.transaction() as state:
            row = next(c for c in state['channels'] if c['id'] == channel_id)
            row.update(youtube_channel_id=result['channel_id'], youtube_account=result['channel_name'])
            state['oauth_channels'].pop(nonce, None)
    return result
