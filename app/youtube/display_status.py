"""Display-only projection of persisted YouTube state; never infer from an MP4."""
from collections import Counter

STATES = ('not_uploaded', 'uploading', 'processing', 'uploaded', 'scheduled', 'published', 'failed')
FAILURES = {'failed', 'needs_review', 'verification_failed', 'processing_timeout', 'thumbnail_retry'}


def publishing_state(row):
    status = row.get('youtube_status', 'pending')
    received = bool(row.get('youtube_video_id'))
    if status in FAILURES or row.get('processing_status') in ('failed', 'terminated'):
        stage = 'failed'
    elif not received:
        stage = 'uploading' if status == 'uploading' else 'not_uploaded'
    elif status == 'published' and row.get('publishing_verified_at'):
        stage = 'published'
    elif status == 'scheduled' and row.get('publishing_verified_at'):
        stage = 'scheduled'
    elif status in ('private', 'unlisted', 'processing_complete', 'thumbnail_uploaded') or row.get('processing_status') == 'succeeded':
        stage = 'uploaded'
    else:
        stage = 'processing'
    return {'state': stage, 'uploaded': received, 'video_id': row.get('youtube_video_id'),
            'last_checked': row.get('processing_checked_at') or row.get('publishing_verified_at'),
            'error': row.get('last_error')}


def status_counts(rows):
    counts = Counter(row['publishing']['state'] for row in rows)
    return {**{key: counts[key] for key in STATES}, 'total': len(rows),
            'uploaded_total': sum(row['publishing']['uploaded'] for row in rows)}
