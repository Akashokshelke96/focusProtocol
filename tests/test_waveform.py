import numpy as np
import pytest
from PIL import Image
from app.config.settings import Settings
from app.video.waveform import draw_waveform, process_amplitudes


def test_thin_waveform_geometry_and_alpha():
    image = draw_waveform(np.linspace(0, 1, 160), 960, 32, 1, (255, 255, 255, 140))
    assert image.getchannel("A").getbbox() == (0, 1, 960, 31)
    pixels = np.asarray(image)
    assert np.count_nonzero(pixels[:, :, 3].max(axis=0)) == 160
    assert set(np.unique(pixels[:, :, 3])) == {0, 140}
    assert np.all(pixels[pixels[:, :, 3] > 0, :3] == 255)


def test_filter_reduces_spikes_and_temporal_changes():
    raw = np.array([0., 0., 1., 0., 0.])
    filtered = process_amplitudes(raw, np.zeros(5), True)
    assert filtered.max() < raw.max()
    assert filtered[1] > 0
    assert np.array_equal(process_amplitudes(raw, np.zeros(5), False), raw)
    assert np.all(process_amplitudes(np.zeros(5), filtered, True) < filtered + 1e-10)


def test_silence_and_overload_stay_bounded():
    for filtered in (True, False):
        values = process_amplitudes(np.zeros(160), np.zeros(160), filtered)
        assert not values.any()
        assert draw_waveform(values, 960, 32, 1, (255, 255, 255, 140)).getbbox()[3] - 15 == 1
        values = process_amplitudes(np.full(160, 100), np.zeros(160), filtered)
        assert np.all((values >= 0) & (values <= 1))


def test_api_overrides_are_isolated(monkeypatch):
    from app.api import jazz_api
    baseline = Settings(_env_file=None)
    captured = []
    monkeypatch.setattr(jazz_api, "get_settings", lambda: baseline)
    monkeypatch.setattr(jazz_api, "current_job", None)
    from app.studio.api import service
    monkeypatch.setattr(service.store, 'read', lambda: {'content': []})
    monkeypatch.setattr(jazz_api, "LongFormJazzOrchestrator", lambda settings: captured.append(settings))
    class Thread:
        def __init__(self, **kwargs): pass
        def start(self): pass
        def is_alive(self): return False
    monkeypatch.setattr(jazz_api.threading, "Thread", Thread)
    client = jazz_api.app.test_client()
    response = client.post('/api/jazz/generate', json={"waveform_enabled": False, "waveform_filter_enabled": False, "watermark_enabled": False})
    assert response.status_code == 202
    assert not captured[-1].waveform_enabled
    assert not captured[-1].waveform_filter_enabled
    assert not captured[-1].watermark_enabled
    assert baseline.waveform_enabled
    assert client.post('/api/jazz/generate', json={}).status_code == 202
    assert captured[-1].waveform_enabled
    assert client.post('/api/jazz/generate', json={"waveform_enabled": "false"}).status_code == 400


def test_dashboard_controls():
    from app.api.jazz_api import app
    with app.test_request_context():
        from flask import render_template
        html = render_template('jazz_dashboard.html', settings=Settings(_env_file=None))
    for control in ('waveform-enabled', 'waveform-filter-enabled', 'watermark-enabled', 'subscribe-overlay-enabled'):
        assert f'id="{control}"' in html
        assert f"getElementById('{control}').checked" in html
