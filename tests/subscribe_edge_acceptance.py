import json, subprocess
from pathlib import Path
from unittest.mock import patch
from PIL import Image
from app.config.settings import Settings
from app.video.short_loop import render_loop
from app.video.subscribe_overlay import overlay_command
from app.utils.ffmpeg import find_ffmpeg,find_ffprobe,probe_media
root=Path('jobs/subscribe_edge_acceptance');root.mkdir(exist_ok=True)
ff,fp=find_ffmpeg(),find_ffprobe()
for case in ['missing','corrupt','encode_failure','overlap1080']:
 folder=root/case;folder.mkdir(exist_ok=True)
 width,height=(1920,1080) if case=='overlap1080' else (320,180)
 Image.new('RGB',(width,height),(40,90,130)).save(folder/'background.png')
 Image.new('RGBA',(width,height)).save(folder/'brand.png')
 subprocess.run([str(ff),'-v','error','-y','-f','lavfi','-i','sine=duration=12','-c:a','aac',str(folder/'music.m4a')],check=True)
 asset='subscribeVideo'
 if case=='missing':asset=str(folder/'absent')
 if case=='corrupt':
  asset=str(folder/'bad.webm');Path(asset).write_bytes(b'not a video')
 settings=Settings(_env_file=None,VIDEO_WIDTH=width,VIDEO_HEIGHT=height,VIDEO_FPS=5,VIDEO_ENCODER='libx264',VISUAL_EFFECT='none',SUBSCRIBE_OVERLAY_PATH=asset,SUBSCRIBE_OVERLAY_INTERVAL_SECONDS=3)
 data={'target_duration_seconds':12}
 def broken(*args):
  command=overlay_command(*args);command[command.index('-filter_complex')+1]='invalid_filter';return command
 with patch('app.video.subscribe_overlay.overlay_command',broken if case=='encode_failure' else overlay_command):
  final=render_loop(settings,folder,data,folder/'background.png',False,folder/'music.m4a',folder/'brand.png',ff,fp)
 assert abs(float(probe_media(final,fp)['format']['duration'])-12)<.3
 if case!='overlap1080':assert not data['subscribe_overlay_enabled'] and data['subscribe_overlay_fallback']
 else:
  assert data['subscribe_overlay_starts']==[3,6,9]
  x,y,w,h=data['subscribe_overlay_bounds'];assert x>=0 and y>=0 and x+w<=width and y+h<=height
 (folder/'metadata.json').write_text(json.dumps(data,indent=2),encoding='utf-8')
 print('PASS',case,flush=True)
