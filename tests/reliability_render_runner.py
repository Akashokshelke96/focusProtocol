"""Controlled render benchmark: python -m tests.reliability_render_runner NAME SECONDS ENCODER STYLE."""
import json
import sys
import time
from pathlib import Path
from app.config.settings import get_settings
from app.pipeline.long_form_jazz_orchestrator import LongFormJazzOrchestrator
from app.youtube.state import write_json


def main():
    name, seconds, encoder, style = sys.argv[1:5]
    duration = float(seconds)
    folder = Path('jobs') / ('reliability_' + name)
    folder.mkdir(exist_ok=True)
    source = json.loads(Path('jobs/20260914_125428_923969_video_001/metadata.json').read_text())
    settings = get_settings().model_copy(update=dict(video_fps=30, video_encoder=encoder, waveform_style=style,
        studio_motion_mode='drift', song_panel_enabled=False, subscribe_overlay_enabled=True))
    engine = LongFormJazzOrchestrator(settings)
    audio = Path(source['audio_path'])
    if duration > 180:
        import subprocess
        from app.utils.ffmpeg import find_ffmpeg
        out = folder / 'audio.aac'
        subprocess.run([str(find_ffmpeg()), '-v', 'error', '-y', '-stream_loop', '-1', '-i', str(audio),
                        '-t', str(duration), '-c:a', 'copy', '-f', 'mp4', str(out)], check=True)
        audio = out
    engine.timeline_builder.add_clip(source['generated_background_path'], 'image', duration)
    metadata = dict(target_duration_seconds=duration, selected_images=source['selected_images'],
        generated_background_path=source['generated_background_path'], thumbnail_path=source['thumbnail_path'],
        youtube_title='Reliability acceptance', youtube_description='Local render verification.', youtube_exclude=True,
        render_config=dict(video_width=1920, video_height=1080, video_fps=30),
        visualization_config=dict(waveform_enabled=True, waveform_style=style))
    started = time.perf_counter()
    output = engine._render_video(folder, metadata, audio)
    if not output:
        raise RuntimeError(metadata.get('render_error'))
    assert engine._validate_output(folder, output, audio, metadata)
    from app.studio.assets import qc_job
    qc = qc_job(folder, dict(video_path=str(output),thumbnail_path=metadata['thumbnail_path'],
                            title=metadata['youtube_title'],description=metadata['youtube_description']), metadata)
    result = dict(elapsed_seconds=round(time.perf_counter()-started, 3), metadata=metadata,
                  output_bytes=output.stat().st_size, qc=qc,
                  resources=json.loads((folder/'render_resources.json').read_text()) if (folder/'render_resources.json').exists() else {})
    write_json(folder/'benchmark.json',result)
    print(json.dumps(result,indent=2))
    assert qc['status']=='pass'


if __name__ == '__main__':
    main()
