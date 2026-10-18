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


def short_command(backend, settings, background, is_video, branding, output, seconds, vis=None, motion=None, dust=None, sub=None, watermark=None):
    """Encode the short clip once with branding + soundwave baked in.

    Loop/mux stay pure stream-copy; no GIFs, fades, or full-duration
    video filters ever enter those stages.
    """
    w, h, fps = settings.video_width, settings.video_height, settings.video_fps
    frames = max(2, round(seconds * fps))
    cmd = [str(backend), '-y', '-filter_complex_threads', str(min(2, settings.render_cpu_threads))]
    cmd += ['-stream_loop', '-1'] if is_video else ['-loop', '1', '-framerate', str(fps)]
    cmd += ['-i', str(background), '-loop', '1', '-framerate', str(fps), '-i', str(branding)]
    if vis is not None:
        cmd += ['-stream_loop', '-1', '-i', str(vis['path'])]
    if dust is not None:
        cmd += ['-stream_loop', '-1', '-i', str(dust['path'])]
    sub_index = 2 + (vis is not None) + (dust is not None)
    if sub is not None:
        # Looped like vis/dust so the sub timeline is continuous and synced.
        # (A short stream with timestamps shifted into the future makes the
        # overlay's frame-sync buffer gigabytes of main frames = RAM trip.)
        cmd += ['-stream_loop', '-1', '-t', str(seconds),
                '-threads', '1', '-c:v', sub['decoder'], '-i', str(sub['path'])]
    fit = f'scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},setsar=1,fps={fps}'
    if is_video:
        # A bounded forward/reverse cycle joins identical end frames at both seams.
        # Only half of the short clip is buffered, never the full-length video.
        half = math.ceil(frames / 2)
        base = (f'[0:v]{fit},trim=end_frame={half},setpts=PTS-STARTPTS,split[f][r];'
                '[r]reverse,setpts=PTS-STARTPTS[back];'
                '[f][back]concat=n=2:v=1:a=0[base]')
    elif motion and motion.get('enabled') and motion.get('preset') != 'static':
        from app.video.image_motion import transform_filter
        base = f'[0:v]{fit},{transform_filter(motion, fps)}[base]'
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
    overlay_base = 'branded'
    if dust is not None:
        dust_index = 3 if vis is not None else 2
        graph += (f';[{dust_index}:v]setpts=PTS-STARTPTS,scale={w}:{h},format=rgba,'
                  f"colorchannelmixer=aa={dust['opacity']},format=yuva420p[dust];"
                  '[branded][dust]overlay=0:0:format=yuv420[dusted]')
        overlay_base = 'dusted'
    prev_label = overlay_base
    if vis is not None:
        # Soundwave baked into the short clip only (bottom-left). The 6s
        # animation loops seamlessly inside the clip, so the later
        # packet-copy loop carries it for free.
        graph += (f";[2:v]setpts=PTS-STARTPTS,format=rgba,"
                  f"scale={vis['width']}:{vis['height']},"
                  f"colorchannelmixer=aa={vis['opacity']}[soundwave];"
                  f"[{overlay_base}][soundwave]overlay=x={vis['x']}:y=H-h-{vis['bottom']}:"
                  f"format=yuv420[with_vis]")
        prev_label = 'with_vis'
    if sub is not None:
        # Subscribe baked once at the END of the short clip (bottom-right).
        # The packet-copy loop repeats it every clip_seconds in the final
        # video, so loop/mux stay pure stream-copy.
        start = sub['starts'][0]
        dur = round(min(sub['duration'], seconds - start), 3)
        crop = f"crop={sub['crop']}," if sub.get('crop') else ''
        graph += (f";[{sub_index}:v]setpts=PTS-STARTPTS,"
                  f"trim=start={start}:end={start+dur},setpts=PTS-STARTPTS,"
                  f"{crop}scale={sub['width']}:{sub['height']},format=yuva420p[sub];"
                  f"[{prev_label}][sub]overlay=x={sub['x']}:y={sub['y']}:"
                  f"eof_action=pass:repeatlast=0:enable='gte(t,{start})*lt(t,{start+dur})',"
                  f"fps={fps},setpts=N/({fps}*TB)[wm_base]")
    else:
        graph += f';[{prev_label}]fps={fps},setpts=N/({fps}*TB)[wm_base]'

    if watermark is not None:
        wm_index = 2 + (vis is not None) + (dust is not None) + (sub is not None)
        mark_width = max(1, round(w * settings.watermark_width_ratio))
        right = max(8, round(w * settings.watermark_right_padding_ratio))
        bottom = max(8, round(h * settings.watermark_bottom_padding_ratio))
        graph += (f";[{wm_index}:v]scale={mark_width}:-1,format=rgba,"
                  f"colorchannelmixer=aa={settings.watermark_opacity}[wm];"
                  f"[wm_base][wm]overlay=x=W-w-{right}:y=H-h-{bottom}:format=yuv420[out]")
        cmd += ['-loop', '1', '-i', str(watermark)]
    else:
        graph += f';[wm_base]fps={fps},setpts=N/({fps}*TB)[out]'
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


def loop_mux_command(ffmpeg, short, audio, output, duration, audio_codec):
    """Loop the short clip and mux audio in ONE stream-copy pass.

    Same bytes as loop-then-mux, but no intermediate looped.mp4: half the
    disk I/O and peak temp space, no quality difference (all -c copy).
    """
    if audio_codec not in ('aac', 'mp3', 'alac'):
        raise ValueError('Final audio must already use an MP4-compatible codec for stream-copy muxing')
    return [str(ffmpeg), '-y', '-stream_loop', '-1', '-i', str(short),
            '-i', str(audio), '-map', '0:v:0', '-map', '1:a:0',
            '-c:v', 'copy', '-c:a', 'copy',
            '-t', str(duration), '-movflags', '+faststart', str(output)]


def render_loop(settings, directory, metadata, background, is_video, audio, branding,
                ffmpeg, ffprobe, watermark=None):
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
    from app.video.image_motion import configuration, parameters
    requested_motion = metadata.get('image_motion', {})
    motion = None
    try:
        candidate = configuration(requested_motion)
        metadata['image_motion'] = candidate
        if candidate['enabled'] and candidate['preset'] != 'static' and not is_video:
            motion = candidate
        metadata['image_motion_applied'] = bool(motion)
    except (ValueError, TypeError):
        from app.config.logging_config import get_logger
        get_logger('video.image_motion').warning('Image motion failed; falling back to static background.')
        metadata.update(image_motion_applied=False, image_motion_fallback='Invalid saved motion configuration', fallback_used=True)
    cycle_seconds = 60.0 if is_video or settings.studio_motion_mode == 'drift' else 6.0
    if motion:
        cycle_seconds = float(parameters(motion)['period'])
    from app.video.subscribe_overlay import has_asset as _has_subscribe_asset
    want_sub = bool(settings.subscribe_overlay_enabled) and _has_subscribe_asset(settings)
    if want_sub:
        # 60s clip with subscribe baked at its start: the copy loop repeats
        # it every 60s. 60 is a multiple of every cycle in the clip
        # (motion 30/60, drift cosine, visualizer/dust 6s), so seams align.
        # Subscribe OFF keeps the legacy fast short cycle.
        cycle_seconds = 60.0
    seconds = min(target, cycle_seconds)
    seconds = max(2, round(seconds * settings.video_fps)) / settings.video_fps
    out = directory / 'output'
    out.mkdir(parents=True, exist_ok=True)
    short, looped, final = (out / name for name in ('short_clip.mp4', 'looped.mp4', 'rendering.mp4'))
    backend, encoder, failures = choose_render_backend(ffmpeg, settings)
    from app.video.visualizer import prepare_visualizer
    group = prepare_visualizer(settings)
    from app.video.dust import prepare_dust
    dust = prepare_dust(settings)
    metadata.update(dust_enabled=bool(dust), dust_path=dust['path'] if dust else None,
                    dust_opacity=dust['opacity'] if dust else 0)
    from app.video.subscribe_overlay import prepare as prepare_subscribe
    sub = prepare_subscribe(settings, target, ffmpeg, ffprobe, metadata,
                            clip_seconds=seconds) if want_sub else None
    if not want_sub:
        metadata['subscribe_overlay_enabled'] = False
    command = short_command(backend, settings, background, is_video, branding, short, seconds, vis=group, motion=motion, dust=dust, sub=sub, watermark=watermark)
    command += [*encoder_args(encoder, settings), '-bf', '0', '-g', str(6 * settings.video_fps),
                '-force_key_frames', 'expr:gte(t,n_forced*6)',
                '-pix_fmt', 'yuv420p', '-movflags', '+faststart', str(short)]
    loop_mux = loop_mux_command(ffmpeg, short, audio, final, target, audio_stream['codec_name'])
    # One stream-copy pass loops the short clip and muxes audio: no
    # intermediate looped.mp4, half the disk I/O, identical bytes.
    # Overlays are already baked into the short clip; the full duration is
    # never re-encoded here.
    metadata.update(visualizer_enabled=bool(group), visualizer_group=group,
                    visualizer_style='decorative_6s_loop' if group else None,
                    music_disc_enabled=False)
    metadata.setdefault('visualization_config', {}).update(visualizer_enabled=bool(group))
    write_json(out / 'render_commands.json', dict(short=command, loop_mux=loop_mux))
    timings = {}
    started = time.perf_counter()
    try:
        render_with_progress(command, directory, seconds, settings)
    except RuntimeError as error:
        # Cancellation, resource protection, and timeouts must never start a retry.
        if not motion or (directory / 'cancel.request').exists() or any(word in str(error).lower() for word in ('cancel', 'resource protection', 'time limit', 'no frame progress')):
            raise
        from app.config.logging_config import get_logger
        get_logger('video.image_motion').warning('Image motion failed; falling back to static background.')
        metadata.update(image_motion_applied=False, image_motion_fallback='FFmpeg motion encode failed', fallback_used=True)
        static = settings.model_copy(update={'studio_motion_mode': 'static'})
        command = short_command(backend, static, background, False, branding, short, seconds, vis=group, dust=dust, sub=sub, watermark=watermark)
        command += [*encoder_args(encoder, settings), '-bf', '0', '-g', str(6 * settings.video_fps),
                    '-force_key_frames', 'expr:gte(t,n_forced*6)', '-pix_fmt', 'yuv420p', '-movflags', '+faststart', str(short)]
        write_json(out / 'render_commands.json', dict(short=command, loop_mux=loop_mux))
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
    # One stream-copy pass loops the clip and muxes audio. Soundwave and
    # subscribe are already baked into the short clip.
    started = time.perf_counter()
    # The same cancellation, process cap, resource monitor and error handling apply.
    render_with_progress(loop_mux, directory, target, settings)
    timings['loop_mux_seconds'] = round(time.perf_counter() - started, 3)
    result = probe(final, ffprobe)
    if abs(float(result['format']['duration'])-target) > settings.audio_duration_tolerance_seconds:
        raise ValueError('loop_mux output does not match target duration')
    metadata.update(render_architecture='short_clip_copy_loop_with_subscribe' if metadata.get('subscribe_overlay_enabled') else ('short_clip_copy_loop_with_visualizer' if group else 'short_clip_copy_loop'), render_segmented=False,
                    render_part_count=1, short_clip_path=str(short), short_clip_seconds=seconds,
                    looped_video_path=None, video_path=str(final), video_encoder=encoder,
                    encoder_probe_failures=failures, render_executable=str(backend),
                    video_duration_seconds=float(result['format']['duration']),
                    render_timings=timings, audio_mux_codec=loop_mux[loop_mux.index('-c:a')+1],
                    loop_seam='forward_reverse' if is_video else settings.studio_motion_mode)
    if metadata.get('image_motion_applied'):
        metadata['image_motion_cycle_seconds'] = float(parameters(motion)['period'])
        metadata['loop_seam'] = 'periodic_image_motion'
    return final
