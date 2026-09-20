import subprocess
from unittest.mock import Mock
import numpy as np
import pytest
from app.config.settings import Settings
from app.video.encoding import choose_encoder, encoder_args, _render_with_progress as render_with_progress
from app.video.waveform import draw_waveform, draw_radial


def test_gpu_probe_checks_real_encoder_and_falls_back(monkeypatch):
    settings = Settings(_env_file=None)
    run = Mock(side_effect=[subprocess.CompletedProcess([],1,'','no NVIDIA driver'), subprocess.CompletedProcess([],0,'','')])
    monkeypatch.setattr('app.video.encoding.subprocess.run',run)
    encoder, reasons = choose_encoder('ffmpeg',settings)
    assert encoder == 'h264_amf' and 'h264_nvenc' in reasons
    assert '-frames:v' in run.call_args.args[0]
    run.side_effect = None; run.return_value = subprocess.CompletedProcess([],1,'','no GPU')
    assert choose_encoder('ffmpeg',settings)[0] == 'libx264'
    assert '-crf' not in encoder_args('h264_nvenc',settings)
    assert '-cq' in encoder_args('h264_nvenc',settings)


def test_real_progress_watchdog_and_early_errors(tmp_path):
    from app.utils.ffmpeg import find_ffmpeg
    import json
    ffmpeg = str(find_ffmpeg()); settings = Settings(_env_file=None)
    command = [ffmpeg,'-v','error','-f','lavfi','-i','color=s=128x72:r=15','-t','1','-f','null','-']
    assert render_with_progress(command,tmp_path,5400,settings) > 5400
    assert json.loads((tmp_path/'render_progress.json').read_text())['status'] == 'complete'
    with pytest.raises(RuntimeError, match='FFmpeg exited'):
        render_with_progress([ffmpeg,'-invalid-option'],tmp_path,60,settings)
    assert json.loads((tmp_path/'render_progress.json').read_text())['status'] == 'failed'


def test_stalled_encoder_is_stopped(monkeypatch,tmp_path):
    settings = Settings(_env_file=None, RENDER_STALL_TIMEOUT_SECONDS=30)
    process = Mock();process.poll.return_value=None;process.wait.return_value=-9
    monkeypatch.setattr('app.video.encoding.subprocess.Popen',Mock(return_value=process))
    clock=iter([0,16,32,33])
    monkeypatch.setattr('app.video.encoding.time.monotonic',lambda:next(clock))
    monkeypatch.setattr('app.video.encoding.time.sleep',lambda value:None)
    with pytest.raises(RuntimeError,match='no frame progress'):
        render_with_progress(['ffmpeg'],tmp_path,5400,settings)
    assert process.kill.called


def test_minimum_waveform_remains_visible_without_hiding_dynamics():
    settings=Settings(_env_file=None)
    for draw in (draw_waveform,draw_radial):
        minimum=draw(np.full(32,settings.waveform_min_amplitude),324,324,settings.waveform_bar_width,(0,0,0,230),outline=(255,255,255,100))
        peak=draw(np.ones(32),324,324,settings.waveform_bar_width,(0,0,0,230),outline=(255,255,255,100))
        assert minimum.getbbox() and np.count_nonzero(np.asarray(minimum)[:,:,3]) < np.count_nonzero(np.asarray(peak)[:,:,3])
