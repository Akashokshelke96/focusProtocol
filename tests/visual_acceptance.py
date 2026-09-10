"""Explicit real renders: python -m pytest tests/visual_acceptance.py -q -s.

Uses the production pipeline with local fallback images and a repeatable seed.
Does not upload. Outputs and measurements stay in jobs/ for visual inspection.
"""
import json
import random
import subprocess
from pathlib import Path

import pytest
from PIL import Image

from app.config.settings import get_settings
from app.pipeline.long_form_jazz_orchestrator import LongFormJazzOrchestrator
from app.utils.ffmpeg import find_ffmpeg


@pytest.mark.parametrize('name,wave,filtered,mark,width,height,minutes', [
    ('filter_on', True, True, True, 1280, 720, 3),
    ('filter_off', True, False, True, 1280, 720, 3),
    ('wave_off', False, True, True, 1280, 720, 3),
    ('mark_off', True, True, False, 1280, 720, 3),
    ('acceptance_10min', True, True, True, 1280, 720, 10),
    ('full_hd', True, True, True, 1920, 1080, 3),
])
def test_real_render(name, wave, filtered, mark, width, height, minutes):
    settings = get_settings().model_copy(update={
        'video_width': width, 'video_height': height, 'video_fps': 15,
        'ffmpeg_preset': 'ultrafast', 'ffmpeg_crf': 28,
        'waveform_enabled': wave, 'waveform_filter_enabled': filtered,
        'watermark_enabled': mark, 'colab_image_enabled': False,
    })
    random.seed(37)
    runner = LongFormJazzOrchestrator(settings)
    assert runner.run(video_count=1, duration_minutes=minutes)
    directory = Path('jobs') / runner.last_job_ids[-1]
    metadata = json.loads((directory / 'metadata.json').read_text())
    video = Path(metadata['video_path'])
    info = runner._probe_media(video)
    assert len(info['streams']) == 2
    v, a = [next(s for s in info['streams'] if s['codec_type'] == kind) for kind in ('video', 'audio')]
    assert (v['width'], v['height']) == (width, height)
    assert v['avg_frame_rate'] == '15/1'
    assert abs(float(v['duration']) - minutes * 60) < .2
    assert abs(float(a['duration']) - minutes * 60) < .2
    assert len(metadata['selected_images']) == 1
    assert 2 <= metadata['music_source_count'] <= 4
    assert metadata['waveform_enabled'] is wave
    assert metadata['watermark_enabled'] is mark
    assert metadata['total_elapsed_seconds'] > 0
    for seconds in (2, 3):
        subprocess.run([str(find_ffmpeg()), '-v', 'error', '-y', '-ss', str(seconds), '-i', str(video), '-frames:v', '1', str(directory / f'frame_{seconds}.png')], check=True)
    if wave:
        bbox = metadata['waveform_visible_bbox']
        assert abs((bbox[2] - bbox[0]) / width - .5) < .01
        assert (bbox[3] - bbox[1]) / height <= .031
        assert metadata['waveform_filter_enabled'] is filtered
        x, y = metadata['waveform_overlay_xy']
        with Image.open(directory / 'frame_2.png') as first, Image.open(directory / 'frame_3.png') as second:
            region = (x, y, x + round(width * .5), y + round(height * .031))
            assert first.crop(region).tobytes() != second.crop(region).tobytes()
    summary = Path('jobs/visual_acceptance_results.json')
    results = json.loads(summary.read_text()) if summary.exists() else {}
    results[name] = {'job': str(directory), 'metadata': metadata, 'streams': info['streams']}
    summary.write_text(json.dumps(results, indent=2))
    print(name, directory, metadata.get('waveform_visible_bbox'), metadata['total_elapsed_seconds'])
