"""Real 1080p acceptance, using a saved package and excluding publishing."""
import json
from pathlib import Path
from app.config.settings import get_settings
from app.pipeline.long_form_jazz_orchestrator import LongFormJazzOrchestrator
from app.studio.store import StudioStore

root = Path('jobs/editorial_acceptance')
state = StudioStore().read()
channel = next(c for c in state['channels'] if c['id'] == 'focus-protocol')
profile = next(p for p in state['profiles'] if p['id'] == channel['profile_id'])
plan = json.loads((root / 'plan_1.json').read_text(encoding='utf-8'))
settings = get_settings().model_copy(update=dict(subscribe_overlay_enabled=False))
assert (settings.video_width, settings.video_height) == (1920, 1080)
reports = []
for minutes in (3, 10):
    context = dict(channel=channel, profile=profile, concept=plan['concept'], content_plan=plan,
                   youtube_exclude=True, content_id=f'editorial-acceptance-{minutes}', background_mode='image')
    engine = LongFormJazzOrchestrator(settings, context=context)
    success = engine.run(video_count=1, duration_minutes=minutes)
    folder = Path('jobs') / engine.last_job_ids[0]
    metadata = json.loads((folder / 'metadata.json').read_text(encoding='utf-8'))
    assert success, metadata.get('render_error')
    qc = json.loads((folder / 'qc.json').read_text(encoding='utf-8'))
    assert qc['status'] == 'pass', qc
    commands = json.loads((folder / 'output/render_commands.json').read_text())
    for stage in ('loop', 'mux'):
        assert commands[stage][commands[stage].index('-c:v') + 1] == 'copy'
    assert metadata['metadata_version'] == 2
    assert metadata['session_chapters']
    assert [t['start_seconds'] for t in metadata['session_chapters']] == [t['start_seconds'] for t in metadata['audio_track_timeline']]
    assert len(metadata['youtube_description'].encode('utf-8')) <= 5000
    report = dict(job_id=folder.name, qc=qc['status'], requested_minutes=minutes,
                  duration=metadata['video_duration_seconds'], render_config=metadata['render_config'],
                  chapters=metadata['session_chapters'], source=metadata['metadata_source'],
                  elapsed=metadata['total_elapsed_seconds'], loudness=metadata.get('loudness'),
                  timings=metadata['render_timings'])
    reports.append(report)
    (root / 'pipeline.json').write_text(json.dumps(reports, indent=2), encoding='utf-8')
    print(json.dumps(report), flush=True)
