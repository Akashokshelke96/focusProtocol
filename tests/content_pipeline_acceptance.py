import json
import shutil
import app.audio.local_timeline as audio_timeline
from pathlib import Path
from app.config.settings import get_settings
from app.pipeline.long_form_jazz_orchestrator import LongFormJazzOrchestrator
from app.studio.profiles import Channel
settings=get_settings().model_copy(update=dict(video_width=1280,video_height=720,video_fps=15,ffmpeg_preset='ultrafast',ffmpeg_crf=23,video_encoder='libx264',visualizer_enabled=True,subscribe_overlay_enabled=False,colab_image_enabled=False))
context=dict(channel=Channel(id='focus-protocol',name='Camping With Blues').model_dump(),profile={},youtube_exclude=True,content_id='content-upgrades-acceptance',background_mode='image',content_plan={'metadata':{'youtube_title':'Content upgrades acceptance','youtube_description':'Local acceptance. Excluded from publishing.','youtube_tags':['test']}})
original_normalize = audio_timeline.normalize_output
def capture_before(output, duration, bitrate='320k', metadata=None):
    shutil.copyfile(output, 'jobs/content_upgrade_acceptance/pipeline_before.m4a')
    return original_normalize(output, duration, bitrate, metadata)
audio_timeline.normalize_output = capture_before
engine=LongFormJazzOrchestrator(settings,context=context)
success=engine.run(video_count=1,duration_minutes=3)
folder=Path('jobs')/engine.last_job_ids[0]
m=json.loads((folder/'metadata.json').read_text(encoding='utf-8'))
assert success,m.get('render_error')
assert m['loudness_normalized'] and m['dust_enabled'], m.get('loudness_fallback')
assert abs(m['loudness']['after']['input_i']+14)<.3
assert m['render_config']['studio_motion_mode']=='drift'
assert m['render_config']['visual_effect']=='old_film'
cmds=json.loads((folder/'output/render_commands.json').read_text())
for k in ['loop','mux']:assert cmds[k][cmds[k].index('-c:v')+1]=='copy'
qc=json.loads((folder/'qc.json').read_text());assert qc['status']=='pass',qc
report=dict(job_id=folder.name,loudness=m['loudness'],timings=m['render_timings'],duration=m['video_duration_seconds'],elapsed=m['total_elapsed_seconds'],qc=qc['status'])
Path('jobs/content_upgrade_acceptance/pipeline.json').write_text(json.dumps(report,indent=2))
print(json.dumps(report,indent=2),flush=True)
