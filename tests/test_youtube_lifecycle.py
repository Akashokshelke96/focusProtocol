from unittest.mock import Mock
from app.config.settings import Settings
from app.youtube.lifecycle import finish


def resource(processing='succeeded', **status):
    return {'processingDetails': {'processingStatus': processing},
            'snippet': {'title': 'Test', 'description': '', 'tags': ['focus']},
            'status': {'privacyStatus': 'private', **status}}


def row():
    return {'youtube_video_id': 'saved', 'title': 'Test', 'tags': ['focus'], 'thumbnail_path': 'thumb.jpg'}


def test_wait_then_thumbnail_then_verification(monkeypatch):
    service=Mock(); service.video_details.side_effect=[resource('processing'), resource(), resource()]
    monkeypatch.setattr('app.youtube.lifecycle.time.sleep', lambda _: None)
    state=row(); snapshots=[]
    finish(service, Settings(_env_file=None), state, lambda r:snapshots.append(r.copy()))
    assert state['youtube_status']=='private'
    assert state['thumbnail_uploaded'] and state['publishing_verified_at']
    assert snapshots[0]['youtube_status']=='processing'
    service.upload.assert_not_called()


def test_timeout_is_recoverable(monkeypatch):
    service=Mock(); service.video_details.return_value=resource('processing')
    ticks=iter([0, 2]); monkeypatch.setattr('app.youtube.lifecycle.time.monotonic', lambda:next(ticks))
    state=row(); finish(service, Settings(_env_file=None,YOUTUBE_PROCESSING_TIMEOUT=1), state, lambda _:None)
    assert state['youtube_status']=='processing_timeout' and state['youtube_video_id']=='saved'
    service.upload_thumbnail.assert_not_called()


def test_thumbnail_retry_never_uploads_video_again():
    service=Mock(); service.video_details.return_value=resource()
    service.upload_thumbnail.side_effect=RuntimeError('retry')
    state=row(); finish(service, Settings(_env_file=None), state, lambda _:None)
    assert state['youtube_status']=='thumbnail_retry'
    service.upload_thumbnail.side_effect=None
    finish(service, Settings(_env_file=None), state, lambda _:None)
    assert state['youtube_status']=='private'
    service.upload.assert_not_called()


def test_unaccepted_schedule_is_not_success():
    service=Mock(); service.video_details.return_value=resource()
    state=row(); state['scheduled_publish_time']='2099-01-01T09:00:00Z'
    finish(service, Settings(_env_file=None), state, lambda _:None)
    assert state['youtube_status']=='verification_failed'
    assert 'schedule' in state['last_error']


def test_processing_failure_is_terminal():
    service=Mock(); service.video_details.return_value=resource('failed', failureReason='codec')
    state=row(); finish(service, Settings(_env_file=None), state, lambda _:None)
    assert state['youtube_status']=='failed' and state['last_error']=='codec'
    service.upload_thumbnail.assert_not_called()
