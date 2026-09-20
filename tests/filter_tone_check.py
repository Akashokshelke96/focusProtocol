import json,subprocess
import numpy as np
from pathlib import Path
from app.video.branding import effect_filter
from app.utils.ffmpeg import find_ffmpeg,no_window_flags
ramp=np.repeat(np.arange(256,dtype=np.uint8)[None,:,None],64,axis=0)
ramp=np.repeat(ramp,3,axis=2)
results=[]
for mode in ('vintage','old_film','warm_film','faded_film','noir','sepia','film_grain','cool_cinematic','soft_vignette'):
    for level in (.06,.12,.20):
        data=subprocess.check_output([str(find_ffmpeg()),'-v','error','-f','rawvideo','-pixel_format','rgb24','-video_size','256x64','-i','-',
             '-vf',effect_filter(mode,level)[1:],'-frames:v','1','-f','rawvideo','-pix_fmt','rgb24','-'],input=ramp.tobytes(),**no_window_flags())
        pixels=np.frombuffer(data,np.uint8)
        results.append(dict(mode=mode,intensity=level,minimum=int(pixels.min()),maximum=int(pixels.max()),clipped_components=int(((pixels==0)|(pixels==255)).sum())))
        assert pixels.min()>0 and pixels.max()<255,results[-1]
Path('jobs/filter_acceptance/tone_check.json').write_text(json.dumps(results,indent=2))
print('All 27 black-to-white gradient checks retain output headroom')
