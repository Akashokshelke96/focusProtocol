"""One explicitly requested normal pipeline job; excluded from publishing."""
import json
import subprocess
import sys
from pathlib import Path

from app.config.settings import get_settings
from app.pipeline.long_form_jazz_orchestrator import LongFormJazzOrchestrator
from app.studio.assets import verify_job_assets
from app.studio.profiles import Channel
from app.utils.ffmpeg import find_ffmpeg
from app.youtube.state import write_json


def run(minutes, mode='image', resume=None):
    settings = get_settings()
    context = dict(channel=Channel(id='focus-protocol', name='Camping With Blues').model_dump(),
                   content_id='short-loop-acceptance', profile={}, youtube_exclude=True,
                   background_mode=mode, content_plan={'metadata': {
                       'youtube_title': f'Camping With Blues | {minutes} minute render verification',
                       'youtube_description': 'Local pipeline acceptance. Excluded from publishing.',
                       'youtube_tags': ['blues']}})
    engine = LongFormJazzOrchestrator(settings, context=context)
    def forbidden(*args, **kwargs):
        raise AssertionError('Legacy visualizer/segmented renderer must never execute')
    engine._render_video_segmented_legacy = forbidden
    engine._build_segment_command = forbidden
    import app.video.visualizer
    app.video.visualizer.prepare_visualizer = forbidden
    success = engine.resume(resume) if resume else engine.run(video_count=1, duration_minutes=minutes)
    directory = Path('jobs') / (resume or engine.last_job_ids[0])
    metadata = json.loads((directory/'metadata.json').read_text(encoding='utf-8'))
    assert success, metadata.get('render_error')
    verify_job_assets(metadata)
    assert abs(metadata['target_duration_seconds']-minutes*60) < 1
    qc = json.loads((directory/'qc.json').read_text(encoding='utf-8'))
    assert qc['status'] != 'fail', qc
    assert metadata['render_architecture'] == 'short_clip_copy_loop'
    final = Path(metadata['video_path'])
    for offset in [1, minutes*30, minutes*60-1]:
        subprocess.run([str(find_ffmpeg()), '-v', 'error', '-y', '-ss', str(offset), '-i', str(final),
                        '-frames:v', '1', str(directory/f'verify_{offset}.png')], check=True)
    write_json(Path('jobs')/f'short_loop_acceptance_{minutes}.json', dict(job_id=directory.name, metadata=metadata, qc=qc))
    print(json.dumps(dict(job_id=directory.name, render_seconds=metadata['render_elapsed_seconds'],
                         audio_seconds=metadata['audio_elapsed_seconds'], timings=metadata['render_timings'],
                         total_seconds=metadata['total_elapsed_seconds'], video=str(final))), flush=True)


if __name__ == '__main__':
    run(int(sys.argv[1]), sys.argv[2] if len(sys.argv)>2 else 'image', sys.argv[3] if len(sys.argv)>3 else None)
