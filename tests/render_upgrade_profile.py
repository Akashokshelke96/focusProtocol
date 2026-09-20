"""Real three-minute profiling, excluded from publishing; optional preset argument."""
import functools,json,subprocess,sys,time
from pathlib import Path
from collections import defaultdict
from app.config.settings import get_settings
from app.pipeline.long_form_jazz_orchestrator import LongFormJazzOrchestrator
from app.studio.profiles import Channel
from app.youtube.state import write_json
import app.audio.local_timeline as audio
import app.studio.assets as assets
import app.providers.media_history as history

label=sys.argv[1]
stats=defaultdict(lambda:dict(seconds=0.,calls=0))
def timed(obj,name):
    fn=getattr(obj,name)
    @functools.wraps(fn)
    def wrapped(*a,**kw):
        t=time.perf_counter()
        try:return fn(*a,**kw)
        finally:
            stats[name]['seconds']+=time.perf_counter()-t;stats[name]['calls']+=1
    setattr(obj,name,wrapped)
for obj,names in ((audio,['_remove_internal_silence','assemble_tracks']),
                  (assets,['asset_sha256','qc_job']), (history,['fingerprint']),
                  (LongFormJazzOrchestrator,['_select_music_files','_prepare_prompt_assets','_validate_output'])):
    for name in names:timed(obj,name)
# Baseline subprocesses are hidden too, without changing their media commands.
original=subprocess.Popen
popups=[]
unhidden=[]
def hidden(*a,**kw):
    popups.append(bool(kw.get('creationflags',0)&getattr(subprocess,'CREATE_NO_WINDOW',0)))
    if not popups[-1]:unhidden.append(str(a[0] if a else kw.get('args')))
    kw.update(creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    return original(*a,**kw)
subprocess.Popen=hidden
s=get_settings().model_copy(update=dict(visualizer_enabled=True,subscribe_overlay_enabled=label=='final',youtube_upload_enabled=False))
if len(sys.argv)>2 and sys.argv[2] != 'resume':s=s.with_quality_preset(sys.argv[2])
context=dict(channel=Channel(id='focus-protocol',name='Camping With Blues').model_dump(),content_id='render-upgrade-'+label,
             profile={},youtube_exclude=True,background_mode='image',content_plan={'metadata':{
             'youtube_title':'Three minute render acceptance '+label,'youtube_description':'Local verification; do not publish.','youtube_tags':['blues']}})
e=LongFormJazzOrchestrator(s,context=context)
import app.video.short_loop, app.video.branding
start=time.perf_counter()
if len(sys.argv)>2 and sys.argv[2]=='resume':
    job_id=json.loads(Path('jobs/upgrade_baseline.json').read_text())['job_id']
    ok=e.resume(job_id);e.last_job_ids=[job_id]
else:ok=e.run(video_count=1,duration_minutes=3)
d=Path('jobs')/e.last_job_ids[0];m=json.loads((d/'metadata.json').read_text())
r=dict(label=label,success=ok,job_id=d.name,wall_seconds=time.perf_counter()-start,profile=dict(stats),
       audio_seconds=m.get('audio_elapsed_seconds'),render_seconds=m.get('render_elapsed_seconds'),timings=m.get('render_timings'),
       config=m.get('render_config'),video=m.get('video_path'),subprocess_calls=len(popups),all_calls_explicitly_hidden=all(popups),unhidden_commands=unhidden)
if r['video']:r['bytes']=Path(r['video']).stat().st_size
write_json(Path('jobs')/('upgrade_'+label+'.json'),r)
print(json.dumps(r,indent=2),flush=True)
assert ok,m.get('render_error')
