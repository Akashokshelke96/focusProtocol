from unittest.mock import patch
from pathlib import Path
import numpy as np
import pytest
from app.config.settings import Settings
from app.video.dust import dust_frame
from app.video.short_loop import short_command,copy_commands
from app.audio.local_timeline import normalize_output

def test_dust_period_and_alpha():
 a=np.array(dust_frame(60));b=np.array(dust_frame(1860));c=np.array(dust_frame(90))
 assert np.array_equal(a,b)
 assert not np.array_equal(a,c)
 assert (a[:,:,3]==0).mean()>.95
 assert np.all(a[:,:,:3]==255)

@pytest.mark.parametrize('vis',[None,dict(path='wave.mov',width=100,height=30,opacity=1,x=10,bottom=10)])
def test_dust_before_soundwave_and_copy_unmodified(vis):
 s=Settings(_env_file=None)
 cmd=short_command('ffmpeg',s,'bg.png',False,'brand.png','out',60,vis=vis,dust=dict(path='dust.mov',opacity=.12))
 graph=cmd[cmd.index('-filter_complex')+1]
 assert '[branded][dust]' in graph
 if vis:assert graph.index('[branded][dust]')<graph.index('[dusted][soundwave]')
 loop,mux=copy_commands('ffmpeg','short','loop','audio','final',180,'aac')
 for command in [loop,mux]:
  assert command[command.index('-c:v')+1]=='copy'
  assert '-filter_complex' not in command
 assert mux[mux.index('-c:a')+1]=='copy'

def test_failed_normalization_preserves_original(tmp_path):
 out=tmp_path/'audio.aac';out.write_bytes(b'original-audio');m={}
 with patch('app.audio.local_timeline.subprocess.run',side_effect=OSError('test failure')):
  assert normalize_output(out,180,metadata=m)==out
 assert out.read_bytes()==b'original-audio'
 assert not m['loudness_normalized']
 assert not list(tmp_path.glob('*.m4a'))
