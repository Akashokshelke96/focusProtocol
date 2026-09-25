"""Real FFmpeg acceptance at small resolution, including pixel and audio checks."""
import json, subprocess
from pathlib import Path
import numpy as np
from PIL import Image
from app.config.settings import Settings
from app.video.short_loop import render_loop
from app.utils.ffmpeg import find_ffmpeg,find_ffprobe,probe_media

root=Path('jobs/subscribe_acceptance');root.mkdir(exist_ok=True)
ff=str(find_ffmpeg());fp=find_ffprobe()
def run(args):
    subprocess.run([ff,'-v','error','-y',*map(str,args)],check=True,capture_output=True)
def frame(path,t):
    result=subprocess.run([ff,'-v','error','-ss',str(t),'-i',str(path),'-frames:v','1','-f','rawvideo','-pix_fmt','rgb24','-'],check=True,capture_output=True)
    return np.frombuffer(result.stdout,np.uint8).reshape(180,320,3)
Image.new('RGB',(320,180),(40,90,130)).save(root/'background.png')
Image.new('RGBA',(320,180),(0,0,0,0)).save(root/'brand.png')
# Fixture includes audio to verify it is ignored.
run(['-c:v','libvpx-vp9','-i','subscribeVideo/subscribe.webm','-f','lavfi','-i','sine=frequency=1400:duration=7.266','-map','0:v','-map','1:a','-c:v','copy','-c:a','libopus','-shortest',root/'with_audio.webm'])
reports=[]
for minutes in [2,5,8,15]:
    folder=root/str(minutes);folder.mkdir(exist_ok=True)
    duration=minutes*60
    run(['-f','lavfi','-i',f'sine=frequency=220:duration={duration}','-c:a','aac',folder/'music.m4a'])
    settings=Settings(_env_file=None,VIDEO_WIDTH=320,VIDEO_HEIGHT=180,VIDEO_FPS=5,VIDEO_ENCODER='libx264',VISUAL_EFFECT='none',SUBSCRIBE_OVERLAY_PATH=str(root/'with_audio.webm'))
    data={'target_duration_seconds':duration}
    final=render_loop(settings,folder,data,root/'background.png',False,folder/'music.m4a',root/'brand.png',ff,fp)
    info=probe_media(final,fp)
    assert sorted(s['codec_type'] for s in info['streams'])==['audio','video']
    assert abs(float(info['format']['duration'])-duration)<.3
    # Compare decoded audio bit-for-bit (no WebM sound and no audio re-encode).
    def audio(path):
        return subprocess.run([ff,'-v','error','-i',str(path),'-map','0:a','-f','hash','-hash','sha256','-'],capture_output=True,check=True).stdout
    assert audio(final)==audio(folder/'music.m4a')
    baseline=frame(final,1)
    if minutes>3:
        for start in data['subscribe_overlay_starts']:
            active=frame(final,start+3)
            assert np.max(np.abs(active.astype(int)-baseline.astype(int)))>20
            assert np.mean(np.abs(active[:100].astype(int)-baseline[:100].astype(int)))<2
            after=frame(final,start+9)
            assert np.mean(np.abs(after.astype(int)-baseline.astype(int)))<2
        Image.fromarray(frame(final,183)).save(folder/'active.png')
    reports.append(dict(minutes=minutes,metadata=data))
    print('PASS',minutes,flush=True)
(root/'report.json').write_text(json.dumps(reports,indent=2),encoding='utf-8')
