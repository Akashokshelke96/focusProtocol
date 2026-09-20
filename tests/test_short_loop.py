from pathlib import Path
from unittest.mock import Mock

import pytest

from app.config.settings import Settings
from app.video.short_loop import copy_commands, short_command, render_loop


@pytest.mark.parametrize('seconds', [180, 600, 5400, 7200, 181.5])
def test_long_operations_only_copy_video(seconds):
    loop, mux = copy_commands('ffmpeg', 'short.mp4', 'loop.mp4', 'audio.aac', 'final.mp4', seconds, 'aac')
    for command in (loop, mux):
        assert command[command.index('-c:v')+1] == 'copy'
        assert command[command.index('-t')+1] == str(seconds)
        assert '-vf' not in command and '-filter_complex' not in command
    assert mux[mux.index('-c:a')+1] == 'copy'


@pytest.mark.parametrize('video,motion', [(False, 'static'), (False, 'drift'), (True, 'static')])
def test_short_clip_has_only_background_and_branding(video, motion):
    settings = Settings(_env_file=None, STUDIO_MOTION_MODE=motion)
    cmd = short_command('ffmpeg', settings, 'background', video, 'branding.png', 'short.mp4', 4)
    assert cmd.count('-i') == 2
    assert '-an' in cmd
    assert cmd[cmd.index('-frames:v')+1] == str(4*settings.video_fps)
    graph = cmd[cmd.index('-filter_complex')+1]
    assert graph.count('overlay=') == 1
    assert not any(word in graph for word in ('fade=', 'waveform', 'soundwave', 'subscribe'))
    if video:
        assert 'reverse' in graph and 'trim=end_frame' in graph


def test_incomplete_audio_stops_before_encoder(monkeypatch, tmp_path):
    monkeypatch.setattr('app.video.short_loop.probe', lambda *a: {
        'streams': [{'codec_type': 'audio', 'codec_name': 'aac'}], 'format': {'duration': '10'}})
    encode = Mock(side_effect=AssertionError('Must not start video'))
    monkeypatch.setattr('app.video.short_loop.choose_render_backend', encode)
    with pytest.raises(ValueError, match='Complete target-length audio'):
        render_loop(Settings(_env_file=None), tmp_path, {'target_duration_seconds':180},
                    Path('background'), False, Path('audio'), Path('brand'), 'ffmpeg', 'ffprobe')
    encode.assert_not_called()


def test_failed_short_encode_never_loops(monkeypatch, tmp_path):
    monkeypatch.setattr('app.video.short_loop.probe', lambda *a: {
        'streams': [{'codec_type': 'audio', 'codec_name': 'aac'}], 'format': {'duration': '180'}})
    monkeypatch.setattr('app.video.short_loop.choose_render_backend', lambda *a: ('ffmpeg','libx264',{}))
    run = Mock(side_effect=RuntimeError('encoder failure'))
    monkeypatch.setattr('app.video.short_loop.render_with_progress', run)
    with pytest.raises(RuntimeError, match='encoder failure'):
        render_loop(Settings(_env_file=None), tmp_path, {'target_duration_seconds':180},
                    Path('background'), False, Path('audio'), Path('brand'), 'ffmpeg', 'ffprobe')
    assert run.call_count == 1


def test_production_ignores_legacy_overlays(monkeypatch, tmp_path):
    from types import SimpleNamespace
    from app.pipeline.long_form_jazz_orchestrator import LongFormJazzOrchestrator
    engine = LongFormJazzOrchestrator.__new__(LongFormJazzOrchestrator)
    engine.settings = Settings(_env_file=None, VISUALIZER_ENABLED=True, WAVEFORM_ENABLED=True,
                               SUBSCRIBE_OVERLAY_ENABLED=True)
    engine.logger = Mock()
    engine.timeline_builder = SimpleNamespace(clips=[SimpleNamespace(asset_path='background.png', asset_type='image')])
    forbidden = Mock(side_effect=AssertionError('Inactive legacy path'))
    monkeypatch.setattr('app.video.visualizer.prepare_visualizer', forbidden)
    monkeypatch.setattr('app.video.waveform.create_waveform', forbidden)
    monkeypatch.setattr(engine, '_render_video_segmented_legacy', forbidden)
    monkeypatch.setattr('app.video.short_loop.render_loop', lambda *a: tmp_path/'final.mp4')
    data = {"render_timings": {}}
    assert engine._render_video(tmp_path, data, tmp_path/'audio.aac') == tmp_path/'final.mp4'
    assert data['visualization_config']['visualizer_enabled'] is True
    assert not data['waveform_enabled'] and not data['subscribe_overlay_enabled']
    assert len(data['branding_regions']) == 2
    forbidden.assert_not_called()
