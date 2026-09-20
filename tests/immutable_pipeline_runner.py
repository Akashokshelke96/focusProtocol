import json, sys
from pathlib import Path
from app.config.settings import get_settings
from app.pipeline.long_form_jazz_orchestrator import LongFormJazzOrchestrator
from app.youtube.state import write_json
from app.studio.assets import verify_job_assets

minutes = int(sys.argv[1])
settings = get_settings().model_copy(update=dict(video_width=1920, video_height=1080, video_fps=30))
engine = LongFormJazzOrchestrator(settings)
# Keep acceptance artifacts out of the publication queue from creation onward.
original = engine._prepare_prompt_assets
def prepare(pair, directory, metadata):
    metadata['youtube_exclude'] = True
    return original(pair, directory, metadata)
engine._prepare_prompt_assets = prepare
success = engine.run(video_count=1, duration_minutes=minutes)
folder = Path('jobs') / engine.last_job_ids[0]
metadata = json.loads((folder/'metadata.json').read_text(encoding='utf-8'))
verify_job_assets(metadata)
assert metadata['video_encoder'] == 'h264_nvenc'
assert metadata['render_config']['video_width'] == 1920
qc = json.loads((folder/'qc.json').read_text(encoding='utf-8'))
assert all(c['status'] == 'pass' or c['name'] == 'YouTube thumbnail upload size' for c in qc['checks']), qc
assert not (folder/'render_background.png').exists()
if success:
    assert engine.resume(folder.name)
write_json(Path('jobs')/f'immutable_acceptance_{minutes}.json', dict(job_id=folder.name, metadata=metadata))
print('ACCEPTANCE_RESULT', folder, flush=True)
