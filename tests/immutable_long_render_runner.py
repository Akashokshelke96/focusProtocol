import json, subprocess, time
from pathlib import Path
import psutil
from app.config.settings import get_settings
from app.pipeline.long_form_jazz_orchestrator import LongFormJazzOrchestrator
from app.studio.assets import verify_job_assets, qc_job
from app.utils.ffmpeg import find_ffmpeg
from app.youtube.state import write_json

# Run after the current acceptance worker exits: never overlap heavy tests.
while psutil.pid_exists(17028):
    time.sleep(5)
folder=Path('jobs/immutable_90min_acceptance'); folder.mkdir(exist_ok=True)
s=get_settings().model_copy(update=dict(video_width=1920,video_height=1080,video_fps=30,
    video_encoder='h264_nvenc',studio_motion_mode='static',waveform_animated=False,
    visual_effect='none',subscribe_overlay_enabled=False,song_panel_enabled=False))
e=LongFormJazzOrchestrator(s)
m=dict(target_duration_seconds=5400, youtube_exclude=True, youtube_title='Immutable 90 minute render acceptance',
       youtube_description='Local acceptance render. Do not publish.',
       render_config=dict(video_width=1920,video_height=1080,video_fps=30),
       visualization_config=dict(waveform_enabled=True))
e._prepare_prompt_assets(None,folder,m)
source=Path('jobs/20260914_211614_128793_video_001/music/audio_concatenated.aac')
audio=folder/'audio.aac'
subprocess.run([str(find_ffmpeg()),'-v','error','-y','-stream_loop','-1','-i',str(source),
                '-t','5400','-c:a','copy','-f','ipod',str(audio)],check=True)
m['audio_path']=str(audio.resolve())
e.timeline_builder.add_clip(m['generated_background_path'],'image',5400)
m['selected_images']=[m['assets']['background']['filename']]
output=e._render_video(folder,m,audio)
write_json(folder/'metadata.json',m)
assert output, m.get('render_error')
assert e._validate_output(folder,output,audio,m)
verify_job_assets(m)
qc=qc_job(folder,dict(video_path=str(output),thumbnail_path=m['thumbnail_path'],title=m['youtube_title'],description=m['youtube_description']),m)
assert all(c['status']=='pass' or c['name']=='YouTube thumbnail upload size' for c in qc['checks']),qc
write_json(folder/'acceptance.json',dict(metadata=m,qc=qc,resources=json.loads((folder/'render_resources.json').read_text())))
print('90 MINUTE RENDER VALIDATED',flush=True)
