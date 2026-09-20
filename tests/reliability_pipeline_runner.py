"""Real ten-minute automatic request through the studio coordinator, without publishing."""
import json
from pathlib import Path
from app.config.settings import get_settings
from app.studio.store import StudioStore
from app.studio.service import StudioService
from app.youtube.state import write_json


def main():
    import app.studio.service as module
    settings = get_settings().model_copy(update={'video_fps':30})
    module.get_settings = lambda:settings
    store = StudioStore('jobs/reliability_acceptance_store')
    with store.transaction() as state:
        state['channels'][0].update(name='Dreamy Acceptance', profile_id='dreamy', duration_minutes=10,
            waveform_style='circular', motion_mode='drift', subscribe_enabled=True, auto_generate=False, auto_publish=False)
    service = StudioService('jobs', store=store)
    rows = service.create_videos('focus-protocol', 1, 'acceptance-automatic-ten-minute-v1', 10)
    service.tick()
    row = next(c for c in store.read()['content'] if c['id']==rows[0]['id'])
    print(json.dumps(row,indent=2),flush=True)
    job = service.job(row['job_id'])
    metadata = job['metadata']
    metadata['youtube_exclude'] = True
    write_json(Path('jobs')/row['job_id']/'metadata.json',metadata)
    write_json(Path('jobs/reliability_acceptance_store')/'result.json', dict(job_id=row['job_id'], stage=job['stage'], qc=job['qc'], metadata=metadata))
    assert job['stage']=='ready_to_publish', job.get('error') or row.get('error')
    assert metadata['video_encoder']=='h264_nvenc'
    assert metadata['waveform_style']=='circular'
    assert metadata['target_duration_seconds'] >= 599
    assert 'jazz' not in metadata['youtube_title'].lower()


if __name__ == '__main__':
    main()
