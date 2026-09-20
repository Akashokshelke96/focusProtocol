"""A six-second subscribe variant and packet-copy assembly of a 480s cycle."""
import json
import time
from pathlib import Path
from PIL import Image, ImageDraw
from app.video.branding import font
from app.video.encoding import encoder_args, render_with_progress
from app.youtube.state import write_json


def subscribe_card(directory, settings):
    scale = settings.video_height / 1080
    w, h = max(160, round(340*scale)), max(34, round(66*scale))
    image = Image.new('RGBA', (w, h))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((0, 0, w-1, h-1), radius=round(h*.2), fill=(198, 20, 28, 240))
    face = font(max(11, round(24*scale)))
    text = 'Subscribe to channel'
    while draw.textlength(text, font=face) > w-20:
        face = font(face.size-1)
    box=draw.textbbox((0,0),text,font=face)
    draw.text(((w-(box[2]-box[0]))/2-box[0], (h-(box[3]-box[1]))/2-box[1]), text, font=face, fill='white')
    path=Path(directory)/'output'/'subscribe_card.png'
    image.save(path)
    return path,w,h


def build_subscribe_cycle(settings, directory, metadata, short, backend, encoder, ffmpeg, ffprobe):
    """Re-encode only six seconds; all cycle assembly is packet copy.

    Short clip GOPs are closed, six seconds long, with B-frames disabled. Thus
    the tail starts at a keyframe and shares encoder parameters/timebase with
    the reminder. The base motion and waveform phases remain unchanged.
    """
    from app.video.short_loop import probe
    out=Path(directory)/'output'
    base_seconds = round(float(probe(short, ffprobe)['format']['duration']))
    if base_seconds not in (6, 60):
        raise ValueError('Subscribe requires a six- or sixty-second base cycle')
    card,w,h=subscribe_card(directory,settings)
    interval=480
    duration=min(5.,settings.subscribe_animation_duration)
    variant,tail,cycle=(out/name for name in ('subscribe_head.mp4','normal_tail.mp4','subscribe_cycle.mp4'))
    margin=round(settings.video_width*.02)
    bottom=round(settings.video_height*.065)
    graph=(f'[1:v]format=rgba,fade=t=in:st=0:d=0.4:alpha=1,'
           f'fade=t=out:st={duration-.4}:d=0.4:alpha=1[card];'
           f'[0:v][card]overlay=x=W-w-{margin}:y=H-h-{bottom}:format=yuv420[out]')
    command=[str(backend),'-y','-filter_complex_threads',str(settings.render_cpu_threads),
             '-i',str(short),'-loop','1','-framerate',str(settings.video_fps),'-i',str(card),
             '-filter_complex',graph,'-map','[out]','-an','-t','6','-r',str(settings.video_fps),
             *encoder_args(encoder,settings),'-bf','0','-g',str(6*settings.video_fps),
             '-pix_fmt','yuv420p','-movflags','+faststart',str(variant)]
    start=time.perf_counter()
    render_with_progress(command,directory,6,settings)
    tail_cmd=[str(ffmpeg),'-y','-ss','6','-i',str(short),'-t','54','-map','0:v:0','-an','-c:v','copy',str(tail)]
    if base_seconds == 60:
        render_with_progress(tail_cmd,directory,54,settings)
    manifest=out/'subscribe_cycle.txt'
    # Relative generated names avoid concat escaping issues in user directories.
    entries = "file 'subscribe_head.mp4'\n"
    if base_seconds == 60:
        entries += "file 'normal_tail.mp4'\n"
    entries += "file 'short_clip.mp4'\n" * (interval // base_seconds - 1)
    manifest.write_text(entries,encoding='utf-8')
    concat=[str(ffmpeg),'-y','-f','concat','-safe','1','-i',str(manifest),'-map','0:v:0','-an','-c:v','copy',str(cycle)]
    render_with_progress(concat,directory,interval,settings)
    info=probe(cycle,ffprobe)
    if abs(float(info['format']['duration'])-interval)>1/settings.video_fps:
        raise ValueError('Subscribe cycle must be exactly 480 seconds')
    # Prevent an incompatible head/tail stream from quietly reaching the final mux.
    base=probe(short,ffprobe)['streams'][0]
    for path in ([variant,tail] if base_seconds == 60 else [variant]):
        stream=probe(path,ffprobe)['streams'][0]
        if any(stream.get(k)!=base.get(k) for k in ('codec_name','width','height','pix_fmt','time_base')):
            raise ValueError('Subscribe variant does not match the base clip')
    metadata.update(subscribe_overlay_enabled=True,subscribe_overlay_interval_seconds=480,
                    subscribe_overlay_position='bottom_right',subscribe_animation_duration=duration,
                    subscribe_overlay_bounds=[settings.video_width-w-margin,settings.video_height-h-bottom,w,h],
                    subscribe_cycle_path=str(cycle),subscribe_schedule=f'0-{duration:g} seconds, then every 480 seconds',
                    subscribe_build_seconds=round(time.perf_counter()-start,3))
    write_json(out/'subscribe_commands.json',dict(head=command,tail=tail_cmd if base_seconds == 60 else None,cycle=concat))
    return cycle
