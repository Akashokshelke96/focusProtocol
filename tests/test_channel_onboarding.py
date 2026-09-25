import json
from pathlib import Path
from unittest.mock import Mock
import pytest

from app.config.settings import Settings
from app.studio.profiles import Channel, channel_settings
from app.studio.service import StudioService
from app.youtube.oauth import YouTubeService
from app.youtube.publishing import PublishingQueue
from app.youtube.state import write_json


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    from app.api.jazz_api import app
    import app.studio.api as api
    monkeypatch.chdir(tmp_path)
    settings = Settings(_env_file=None, DATABASE_PATH=str(tmp_path/'missing.db'),
                        YOUTUBE_CLIENT_ID='legacy-client', YOUTUBE_CLIENT_SECRET='legacy-secret',
                        YOUTUBE_TOKEN_FILE='youtube_token.json', YOUTUBE_REDIRECT_URI='http://localhost:5001/callback')
    service = StudioService()
    for module in ('app.studio.api', 'app.studio.service', 'app.api.jazz_api'):
        monkeypatch.setattr(module+'.get_settings', lambda: settings)
    monkeypatch.setattr(api, 'service', service)
    return app.test_client(), service, settings


def onboard(client, id='wolfie-blues'):
    return client.post('/api/studio/channels', json=dict(id=id, name=id, create_only=True,
        music_dir='music-'+id, background_dir='backgroundImages-'+id, thumbnail_dir='thumbnail-'+id,
        watermark_path='watermark-'+id+'/logo.png', output_dir='jobs/output-'+id, ui_palette='midnight',
        oauth_client_id=id+'-client', oauth_client_secret='private-test-secret'))


def test_onboarding_creates_folders_and_private_credentials(workspace):
    client, service, settings = workspace
    response = onboard(client)
    assert response.status_code == 200
    assert 'private-test-secret' not in response.text
    assert 'oauth_client' not in Path('jobs/studio/operations.json').read_text()
    for name in ('music-wolfie-blues', 'backgroundImages-wolfie-blues', 'thumbnail-wolfie-blues', 'watermark-wolfie-blues', 'jobs/output-wolfie-blues'):
        assert Path(name).is_dir()
    path = Path('jobs/studio/credentials/wolfie-blues/client_secrets.json')
    assert json.loads(path.read_text())['web']['client_id'] == 'wolfie-blues-client'
    assert service.store.channel('focus-protocol')['name'] == 'Camping With Blues'
    assert service.store.channel('wolfie-blues')['ui_palette'] == 'midnight'
    assert not Path('.env').exists()
    assert onboard(client).status_code == 400


def test_invalid_path_and_incomplete_credentials_do_not_persist(workspace):
    client, service, _ = workspace
    for fields in ({'output_dir':'../escape'}, {'watermark_path':'../secret.png'}, {'oauth_client_secret':'private-test-secret'}):
        response = client.post('/api/studio/channels', json=dict(id='bad', name='Bad', **fields))
        assert response.status_code == 400
        assert 'private-test-secret' not in response.text
    assert len(service.store.read()['channels']) == 1


def test_new_channel_never_falls_back_to_global_client(workspace):
    _, _, settings = workspace
    channel = Channel(id='other', name='Other').model_dump()
    with pytest.raises(RuntimeError, match='Missing configuration'):
        YouTubeService(channel_settings(settings, channel))._client_config()
    default = Channel(id='focus-protocol', name='Camping With Blues').model_dump()
    assert channel_settings(settings, default).youtube_token_file == settings.youtube_token_file
    assert YouTubeService(channel_settings(settings, default))._client_config()['web']['client_id'] == 'legacy-client'


def test_shared_callback_tokens_and_status_are_isolated(workspace, monkeypatch):
    client, service, settings = workspace
    assert onboard(client, 'a').status_code == 200
    assert onboard(client, 'b').status_code == 200
    Path('youtube_token.json').write_text('existing-token-do-not-touch')
    from google_auth_oauthlib.flow import Flow
    def factory(config, **kwargs):
        id = config['web']['client_id']
        flow = Mock(code_verifier='verifier')
        flow.authorization_url.return_value = ('https://accounts.google.com/auth?state=nonce-'+id, 'nonce-'+id)
        flow.credentials.to_json.return_value = json.dumps({'client_id': id})
        return flow
    monkeypatch.setattr(Flow, 'from_client_config', factory)
    def status(self):
        return dict(connected=self.token_path.is_file(), channel_id=self.channel_id,
                    channel_name=self.channel_id+' account')
    monkeypatch.setattr(YouTubeService, 'connection_status', status)
    assert client.get('/api/jazz/youtube/connect?channel=a').status_code == 302
    assert client.get('/api/jazz/youtube/connect?channel=b').status_code == 302
    mapping = json.loads(Path('youtube_oauth_state.json').read_text())['attempts']
    assert {a['channel_id'] for a in mapping} == {'a','b'}
    response = client.get('/callback?state=nonce-a-client&code=mock', base_url='http://localhost:5001')
    assert 'youtube=connected' in response.location
    assert Path('jobs/studio/credentials/a/token.json').is_file()
    assert not Path('jobs/studio/credentials/b/token.json').exists()
    assert Path('youtube_token.json').read_text() == 'existing-token-do-not-touch'
    assert len(json.loads(Path('youtube_oauth_state.json').read_text())['attempts']) == 1
    assert client.get('/api/jazz/youtube/status?channel=a').json['connected']
    assert not client.get('/api/jazz/youtube/status?channel=b').json['connected']
    assert 'youtube_error' in client.get('/callback?state=nonce-a-client&code=mock', base_url='http://localhost:5001').location


def test_publish_resolution_and_legacy_jobs(workspace):
    client, service, settings = workspace
    onboard(client, 'a')
    write_json('jobs/old/metadata.json', dict(generation_status='completed'))
    write_json('jobs/new/metadata.json', dict(generation_status='completed', channel_id='a'))
    queue = PublishingQueue(settings)
    rows = {r['job_id']:r for r in queue.scan()}
    assert rows['old']['channel_id'] == 'focus-protocol'
    assert queue.for_channel(rows['old']['channel_id']).service.token_path == Path('youtube_token.json')
    selected = queue.for_channel(rows['new']['channel_id'])
    assert selected.service.token_path == Path('jobs/studio/credentials/a/token.json')
    assert selected.service._client_config()['web']['client_id'] == 'a-client'
    assert [r['job_id'] for r in selected.scan()] == ['new']
    assert client.post('/api/jazz/video/new/upload?channel=focus-protocol', json={}).status_code == 400


def test_wrong_account_does_not_replace_existing_token(workspace, monkeypatch):
    client, service, settings = workspace
    onboard(client, 'a')
    with service.store.transaction() as state:
        next(c for c in state['channels'] if c['id']=='a')['youtube_channel_id']='expected'
    token = Path('jobs/studio/credentials/a/token.json')
    token.write_text('existing-token')
    from google_auth_oauthlib.flow import Flow
    flow = Mock(code_verifier='v')
    flow.authorization_url.return_value = ('https://accounts.google.com/auth?state=nonce', 'nonce')
    monkeypatch.setattr(Flow, 'from_client_config', Mock(return_value=flow))
    remote=Mock()
    remote.channels.return_value.list.return_value.execute.return_value={'items':[{'id':'wrong'}]}
    monkeypatch.setattr('googleapiclient.discovery.build', Mock(return_value=remote))
    client.get('/api/jazz/youtube/connect?channel=a')
    result=client.get('/callback?state=nonce&code=mock', base_url='http://localhost:5001')
    assert 'youtube_error' in result.location
    assert token.read_text() == 'existing-token'


def test_generation_uses_selected_channel_snapshot(workspace, monkeypatch):
    client, service, settings = workspace
    onboard(client, 'a')
    import app.api.jazz_api as api
    engine = Mock()
    factory = Mock(return_value=engine)
    monkeypatch.setattr(api, 'LongFormJazzOrchestrator', factory)
    monkeypatch.setattr(api, 'generation_thread', None)
    monkeypatch.setattr(api, 'active_orchestrator', None)
    monkeypatch.setattr(api, 'current_job', None)
    monkeypatch.setattr(api.threading, 'Thread', Mock())
    result = client.post('/api/jazz/generate', json=dict(channel_id='a', music_dir='music-b', duration_minutes=1))
    assert result.status_code == 202
    context = factory.call_args.kwargs['context']
    assert context['channel']['music_dir'] == 'music-a'
    assert context['channel']['background_dir'] == 'backgroundImages-a'
    assert Path(context['channel']['watermark_path']) == Path('watermark-a/logo.png')
    assert factory.call_args.args[0].channel_brand_name == 'a'


def test_expired_callback_does_not_write_tokens(workspace):
    client, _, _ = workspace
    onboard(client, 'a')
    write_json('youtube_oauth_state.json', {'attempts':[dict(state='expired', created=0, channel_id='a')]})
    result = client.get('/callback?state=expired&code=mock', base_url='http://localhost:5001')
    assert 'youtube_error' in result.location
    assert not Path('jobs/studio/credentials/a/token.json').exists()
    assert not Path('youtube_token.json').exists()
