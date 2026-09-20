"""Requested local 23-minute acceptance through the production pipeline."""
import json
from pathlib import Path

from app.config.settings import get_settings
from app.pipeline.long_form_jazz_orchestrator import LongFormJazzOrchestrator
from app.studio.assets import verify_job_assets
from app.studio.profiles import Channel
from app.youtube.state import write_json


def run():
    settings = get_settings().model_copy(update=dict(visualizer_enabled=True,
        video_width=1920, video_height=1080, youtube_upload_enabled=False))
    context = dict(channel=Channel(id='focus-protocol', name='Camping With Blues').model_dump(),
                   content_id='loop-visualizer-acceptance', profile={}, youtube_exclude=True,
                   background_mode='image', content_plan={'metadata': {
                       'youtube_title': 'Camping With Blues | 23 minute waveform verification',
                       'youtube_description': 'Local acceptance. Excluded from publishing.',
                       'youtube_tags': ['blues']}})
    engine = LongFormJazzOrchestrator(settings, context=context)
    def forbidden(*args, **kwargs):
        raise AssertionError('Old audio-reactive waveform path must never execute')
    engine._render_video_segmented_legacy = forbidden
    engine._create_waveform_asset = forbidden
    engine._try_astrofox_render = forbidden
    import app.video.waveform
    app.video.waveform.create_waveform = forbidden
    success = engine.run(video_count=1, duration_minutes=23)
    directory = Path('jobs') / engine.last_job_ids[0]
    write_json(Path('jobs/loop_visualizer_acceptance.json'), dict(job_id=directory.name, success=success))
    metadata = json.loads((directory/'metadata.json').read_text(encoding='utf-8'))
    assert success, metadata.get('render_error')
    verify_job_assets(metadata)
    assert metadata['visualizer_enabled'] and not metadata['waveform_enabled']
    assert not metadata['music_disc_enabled']
    assert metadata['target_duration_seconds'] == 1380
    print(json.dumps(dict(job_id=directory.name, video=metadata['video_path'],
        render_seconds=metadata['render_elapsed_seconds'], total_seconds=metadata['total_elapsed_seconds'])), flush=True)


if __name__ == '__main__':
    run()
