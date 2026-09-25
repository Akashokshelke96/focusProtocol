"""Local content upgrade measurements; excludes publishing and changes no QC."""
import json, subprocess, sys
from pathlib import Path
import numpy as np
from PIL import Image
from app.config.settings import Settings
from app.video.short_loop import render_loop
from app.utils.ffmpeg import find_ffmpeg,find_ffprobe,probe_media
root=Path('jobs/content_upgrade_acceptance');root.mkdir(exist_ok=True)
source=Path('jobs/20260924_212327_276616_video_001/background_images/background.png')
ff,fp=str(find_ffmpeg()),find_ffprobe()
Image.new('RGBA',(1280,720)).save(root/'branding.png')
subprocess.run([ff,'-v','error','-y','-i',str(root/'before.m4a'),'-t','66','-c:a','copy',str(root/'audio66.m4a')],check=True)
report=json.loads((root/'visual_measurements.json').read_text()) if '--dust-only' in sys.argv else {}
profiles=[('static','static','none',False),('grain','static','old_film',False),('drift_grain','drift','old_film',False),('all','drift','old_film',True)]
for name,mode,effect,dust in (profiles[-1:] if '--dust-only' in sys.argv else profiles):
 folder=root/name;folder.mkdir(exist_ok=True)
 s=Settings(_env_file=None,VIDEO_WIDTH=1280,VIDEO_HEIGHT=720,VIDEO_FPS=15,VIDEO_ENCODER='libx264',FFMPEG_CRF=23,STUDIO_MOTION_MODE=mode,VISUAL_EFFECT=effect,VISUAL_EFFECT_OPACITY=.06,DUST_ENABLED=dust,VISUALIZER_ENABLED=False,SUBSCRIBE_OVERLAY_ENABLED=False)
 m={'target_duration_seconds':66}
 path=render_loop(s,folder,m,source,False,root/'audio66.m4a',root/'branding.png',ff,fp)
 cmds=json.loads((folder/'output/render_commands.json').read_text())
 assert set(cmds)=={'short','loop','mux'}
 for key in ['loop','mux']:assert cmds[key][cmds[key].index('-c:v')+1]=='copy'
 assert cmds['mux'][cmds['mux'].index('-c:a')+1]=='copy'
 (folder/'metadata.json').write_text(json.dumps(m,indent=2))
 report[name]=dict(path=str(path),short_encode_seconds=m['render_timings']['short_encode_seconds'])
 print('RENDER',name,report[name],flush=True)
def frame(name,t):
 p=Path(report[name]['path']);r=subprocess.run([ff,'-v','error','-ss',str(t),'-i',str(p),'-frames:v','1','-f','rawvideo','-pix_fmt','rgb24','-'],capture_output=True,check=True)
 a=np.frombuffer(r.stdout,np.uint8).reshape(720,1280,3)
 Image.fromarray(a).save(root/name/f'frame_{t}.png');return a
def diff(a,b):return float(np.mean(np.abs(a.astype(float)-b.astype(float))))
report['measurements']={
 'static_temporal_mae':diff(frame('static',2),frame('static',30)),
 'grain_temporal_mae':diff(frame('grain',2),frame('grain',2+1/15)),
 'drift_half_cycle_mae':diff(frame('drift_grain',2),frame('drift_grain',32)),
 'drift_seam_mae':diff(frame('drift_grain',60-1/15),frame('drift_grain',60)),
 'dust_contribution_mae':diff(frame('all',2),frame('drift_grain',2)),
 'dust_phase_2_vs_62_mae':diff(frame('all',2),frame('all',62)),
 'all_seam_mae':diff(frame('all',60-1/15),frame('all',60)),
 'dust_encode_delta_seconds':report['all']['short_encode_seconds']-report['drift_grain']['short_encode_seconds']}
assert report['measurements']['dust_phase_2_vs_62_mae']==0
assert report['measurements']['grain_temporal_mae']>0
assert 0<report['measurements']['dust_contribution_mae']<3
(root/'visual_measurements.json').write_text(json.dumps(report,indent=2));print(json.dumps(report,indent=2),flush=True)
