import json
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import Mock
import pytest
from app.config.settings import Settings
from app.youtube.publishing import PublishingQueue, next_slot
from app.youtube.state import write_json, publishing_lock


@pytest.fixture
def setup(tmp_path, monkeypatch):
    settings = Settings(_env_file=None, YOUTUBE_UPLOAD_ENABLED=True, DATABASE_PATH=str(tmp_path/'absent.db'))
    service = Mock()
    service.channel_videos.return_value = []
    def upload(path, metadata, uploaded_callback):
        service.video_details.return_value = {'snippet': metadata, 'status': {'privacyStatus': metadata['privacy_status'], 'publishAt': metadata.get('scheduled_publish_time')}, 'processingDetails': {'processingStatus': 'succeeded'}}
        result = {'video_id': 'abc123'}
        uploaded_callback(result)
        return result
    service.upload.side_effect = upload
    queue = PublishingQueue(settings, tmp_path, service)
    monkeypatch.setattr('app.youtube.publishing.validate_video', lambda *args: 60)
    def add(name, content=b'video'):
        directory=tmp_path/name; directory.mkdir()
        video=directory/'video.mp4'; video.write_bytes(content)
        write_json(directory/'metadata.json', {'generation_status':'completed','video_path':str(video),'youtube_title':name})
    return queue, service, add


def test_daily_schedule_and_existing_slots():
    s=Settings(_env_file=None)
    now=datetime(2026,9,9,0,0,tzinfo=timezone.utc)
    first=next_slot(s, [], now)
    second=next_slot(s, [first], now)
    third=next_slot(s, [first,second], now)
    assert first=='2026-09-09T03:30:00+00:00'
    assert second=='2026-09-09T12:30:00+00:00'
    assert third=='2026-09-10T03:30:00+00:00'


def test_automatic_reservation_recovers_from_expired_slot(setup):
    q, service, add = setup
    add('a')
    row = q.scan()[0]
    row.update(scheduled_publish_time='2020-01-01T09:00:00+00:00', schedule_source='automatic')
    q.save(row)
    result = q.publish()[0]
    assert result['youtube_status'] == 'scheduled'
    assert datetime.fromisoformat(result['scheduled_publish_time']) > datetime.now(timezone.utc)


def test_duplicate_restart_and_two_slots(setup):
    q, service, add=setup
    add('a'); add('b'); add('c',b'different')
    rows=q.publish()
    assert [r['youtube_status'] for r in rows]==['scheduled','duplicate','scheduled']
    assert service.upload.call_count==2
    assert q.publish()==[]


def test_uncertain_upload_never_retries_blindly(setup):
    q,service,add=setup; add('a')
    service.upload.side_effect=TimeoutError('lost response')
    assert q.publish()[0]['youtube_status']=='needs_review'
    assert q.publish()[0]['youtube_status']=='needs_review'
    assert service.upload.call_count==1
    row=q.scan()[0]
    service.video_details.return_value={'processingDetails':{'processingStatus':'failed'},'status':{'failureReason':'codec'}}
    service.channel_videos.return_value=[{'id':'recovered','snippet':{'tags':['engine-sha256-'+row['sha256']]},'status':{}}]
    assert q.publish()[0]['youtube_video_id']=='recovered'
    assert service.upload.call_count==1


def test_id_persisted_before_thumbnail_failure(setup):
    q,service,add=setup; add('a')
    def upload(path,metadata,uploaded_callback):
        uploaded_callback({'video_id':'saved'})
        raise RuntimeError('thumbnail failure')
    service.upload.side_effect=upload
    assert q.publish()[0]['youtube_video_id']=='saved'
    service.video_details.return_value={'processingDetails':{'processingStatus':'failed'}, 'status':{'failureReason':'codec'}}
    q.publish()
    assert service.upload.call_count == 1


def test_dry_run_does_not_upload_or_persist(setup):
    q,service,add=setup; add('a')
    assert q.publish(dry_run=True)[0]['youtube_status']=='ready'
    assert not list(q.root.glob('*/youtube.json'))
    service.upload.assert_not_called(); service.channel_videos.assert_not_called()


def test_invalid_metadata_fails_before_network_upload(setup, monkeypatch):
    q,service,add=setup; add('a')
    def invalid(*args): raise ValueError('Missing title')
    monkeypatch.setattr('app.youtube.publishing.validate_video', invalid)
    assert q.publish()[0]['youtube_status']=='failed'
    service.upload.assert_not_called()


def test_corrupt_state_blocks_publishing(setup):
    q,service,add=setup; add('a')
    (q.root/'a/youtube.json').write_text('{')
    with pytest.raises(RuntimeError): q.publish()
    service.upload.assert_not_called()


def test_lock_released_and_exclusive(tmp_path):
    with publishing_lock(tmp_path):
        with pytest.raises(RuntimeError):
            with publishing_lock(tmp_path): pass
    with publishing_lock(tmp_path): pass


def test_oauth_http_loopback_uses_code_exchange(tmp_path, monkeypatch):
    from app.youtube.oauth import YouTubeService
    from urllib.parse import urlencode
    import time
    settings=Settings(_env_file=None,YOUTUBE_TOKEN_FILE=str(tmp_path/'token.json'),YOUTUBE_REDIRECT_URI='http://localhost:5000/callback')
    s=YouTubeService(settings)
    monkeypatch.setattr(s,'_client_config',lambda:{})
    monkeypatch.setattr(s,'connection_status',lambda:{'connected':True})
    flow=Mock(); flow.credentials.to_json.return_value='{"token":"test"}'
    monkeypatch.setattr('google_auth_oauthlib.flow.Flow.from_client_config',Mock(return_value=flow))
    write_json(s.state_path,{'attempts':[{'state':'nonce','created':time.time()}]})
    s.complete_authorization('http://localhost:5000/callback?'+urlencode({'code':'test','state':'nonce'}))
    flow.fetch_token.assert_called_once_with(code='test')
    assert s.token_path.exists()
    assert not s.state_path.exists()


def test_oauth_rejects_bad_state(tmp_path):
    from app.youtube.oauth import YouTubeService
    s=YouTubeService(Settings(_env_file=None,YOUTUBE_TOKEN_FILE=str(tmp_path/'token.json'),YOUTUBE_REDIRECT_URI='http://localhost:5000/callback'))
    with pytest.raises(ValueError,match='state'): s.complete_authorization('http://localhost:5000/callback?code=x&state=invalid')

def test_remote_reserved_slots_are_avoided(setup):
    q,service,add=setup; add('a')
    slot=next_slot(q.settings, [])
    service.channel_videos.return_value=[{'id':'remote','status':{'publishAt':slot}}]
    assert q.publish()[0]['scheduled_publish_time']!=slot


def test_conflicting_explicit_schedule_fails(setup):
    q,service,add=setup; add('a')
    slot=next_slot(q.settings, [])
    row=q.scan()[0]; row['scheduled_publish_time']=slot; q.save(row)
    service.channel_videos.return_value=[{'id':'remote','status':{'publishAt':slot}}]
    assert q.publish()[0]['youtube_status']=='failed'
    service.upload.assert_not_called()


def test_validation_checks_real_probe(tmp_path):
    from app.youtube.publishing import validate_video
    with pytest.raises(ValueError,match='missing'): validate_video(tmp_path/'absent.mp4',{'title':'Test'})
    source=Path('jobs/render_benchmark_after/output/final_90min_video.mp4')
    if not source.exists(): pytest.skip('Run render benchmark first')
    assert validate_video(source,{'title':'Test'})>0
    with pytest.raises(ValueError,match='title'): validate_video(source,{'title':''})
    with pytest.raises(ValueError,match='duration'): validate_video(source,{'title':'Test','target_duration_seconds':600})


def test_scheduled_upload_private_and_retry(tmp_path,monkeypatch):
    from app.youtube.oauth import YouTubeService
    settings=Settings(_env_file=None)
    service=YouTubeService(settings)
    monkeypatch.setattr(service,'_credentials',lambda:Mock())
    client=Mock(); monkeypatch.setattr(service,'client',lambda:client)
    request=client.videos.return_value.insert.return_value
    request.next_chunk.return_value=(None,{'id':'result'})
    video=tmp_path/'v.mp4'; video.write_bytes(b'video')
    result=service.upload(video,{'title':'Test','scheduled_publish_time':'2099-01-01T09:00:00+05:30','privacy_status':'public'})
    body=client.videos.return_value.insert.call_args.kwargs['body']
    assert body['status']['privacyStatus']=='private'
    assert body['status']['publishAt'].startswith('2099-01-01')
    request.next_chunk.assert_called_once_with(num_retries=settings.max_retries)
    assert result['video_id']=='result'


def test_failed_generation_and_excluded_test_not_pending(setup):
    q,service,add=setup; add('a'); add('b')
    for name, extra in [('a',{'generation_status':'failed'}),('b',{'youtube_exclude':True})]:
        path=q.root/name/'metadata.json'; data=json.loads(path.read_text()); data.update(extra); write_json(path,data)
    assert q.scan()==[]


def test_refresh_persists_token(tmp_path,monkeypatch):
    from app.youtube.oauth import YouTubeService
    settings=Settings(_env_file=None,YOUTUBE_TOKEN_FILE=str(tmp_path/'token.json'))
    service=YouTubeService(settings); service.token_path.write_text('{}')
    credentials=Mock(expired=True,refresh_token='refresh',valid=True)
    credentials.to_json.return_value='{"token":"renewed"}'
    monkeypatch.setattr('google.oauth2.credentials.Credentials.from_authorized_user_file',lambda *a:credentials)
    assert service._credentials() is credentials
    credentials.refresh.assert_called_once()
    assert json.loads(service.token_path.read_text())['token']=='renewed'


def test_omniroute_sse(monkeypatch):
    from app.llm.gemini import GeminiProvider
    response=Mock(); response.text='data: {"choices":[{"delta":{"content":"OK"}}]}\n\ndata: [DONE]\n'
    monkeypatch.setattr('app.llm.gemini.requests.post',lambda *a,**k:response)
    provider=GeminiProvider(Settings(_env_file=None,LLM_PROVIDER='omniroute'))
    assert provider._call_omniroute('Test')=='OK'


def test_reconcile_does_not_claim_processing_success(setup):
    q, service, add = setup
    add('a')
    row=q.scan()[0]; row.update(youtube_video_id='existing', youtube_status='scheduled'); q.save(row)
    service.video_details.return_value={'status':{'privacyStatus':'public'}, 'processingDetails':{'processingStatus':'processing'}}
    assert q.reconcile()[0]['youtube_status']=='processing'
    service.upload.assert_not_called()
