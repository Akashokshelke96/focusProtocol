import json
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import Mock
import pytest
from app.studio.profiles import Channel, DEFAULT_PROFILES, metadata_for, channel_settings
from app.studio.store import StudioStore
from app.studio.service import StudioService
from app.youtube.state import write_json
from app.youtube.publishing import PublishingQueue, next_slot
from app.config.settings import Settings


def test_profiles_do_not_leak_jazz():
    for profile in DEFAULT_PROFILES:
        result = metadata_for(profile.model_dump(), {'name': 'Example'}, 'Evening Session', 10)
        assert len(result['youtube_title']) <= 100
        assert len(result['youtube_description']) < 500
        if profile.id != 'jazz':
            assert 'jazz' not in json.dumps(result).lower()


def test_independent_tokens_and_schedule():
    settings = Settings(_env_file=None)
    a = Channel(id='a', name='A').model_dump()
    b = Channel(id='b', name='B', timezone='UTC', upload_times=['10:00','20:00']).model_dump()
    sa, sb = channel_settings(settings, a), channel_settings(settings, b)
    assert sa.youtube_token_file != sb.youtube_token_file
    assert settings.youtube_timezone == 'Asia/Kolkata'
    now = datetime(2026, 9, 10, tzinfo=timezone.utc)
    slots = []
    for _ in range(4):
        slots.append(next_slot(sa, slots, now))
    assert [s[:10] for s in slots] == ['2026-09-10'] * 2 + ['2026-09-11'] * 2
    assert next_slot(sb, [], now) == '2026-09-10T10:00:00+00:00'


def test_channel_rejects_paths_and_bad_times():
    with pytest.raises(ValueError):
        Channel(id='../escape', name='x')
    with pytest.raises(ValueError):
        Channel(id='x', name='x', music_dir='../other-project')
    with pytest.raises(ValueError):
        Channel(id='x', name='x', upload_times=['09:00','09:00'])


def test_store_rolls_back_and_survives_restart(tmp_path):
    store = StudioStore(tmp_path)
    with store.transaction() as state:
        state['paused'] = False
    with pytest.raises(ValueError):
        with store.transaction() as state:
            state['paused'] = True
            raise ValueError('abort')
    assert StudioStore(tmp_path).read()['paused'] is False


def test_content_duplicate_and_recovery(tmp_path):
    service = StudioService(tmp_path)
    item = service.add_content('focus-protocol', ['Late Night'], 10)[0]
    with pytest.raises(ValueError, match='already exists'):
        service.add_content('focus-protocol', ['late night'])
    service.plan([item['id']])
    with service.store.transaction() as state:
        state['content'][0].update(stage='generating', job_id='one')
    service._recover()
    assert service.store.read()['content'][0]['stage'] == 'interrupted'
    write_json(tmp_path / 'one/metadata.json', {'generation_status':'completed'})
    with service.store.transaction() as state:
        state['content'][0]['stage'] = 'generating'
    service._recover()
    assert service.store.read()['content'][0]['stage'] == 'ready'


def test_channel_scoped_scan(tmp_path):
    settings = Settings(_env_file=None, DATABASE_PATH=str(tmp_path/'missing.db'))
    for name in ['a','b']:
        write_json(tmp_path/name/'metadata.json', {'generation_status':'completed', 'channel_id':name, 'youtube_title':name})
    assert [r['job_id'] for r in PublishingQueue(settings,tmp_path,channel_id='a').scan()] == ['a']


def test_failed_publishing_blocks_production(tmp_path, monkeypatch):
    service = StudioService(tmp_path)
    service.add_content('focus-protocol', ['Night'], planned=True)
    with service.store.transaction() as state:
        state['paused'] = False
        state['batches'] = [{'id':'b','status':'needs_attention','jobs':[{'job_id':'x','status':'failed'}]}]
    generate = Mock()
    monkeypatch.setattr(service, '_generate', generate)
    service.tick()
    generate.assert_not_called()


def test_http_context_and_no_secrets(tmp_path, monkeypatch):
    from app.api.jazz_api import app
    import app.studio.api as studio_api
    service = StudioService(tmp_path)
    monkeypatch.setattr(studio_api, 'service', service)
    monkeypatch.setattr(service, 'jobs', lambda: [])
    client = app.test_client()
    response = client.get('/api/studio/state')
    assert response.status_code == 200
    assert b'client_secret' not in response.data and b'refresh_token' not in response.data
    response = client.post('/api/studio/automation', json={'paused':False}, headers={'Origin':'https://unrelated.example'})
    assert response.status_code == 403
    assert client.get('/job/video-A').location == '/#job/video-A'
    assert client.get('/api/studio/media/preview?path=.env').status_code == 400


def test_batch_recovery_never_requeues_completed_items(tmp_path):
    service = StudioService(tmp_path)
    with service.store.transaction() as state:
        state['batches'] = [{'id':'batch', 'status':'running', 'jobs':[{'job_id':'1','status':'complete'}, {'job_id':'2','status':'running'}]}]
    StudioService(tmp_path)._recover()
    assert [r['status'] for r in service.store.read()['batches'][0]['jobs']] == ['complete','queued']


def test_save_channel_requires_daily_slots(tmp_path):
    service = StudioService(tmp_path)
    with pytest.raises(ValueError, match='preferred time'):
        service.save_channel(Channel(id='new', name='New', videos_per_day=3).model_dump())


def test_twenty_videos_get_ten_days_of_slots():
    settings = Settings(_env_file=None)
    slots = []
    now = datetime(2026, 9, 10, tzinfo=timezone.utc)
    for _ in range(20):
        slots.append(next_slot(settings, slots, now))
    from collections import Counter
    assert len(set(slots)) == 20
    assert list(Counter(slot[:10] for slot in slots).values()) == [2] * 10


def test_legacy_upload_route_keeps_clicked_video(monkeypatch):
    from app.api.jazz_api import app
    from app.studio.api import service
    enqueue = Mock(return_value={'id':'batch'})
    monkeypatch.setattr(service, 'enqueue_publish', enqueue)
    response = app.test_client().post('/api/jazz/video/selected-video/upload', json={})
    assert response.status_code == 202
    enqueue.assert_called_once_with(['selected-video'])


def test_explicit_planned_content_ignores_automatic_backlog_limit(tmp_path, monkeypatch):
    service = StudioService(tmp_path)
    item = service.add_content('focus-protocol', ['Explicit concept'], planned=True)[0]
    with service.store.transaction() as state:
        state['paused'] = False
    monkeypatch.setattr(service, 'jobs', lambda: [{'channel_id':'focus-protocol','stage':'qc'}] * 30)
    generate = Mock()
    monkeypatch.setattr(service, '_generate', generate)
    service.tick()
    assert generate.call_args.args[0]['id'] == item['id']
