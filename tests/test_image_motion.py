import json
from pathlib import Path
from unittest.mock import Mock
import pytest
from app.config.settings import Settings
from app.video.image_motion import configuration, parameters, transform_filter
from app.video.short_loop import short_command, render_loop


def test_off_and_video_inputs_keep_existing_graph():
    settings = Settings(_env_file=None, VISUAL_EFFECT='none', VIDEO_FPS=24, STUDIO_MOTION_MODE='static')
    args = ('ffmpeg', settings, 'image', False, 'brand', 'out', 6)
    original = short_command(*args)
    assert short_command(*args, motion=configuration()) == original
    assert short_command(*args, motion=configuration({'enabled':True,'preset':'static'})) == original
    video_args = (*args[:3], True, *args[4:])
    assert short_command(*video_args, motion=configuration({'enabled':True})) == short_command(*video_args)
    graph = original[original.index('-filter_complex')+1]
    assert graph.startswith('[0:v]scale=1920:1080:force_original_aspect_ratio=increase,crop=1920:1080,setsar=1,fps=24[base]')


def test_seed_and_validation():
    cfg = configuration({'enabled':True, 'preset':'random_gentle'})
    assert cfg['seed'] is not None
    assert configuration(cfg) == cfg
    assert transform_filter(cfg,24) == transform_filter(configuration(cfg),24)
    assert configuration({'enabled':True,'randomize':False})['seed'] == 0
    with pytest.raises(ValueError):
        configuration({'enabled':True,'strength':'aggressive'})


@pytest.mark.parametrize('preset', ['gentle_float','slow_sway','slow_drift','gentle_zoom','float_zoom','cinematic','random_gentle'])
def test_overscan_covers_all_corners_and_seam(preset):
    import math
    cfg=configuration(dict(enabled=True,preset=preset,strength='medium',rotation=True,zoom=True,seed=123))
    p=parameters(cfg)
    def transform(t):
        phase=2*math.pi*t/p['period']+p['phase']
        return (854*p['x']*math.sin(phase),480*p['y']*math.sin(2*math.pi*t/p['period']+p['y_phase']),
                1.04+p['zoom']*(1-math.cos(phase)),p['angle']*math.sin(phase))
    assert transform(0) == pytest.approx(transform(60),abs=1e-10)
    for frame in range(900):
        tx,ty,scale,angle=transform(frame/15)
        for x,y in [(-427,-240),(427,-240),(-427,240),(427,240)]:
            source_x=((x-tx)*math.cos(angle)+(y-ty)*math.sin(angle))/scale
            source_y=(-(x-tx)*math.sin(angle)+(y-ty)*math.cos(angle))/scale
            assert abs(source_x)<427 and abs(source_y)<240


def test_visualizer_graph_is_identical_after_background():
    s=Settings(_env_file=None)
    vis=dict(path='vis.mov',width=200,height=60,x=30,bottom=30,opacity=.9)
    args=('ffmpeg',s,'image',False,'brand','out',60)
    graphs=[]
    for motion in (None,configuration(dict(enabled=True))):
        cmd=short_command(*args,vis=vis,motion=motion)
        graphs.append(cmd[cmd.index('-filter_complex')+1])
    assert graphs[0].split('[branded]',1)[1] == graphs[1].split('[branded]',1)[1]
    assert 'perspective=' in graphs[1].split('[base]')[0]


def mock_renderer(monkeypatch, tmp_path, failure):
    import app.video.short_loop as module
    settings=Settings(_env_file=None,VISUALIZER_ENABLED=False,SUBSCRIBE_OVERLAY_ENABLED=False,VISUAL_EFFECT='none')
    def probe(path, _):
        if str(path)=='audio':
            return dict(streams=[dict(codec_type='audio',codec_name='aac')],format={'duration':'60'})
        streams=[dict(codec_type='video',width=1920,height=1080)]
        if Path(path).name=='rendering.mp4': streams.append(dict(codec_type='audio'))
        return dict(streams=streams,format={'duration':'60'})
    monkeypatch.setattr(module,'probe',probe)
    monkeypatch.setattr(module,'choose_render_backend',lambda *a:('ffmpeg','libx264',{}))
    monkeypatch.setattr('app.video.visualizer.prepare_visualizer',lambda *a:None)
    runner=Mock(side_effect=[failure,None,None,None])
    monkeypatch.setattr(module,'render_with_progress',runner)
    metadata=dict(target_duration_seconds=60,image_motion=configuration(dict(enabled=True,speed='very_slow')))
    return settings,metadata,runner


def test_motion_failure_retries_static_but_keeps_loop_and_mux(monkeypatch,tmp_path):
    settings,metadata,runner=mock_renderer(monkeypatch,tmp_path,RuntimeError('FFmpeg exited with code 1: perspective unsupported'))
    render_loop(settings,tmp_path,metadata,'image',False,'audio','brand','ffmpeg','ffprobe')
    assert runner.call_count==4 and not metadata['image_motion_applied']
    assert metadata['fallback_used']
    commands=json.loads((tmp_path/'output/render_commands.json').read_text())
    assert 'perspective=' not in ' '.join(commands['short'])
    for name in ('loop','mux'):
        cmd=commands[name];assert cmd[cmd.index('-c:v')+1]=='copy'


def test_cancellation_never_retries(monkeypatch,tmp_path):
    settings,metadata,runner=mock_renderer(monkeypatch,tmp_path,RuntimeError('Cancelled by user'))
    with pytest.raises(RuntimeError,match='Cancelled'):
        render_loop(settings,tmp_path,metadata,'image',False,'audio','brand','ffmpeg','ffprobe')
    assert runner.call_count==1


def test_content_snapshots_motion_and_old_content_defaults_off(tmp_path):
    from app.studio.service import StudioService
    service=StudioService(tmp_path)
    rows=service.add_content('focus-protocol',['Moving'],image_motion={'enabled':True,'preset':'slow_sway'})
    assert rows[0]['image_motion']['seed'] is not None
    assert service.store.read()['content'][0]['image_motion']==rows[0]['image_motion']
    assert not service.add_content('focus-protocol',['Static'])[0]['image_motion']['enabled']
