"""Recoverable post-upload verification; a video ID is never uploaded again."""
import time
from datetime import datetime, timezone


def observe(row, video):
    status = video.get('status', {})
    processing = video.get('processingDetails', {})
    row.update(processing_status=processing.get('processingStatus', 'unknown'),
               remote_privacy_status=status.get('privacyStatus'),
               remote_publish_at=status.get('publishAt'),
               processing_checked_at=datetime.now(timezone.utc).isoformat())
    if status.get('uploadStatus') in ('failed', 'rejected', 'deleted') or row['processing_status'] in ('failed', 'terminated'):
        row.update(youtube_status='failed', last_error=status.get('failureReason') or status.get('rejectionReason') or processing.get('processingFailureReason') or 'YouTube processing failed')
        return False
    if row['processing_status'] != 'succeeded':
        row['youtube_status'] = 'processing'
        return False
    row['youtube_status'] = 'processing_complete'
    row.setdefault('processing_completed_at', datetime.now(timezone.utc).isoformat())
    if row.get('upload_timestamp'):
        row['processing_elapsed_seconds'] = round((datetime.fromisoformat(row['processing_completed_at']) - datetime.fromisoformat(row['upload_timestamp'])).total_seconds(), 3)
    return True


def finish(service, settings, row, save, wait=True):
    deadline = time.monotonic() + settings.youtube_processing_timeout
    row['last_error'] = None
    try:
        while True:
            video = service.video_details(row['youtube_video_id'])
            ready = observe(row, video)
            save(row)
            if ready:
                break
            if row['youtube_status'] == 'failed' or not wait:
                return row
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                row.update(youtube_status='processing_timeout', last_error='YouTube is still processing. Retry this job to resume verification without re-uploading.')
                save(row)
                return row
            time.sleep(min(settings.youtube_processing_poll_interval, remaining))
        if row.get('thumbnail_path') and not row.get('thumbnail_uploaded'):
            row['youtube_status'] = 'thumbnail_uploading'
            save(row)
            from app.studio.assets import verify_job_assets
            verify_job_assets(row)
            if row.get('assets'):
                from app.studio.assets import ensure_uploadable_thumbnail
                row['thumbnail_path'] = str(ensure_uploadable_thumbnail(row['assets']['thumbnail']['path']))
            service.upload_thumbnail(row['youtube_video_id'], row['thumbnail_path'])
            row.update(thumbnail_uploaded=True, youtube_status='thumbnail_uploaded')
            save(row)
        elif not row.get('thumbnail_path'):
            row['thumbnail_status'] = 'not_requested'
        video = service.video_details(row['youtube_video_id'])
        snippet, status = video.get('snippet', {}), video.get('status', {})
        errors = []
        for field in ('title', 'description'):
            if snippet.get(field, '') != row.get(field, ''):
                errors.append(field + ' differs from the requested metadata')
        if not set(row.get('tags', [])).issubset(snippet.get('tags', [])):
            errors.append('requested tags are missing')
        scheduled = row.get('scheduled_publish_time')
        parse = lambda value: datetime.fromisoformat(value.replace('Z', '+00:00'))
        if scheduled and parse(scheduled) > datetime.now(timezone.utc):
            if status.get('privacyStatus') != 'private' or not status.get('publishAt') or parse(status['publishAt']) != parse(scheduled):
                errors.append('YouTube did not confirm the requested private schedule')
        elif scheduled:
            if status.get('privacyStatus') != 'public':
                errors.append('scheduled time passed but the video is not public')
        elif status.get('privacyStatus') != row.get('privacy_status', 'private'):
            errors.append('visibility differs from the requested setting')
        row.update(metadata_verified=not any('metadata' in e or 'tags' in e for e in errors),
                   remote_privacy_status=status.get('privacyStatus'), remote_publish_at=status.get('publishAt'))
        if errors:
            row.update(youtube_status='verification_failed', last_error='; '.join(errors))
        else:
            row.update(youtube_status='scheduled' if status.get('publishAt') else ('published' if status.get('privacyStatus') == 'public' else status.get('privacyStatus', 'private')),
                       publishing_verified_at=datetime.now(timezone.utc).isoformat(), last_error=None)
        save(row)
    except Exception as error:
        message = f'{type(error).__name__}: verification failed; retry using the saved video ID.'
        if hasattr(error, 'content'):
            try:
                import json
                detail = json.loads(error.content).get('error', {})
                message = f"YouTube {detail.get('code', '')}: {detail.get('message', 'Operation failed')}"
            except (ValueError, TypeError):
                pass
        row.update(youtube_status='thumbnail_retry' if row.get('youtube_status') == 'thumbnail_uploading' else 'verification_failed', last_error=message)
        save(row)
    return row
