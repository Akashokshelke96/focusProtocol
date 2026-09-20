"""Inspect actual acceptance media and compare ON/OFF through the same renderer."""
import json
import subprocess
from pathlib import Path
import numpy as np
from PIL import Image, ImageDraw
from app.config.settings import get_settings
from app.utils.ffmpeg import find_ffmpeg, find_ffprobe
from app.video.short_loop import render_loop, probe
from app.video.branding import loop_branding
from app.studio.assets import verify_job_assets
from app.youtube.state import write_json


def run():
    result=json.loads(Path('jobs/loop_visualizer_acceptance.json').read_text())
    assert result['success']
    directory=Path('jobs')/result['job_id']
    m=json.loads((directory/'metadata.json').read_text())
    final=Path(m['video_path'])
    ffmpeg,ffprobe=find_ffmpeg(),find_ffprobe()
    info=probe(final,ffprobe)
    streams=info['streams']
    assert [s['codec_type'] for s in streams] == ['video','audio']
    assert (streams[0]['width'],streams[0]['height']) == (1920,1080)
    assert abs(float(streams[0]['duration'])-1380)<.1
    assert abs(float(streams[1]['duration'])-1380)<.1
    verify_job_assets(m)
    frames={}
    for offset in (1,2,7,691,692,1375,1376):
        dest=directory/f'verify_{offset}.png'
        subprocess.run([str(ffmpeg),'-v','error','-y','-ss',str(offset),'-i',str(final),'-frames:v','1',str(dest)],check=True)
        frames[offset]=np.array(Image.open(dest).convert('RGB'))
    region=(slice(910,1020),slice(60,480))
    changes={str(t):float(np.abs(frames[t][region].astype(float)-frames[t+1][region]).mean()) for t in (1,691,1375)}
    repeat=float(np.abs(frames[1][region].astype(float)-frames[7][region]).mean())
    assert min(changes.values())>1,changes
    assert repeat<min(changes.values())*.3,(repeat,changes)
    sheet=Image.new('RGB',(960,3*570),(24,24,24))
    pen=ImageDraw.Draw(sheet)
    for row,t in enumerate((1,691,1375)):
        pen.text((16,row*570+8),f'{t}s - actual final MP4',fill='white')
        sheet.paste(Image.fromarray(frames[t]).resize((960,540)),(0,row*570+30))
    sheet.save(directory/'verification_contact_sheet.jpg')
    strip=Image.new('RGB',(420*3,140),(24,24,24)); pen=ImageDraw.Draw(strip)
    for col,t in enumerate((1,2,7)):
        strip.paste(Image.fromarray(frames[t][region]),(col*420,30))
        pen.text((col*420+10,8),f'{t} seconds',fill='white')
    strip.save(directory/'verification_motion.png')
    # OFF uses the unchanged render path and identical source artwork/branding.
    off=directory/'verify_off';off.mkdir(exist_ok=True)
    audio=off/'audio.aac'
    subprocess.run([str(ffmpeg),'-v','error','-y','-i',m['audio_path'],'-t','12','-c:a','copy','-f','ipod',str(audio)],check=True)
    settings=get_settings().model_copy(update=dict(visualizer_enabled=False))
    off_meta={'target_duration_seconds':12}
    branding=loop_branding(off,settings,off_meta)
    off_video=render_loop(settings,off,off_meta,Path(m['generated_background_path']),False,audio,branding,ffmpeg,ffprobe)
    off_frame=off/'frame.png'
    subprocess.run([str(ffmpeg),'-v','error','-y','-ss','1','-i',str(off_video),'-frames:v','1',str(off_frame)],check=True)
    pixels=np.array(Image.open(off_frame).convert('RGB'))
    delta=np.abs(frames[1].astype(float)-pixels)
    mask=np.ones(delta.shape[:2],bool);mask[900:1030,50:490]=False
    outside=float(delta[mask].mean());inside=float(delta[region].mean())
    assert inside>outside*3,(inside,outside)
    assert not off_meta['visualizer_enabled']
    def audio_hash(path):
        return subprocess.check_output([str(ffmpeg),'-v','error','-i',str(path),'-map','0:a:0','-c:a','copy','-f','hash','-hash','sha256','-'],text=True).strip()
    assert audio_hash(final)==audio_hash(m['audio_path'])
    decode=subprocess.run([str(ffmpeg),'-v','error','-xerror','-i',str(final),'-f','null','-'],capture_output=True,text=True)
    assert decode.returncode==0,decode.stderr
    report=dict(video=str(final.resolve()),duration_seconds=1380,resolution=[1920,1080],
        fps=streams[0]['avg_frame_rate'],movement_mean_pixel_change=changes,repeat_6s_mean_pixel_change=repeat,
        off_comparison=dict(inside_mean_pixel_change=inside,outside_mean_pixel_change=outside),
        audio_packet_hash_matches=True,full_decode_passed=True,source_hashes_verified=True,
        render_seconds=m['render_elapsed_seconds'],total_seconds=m['total_elapsed_seconds'],
        timings=m['render_timings'],resources=json.loads((directory/'render_resources.json').read_text()),
        asset_bytes=Path(m['visualizer_group']['path']).stat().st_size,final_bytes=final.stat().st_size)
    write_json(directory/'visualizer_verification.json',report)
    print(json.dumps(report,indent=2))

if __name__=='__main__':
    run()
