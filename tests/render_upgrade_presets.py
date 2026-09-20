"""Reuse the same real 3-minute source media to compare all quality presets."""
import json,subprocess,time
from pathlib import Path
from copy import deepcopy
from app.config.settings import get_settings
from app.pipeline.long_form_jazz_orchestrator import LongFormJazzOrchestrator
from app.utils.ffmpeg import find_ffmpeg,find_ffprobe,no_window_flags
from app.video.short_loop import probe
from app.studio.assets import qc_job,verify_job_assets
from app.youtube.state import write_json
from PIL import Image,ImageDraw

baseline=json.loads(Path('jobs/upgrade_baseline_finish.json').read_text())
source=Path('jobs')/baseline['job_id']
original=json.loads((source/'metadata.json').read_text())
results=[]
for preset in ('1080p','720p','480p'):
    directory=Path('jobs')/('upgrade_preset_'+preset);directory.mkdir(exist_ok=True)
    s=get_settings().with_quality_preset(preset).model_copy(update=dict(visualizer_enabled=True,subscribe_overlay_enabled=True))
    ffmpeg,ffprobe=find_ffmpeg(),find_ffprobe()
    audio=directory/'audio.aac'
    subprocess.run([str(ffmpeg),'-v','error','-y','-i',original['audio_path'],'-c:a','aac','-b:a',s.ffmpeg_audio_bitrate,'-f','ipod',str(audio)],check=True,**no_window_flags())
    m=deepcopy(original)
    m.update(target_duration_seconds=180,audio_path=str(audio.resolve()),render_config={k:getattr(s,k) for k in ('quality_preset','video_width','video_height','video_fps','ffmpeg_crf','video_encoder_quality','ffmpeg_audio_bitrate')})
    engine=LongFormJazzOrchestrator(s)
    engine.timeline_builder.add_clip(m['generated_background_path'],'image',180)
    start=time.perf_counter();video=engine._render_video(directory,m,audio)
    assert video,m.get('render_error')
    assert engine._validate_output(directory,video,audio,m)
    verify_job_assets(m)
    qc=qc_job(directory,dict(video_path=str(video),thumbnail_path=m['thumbnail_path'],title='Preset verification',description='Local test'),m)
    assert qc['status']!='fail',qc
    frames={}
    for t in (1,10,61,121,179):
        image=directory/f'verify_{t}.png'
        subprocess.run([str(ffmpeg),'-v','error','-y','-ss',str(t),'-i',str(video),'-frames:v','1',str(image)],check=True,**no_window_flags())
        frames[t]=str(image)
    commands=json.loads((directory/'output/render_commands.json').read_text())
    for name in ('loop','mux'):
        c=commands[name];assert c[c.index('-c:v')+1]=='copy' and '-filter_complex' not in c
    assert commands['mux'][commands['mux'].index('-c:a')+1]=='copy'
    info=probe(video,ffprobe)
    assert abs(float(info['format']['duration'])-180)<.1
    write_json(directory/'metadata.json',m)
    results.append(dict(preset=preset,bytes=video.stat().st_size,render_seconds=m['render_elapsed_seconds'],
        timings=m['render_timings'],dimensions=[s.video_width,s.video_height],frames=frames,video=str(video.resolve())))
    write_json(Path('jobs/upgrade_presets.json'),results)
    print(json.dumps(results[-1]),flush=True)
# Extend the already-encoded cycle with pure copy to prove two 8-minute boundaries.
directory=Path('jobs/upgrade_preset_1080p');m=json.loads((directory/'metadata.json').read_text())
video=directory/'cadence_16min.mp4'
subprocess.run([str(ffmpeg),'-v','error','-y','-stream_loop','-1','-i',m['subscribe_cycle_path'],'-t','970','-an','-c:v','copy',str(video)],check=True,**no_window_flags())
for t in (1,5,479,481,485,959,961,965):
    subprocess.run([str(ffmpeg),'-v','error','-y','-ss',str(t),'-i',str(video),'-frames:v','1',str(directory/f'cadence_{t}.png')],check=True,**no_window_flags())
print('Cadence frames ready',flush=True)
