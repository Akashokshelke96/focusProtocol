import json
from pathlib import Path
from app.config.settings import get_settings
from app.pipeline.long_form_jazz_orchestrator import LongFormJazzOrchestrator
from app.youtube.state import write_json
p=Path('jobs/upgrade_preset_480p');m=json.loads((p/'metadata.json').read_text());d=Path('jobs/upgrade_subscribe_drift');d.mkdir(exist_ok=True)
s=get_settings().with_quality_preset('480p').model_copy(update=dict(studio_motion_mode='drift',subscribe_overlay_enabled=True,visualizer_enabled=True))
e=LongFormJazzOrchestrator(s);e.timeline_builder.add_clip(m['generated_background_path'],'image',180)
v=e._render_video(d,m,Path(m['audio_path']));assert v,m.get('render_error');assert e._validate_output(d,v,Path(m['audio_path']),m);write_json(d/'metadata.json',m);print(m['render_timings'])
