import json,random
from pathlib import Path
from app.config.settings import get_settings
from app.pipeline.long_form_jazz_orchestrator import LongFormJazzOrchestrator
s=get_settings().model_copy(update={'video_width':1280,'video_height':720,'video_fps':15,'ffmpeg_preset':'ultrafast','ffmpeg_crf':28,'colab_image_enabled':False})
random.seed(37)
r=LongFormJazzOrchestrator(s)
assert r.run(video_count=1,duration_minutes=10)
p=Path('jobs')/r.last_job_ids[-1]/'metadata.json'
d=json.loads(p.read_text()); d['youtube_exclude']=True; p.write_text(json.dumps(d,indent=2))
info=r._probe_media(Path(d['video_path']))
assert len(info['streams'])==2
assert d['image_count']==1
for stream in info['streams']: assert abs(float(stream['duration'])-600)<.2
print('ACCEPTANCE',p,d['total_elapsed_seconds'],d.get('youtube_title'),flush=True)
