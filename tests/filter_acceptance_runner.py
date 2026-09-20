"""Real 120-second renders through the production short-clip-copy-loop path."""
import json,subprocess,time
from copy import deepcopy
from pathlib import Path
import numpy as np
from PIL import Image,ImageDraw
from app.config.settings import get_settings
from app.pipeline.long_form_jazz_orchestrator import LongFormJazzOrchestrator
from app.video.branding import effect_filter
from app.utils.ffmpeg import find_ffmpeg,find_ffprobe,no_window_flags,probe_media
from app.youtube.state import write_json
from app.studio.assets import qc_job

root=Path('jobs/filter_acceptance');root.mkdir(exist_ok=True)
original=json.loads(Path('jobs/20260920_121333_064977_video_001/metadata.json').read_text())
ffmpeg=find_ffmpeg();audio=root/'audio_120s.aac'
if not audio.exists():
    subprocess.run([str(ffmpeg),'-v','error','-y','-i',original['audio_path'],'-t','120','-c:a','copy','-f','ipod',str(audio)],check=True,**no_window_flags())
modes=['none','vintage','old_film','warm_film','faded_film','noir','sepia','film_grain','cool_cinematic','soft_vignette']
cases=[(mode,.12) for mode in modes]+[(mode,level) for mode in ('old_film','noir') for level in (.06,.20)]+[('old_film',0)]
results=[];control=None
for mode,level in cases:
    label=f'{mode}_{level:.2f}';directory=root/label;directory.mkdir(exist_ok=True)
    s=get_settings().model_copy(update=dict(visual_effect=mode,visual_effect_opacity=level,
        visualizer_enabled=True,subscribe_overlay_enabled=False,studio_motion_mode='static'))
    m=deepcopy(original);m.update(target_duration_seconds=120,audio_path=str(audio.resolve()),
        youtube_exclude=True,render_config=dict(video_width=s.video_width,video_height=s.video_height,video_fps=s.video_fps))
    engine=LongFormJazzOrchestrator(s)
    engine.timeline_builder.add_clip(m['generated_background_path'],'image',120)
    video=directory/'output/rendering.mp4'
    # Reuse only an already validated render whose exact filter string matches.
    prior=directory/'acceptance.json'
    reusable=prior.exists() and json.loads(prior.read_text()).get('filter')==effect_filter(mode,level)
    if not reusable:
        video=engine._render_video(directory,m,audio)
        assert video,m.get('render_error')
        assert engine._validate_output(directory,video,audio,m)
        qc=qc_job(directory,dict(video_path=str(video),thumbnail_path=m['thumbnail_path'],title='Filter acceptance',description='Local render verification'),m)
        assert qc['status']!='fail',qc
        write_json(directory/'metadata.json',m)
    else:m=json.loads((directory/'metadata.json').read_text())
    assert m['visual_effect']==mode and m['visual_effect_opacity']==level
    commands=json.loads((directory/'output/render_commands.json').read_text())
    grade=effect_filter(mode,level);graph=commands['short'][commands['short'].index('-filter_complex')+1]
    assert (grade[1:] in graph) if grade else '[graded]' not in graph
    for name in ('loop','mux'):
        cmd=commands[name];assert cmd[cmd.index('-c:v')+1]=='copy' and '-filter_complex' not in cmd
    assert commands['mux'][commands['mux'].index('-c:a')+1]=='copy'
    dest=directory/'frame_5.png'
    subprocess.run([str(ffmpeg),'-v','error','-y','-ss','5','-i',str(video),'-frames:v','1',str(dest)],check=True,**no_window_flags())
    pixels=np.asarray(Image.open(dest).convert('RGB')).astype(float)
    if control is None:control=pixels
    mae=float(np.abs(pixels-control).mean())
    # Use background-only area for clipping statistics (white branding stays clean).
    background=pixels[100:900,100:1800]
    result=dict(mode=mode,intensity=level,mean_absolute_pixel_difference=mae,
        black_fraction=float((background==0).mean()),white_fraction=float((background==255).mean()),
        filter=grade,video=str(video.resolve()),render_seconds=m.get('render_elapsed_seconds'))
    write_json(prior,result);results.append(result);write_json(root/'results.json',results)
    print(label,round(mae,4),flush=True)
for r in results:
    if r['mode']!='none' and r['intensity']>0:assert r['mean_absolute_pixel_difference']>3,r
assert results[-1]['mean_absolute_pixel_difference']==0,results[-1]
for mode in ('old_film','noir'):
    selected=sorted((r for r in results if r['mode']==mode and r['intensity']>0),key=lambda r:r['intensity'])
    assert all(a['mean_absolute_pixel_difference']<b['mean_absolute_pixel_difference'] for a,b in zip(selected,selected[1:])),selected
seams={}
fps=get_settings().video_fps
for mode in ('old_film','film_grain'):
    video=root/f'{mode}_0.12'/'output/rendering.mp4';seams[mode]={}
    for boundary in (6,60):
        # Ten adjacent decoded frames around the actual packet-copy seam.
        output=subprocess.check_output([str(ffmpeg),'-v','error','-ss',str(boundary-4/fps-0.000001),'-i',str(video),'-frames:v','10','-pix_fmt','rgb24','-f','rawvideo','-'],**no_window_flags())
        frames=np.frombuffer(output,np.uint8).reshape(10,1080,1920,3)[:,200:800,250:1500].astype(float)
        diffs=np.abs(np.diff(frames,axis=0)).mean(axis=(1,2,3))
        seam=float(diffs[3]);ordinary=float(np.median(np.delete(diffs,3)));ratio=seam/ordinary
        assert ordinary>.05,(mode,boundary,diffs)
        assert .5<ratio<2,(mode,boundary,ratio,diffs)
        seams[mode][boundary]=dict(seam_mae=seam,ordinary_mae=ordinary,ratio=ratio,frame_differences=diffs.tolist())
write_json(root/'seams.json',seams)
sheet=Image.new('RGB',(960,295*5),(25,25,25));pen=ImageDraw.Draw(sheet)
for i,mode in enumerate(modes):
    im=Image.open(root/f'{mode}_0.12/frame_5.png').resize((480,270))
    x=(i%2)*480;y=(i//2)*295
    sheet.paste(im,(x,y+25));pen.text((x+12,y+6),mode,fill='white')
sheet.save(root/'contact_sheet.jpg')
print('ACCEPTANCE PASSED',flush=True)
