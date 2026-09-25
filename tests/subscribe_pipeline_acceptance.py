import json
from pathlib import Path
from app.config.settings import get_settings
from app.pipeline.long_form_jazz_orchestrator import LongFormJazzOrchestrator
settings=get_settings().model_copy(update=dict(video_width=1280,video_height=720,video_fps=15,ffmpeg_preset='ultrafast',ffmpeg_crf=28,video_encoder='libx264',visualizer_enabled=True,subscribe_overlay_enabled=True,subscribe_overlay_interval_seconds=180,colab_image_enabled=False))
from app.studio.profiles import Channel
context=dict(channel=Channel(id='focus-protocol',name='Focus Protocol').model_dump(),profile={},image_motion={'enabled':True,'preset':'gentle_float','seed':42},youtube_exclude=True,content_id='subscribe-overlay-acceptance',background_mode='image',content_plan={'metadata':{'youtube_title':'Subscribe overlay acceptance','youtube_description':'Local acceptance test. Do not publish.','youtube_tags':['test']}})
engine=LongFormJazzOrchestrator(settings,context=context)
success=engine.run(video_count=1,duration_minutes=10)
folder=Path('jobs')/engine.last_job_ids[0]
metadata=json.loads((folder/'metadata.json').read_text(encoding='utf-8'))
print('PIPELINE_RESULT',success,str(folder),metadata.get('render_error'),flush=True)
assert success
assert metadata['subscribe_overlay_starts']==[180,360,540]
