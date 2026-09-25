from pathlib import Path
from unittest.mock import Mock
import pytest
from app.config.settings import Settings
from app.video.subscribe_overlay import schedule, prepare, files, overlay_command

@pytest.mark.parametrize('seconds, expected', [(120, []),(165, []),(180, []),(190,[180]),(300,[180]),(480,[180,360]),(900,[180,360,540,720]),(1800,list(range(180,1800,180))),(5400,list(range(180,5400,180)))])
def test_schedule(seconds, expected):
    assert schedule(seconds,180)==expected

def test_explicit_intro():
    assert schedule(400,180,0)==[0,180,360]

def test_missing(tmp_path):
    metadata={}
    assert prepare(Settings(_env_file=None,SUBSCRIBE_OVERLAY_PATH=str(tmp_path)),300,'ffmpeg','ffprobe',metadata) is None
    assert not metadata['subscribe_overlay_enabled']
    assert 'not found' in metadata['subscribe_overlay_fallback']

def test_disabled():
    assert prepare(Settings(_env_file=None,SUBSCRIBE_OVERLAY_ENABLED=False),300,None,None,{}) is None

def test_file_discovery(tmp_path):
    (tmp_path/'b.webm').touch();(tmp_path/'a.WEBM').touch();(tmp_path/'ignore.mp4').touch()
    assert [p.name for p in files(Settings(_env_file=None,SUBSCRIBE_OVERLAY_PATH=str(tmp_path)))]==['a.WEBM','b.webm']

def test_audio_and_alpha_mapping():
    command=overlay_command('ffmpeg',Settings(_env_file=None),'video','music','out',480,'libx264',dict(path='sub.webm',decoder='libvpx-vp9',starts=[180,360],duration=7.266,width=326,height=183,x=1498,y=827))
    assert command[command.index('-c:a')+1]=='copy'
    assert [command[i+1] for i,v in enumerate(command) if v=='-map']==['[v1]','1:a:0']
    graph=command[command.index('-filter_complex')+1]
    assert graph.count('repeatlast=0')==2
    assert graph.count('format=yuva420p')==2
    assert '-stream_loop' not in command
