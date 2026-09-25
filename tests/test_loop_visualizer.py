import json
import subprocess
from pathlib import Path

import numpy as np

from app.config.settings import Settings
from app.utils.ffmpeg import find_ffmpeg, find_ffprobe
from app.video.visualizer import animation_frame, prepare_visualizer, add_visualizer


def test_motion_is_periodic_transparent_and_smooth():
    start = np.array(animation_frame(0, 15)).astype(float)
    assert np.array_equal(start, np.array(animation_frame(90, 15)))
    assert not np.array_equal(start, np.array(animation_frame(20, 15)))
    assert start[0, 0, 3] == 0 and start[:, :, 3].max() > 0
    seam = np.abs(start - np.array(animation_frame(89, 15))).mean()
    normal = np.abs(start - np.array(animation_frame(1, 15))).mean()
    assert seam < normal * 2


def test_real_asset_and_cache(tmp_path, monkeypatch):
    settings = Settings(_env_file=None, VISUALIZER_ENABLED=True, VIDEO_FPS=15)
    group = prepare_visualizer(settings, tmp_path)
    info = json.loads(subprocess.check_output([str(find_ffprobe()), '-v', 'error',
        '-show_streams', '-show_format', '-of', 'json', group['path']]))
    assert float(info['format']['duration']) == 6
    assert len(info['streams']) == 1
    assert info['streams'][0]['pix_fmt'] == 'argb'
    assert int(info['streams'][0]['nb_frames']) == 90
    assert (group['width'], group['height'], group['x'], group['bottom']) == (420, 110, 60, 60)
    def forbidden(*args, **kwargs):
        raise AssertionError('Cached animation must not regenerate')
    monkeypatch.setattr('app.video.visualizer.animation_frame', forbidden)
    assert prepare_visualizer(settings, tmp_path) == group
    cmd, filters = [], []
    add_visualizer(cmd, filters, 'base', group, 2, 7)
    assert cmd[:4] == ['-stream_loop', '-1', '-ss', '1']
    assert 'y=H-h-60' in filters[-1]


def test_enabled_loop_preserves_background_and_audio(monkeypatch, tmp_path):
    from app.video.short_loop import render_loop
    settings = Settings(_env_file=None, VISUALIZER_ENABLED=True, STUDIO_MOTION_MODE='static',
                        DUST_ENABLED=False, SUBSCRIBE_OVERLAY_ENABLED=False)
    def probe(path, ffprobe):
        if str(path) == 'audio':
            return {'streams': [{'codec_type': 'audio', 'codec_name': 'aac'}], 'format': {'duration': '1380'}}
        return {'streams': [{'codec_type': 'video', 'width': 1920, 'height': 1080}],
                'format': {'duration': '6' if Path(path).name == 'short_clip.mp4' else '1380'}}
    monkeypatch.setattr('app.video.short_loop.probe', probe)
    monkeypatch.setattr('app.video.short_loop.choose_render_backend', lambda *a: ('ffmpeg', 'libx264', {}))
    monkeypatch.setattr('app.video.visualizer.prepare_visualizer', lambda *a: dict(
        path='waveform.mov', width=420, height=110, x=60, bottom=60, opacity=1))
    commands = []
    monkeypatch.setattr('app.video.short_loop.render_with_progress', lambda cmd, *a: commands.append(cmd))
    metadata = {'target_duration_seconds': 1380}
    render_loop(settings, tmp_path, metadata, 'background', False, 'audio', 'brand', 'ffmpeg', 'ffprobe')
    short, loop, mux = commands
    assert short.count('-i') == 3 and 'waveform.mov' in short
    assert loop[loop.index('-c:v')+1] == 'copy'
    assert mux.count('-i') == 2 and 'waveform.mov' not in mux
    assert mux[mux.index('-c:v')+1] == 'copy'
    assert '-filter_complex' not in mux
    assert mux[mux.index('-c:a')+1] == 'copy'
    assert mux[mux.index('-t')+1] == '1380.0'
    assert metadata['visualizer_enabled'] and not metadata['music_disc_enabled']
