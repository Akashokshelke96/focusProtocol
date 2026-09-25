"""Sequential PCM assembly with bounded crossfade buffers; no repeated base block."""
from app.utils.ffmpeg import no_window_flags
import shutil
import subprocess
import tempfile
import os
import json
import re
import math
import time
from pathlib import Path
import numpy as np
from app.utils.ffmpeg import find_ffmpeg


def _loudness_stats(stderr):
    return json.loads(re.findall(r'\{[^{}]*"input_i"[^{}]*\}', stderr)[-1])


def normalize_output(output, duration, bitrate='320k', metadata=None):
    """Normalize the finished AAC safely; retain it unchanged if this upgrade fails."""
    from app.utils.ffmpeg import probe_media
    from app.config.logging_config import get_logger
    metadata = metadata if metadata is not None else {}
    metadata['loudness_normalized'] = False
    output = Path(output)
    started = time.perf_counter()
    with tempfile.NamedTemporaryFile(dir=output.parent, suffix='.m4a', delete=False) as temp:
        temporary = Path(temp.name)
    try:
        ffmpeg = str(find_ffmpeg())
        # AAC measured +0.12 dB above the filter ceiling in acceptance. Reserve
        # 0.2 dB encoder headroom while retaining the requested -1.5 dBTP ceiling.
        params = 'loudnorm=I=-14:TP=-1.7:LRA=11:print_format=json'
        analysis = subprocess.run([ffmpeg, '-hide_banner', '-nostats', '-i', str(output),
                                   '-af', params, '-f', 'null', '-'], capture_output=True,
                                  text=True, check=True, timeout=max(180, duration*2), **no_window_flags())
        before = _loudness_stats(analysis.stderr)
        if not math.isfinite(float(before['input_i'])):
            raise ValueError('No measurable programme loudness')
        params += ':linear=true:' + ':'.join(f'{key}={before[value]}' for key, value in (
            ('measured_I', 'input_i'), ('measured_TP', 'input_tp'), ('measured_LRA', 'input_lra'),
            ('measured_thresh', 'input_thresh'), ('offset', 'target_offset')))
        result = subprocess.run([ffmpeg, '-hide_banner', '-nostats', '-y', '-i', str(output),
                                 '-map', '0:a:0', '-af', params, '-ar', '48000', '-c:a', 'aac',
                                 '-b:a', bitrate, '-t', str(duration), '-f', 'ipod', str(temporary)],
                                capture_output=True, text=True, check=True,
                                timeout=max(180, duration*2), **no_window_flags())
        filtered = _loudness_stats(result.stderr)
        if not math.isfinite(float(filtered['input_i'])):
            raise ValueError('No measurable programme loudness')
        info = probe_media(temporary)
        streams = info['streams']
        if len(streams) != 1 or streams[0]['codec_name'] != 'aac' or abs(float(info['format']['duration'])-duration) > 1/48000:
            raise ValueError('Normalized AAC codec or duration changed')
        # Measure decoded AAC, not just the pre-encoder loudnorm estimate.
        measured = subprocess.run([ffmpeg, '-hide_banner', '-nostats', '-i', str(temporary),
                                   '-af', 'loudnorm=I=-14:TP=-1.5:LRA=11:print_format=json', '-f', 'null', '-'],
                                  capture_output=True, text=True, check=True,
                                  timeout=max(180, duration*2), **no_window_flags())
        after = _loudness_stats(measured.stderr)
        if not math.isfinite(float(after['input_i'])) or abs(float(after['input_i'])+14) > .3 or float(after['input_tp']) > -1.5:
            raise ValueError('Encoded AAC misses requested loudness/true-peak limits')
        os.replace(temporary, output)
        metadata.update(loudness_normalized=True, loudness={
            'method': 'dual_pass', 'target_i': -14, 'target_tp': -1.5, 'target_lra': 11,
            'filter_tp': -1.7, 'before': {k: float(before[k]) for k in ('input_i', 'input_tp', 'input_lra')},
            'after': {k: float(after[k]) for k in ('input_i', 'input_tp', 'input_lra')},
            'elapsed_seconds': round(time.perf_counter()-started, 3)})
    except (OSError, ValueError, IndexError, KeyError, subprocess.SubprocessError) as error:
        metadata['loudness_fallback'] = str(error)
        get_logger('audio.loudness').warning('Loudness normalization skipped; retaining original AAC: %s', error)
    finally:
        temporary.unlink(missing_ok=True)
    return output


def _remove_internal_silence(source, target, rate, channels, threshold_db, min_seconds,
                             keep_seconds, protected_edge_seconds):
    samples = np.memmap(source, dtype='<i2', mode='r')
    frame_count = len(samples) // channels
    samples = samples[:frame_count * channels].reshape(frame_count, channels)
    window = max(1, round(rate * 0.05))
    # Reduce ten seconds at a time; never expand a whole long source into floats.
    window_rms = []
    for start in range(0, frame_count, window * 200):
        chunk = samples[start:min(start + window*200, frame_count)].astype(np.float32)
        rms = np.sqrt(np.mean(np.square(chunk), axis=1))
        n = len(rms)
        trimmed = n - (n % window)
        if trimmed > 0:
            window_rms.extend(rms[:trimmed].reshape(-1, window).mean(axis=1))
        if trimmed < n:
            window_rms.append(rms[trimmed:].mean())
    window_rms = np.asarray(window_rms)
    threshold = 32768 * (10 ** (threshold_db / 20))
    silent = window_rms <= threshold
    minimum_windows = max(1, round(min_seconds / 0.05))
    protected_windows = round(protected_edge_seconds / 0.05)
    keep_windows = round(keep_seconds / 0.05)
    remove = np.zeros(len(silent), dtype=bool)
    index = 0
    while index < len(silent):
        if not silent[index]:
            index += 1
            continue
        end = index
        while end < len(silent) and silent[end]:
            end += 1
        if end - index >= minimum_windows and index >= protected_windows and end <= len(silent) - protected_windows:
            remove[index + keep_windows:max(index + keep_windows, end - keep_windows)] = True
        index = end
    if not remove.any():
        del samples
        # Caller can use the original PCM directly; avoid a redundant full copy.
        return 0
    removed_frames = 0
    with Path(target).open('wb') as stream:
        for start in range(0, len(remove), 200):
            stop = min(start+200, len(remove))
            # A bounded mask covers at most ten seconds, including the partial tail.
            chunk = samples[start*window:min(stop*window, frame_count)]
            keep = np.repeat(~remove[start:stop], window)[:len(chunk)]
            stream.write(chunk[keep].tobytes())
            removed_frames += int((~keep).sum())
    del samples
    return int(removed_frames / rate)



def assemble_tracks(tracks, output, duration, crossfade=4, bitrate='320k', intro_fade=0, outro_fade=0,
                    remove_silence=True, silence_threshold_db=-52, silence_min_seconds=3,
                    silence_keep_seconds=0.25, metadata=None):
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    ffmpeg = str(find_ffmpeg())
    rate, channels = 48000, 2
    frame_bytes = channels * 2
    fade_frames = round(crossfade * rate)
    fade_bytes = fade_frames * frame_bytes
    target_bytes = round(duration * rate) * frame_bytes
    track_timeline = []
    with tempfile.TemporaryDirectory(prefix='audio_timeline_', dir=output.parent) as temporary:
        root = Path(temporary)
        mixed = root / 'timeline.pcm'
        tail = b''
        with mixed.open('wb') as stream:
            for index, track in enumerate(tracks):
                decoded = root / 'track.pcm'
                remaining = max(0, (target_bytes - stream.tell()) / frame_bytes / rate)
                if remaining <= 0:
                    break
                subprocess.run([ffmpeg, '-v', 'error', '-xerror', '-y', '-i', str(track),
                                '-t', str(remaining), '-vn', '-ar', str(rate), '-ac', str(channels),
                                '-f', 's16le', str(decoded)], capture_output=True, check=True, timeout=max(120, remaining), **no_window_flags())
                if remove_silence:
                    cleaned = root / 'cleaned.pcm'
                    _remove_internal_silence(
                        decoded, cleaned, rate, channels, silence_threshold_db,
                        silence_min_seconds, silence_keep_seconds,
                        max(6, crossfade, intro_fade, outro_fade),
                    )
                    if cleaned.exists():
                        decoded.unlink()
                        cleaned.rename(decoded)
                size = decoded.stat().st_size
                if size < fade_bytes * 2 and index < len(tracks) - 1:
                    raise ValueError('A selected track is too short for the configured crossfade')
                # Observations only: actual cleaned PCM/crossfade boundaries, no audio changes.
                start_seconds = stream.tell() / frame_bytes / rate
                track_timeline.append(dict(filename=Path(track).name, start_seconds=start_seconds,
                                           duration_seconds=min(size / frame_bytes / rate, duration-start_seconds)))
                with decoded.open('rb') as incoming:
                    if tail:
                        head = incoming.read(fade_bytes)
                        n = min(len(head), len(tail)) // frame_bytes
                        a = np.frombuffer(tail[:n*frame_bytes], dtype='<i2').reshape(n, channels).astype(np.float32)
                        b = np.frombuffer(head[:n*frame_bytes], dtype='<i2').reshape(n, channels).astype(np.float32)
                        weight = np.linspace(0, 1, n, dtype=np.float32)[:, None]
                        # Complementary linear gains avoid overshoot for correlated tracks.
                        blend = np.clip(a*(1-weight)+b*weight, -32768, 32767).astype('<i2').tobytes()
                        stream.write(blend[:max(0, target_bytes-stream.tell())])
                    remaining_body = max(0, size - incoming.tell() - (fade_bytes if index < len(tracks)-1 else 0))
                    while remaining_body and stream.tell() < target_bytes:
                        block = incoming.read(min(1024*1024, remaining_body, target_bytes-stream.tell()))
                        if not block:
                            raise ValueError('Truncated decoded audio')
                        stream.write(block)
                        remaining_body -= len(block)
                    tail = incoming.read(fade_bytes) if index < len(tracks)-1 else b''
                decoded.unlink()
            if stream.tell() < target_bytes and tail:
                stream.write(tail[:target_bytes-stream.tell()])
        actual = mixed.stat().st_size / frame_bytes / rate
        if abs(actual-duration) > .1:
            raise ValueError(f'Assembled audio is {actual:.3f}s; expected {duration:.3f}s')
        filters = ['asetpts=N/SR/TB']
        intro_fade, outro_fade = min(intro_fade, actual/2), min(outro_fade, actual/2)
        if intro_fade:
            filters.append(f'afade=t=in:st=0:d={intro_fade}')
        if outro_fade:
            filters.append(f'afade=t=out:st={max(0, actual-outro_fade)}:d={outro_fade}')
        subprocess.run([ffmpeg, '-v', 'error', '-y', '-f', 's16le', '-ar', str(rate), '-ac', str(channels),
                        '-i', str(mixed), '-af', ','.join(filters), '-t', str(actual), '-c:a', 'aac',
                        '-b:a', bitrate, '-f', 'ipod', str(output)], capture_output=True, check=True,
                       timeout=max(180, actual), **no_window_flags())
    if metadata is not None:
        metadata['audio_track_timeline'] = track_timeline
    return normalize_output(output, duration, bitrate, metadata)
