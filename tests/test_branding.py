import json
from unittest.mock import Mock
from pathlib import Path
import pytest
from PIL import Image
from app.video.branding import session_metadata, brand_image, effect_filter
from app.config.settings import Settings
from app.pipeline.long_form_jazz_orchestrator import LongFormJazzOrchestrator


def test_session_names_repeat_rejected_and_chapters_honest(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    llm = Mock()
    llm._extract_json.return_value = {'titles': [f'Quiet Memory {i}' for i in range(12)]}
    a = session_metadata(llm, 'one', 90)
    b = session_metadata(llm, 'two', 90)
    assert a['session_title_source'] == 'llm'
    assert b['session_title_source'] == 'local_fallback'
    assert not set(a['session_titles']) & set(b['session_titles'])
    assert a['session_chapters'][0]['start_seconds'] == 0
    assert a['session_chapters'][-1]['start_seconds'] == 4950
    assert 'not source song titles' in a['youtube_description']


def test_background_rotation_prefers_primary_and_skips_corrupt(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    folder = tmp_path / 'backgroundImages'; folder.mkdir()
    for i in range(3):
        image = Image.new('RGB', (1920, 1080), (i*60, 30, 40))
        from PIL import ImageDraw
        ImageDraw.Draw(image).rectangle((200,200,1000,800),fill=(100,100,100))
        image.save(folder / f'{i}.png')
    (folder / 'bad.png').write_bytes(b'bad')
    fallback = tmp_path / 'thumbnails'; fallback.mkdir()
    Image.new('RGB', (64,36)).save(fallback / 'other.png')
    engine = LongFormJazzOrchestrator.__new__(LongFormJazzOrchestrator)
    # Even legacy settings enabling external APIs must use local images exclusively.
    engine.settings = Settings(_env_file=None, COLAB_IMAGE_ENABLED=True, POLLINATION_IMAGE_ENABLED=True)
    engine.context = {}; engine._asset_fallbacks=[]; engine.logger=Mock()
    paths=[]
    for i in range(4):
        meta={}
        engine._generate_or_reuse_image({'id':i,'title':'Night','prompt':'Night'},tmp_path/f'out{i}.png','background',meta)
        paths.append(meta['background_source_path'])
    assert len(set(paths[:3])) == 3
    assert paths[2] != paths[3]
    assert all(Path(p).parent == folder for p in paths)


@pytest.mark.parametrize('enabled', [False, True])
def test_brand_panel_toggle(tmp_path, enabled):
    path=tmp_path/'image.png';Image.new('RGB',(1280,720)).save(path)
    settings=Settings(_env_file=None, SONG_PANEL_ENABLED=enabled)
    meta={'session_titles':[f'Evening Memory {i}' for i in range(12)]}
    brand_image(path,settings,meta)
    assert meta['song_panel_enabled'] == enabled
    assert Image.open(path).size == (1280,720)
    assert effect_filter('old_film',0) == ''
    assert 'noise=' in effect_filter('old_film',.12)
