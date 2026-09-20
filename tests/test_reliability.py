import json
import os
from pathlib import Path
from unittest.mock import Mock
import pytest
import psutil
from app.config.settings import Settings
from app.studio.service import StudioService
from app.studio.content import create_plan
from app.studio.profiles import DEFAULT_PROFILES
from app.studio.recovery import reconcile
from app.youtube.state import write_json, publishing_lock


@pytest.fixture
def studio(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    settings = Settings(_env_file=None, DATABASE_PATH=str(tmp_path/'jobs/registry.db'))
    monkeypatch.setattr('app.studio.service.get_settings', lambda: settings)
    monkeypatch.setattr('app.config.settings.get_settings', lambda: settings)
    return StudioService(tmp_path/'jobs')


@pytest.mark.parametrize('count', [1, 3, 20, 100])
def test_automatic_queue_count_restart_and_idempotency(studio, count):
    rows = studio.create_videos('focus-protocol', count, 'request-unique')
    assert len({r['job_id'] for r in rows}) == count
    assert all(r['stage'] == 'planned' and r['automatic'] for r in rows)
    assert len(studio.create_videos('focus-protocol', count, 'request-unique')) == count
    assert len(StudioService(studio.root).store.read()['content']) == count
    with pytest.raises(ValueError):
        studio.create_videos('focus-protocol', count, 'request-unique', 10)
    assert not studio.store.read()['paused']
    assert studio.snapshot()['counts']['planned'] == count


def test_twenty_requests_consumed_one_per_tick(studio, monkeypatch):
    studio.create_videos('focus-protocol', 20, 'request-many')
    running = []
    def generate(item, channel, state):
        running.append(item['job_id'])
        with studio.store.transaction() as latest:
            next(c for c in latest['content'] if c['id'] == item['id'])['stage'] = 'ready'
    monkeypatch.setattr(studio, '_generate', generate)
    for index in range(20):
        studio.tick()
        assert len(running) == index + 1
    assert len(set(running)) == 20


def test_channel_snapshot_and_distinct_fallback(studio):
    profile = DEFAULT_PROFILES[2].model_dump()
    with studio.store.transaction() as state:
        state['channels'][0].update(name='Girls Music', profile_id=profile['id'])
    rows = studio.create_videos('focus-protocol', 20, 'snapshot-request')
    history = []
    llm = Mock(); llm._generate_with_retry.side_effect = RuntimeError('offline')
    for _ in range(20):
        plan = create_plan(llm, profile, rows[0]['channel_snapshot'], 3, history)
        history.append(plan['concept'])
        assert 'jazz' not in json.dumps(plan).lower()
        assert plan['source'] == 'local_fallback' and plan['provider_error'] == 'offline'
        assert len(plan['scene_structure']) == 1 and plan['narration'] is None
    assert len(set(history)) == 20
    with studio.store.transaction() as state:
        state['channels'][0]['profile_id'] = 'jazz'
    assert studio.store.read()['content'][0]['profile_snapshot']['id'] == 'dreamy'


def manifest(studio, name='orphan', **metadata):
    directory = studio.root/name
    write_json(directory/'job.json', dict(id=name,status='running',stage='VIDEO_RENDERING',metadata=metadata,created_at='2026-09-14T00:00:00'))
    return directory


def test_recovery_never_marks_partial_output_ready(studio):
    directory = manifest(studio)
    (directory/'output').mkdir()
    (directory/'output/rendering.mp4').write_bytes(b'partial')
    reconcile(studio)
    assert json.loads((directory/'job.json').read_text())['status'] == 'interrupted'


def test_recovery_does_not_race_live_owner_or_lock(studio):
    directory = manifest(studio)
    write_json(directory/'render_progress.json', dict(status='running', owner=dict(pid=os.getpid(), created=psutil.Process().create_time())))
    reconcile(studio)
    assert json.loads((directory/'job.json').read_text())['status'] == 'running'
    other = manifest(studio, 'locked')
    with publishing_lock(studio.root/'generation'):
        reconcile(studio)
    assert json.loads((other/'job.json').read_text())['status'] == 'running'


def test_recovery_runs_qc_before_completion(studio, monkeypatch):
    directory = manifest(studio)
    video = directory/'final.mp4'; video.write_bytes(b'fixture')
    write_json(directory/'metadata.json', dict(video_path=str(video), youtube_title='Night',youtube_description='Quiet'))
    write_json(directory/'render_progress.json', dict(status='complete'))
    qc = Mock(return_value=dict(status='pass', checks=[]))
    monkeypatch.setattr('app.studio.recovery.qc_job', qc)
    reconcile(studio)
    assert qc.call_count == 1
    assert json.loads((directory/'job.json').read_text())['status'] == 'completed'
    reconcile(StudioService(studio.root))
    assert qc.call_count == 1


def test_recovery_validation_failure_is_visible(studio, monkeypatch):
    directory = manifest(studio)
    video = directory/'final.mp4'; video.write_bytes(b'fixture')
    write_json(directory/'metadata.json', dict(video_path=str(video)))
    write_json(directory/'render_progress.json', dict(status='complete'))
    monkeypatch.setattr('app.studio.recovery.qc_job', lambda *a:dict(status='fail',checks=[dict(status='fail',name='Decode')]))
    reconcile(studio)
    saved = json.loads((directory/'job.json').read_text())
    assert saved['status'] == 'failed' and 'Decode' in saved['error_message']


def test_api_create_videos_is_quick_and_replay_safe(studio, monkeypatch):
    from app.api.jazz_api import app
    monkeypatch.setattr('app.studio.api.service', studio)
    client = app.test_client()
    request = dict(channel_id='focus-protocol', count=3, request_id='http-request')
    response = client.post('/api/studio/create-videos', json=request)
    assert response.status_code == 202 and len(response.json['items']) == 3
    assert client.post('/api/studio/create-videos', json=request).json == response.json
    assert client.post('/api/studio/create-videos', json={**request,'count':101}).status_code == 400


def test_cpu_pressure_reduces_only_owned_process(studio, monkeypatch):
    from app.video.resources import ResourceMonitor
    process = Mock()
    process.memory_info.return_value.rss = 100*2**20
    process.cpu_percent.return_value = 150
    monkeypatch.setattr('app.video.resources.psutil.Process', lambda pid:process)
    limit = Mock(return_value=True)
    monkeypatch.setattr('app.video.resources.constrain', limit)
    monkeypatch.setattr('app.video.resources.gpu_sample', lambda:{})
    monkeypatch.setattr('app.video.resources.psutil.cpu_percent', lambda:95)
    monkeypatch.setattr('app.video.resources.psutil.virtual_memory', lambda:Mock(percent=80,available=2**30))
    tick = iter([1,1,40,40])
    monkeypatch.setattr('app.video.resources.time.monotonic', lambda:next(tick))
    monitor = ResourceMonitor(123, Settings(_env_file=None))
    monitor.sample(); monitor.sample()
    assert monitor.throttled and limit.call_args.args == (process,1)


def test_worker_failure_and_retry_keep_job_identity_and_plan(studio, monkeypatch):
    import app.studio.service as module
    from app.pipeline.long_form_jazz_orchestrator import LongFormJazzOrchestrator
    from app.jobs.manager import JobManager
    from app.api import jazz_api
    monkeypatch.setattr(jazz_api, 'generation_thread', None)
    monkeypatch.setattr('app.video.resources.gpu_sample', lambda:{})
    monkeypatch.setattr('psutil.virtual_memory', lambda:Mock(percent=50))
    item = studio.create_videos('focus-protocol',1,'retry-request')[0]
    plan = dict(concept='The Quiet Observatory', metadata={}, source='llm')
    planner = Mock(return_value=plan)
    monkeypatch.setattr('app.studio.content.create_plan', planner)
    monkeypatch.setattr('app.llm.gemini.GeminiProvider', Mock())
    identities = []
    class Engine:
        def __init__(self, settings, context):
            self.context=context
        def run(self, **kwargs):
            identities.append(self.context['job_id'])
            write_json(studio.root/self.context['job_id']/'job.json',dict(id=self.context['job_id'],status='failed',stage='VIDEO_RENDERING',error_message='Injected encoder failure'))
            return False
        def resume(self, job_id):
            identities.append(job_id)
            write_json(studio.root/job_id/'job.json',dict(id=job_id,status='completed',stage='VALIDATE_OUTPUT'))
            return True
    monkeypatch.setattr('app.pipeline.long_form_jazz_orchestrator.LongFormJazzOrchestrator',Engine)
    monkeypatch.setattr(studio,'qc',lambda job_id:{'status':'pass'})
    studio.tick()
    saved = studio.store.read()['content'][0]
    assert saved['stage']=='failed' and 'Injected' in saved['error']
    studio.plan([item['id']]); studio.tick()
    assert studio.store.read()['content'][0]['stage']=='ready'
    assert identities == [item['job_id'],item['job_id']]
    assert planner.call_count == 1


def test_silence_removal_uses_bounded_disk_backed_samples(tmp_path):
    import numpy as np
    from app.audio.local_timeline import _remove_internal_silence
    rate=8000
    values=np.ones((rate*24,2),dtype='<i2')*3000
    values[rate*9:rate*15]=0
    source=tmp_path/'in.pcm'; target=tmp_path/'out.pcm'
    values.tofile(source)
    removed=_remove_internal_silence(source,target,rate,2,-52,3,.25,6)
    assert removed==5
    assert target.stat().st_size==int((24-5.5)*rate*4)
    # Deletion works on Windows too: no outstanding mmap holds the source open.
    source.unlink()


def test_resume_rerenders_saved_media_without_reselection(studio):
    from types import SimpleNamespace
    from app.pipeline.long_form_jazz_orchestrator import LongFormJazzOrchestrator
    directory=studio.root/'retry'
    directory.mkdir(parents=True)
    audio=directory/'audio.aac'; audio.write_bytes(b'prepared')
    image=directory/'background.png'; image.write_bytes(b'prepared')
    metadata=dict(audio_path=str(audio),generated_background_path=str(image),target_duration_seconds=180,
                  started_at='2026-09-14T01:00:00+00:00', render_config={'video_fps':30})
    write_json(directory/'job.json',dict(status='failed',metadata=metadata))
    write_json(directory/'render_progress.json',dict(status='failed'))
    engine=object.__new__(LongFormJazzOrchestrator)
    job=SimpleNamespace(status='failed',duration_minutes=3)
    engine.job_manager=Mock(); engine.job_manager.get_job.return_value=job
    engine.settings=Settings(_env_file=None)
    engine.timeline_builder=SimpleNamespace(clips=[],add_clip=Mock())
    engine._render_video=Mock(return_value=directory/'rendered.mp4')
    engine._finish_video=Mock(return_value=True)
    engine._run_batch=Mock(side_effect=AssertionError('Must not regenerate sources'))
    assert engine.resume('retry')
    engine._render_video.assert_called_once()
    assert engine._render_video.call_args.args[2]==audio
    assert engine.settings.video_fps==30
    assert audio.exists() and image.exists()


def test_cancel_signals_only_the_selected_worker(studio, monkeypatch):
    from app.api import jazz_api
    worker=Mock(last_job_ids=['owned-job'],cancel_requested=False)
    monkeypatch.setattr(jazz_api,'active_orchestrator',worker)
    monkeypatch.setattr(jazz_api,'current_job',dict(status='running'))
    subprocess_call=Mock(side_effect=AssertionError('Cancellation must never kill all FFmpeg processes'))
    monkeypatch.setattr(jazz_api.subprocess,'run',subprocess_call)
    response=jazz_api.app.test_client().post('/api/jazz/cancel',json={})
    assert response.status_code==202
    assert worker.cancel_requested
    assert (Path('jobs/owned-job/cancel.request')).is_file()
    subprocess_call.assert_not_called()
