"""Real GIF-render acceptance; sequential cases, no publishing or source edits."""
import json, subprocess, sys, time
from pathlib import Path
from app.config.settings import get_settings
from app.pipeline.long_form_jazz_orchestrator import LongFormJazzOrchestrator
from app.utils.ffmpeg import find_ffmpeg, find_ffprobe
from app.studio.assets import qc_job, verify_job_assets
from app.youtube.state import write_json


def run(name, duration, enabled, effect, motion='static', captions=False):
    directory=Path('jobs/gif_acceptance')/name; directory.mkdir(parents=True,exist_ok=True)
    settings=get_settings().model_copy(update=dict(video_width=1920,video_height=1080,video_fps=30,
        visualizer_enabled=enabled,visual_effect=effect,visual_effect_opacity=.12,studio_motion_mode=motion,
        waveform_enabled=True,watermark_enabled=True,subscribe_overlay_enabled=False,render_segment_seconds=600))
    engine=LongFormJazzOrchestrator(settings)
    import app.video.waveform as old
    old.create_waveform=lambda *a,**kw: (_ for _ in ()).throw(AssertionError('Old waveform must not run'))
    metadata=dict(target_duration_seconds=duration,youtube_exclude=True,youtube_title='GIF visualizer acceptance',
        youtube_description='Local verification only.',render_config=dict(video_width=1920,video_height=1080,video_fps=30))
    engine._prepare_prompt_assets(None,directory,metadata)
    # Reuse one real assigned scene across cases for comparisons.
    baseline=Path('jobs/gif_acceptance/scene.json')
    if baseline.exists():
        metadata['assets']['background']=json.loads(baseline.read_text())
        metadata['generated_background_path']=metadata['assets']['background']['path']
        metadata['background_source_path']=metadata['assets']['background']['source']
    else: write_json(baseline,metadata['assets']['background'])
    audio=directory/'audio.aac'
    source=Path('jobs/gif_acceptance/base_audio.aac')
    if not source.exists():
        track=next(Path('music').glob('*.mp3'))
        subprocess.run([str(find_ffmpeg()),'-v','error','-y','-stream_loop','-1','-i',str(track),'-t','180','-c:a','aac','-b:a','320k','-f','ipod',str(source)],check=True)
    subprocess.run([str(find_ffmpeg()),'-v','error','-y','-stream_loop','-1','-i',str(source),'-t',str(duration),'-c:a','copy','-f','ipod',str(audio)],check=True)
    metadata['audio_path']=str(audio.resolve())
    engine.timeline_builder.add_clip(metadata['generated_background_path'],'image',duration)
    metadata['selected_images']=[metadata['assets']['background']['filename']]
    output=engine._render_video(directory,metadata,audio)
    write_json(directory/'metadata.json',metadata)
    if not output: raise RuntimeError(metadata.get('render_error'))
    if captions:
        (directory/'lyrics.srt').write_text('1\n00:00:00,500 --> 00:00:04,500\nCaption continuity check\n',encoding='utf-8')
        metadata['lyrics_captions']=True
        engine._mux_lyrics_track(directory,metadata,output)
        assert metadata.get('lyrics_muxed')
    assert engine._validate_output(directory,output,audio,metadata)
    verify_job_assets(metadata)
    qc=qc_job(directory,dict(video_path=metadata['video_path'],thumbnail_path=metadata['thumbnail_path'],
        title=metadata['youtube_title'],description=metadata['youtube_description']),metadata)
    assert qc['status']!='fail',qc
    final=Path(metadata['video_path'])
    for offset in [2, min(duration-1,4)]:
        subprocess.run([str(find_ffmpeg()),'-v','error','-y','-ss',str(offset),'-i',str(final),'-frames:v','1',str(directory/f'frame_{offset}.png')],check=True)
    write_json(directory/'metadata.json',metadata)
    write_json(directory/'result.json',dict(metadata=metadata,qc=qc))
    print(name,metadata['render_elapsed_seconds'],'seconds',flush=True)

if __name__=='__main__':
    if sys.argv[1]=='smoke':
        for effect in ('none','vintage','noir','sepia'):
            run(effect+'_on',6,True,effect)
        run('off_motion_captions',6,False,'vintage','drift',True)
    else:
        seconds=int(sys.argv[1]); run('duration_'+str(seconds),seconds,True,'vintage')
