from pathlib import Path
from unittest.mock import Mock
import pytest
from PIL import Image
from app.pipeline.long_form_jazz_orchestrator import LongFormJazzOrchestrator
from app.studio.assets import asset_sha256, verify_job_assets


def test_assignment_copy_resume_and_tamper(tmp_path, monkeypatch):
    backgrounds, thumbnails = tmp_path/'backgrounds', tmp_path/'thumbs'
    backgrounds.mkdir(); thumbnails.mkdir()
    for folder in (backgrounds, thumbnails):
        for i in range(2):
            Image.new('RGB', (800, 450), (i*100, 70, 25)).save(folder/f'{i}.jpg')
        (folder/'broken.png').write_bytes(b'not an image')
    engine = LongFormJazzOrchestrator.__new__(LongFormJazzOrchestrator)
    engine.context = {'channel': {'background_dir': str(backgrounds), 'thumbnail_dir': str(thumbnails)}}
    engine._generate_or_reuse_image = Mock(side_effect=AssertionError('AI must never run'))
    directory = tmp_path/'job'; directory.mkdir()
    metadata = {}
    engine._prepare_prompt_assets(None, directory, metadata)
    assert set(metadata['assets']) == {'background', 'thumbnail'}
    for asset in metadata['assets'].values():
        assert asset_sha256(asset['source']) == asset_sha256(asset['path']) == asset['sha256']
        assert Path(asset['path']).suffix == '.jpg'
    monkeypatch.setattr('random.choice', Mock(side_effect=AssertionError('Reselection on retry')))
    resumed = {}
    engine._prepare_prompt_assets(None, directory, resumed)
    assert resumed['assets'] == metadata['assets']
    Path(metadata['assets']['thumbnail']['path']).write_bytes(b'changed')
    with pytest.raises(ValueError, match='missing or changed'):
        verify_job_assets(metadata)


def test_preview_uses_assignment_over_stale_youtube_path(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from app.api.jazz_api import app
    import app.studio.api as api
    monkeypatch.chdir(tmp_path)
    directory = tmp_path/'jobs'/'test'; directory.mkdir(parents=True)
    original = directory/'thumbnail.jpg'
    Image.new('RGB',(800,450),'red').save(original)
    stale = directory/'stale.jpg'
    Image.new('RGB',(800,450),'blue').save(stale)
    row = dict(metadata={'assets': {'thumbnail': {'path': str(original)}}},
               youtube={'thumbnail_path': str(stale)})
    monkeypatch.setattr(api, 'service', SimpleNamespace(job=lambda _:row,
        store=SimpleNamespace(read=lambda:{'channels':[]})))
    result = app.test_client().get('/api/studio/jobs/test/asset/thumbnail')
    assert result.status_code == 200
    assert result.data == original.read_bytes()
    assert result.data != stale.read_bytes()


def test_interrupted_copy_keeps_both_assignments(tmp_path, monkeypatch):
    import app.studio.assets as helpers
    folder = tmp_path/'sources'; folder.mkdir()
    Image.new('RGB',(800,450),'green').save(folder/'original.jpg')
    engine = LongFormJazzOrchestrator.__new__(LongFormJazzOrchestrator)
    engine.context = {'channel': {'background_dir':str(folder),'thumbnail_dir':str(folder)}}
    directory = tmp_path/'job'; directory.mkdir()
    original_copy = helpers.copy_thumbnail
    monkeypatch.setattr(helpers, 'copy_thumbnail', Mock(side_effect=OSError('interrupted')))
    with pytest.raises(OSError):
        engine._prepare_prompt_assets(None,directory,{})
    assert (directory/'prompt_assets.json').is_file()
    monkeypatch.setattr(helpers, 'copy_thumbnail', original_copy)
    monkeypatch.setattr('random.choice', Mock(side_effect=AssertionError('Must reuse saved assignment')))
    metadata = {}
    engine._prepare_prompt_assets(None,directory,metadata)
    verify_job_assets(metadata)


def test_qc_surfaces_tampered_copy_as_named_fail(tmp_path):
    from app.studio.assets import qc_job
    folder = tmp_path/'sources'; folder.mkdir()
    Image.new('RGB', (1280, 720), 'green').save(folder/'original.png')
    engine = LongFormJazzOrchestrator.__new__(LongFormJazzOrchestrator)
    engine.context = {'channel': {'background_dir': str(folder), 'thumbnail_dir': str(folder)}}
    directory = tmp_path/'job'; directory.mkdir()
    metadata = {}
    engine._prepare_prompt_assets(None, directory, metadata)
    Path(metadata['assets']['thumbnail']['path']).write_bytes(b'edited')
    row = dict(video_path=str(directory/'missing.mp4'),
               thumbnail_path=metadata['assets']['thumbnail']['path'])
    result = qc_job(directory, row, metadata)
    assert result['status'] == 'fail'
    integrity = next(c for c in result['checks'] if c['name'] == 'Original asset SHA-256 integrity')
    assert integrity['status'] == 'fail'


def test_validate_output_rejects_background_mismatch(tmp_path, monkeypatch):
    from types import SimpleNamespace
    folder = tmp_path/'sources'; folder.mkdir()
    Image.new('RGB', (1920, 1080), 'green').save(folder/'original.jpg')
    engine = LongFormJazzOrchestrator.__new__(LongFormJazzOrchestrator)
    engine.context = {'channel': {'background_dir': str(folder), 'thumbnail_dir': str(folder)}}
    engine.logger = Mock()
    engine.settings = SimpleNamespace(video_width=1920, video_height=1080,
                                      audio_duration_tolerance_seconds=5, waveform_enabled=False)
    directory = tmp_path/'job'; directory.mkdir()
    metadata = {'target_duration_seconds': 60, 'selected_images': ['background.jpg']}
    engine._prepare_prompt_assets(None, directory, metadata)
    video, audio = directory/'v.mp4', directory/'a.aac'
    video.write_bytes(b'0' * 1024); audio.write_bytes(b'1' * 1024)
    monkeypatch.setattr(engine, '_probe_media',
                        lambda p: {'streams': [{'codec_type': 'video', 'width': 1920, 'height': 1080},
                                              {'codec_type': 'audio'}], 'format': {'duration': '60.0'}})
    monkeypatch.setattr(engine, '_probe_duration', lambda p: 60.0)
    assert engine._validate_output(directory, video, audio, metadata) is True
    Path(metadata['assets']['background']['path']).write_bytes(b'tampered')
    assert engine._validate_output(directory, video, audio, metadata) is False


def test_generate_reverts_to_planned_when_legacy_busy(tmp_path, monkeypatch):
    import contextlib
    from unittest.mock import MagicMock
    from app.studio import service as service_module
    service = service_module.StudioService.__new__(service_module.StudioService)
    service.root = tmp_path
    item = dict(id='c1', channel_id='ch1')
    state = {'content': [dict(id='c1', stage='generating', job_id='job1', attempts=1)]}
    store = MagicMock()
    store.transaction.return_value = contextlib.contextmanager(lambda: iter([state]))()
    service.store = store
    monkeypatch.setattr(service_module, 'publishing_lock', lambda *a, **k: contextlib.nullcontext())
    fake_api = MagicMock()
    fake_api.generation_thread.is_alive.return_value = True
    monkeypatch.setitem(__import__('sys').modules, 'app.api.jazz_api', fake_api)
    monkeypatch.setattr('app.api.jazz_api', fake_api, raising=False)
    service._generate(dict(item), {}, state)
    assert state['content'][0]['stage'] == 'planned'


def test_render_queue_cancels_without_starting_ffmpeg(tmp_path, monkeypatch):
    from app.video.encoding import render_with_progress
    from app.config.settings import Settings
    (tmp_path/'cancel.request').touch()
    run = Mock(side_effect=AssertionError('Cancelled work must not start'))
    monkeypatch.setattr('app.video.encoding._render_with_progress',run)
    with pytest.raises(RuntimeError,match='Cancelled'):
        render_with_progress(['ffmpeg'],tmp_path,600,Settings(_env_file=None))


def test_render_slot_capacity(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from app.video.encoding import render_with_progress
    from app.youtube.state import publishing_lock
    from app.config.settings import Settings
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr('psutil.virtual_memory',lambda:SimpleNamespace(percent=20))
    monkeypatch.setattr('app.video.resources.gpu_sample',lambda:{})
    run = Mock(return_value=123)
    monkeypatch.setattr('app.video.encoding._render_with_progress',run)
    with publishing_lock(Path('jobs/render_slots/0')):
        assert render_with_progress(['ffmpeg'],tmp_path,600,Settings(_env_file=None,RENDER_MAX_CONCURRENT=2))==123
    run.assert_called_once()


def test_upload_sends_original_bytes_and_rejects_tampering(tmp_path):
    from app.youtube.lifecycle import finish
    from app.config.settings import Settings
    source = tmp_path/'source.png'
    Image.new('RGB',(800,450),'green').save(source)
    engine = LongFormJazzOrchestrator.__new__(LongFormJazzOrchestrator)
    engine.context = {'channel': {'background_dir':str(tmp_path),'thumbnail_dir':str(tmp_path)}}
    directory = tmp_path/'job'; directory.mkdir()
    metadata = {}
    engine._prepare_prompt_assets(None,directory,metadata)
    row = dict(metadata, youtube_video_id='existing',title='Test',description='',tags=[])
    service = Mock()
    service.video_details.return_value = dict(processingDetails={'processingStatus':'succeeded'},
        snippet={'title':'Test','description':'','tags':[]},status={'privacyStatus':'private'})
    sent = []
    service.upload_thumbnail.side_effect = lambda video, path:sent.append(Path(path).read_bytes())
    finish(service,Settings(_env_file=None),row,lambda _:None)
    assert sent == [source.read_bytes()]
    assert row['thumbnail_uploaded']
    row['thumbnail_uploaded'] = False
    Path(row['thumbnail_path']).write_bytes(b'edited')
    finish(service,Settings(_env_file=None),row,lambda _:None)
    assert row['youtube_status'] == 'thumbnail_retry'
    assert len(sent) == 1
