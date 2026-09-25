import json,re,subprocess,time
from pathlib import Path
from app.utils.ffmpeg import find_ffmpeg
root=Path('jobs/content_upgrade_acceptance');root.mkdir(exist_ok=True)
ff=str(find_ffmpeg())
source=Path('jobs/20260924_212327_276616_video_001/music/audio_concatenated.aac')
def run(args):
 t=time.perf_counter();r=subprocess.run([ff,'-hide_banner','-nostats','-y',*map(str,args)],capture_output=True,text=True,check=True);return r,time.perf_counter()-t
run(['-i',source,'-t','180','-c:a','copy','-f','ipod',root/'before.m4a'])
def stats(r):return json.loads(re.findall(r'\{[^{}]*"input_i"[^{}]*\}',r.stderr)[-1])
base='loudnorm=I=-14:TP=-1.5:LRA=11:print_format=json'
r,single=run(['-i',root/'before.m4a','-af',base,'-ar','48000','-c:a','aac','-b:a','320k',root/'single.m4a']);s=stats(r)
r,analysis=run(['-i',root/'before.m4a','-af',base,'-f','null','-']);a=stats(r)
params=base+':linear=true:'+':'.join(f'{k}={a[v]}' for k,v in [('measured_I','input_i'),('measured_TP','input_tp'),('measured_LRA','input_lra'),('measured_thresh','input_thresh'),('offset','target_offset')])
r,encode=run(['-i',root/'before.m4a','-af',params,'-ar','48000','-c:a','aac','-b:a','320k',root/'dual.m4a']);d=stats(r)
report=dict(single_seconds=single,dual_analysis_seconds=analysis,dual_encode_seconds=encode,before=a,single_filter=s,dual_filter=d)
for name in ['single','dual']:
 r,t=run(['-i',root/f'{name}.m4a','-af',base,'-f','null','-']);report[name+'_measured']=stats(r)
(root/'loudness_benchmark.json').write_text(json.dumps(report,indent=2));print(json.dumps(report,indent=2),flush=True)
