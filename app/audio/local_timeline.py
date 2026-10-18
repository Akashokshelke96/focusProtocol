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
        # Single dynamic pass (was: measure + encode + verify = 3 full runs
        # over the audio). Slightly looser true-peak control, ~3x faster.
        result = subprocess.run([ffmpeg, '-hide_banner', '-nostats', '-y', '-i', str(output),
                                 '-map', '0:a:0', '-af', 'loudnorm=I=-14:TP=-1.5:LRA=11',
                                 '-ar', '48000', '-c:a', 'aac',
                                 '-b:a', bitrate, '-t', str(duration), '-f', 'ipod', str(temporary)],
                                capture_output=True, text=True, check=True,
                                timeout=max(180, duration*2), **no_window_flags())
        if result.returncode != 0:
            raise ValueError('Loudness encode failed')
        info = probe_media(temporary)
        streams = info['streams']
        if len(streams) != 1 or streams[0]['codec_name'] != 'aac' or abs(float(info['format']['duration'])-duration) > 1/48000:
            raise ValueError('Normalized AAC codec or duration changed')
        os.replace(temporary, output)
        metadata.update(loudness_normalized=True, loudness={
            'method': 'single_pass', 'target_i': -14, 'target_tp': -1.5, 'target_lra': 11,
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



def _decode_and_clean(index, track, root, ffmpeg, rate, channels, crossfade,
                      intro_fade, outro_fade, remove_silence, silence_threshold_db,
                      silence_min_seconds, silence_keep_seconds):
    """Decode one track to PCM and strip internal silence. Thread-safe:
    every worker owns its filenames; order is restored by the caller."""
    decoded = root / f'track_{index:03d}.pcm'
    subprocess.run([ffmpeg, '-v', 'error', '-xerror', '-y', '-i', str(track),
                    '-vn', '-ar', str(rate), '-ac', str(channels),
                    '-f', 's16le', str(decoded)], capture_output=True, check=True,
                   timeout=1800, **no_window_flags())
    if remove_silence:
        cleaned = root / f'cleaned_{index:03d}.pcm'
        _remove_internal_silence(
            decoded, cleaned, rate, channels, silence_threshold_db,
            silence_min_seconds, silence_keep_seconds,
            max(6, crossfade, intro_fade, outro_fade),
        )
        if cleaned.exists():
            decoded.unlink()
            cleaned.rename(decoded)
    return decoded


def assemble_tracks_fast(tracks, output, duration, bitrate='320k', metadata=None):
    """Sequential concat without crossfade, fades, silence removal, or loudness.

    Single FFmpeg concat-demuxer encode; tracks play one after another trimmed
    to exactly ``duration`` seconds.
    """
    from app.utils.ffmpeg import probe_media
    from app.config.logging_config import get_logger
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    ffmpeg = str(find_ffmpeg())
    list_path = output.parent / 'concat_list.txt'
    with list_path.open('w', encoding='utf-8') as handle:
        for track in tracks:
            resolved = str(Path(track).resolve()).replace("'", "'\\''")
            handle.write(f"file '{resolved}'\n")
    try:
        subprocess.run([ffmpeg, '-v', 'error', '-y', '-f', 'concat', '-safe', '0',
                        '-i', str(list_path), '-t', str(duration),
                        '-ar', '48000', '-ac', '2', '-c:a', 'aac',
                        '-b:a', bitrate, '-f', 'ipod', str(output)],
                       capture_output=True, check=True,
                       timeout=max(180, duration * 2), **no_window_flags())
    finally:
        list_path.unlink(missing_ok=True)
    info = probe_media(output)
    actual = float(info['format']['duration'])
    if abs(actual - duration) > 5.0:
        raise ValueError(f'Fast-concat audio is {actual:.3f}s; expected {duration:.3f}s')
    track_timeline = []
    cursor = 0.0
    for track in tracks:
        if cursor >= duration:
            break
        try:
            track_duration = float(probe_media(Path(track))['format']['duration'])
        except Exception:
            track_duration = 0.0
        playable = min(track_duration, duration - cursor)
        if playable <= 0:
            continue
        track_timeline.append(dict(filename=Path(track).name, start_seconds=round(cursor, 3),
                                   duration_seconds=round(playable, 3)))
        cursor += playable
    if metadata is not None:
        metadata['audio_track_timeline'] = track_timeline
        metadata['loudness_normalized'] = False
        metadata['audio_processing_mode'] = 'fast_concat'
        metadata['audio_crossfade_enabled'] = False
        metadata['audio_loudness_enabled'] = False
    get_logger('audio.timeline').info('Fast-concat audio assembled: %s tracks, %.1fs', len(track_timeline), actual)
    return output


def assemble_tracks(tracks, output, duration, crossfade=4, bitrate='320k', intro_fade=0, outro_fade=0,
                    remove_silence=True, silence_threshold_db=-52, silence_min_seconds=3,
                    silence_keep_seconds=0.25, metadata=None, decode_workers=4, enable_loudness=True):
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
        # Phase 1 (parallel): decode + silence-clean every track. FFmpeg
        # subprocesses and numpy both release the GIL, so threads scale.
        # Full tracks are decoded; the serial mixer below still trims to
        # the target. Order is restored via executor.map.
        from concurrent.futures import ThreadPoolExecutor
        workers = max(1, min(decode_workers, len(tracks)))
        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix='audio_decode') as pool:
            prepared = list(pool.map(
                lambda item: _decode_and_clean(
                    item[0], item[1], root, ffmpeg, rate, channels, crossfade,
                    intro_fade, outro_fade, remove_silence, silence_threshold_db,
                    silence_min_seconds, silence_keep_seconds),
                list(enumerate(tracks))))
        # Phase 2 (serial): crossfade mix in order. Unchanged logic.
        with mixed.open('wb') as stream:
            for index, decoded in enumerate(prepared):
                remaining = max(0, (target_bytes - stream.tell()) / frame_bytes / rate)
                if remaining <= 0:
                    break
                size = decoded.stat().st_size
                if size < fade_bytes * 2 and index < len(tracks) - 1:
                    raise ValueError('A selected track is too short for the configured crossfade')
                # Observations only: actual cleaned PCM/crossfade boundaries, no audio changes.
                start_seconds = stream.tell() / frame_bytes / rate
                track_timeline.append(dict(filename=Path(tracks[index]).name, start_seconds=start_seconds,
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
    if not enable_loudness:
        if metadata is not None:
            metadata['loudness_normalized'] = False
            metadata['audio_loudness_enabled'] = False
        return output
    return normalize_output(output, duration, bitrate, metadata)
