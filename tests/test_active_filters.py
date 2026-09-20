from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from app.config.settings import Settings
from app.video.branding import effect_filter
from app.video.short_loop import short_command,copy_commands

MODES=('none','vintage','old_film','warm_film','faded_film','noir','sepia','film_grain','cool_cinematic','soft_vignette')

@pytest.mark.parametrize('mode',MODES)
def test_zero_grade_is_exact_passthrough(mode):
    assert effect_filter(mode,0)==''
    original=Settings(_env_file=None,VISUAL_EFFECT='none')
    zero=original.model_copy(update=dict(visual_effect=mode,visual_effect_opacity=0))
    args=('ffmpeg',original,'background',False,'brand','out',60)
    assert short_command(*args)==short_command('ffmpeg',zero,*args[2:])

@pytest.mark.parametrize('video,motion',[(False,'static'),(False,'drift'),(True,'static')])
def test_grade_is_background_only_and_copy_operations_stay_copy(video,motion):
    s=Settings(_env_file=None,VISUAL_EFFECT='sepia',VISUAL_EFFECT_OPACITY=.12,STUDIO_MOTION_MODE=motion)
    vis=dict(path='wave.mov',width=420,height=110,x=60,bottom=60,opacity=1)
    cmd=short_command('ffmpeg',s,'background',video,'brand','out',60,vis)
    graph=cmd[cmd.index('-filter_complex')+1]
    assert '[base]'+effect_filter('sepia',.12,fps=s.video_fps)[1:]+'[graded]' in graph
    assert graph.index('[graded]')<graph.index('[graded][1:v]overlay')<graph.index('[branded][soundwave]overlay')
    for command in copy_commands('ffmpeg','short','loop','audio','out',120,'aac'):
        assert command[command.index('-c:v')+1]=='copy'
        assert '-filter_complex' not in command and '-vf' not in command

@pytest.mark.parametrize('mode',MODES[1:])
def test_strengths_are_distinct_and_deterministic(mode):
    values=[effect_filter(mode,a) for a in (.06,.12,.20)]
    assert len(set(values))==3
    assert effect_filter(mode,.12)==effect_filter(mode,.12)
    if mode in ('film_grain','old_film'):
        assert 'allf=t+u:all_seed=1729' in values[1]
    assert effect_filter('none',.20)==''

def test_metadata_records_requested_settings(monkeypatch,tmp_path):
    from app.pipeline.long_form_jazz_orchestrator import LongFormJazzOrchestrator
    e=LongFormJazzOrchestrator.__new__(LongFormJazzOrchestrator)
    e.settings=Settings(_env_file=None,VISUAL_EFFECT='noir',VISUAL_EFFECT_OPACITY=.20)
    e.logger=Mock();e.timeline_builder=SimpleNamespace(clips=[SimpleNamespace(asset_path='background',asset_type='image')])
    monkeypatch.setattr('app.video.branding.loop_branding',lambda *a:tmp_path/'brand.png')
    monkeypatch.setattr('app.video.short_loop.render_loop',lambda *a:tmp_path/'out.mp4')
    m={'render_timings':{}}
    assert e._render_video(tmp_path,m,tmp_path/'audio')
    assert (m['visual_effect'],m['visual_effect_opacity'])==('noir',.20)
