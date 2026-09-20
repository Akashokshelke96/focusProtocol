"""Encode seconds of branded video, then copy packets for the requested duration."""
import json
import math
import time
from pathlib import Path

from app.video.encoding import choose_render_backend, encoder_args, render_with_progress
from app.youtube.state import write_json


def probe(path, ffprobe):
    from app.utils.ffmpeg import probe_media
    return probe_media(path, ffprobe)


def short_command(backend, settings, background, is_video, branding, output, seconds, vis=None):
    """Encode the short clip once with branding + soundwave baked in.

    Loop/mux stay pure stream-copy; no GIFs, fades, or full-duration
    video filters ever enter those stages.
    """
    w, h, fps = settings.video_width, settings.video_height, settings.video_fps
    frames = max(2, round(seconds * fps))
    cmd = [str(backend), '-y', '-filter_complex_threads', str(settings.render_cpu_threads)]
    cmd += ['-stream_loop', '-1'] if is_video else ['-loop', '1', '-framerate', str(fps)]
    cmd += ['-i', str(background), '-loop', '1', '-framerate', str(fps), '-i', str(branding)]
    if vis is not None:
        cmd += ['-stream_loop', '-1', '-i', str(vis['path'])]
    fit = f'scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},setsar=1,fps={fps}'
    if is_video:
        # A bounded forward/reverse cycle joins identical end frames at both seams.
        # Only half of the short clip is buffered, never the full-length video.
        half = math.ceil(frames / 2)
        base = (f'[0:v]{fit},trim=end_frame={half},setpts=PTS-STARTPTS,split[f][r];'
                '[r]reverse,setpts=PTS-STARTPTS[back];'
                '[f][back]concat=n=2:v=1:a=0[base]')
    elif settings.studio_motion_mode == 'drift':
        margin = max(2, round(w * .018))
        base = (f'[0:v]scale={w+margin}:{h+margin}:force_original_aspect_ratio=increase,'
                f"crop={w}:{h}:x='{margin}/2*(1-cos(2*PI*t/{seconds}))':y={margin}/2,"
                f'setsar=1,fps={fps}[base]')
    else:
        base = f'[0:v]{fit}[base]'
    from app.video.branding import effect_filter
    grade = effect_filter(settings.visual_effect, settings.visual_effect_opacity, fps=fps)
    if grade:
        # Apply after fitting/motion but before either overlay. An empty grade
        # leaves the original command graph byte-for-byte unchanged.
        base += f';[base]{grade[1:]}[graded]'
    background_label = 'graded' if grade else 'base'
    graph = base + f';[{background_label}][1:v]overlay=0:0:format=yuv420[branded]'
    if vis is not None:
        # Soundwave baked into the short clip only (bottom-left). The 6s
        # animation loops seamlessly inside the 60s clip, so the later
        # packet-copy loop to 90min carries it for free.
        graph += (f";[2:v]setpts=PTS-STARTPTS,format=rgba,"
                  f"scale={vis['width']}:{vis['height']},"
                  f"colorchannelmixer=aa={vis['opacity']}[soundwave];"
                  f"[branded][soundwave]overlay=x={vis['x']}:y=H-h-{vis['bottom']}:"
                  f"format=auto,fps={fps},setpts=N/({fps}*TB)[out]")
    else:
        graph += f';[branded]fps={fps},setpts=N/({fps}*TB)[out]'
    cmd += ['-filter_complex', graph, '-map', '[out]', '-an', '-r', str(fps), '-frames:v', str(frames)]
    return cmd


def copy_commands(ffmpeg, short, looped, audio, output, duration, audio_codec):
    if audio_codec not in ('aac', 'mp3', 'alac'):
        raise ValueError('Final audio must already use an MP4-compatible codec for stream-copy muxing')
    loop = [str(ffmpeg), '-y', '-stream_loop', '-1', '-i', str(short),
            '-map', '0:v:0', '-an', '-c:v', 'copy', '-t', str(duration), str(looped)]
    mux = [str(ffmpeg), '-y', '-i', str(looped), '-i', str(audio),
           '-map', '0:v:0', '-map', '1:a:0', '-c:v', 'copy',
           '-c:a', 'copy',
           '-t', str(duration), '-movflags', '+faststart', str(output)]
    return loop, mux


def render_loop(settings, directory, metadata, background, is_video, audio, branding,
                ffmpeg, ffprobe):
    directory = Path(directory)
    target = float(metadata['target_duration_seconds'])
    if not math.isfinite(target) or target <= 0:
        raise ValueError('Target duration must be positive and finite')
    audio_info = probe(audio, ffprobe)
    audio_stream = next(s for s in audio_info['streams'] if s['codec_type'] == 'audio')
    if abs(float(audio_info['format']['duration']) - target) > settings.audio_duration_tolerance_seconds:
        raise ValueError('Complete target-length audio is required before encoding video')
    # Static artwork plus a six-second visualizer needs only one six-second
    # encode. Preserve the established 60s motion cycle for moving backgrounds.
    subscribe = settings.subscribe_overlay_enabled
    cycle_seconds = 60.0 if is_video or settings.studio_motion_mode == 'drift' else 6.0
    seconds = cycle_seconds if subscribe else min(target, cycle_seconds)
    seconds = max(2, round(seconds * settings.video_fps)) / settings.video_fps
    out = directory / 'output'
    out.mkdir(parents=True, exist_ok=True)
    short, looped, final = (out / name for name in ('short_clip.mp4', 'looped.mp4', 'rendering.mp4'))
    backend, encoder, failures = choose_render_backend(ffmpeg, settings)
    from app.video.visualizer import prepare_visualizer
    group = prepare_visualizer(settings)
    command = short_command(backend, settings, background, is_video, branding, short, seconds, vis=group)
    command += [*encoder_args(encoder, settings), '-bf', '0', '-g', str(6 * settings.video_fps),
                '-force_key_frames', 'expr:gte(t,n_forced*6)',
                '-pix_fmt', 'yuv420p', '-movflags', '+faststart', str(short)]
    loop, mux = copy_commands(ffmpeg, short, looped, audio, final, target, audio_stream['codec_name'])
    # Loop and mux stay pure stream-copy. The soundwave is already baked
    # into the short clip; never re-encode the full duration here.
    metadata.update(visualizer_enabled=bool(group), visualizer_group=group,
                    visualizer_style='decorative_6s_loop' if group else None,
                    music_disc_enabled=False)
    metadata.setdefault('visualization_config', {}).update(visualizer_enabled=bool(group))
    write_json(out / 'render_commands.json', dict(short=command, loop=loop, mux=mux))
    timings = {}
    started = time.perf_counter()
    render_with_progress(command, directory, seconds, settings)
    timings['short_encode_seconds'] = round(time.perf_counter() - started, 3)
    resource_path = directory / 'render_resources.json'
    if resource_path.is_file():
        metadata['short_encode_resources'] = json.loads(resource_path.read_text())
    info = probe(short, ffprobe)
    if [s['codec_type'] for s in info['streams']] != ['video']:
        raise ValueError('Short clip must contain exactly one video stream and no audio')
    video = info['streams'][0]
    if (video['width'], video['height']) != (settings.video_width, settings.video_height) or abs(float(info['format']['duration'])-seconds) > 1/settings.video_fps:
        raise ValueError('Short clip dimensions or duration are invalid')
    if subscribe:
        from app.video.subscribe_loop import build_subscribe_cycle
        cycle = build_subscribe_cycle(settings, directory, metadata, short, backend, encoder, ffmpeg, ffprobe)
        timings['subscribe_build_seconds'] = metadata['subscribe_build_seconds']
        loop, mux = copy_commands(ffmpeg, cycle, looped, audio, final, target, audio_stream['codec_name'])
        write_json(out / 'render_commands.json', dict(short=command, loop=loop, mux=mux))
    for name, cmd, result_path in [('loop', loop, looped), ('mux', mux, final)]:
        started = time.perf_counter()
        # The same cancellation, process cap, resource monitor and error handling apply.
        render_with_progress(cmd, directory, target, settings)
        timings[name + '_seconds'] = round(time.perf_counter() - started, 3)
        result = probe(result_path, ffprobe)
        if abs(float(result['format']['duration'])-target) > settings.audio_duration_tolerance_seconds:
            raise ValueError(f'{name} output does not match target duration')
    metadata.update(render_architecture='short_clip_copy_loop_with_subscribe' if subscribe else ('short_clip_copy_loop_with_visualizer' if group else 'short_clip_copy_loop'), render_segmented=False,
                    render_part_count=1, short_clip_path=str(short), short_clip_seconds=seconds,
                    looped_video_path=str(looped), video_path=str(final), video_encoder=encoder,
                    encoder_probe_failures=failures, render_executable=str(backend),
                    video_duration_seconds=float(result['format']['duration']),
                    render_timings=timings, audio_mux_codec=mux[mux.index('-c:a')+1],
                    loop_seam='forward_reverse' if is_video else settings.studio_motion_mode)
    return final
