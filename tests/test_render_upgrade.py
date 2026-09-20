import ast
import json
from pathlib import Path
from unittest.mock import Mock
import numpy as np
import pytest
from PIL import Image
from app.config.settings import Settings
from app.video.branding import loop_branding
from app.utils.ffmpeg import probe_media,_probe_cached

@pytest.mark.parametrize('preset,size',[('480p',(854,480)),('720p',(1280,720)),('1080p',(1920,1080))])
def test_quality_dimensions_and_scaled_branding(preset,size,tmp_path):
    s=Settings(_env_file=None,QUALITY_PRESET=preset)
    assert (s.video_width,s.video_height)==size
    assert s.ffmpeg_preset=='ultrafast'
    m={};p=loop_branding(tmp_path,s,m);pixels=np.asarray(Image.open(p))
    top,bottom=m['branding_regions']
    assert 'icon_bounds' in top and 'icon_bounds' not in bottom
    x,y,w,h=top['icon_bounds'];tx,ty,tw,th=top['text_bounds']
    assert x+w<tx and h<=th
    crop=pixels[y:y+h,x:x+w]
    assert ((crop[:,:,0]>220)&(crop[:,:,1]<25)&(crop[:,:,2]<25)).any()
    assert ((crop[:,:,:3]>245).all(axis=2)).any()
    assert size[0]-(top['bounds'][0]+top['bounds'][2])==max(8,round(25*size[1]/1080))
    assert top['bounds'][1]==max(8,round(25*size[1]/1080))

def test_preset_validation_and_legacy_settings():
    with pytest.raises(ValueError):Settings(_env_file=None,QUALITY_PRESET='4k')
    s=Settings(_env_file=None,VIDEO_WIDTH=1280,VIDEO_HEIGHT=720,VIDEO_ENCODER_QUALITY=18)
    assert (s.video_width,s.video_height,s.video_encoder_quality)==(1280,720,18)
    assert s.with_quality_preset('1080p').ffmpeg_audio_bitrate=='192k'

def test_probe_cache_invalidates_on_changed_file(tmp_path,monkeypatch):
    path=tmp_path/'movie';path.write_bytes(b'a')
    run=Mock(return_value=Mock(stdout=json.dumps({'format':{'duration':'2'}})))
    monkeypatch.setattr('app.utils.ffmpeg.subprocess.run',run);_probe_cached.cache_clear()
    first=probe_media(path,'ffprobe');first['format']['duration']='wrong'
    assert probe_media(path,'ffprobe')['format']['duration']=='2'
    assert run.call_count==1
    path.write_bytes(b'changed')
    probe_media(path,'ffprobe');assert run.call_count==2

def test_render_subprocesses_are_hidden():
    paths=[p for folder in ('app/audio','app/video','app/providers','app/utils') for p in Path(folder).glob('*.py')]
    paths += [Path('app/studio/assets.py'),Path('app/pipeline/long_form_jazz_orchestrator.py'),Path('app/youtube/publishing.py')]
    for path in paths:
        tree=ast.parse(Path(path).read_text(encoding='utf-8'))
        for n in ast.walk(tree):
            if isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute) and isinstance(n.func.value,ast.Name) and n.func.value.id=='subprocess' and n.func.attr in ('run','Popen','check_output'):
                assert any(k.arg=='creationflags' or (k.arg is None and 'no_window_flags' in ast.unparse(k.value)) for k in n.keywords), (path,n.lineno)

def test_clean_silence_scan_does_not_copy_pcm(tmp_path):
    from app.audio.local_timeline import _remove_internal_silence
    source=tmp_path/'source.pcm';target=tmp_path/'cleaned.pcm'
    np.full((48000*2,2),1000,dtype='<i2').tofile(source)
    assert _remove_internal_silence(source,target,48000,2,-52,3,.25,6)==0
    assert not target.exists() and source.stat().st_size>0

@pytest.mark.parametrize('preset,width,height',[('480p',854,480),('720p',1280,720),('1080p',1920,1080)])
def test_generate_endpoint_passes_quality_to_orchestrator(monkeypatch,preset,width,height):
    import app.api.jazz_api as api
    import app.studio.api as studio
    fake=Mock();fake.store.read.return_value={'content':[]}
    monkeypatch.setattr(studio,'service',fake)
    monkeypatch.setattr(api,'generation_thread',None)
    monkeypatch.setattr(api.threading,'Thread',Mock())
    engine=Mock();monkeypatch.setattr(api,'LongFormJazzOrchestrator',engine)
    response=api.app.test_client().post('/api/jazz/generate',json={'quality_preset':preset,'duration_minutes':3})
    assert response.status_code==202,response.get_json()
    s=engine.call_args.args[0]
    assert (s.video_width,s.video_height)==(width,height)
    # Reset the mocked thread's busy flag before testing request validation.
    monkeypatch.setattr(api,'generation_thread',None)
    bad=api.app.test_client().post('/api/jazz/generate',json={'quality_preset':'4k'})
    assert bad.status_code==400
