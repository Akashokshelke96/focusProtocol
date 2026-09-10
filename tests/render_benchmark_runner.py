import json,time,sys,os
from pathlib import Path
from app.config.settings import get_settings
from app.pipeline.long_form_jazz_orchestrator import LongFormJazzOrchestrator
s=get_settings()
if 'drift' in sys.argv:
    s=s.model_copy(update={'studio_motion_mode':'drift'})
if 'cta' in sys.argv:
    s=s.model_copy(update={'subscribe_overlay_enabled':True})
r=LongFormJazzOrchestrator(s)
source=json.loads(Path('jobs/20260909_010930_video_001/metadata.json').read_text())
folder=Path('jobs/render_benchmark_'+sys.argv[1]); folder.mkdir(exist_ok=True); (folder/'output').mkdir(exist_ok=True)
duration=float(os.getenv('BENCHMARK_DURATION_SECONDS','12'))
r.timeline_builder.add_clip(source['generated_background_path'],'image',duration)
m={'target_duration_seconds':duration}
t=time.perf_counter(); output=r._render_video(folder,m,Path(source['audio_path'])); elapsed=time.perf_counter()-t
assert output
info=r._probe_media(output)
(folder/'benchmark.json').write_text(json.dumps({'elapsed_seconds':elapsed,'metadata':m,'streams':info['streams']},indent=2))
print('BENCHMARK',sys.argv[1],elapsed,flush=True)
