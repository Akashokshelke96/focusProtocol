import io
import json
import subprocess
from unittest.mock import Mock
import numpy as np
from app.config.settings import Settings
from app.video.transitions import fade_filter
from app.audio.local_timeline import assemble_tracks
from app.utils.ffmpeg import find_ffmpeg
from tests.test_production_hardening import audio


def test_fades_reach_black_at_both_ends(tmp_path):
    settings = Settings(_env_file=None, VIDEO_FPS=15)
    filters = fade_filter(8, settings)
    output = subprocess.run([str(find_ffmpeg()),'-v','error','-f','lavfi','-i','color=white:s=64x36:r=15',
        '-vf',filters+',format=gray','-t','8','-f','rawvideo','-'],capture_output=True,check=True).stdout
    frames = np.frombuffer(output,dtype=np.uint8).reshape(-1,36,64)
    assert frames[0].mean() < 1 and frames[-1].mean() < 1
    assert frames[15].mean() < frames[45].mean()
    assert frames[45].mean() > 245
    assert fade_filter(8,Settings(_env_file=None,INTRO_FADE_SECONDS=0,OUTRO_FADE_SECONDS=0)) == ''


def test_audio_intro_and_outro_are_faded_before_single_encode(tmp_path):
    source = audio(tmp_path/'tone.wav',seconds=12)
    target = tmp_path/'mix.aac'
    assemble_tracks([source],target,12,intro_fade=2,outro_fade=3)
    result=subprocess.run([str(find_ffmpeg()),'-v','error','-i',str(target),'-ac','1','-ar','8000','-f','f32le','-'],capture_output=True,check=True)
    samples=np.frombuffer(result.stdout,dtype='<f4')
    rms=lambda x: np.sqrt(np.mean(x*x))
    mid=rms(samples[32000:32800])
    assert rms(samples[:800]) < mid*.1
    assert rms(samples[95200:96000]) < mid*.1


def test_browser_connect_opens_local_callback_entry(tmp_path,monkeypatch):
    from app.api.jazz_api import app
    import app.studio.api as api
    from app.studio.service import StudioService
    service=StudioService(tmp_path/'jobs'); monkeypatch.setattr(api,'service',service)
    opener=Mock(return_value=True);monkeypatch.setattr('webbrowser.open',opener)
    monkeypatch.setattr(api,'get_settings',lambda:Settings(_env_file=None,YOUTUBE_REDIRECT_URI='http://localhost:5001/callback'))
    response=app.test_client().post('/api/studio/channels/focus-protocol/connect-browser',json={})
    assert response.status_code==200 and response.json['opened']
    opener.assert_called_once_with('http://localhost:5001/api/studio/channels/focus-protocol/connect',new=2)
    assert app.test_client().post('/api/studio/channels/focus-protocol/connect-browser',json={},headers={'Origin':'https://foreign.test'}).status_code==403


def test_connection_check_uses_bounded_transport(monkeypatch):
    from app.youtube.oauth import YouTubeService
    service=YouTubeService(Settings(_env_file=None))
    credentials=Mock();credentials.has_scopes.return_value=True
    monkeypatch.setattr(service,'_credentials',lambda:credentials)
    client=Mock();client.channels.return_value.list.return_value.execute.return_value={'items':[{'id':'channel','snippet':{'title':'Camping With Blues'}}]}
    factory=Mock(return_value=client);monkeypatch.setattr(service,'client',factory)
    assert service.connection_status()['connected']
    factory.assert_called_once_with(timeout=20)
