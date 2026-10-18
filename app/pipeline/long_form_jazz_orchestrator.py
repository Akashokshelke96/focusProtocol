"""
Long-form Jazz video orchestrator.
Specialized pipeline for generating 90-minute jazz videos without narration or captions.
"""
from app.utils.ffmpeg import no_window_flags
import json
import hashlib
import random
import re
import shutil
import subprocess
import time
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict, Any
from app.config.settings import Settings, get_settings
from app.config.logging_config import get_logger
from app.providers.local_music import LocalMusicProvider
from app.providers.local_background import LocalBackgroundProvider
from app.audio import AudioMixer
from app.video.timeline import TimelineBuilder
from app.video.renderer import FFmpegRenderer
from app.jobs.manager import JobManager, JobState, JobStage
from app.llm.gemini import GeminiProvider
from app.youtube.state import write_json

logger = get_logger("pipeline.long_form_jazz")


class LongFormJazzOrchestrator:
    """Orchestrator for long-form jazz video generation."""

    # Jazz-specific job stages
    JAZZ_STAGES = {
        "DISCOVER_VALIDATE": "DISCOVER_VALIDATE",
        "ASSEMBLE_AUDIO": "ASSEMBLE_AUDIO",
        "VERIFY_AUDIO": "VERIFY_AUDIO",
        "DISCOVER_IMAGES": "DISCOVER_IMAGES",
        "BUILD_TIMELINE": "BUILD_TIMELINE",
        "APPLY_MOTION_RENDER": "APPLY_MOTION_RENDER",
        "VALIDATE_OUTPUT": "VALIDATE_OUTPUT",
    }

    def __init__(self, settings: Optional[Settings] = None, context=None):
        """Initialize jazz orchestrator."""
        self.settings = settings or get_settings()
        self.context = context or {}
        self.cancel_requested = False
        self.job_manager = JobManager()
        self.logger = logger

        # Initialize providers
        self.music_provider = LocalMusicProvider(self.context.get('channel', {}).get('music_dir'))
        self.background_provider = LocalBackgroundProvider()
        self.llm = GeminiProvider(self.settings)

        # Initialize processors
        self.audio_mixer = AudioMixer(self.settings)
        self.timeline_builder = TimelineBuilder(
            fps=self.settings.video_fps,
            transition_seconds=self.settings.video_transition_seconds,
        )
        self.renderer = FFmpegRenderer(self.settings)
        self.last_job_ids: List[str] = []
        self._asset_fallbacks: List[str] = []

        self.logger.info("Long-form jazz orchestrator initialized")

    def run(
        self, video_count=1, test_mode=False, test_duration_minutes=None, duration_minutes=None,
    ) -> bool:
        from app.youtube.state import publishing_lock
        with publishing_lock(Path('jobs') / 'generation'):
            return self._run_batch(video_count, test_mode, test_duration_minutes, duration_minutes)

    def _run_batch(
        self,
        video_count: int = 1,
        test_mode: bool = False,
        test_duration_minutes: Optional[int] = None,
        duration_minutes: Optional[int] = None,
    ) -> bool:
        """Execute jazz video generation pipeline.

        Args:
            video_count: Number of videos to generate (default 1)
            test_mode: Use shorter duration for testing
            test_duration_minutes: Override test duration

        Returns:
            True if successful, False otherwise
        """
        self.logger.info(f"\n{'='*60}")
        self.logger.info(f"JAZZ VIDEO GENERATION")
        self.logger.info(f"{'='*60}")
        self.logger.info(f"Mode: Long-form Jazz")
        self.logger.info(f"Videos to generate: {video_count}")
        self.logger.info(f"Test mode: {test_mode}")
        self.logger.info(f"{'='*60}\n")

        success_count = 0
        self.last_job_ids = []
        prompt_pairs = [None] * video_count  # Local artwork does not consume image prompts.

        for i in range(video_count):
            if self.cancel_requested:
                break
            self.logger.info(f"\n--- Video {i+1}/{video_count} ---\n")

            if self._run_single_video(
                i,
                video_count,
                test_mode,
                test_duration_minutes,
                duration_minutes,
                prompt_pairs[i],
            ):
                success_count += 1
            else:
                self.logger.error(f"Video {i+1} generation failed")

        self.logger.info(f"\n{'='*60}")
        self.logger.info(f"JAZZ GENERATION COMPLETE")
        self.logger.info(f"Success: {success_count}/{video_count}")
        self.logger.info(f"{'='*60}\n")

        return success_count == video_count

    def resume(self, job_id):
        """Retry finalization or rendering from the job's saved media, without re-sourcing."""
        from app.youtube.state import publishing_lock
        from app.studio.store import read_json
        with publishing_lock(Path('jobs') / 'generation'):
            job_dir = Path('jobs') / job_id
            (job_dir / 'cancel.request').unlink(missing_ok=True)
            saved = read_json(job_dir / 'job.json', {})
            metadata = {**saved.get('metadata', {}), **read_json(job_dir / 'metadata.json', {})}
            job = self.job_manager.get_job(job_id)
            if not job:
                raise ValueError('Retry job is missing from the existing registry')
            from app.studio.recovery import process_alive
            progress = read_json(job_dir / 'render_progress.json', {})
            if progress.get('status') not in ('complete', 'failed') and process_alive(progress.get('owner')):
                raise RuntimeError('The previous FFmpeg process is still running; wait before retrying')
            if job.status in ('completed', 'completed_with_fallback'):
                from app.studio.assets import verify_job_assets
                verify_job_assets(metadata)
                return True
            # Early failures have no reusable media. Re-enter under the same identity.
            audio = Path(metadata.get('audio_path') or job_dir / 'music/audio_concatenated.aac')
            from app.studio.assets import verify_job_assets
            verify_job_assets(metadata)
            background = Path(metadata.get('generated_background_path') or '')
            if not audio.is_file() or not background.is_file():
                self._resume_job_id = job_id
                try:
                    return self._run_batch(1, duration_minutes=job.duration_minutes)
                finally:
                    self._resume_job_id = None
            config = metadata.get('render_config', {})
            for key, value in {**config, **metadata.get('visualization_config', {})}.items():
                if hasattr(self.settings, key):
                    setattr(self.settings, key, value)
            # Channel config always wins for channel-owned visual settings so a
            # per-request render_config cannot override a channel's explicit
            # visual_effect / branding / opacity choice.
            channel = self.context.get('channel', {}) or {}
            for key in ('visual_effect', 'visual_effect_opacity', 'branding_enabled', 'watermark_enabled'):
                if key in channel and channel[key] is not None:
                    try:
                        setattr(self.settings, key, channel[key])
                    except ValueError:
                        pass
            job.status, job.error_message = 'running', None
            metadata.update(generation_status='running', retry_started_at=datetime.now().astimezone().isoformat())
            job.metadata = metadata
            self.job_manager.update_job(job)
            self._maybe_transcribe_lyrics(job_dir, metadata, audio)
            started = datetime.fromisoformat(metadata['started_at'])
            video = Path(metadata.get('video_path') or job_dir / 'output/rendering.mp4')
            try:
                if not video.is_file() or progress.get('status') != 'complete':
                    self.timeline_builder.clips.clear()
                    background_media = (metadata.get('assets', {}).get('background', {}).get('media', 'image'))
                    self.timeline_builder.add_clip(str(background), 'video' if background_media == 'video' else 'image',
                                                   metadata['target_duration_seconds'])
                    job.stage = 'VIDEO_RENDERING'
                    self.job_manager.update_job(job)
                    video = self._render_video(job_dir, metadata, audio)
                    if not video:
                        raise RuntimeError(metadata.get('render_error', 'Render failed'))
                return self._finish_video(job, job_dir, metadata, video, audio, started)
            except Exception as error:
                metadata.update(generation_status='failed', completed_at=datetime.now().astimezone().isoformat())
                job.status, job.error_message = 'failed', str(error)
                write_json(job_dir / 'metadata.json', metadata)
                self.job_manager.update_job(job)
                return False

    def _run_single_video(
        self,
        video_index: int,
        video_count: int,
        test_mode: bool = False,
        test_duration_minutes: Optional[int] = None,
        duration_minutes: Optional[int] = None,
        prompt_pair: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """Generate a single 90-minute jazz video.

        Args:
            test_mode: Use shorter duration for testing
            test_duration_minutes: Override test duration in minutes

        Returns:
            True if successful, False otherwise
        """
        # Determine target duration
        if test_mode:
            target_duration_seconds = (test_duration_minutes or 3) * 60
        else:
            target_duration_seconds = (duration_minutes or self.settings.target_duration_minutes) * 60

        # Generate job ID
        job_id = getattr(self, '_resume_job_id', None) or self.context.get('job_id') or datetime.now().strftime("%Y%m%d_%H%M%S_%f") + f"_video_{video_index + 1:03d}"
        self.last_job_ids.append(job_id)

        self.logger.info(f"Job ID: {job_id}")
        self.logger.info(f"Target duration: {target_duration_seconds/60:.1f} minutes")

        # Create job
        job = self.job_manager.create_job(
            job_id,
            "Long-form Jazz Video",
            int(target_duration_seconds / 60)
        )
        job_dir = Path("jobs") / job_id
        job_dir.mkdir(parents=True, exist_ok=True)
        job_metadata = dict(job.metadata or {})
        from app.video.image_motion import configuration
        job_metadata.setdefault('image_motion', configuration(self.context.get('image_motion')))
        if self.context:
            job_metadata.update(channel_id=self.context['channel']['id'], content_id=self.context['content_id'],
                                profile_snapshot=self.context['profile'], channel_snapshot=self.context['channel'])
        import os, psutil
        job_metadata['worker_owner'] = dict(pid=os.getpid(), created=psutil.Process().create_time())
        if self.context.get('content_plan'):
            job_metadata['content_plan'] = self.context['content_plan']
        job_metadata['render_config'] = {key: getattr(self.settings, key) for key in ('quality_preset', 'video_width', 'video_height', 'video_fps', 'ffmpeg_preset', 'ffmpeg_crf', 'ffmpeg_audio_bitrate', 'video_encoder', 'video_encoder_quality', 'studio_motion_mode', 'visual_effect', 'visual_effect_opacity')}
        job_metadata["youtube_exclude"] = bool(self.context.get("youtube_exclude", job_metadata.get("youtube_exclude", False)))
        job_metadata["target_duration_seconds"] = target_duration_seconds
        job_metadata["visualization_config"] = {
            key: value for key, value in self.settings.model_dump().items()
            if key.startswith(("waveform_", "watermark_", "subscribe_", "visualizer_"))
        }
        started_at = datetime.now().astimezone()
        job_metadata["started_at"] = started_at.isoformat()
        pipeline_started = time.perf_counter()
        job.metadata = job_metadata
        self.job_manager.update_job(job)

        try:
            if self.cancel_requested or (job_dir / 'cancel.request').exists():
                raise RuntimeError('Cancelled by user')
            # Stage 1: DISCOVER & VALIDATE
            self.logger.info("\n[STAGE 1/7] DISCOVER & VALIDATE")
            music_files = self._select_music_files(job_dir, job_metadata, target_duration_seconds)
            if not music_files:
                raise Exception("Failed to select music files")

            job.stage = self.JAZZ_STAGES["DISCOVER_VALIDATE"]
            self.job_manager.update_job(job)
            self.logger.info(f"[OK] Selected {len(music_files)} music files\n")

            target_duration_seconds = job_metadata['target_duration_seconds']

            # Stage 2: ASSEMBLE AUDIO
            self.logger.info("[STAGE 2/7] ASSEMBLE AUDIO")
            stage_started = time.perf_counter()
            audio_path = self._concatenate_audio(
                [m["path"] for m in music_files],
                job_dir,
                job_metadata,
                target_duration_seconds,
            )
            if not audio_path:
                raise Exception("Failed to assemble audio")
            job_metadata['audio_elapsed_seconds'] = round(time.perf_counter() - stage_started, 3)

            job.stage = self.JAZZ_STAGES["ASSEMBLE_AUDIO"]
            self.job_manager.update_job(job)
            self.logger.info(f"[OK] Audio assembled: {audio_path}\n")

            # Stage 3: VERIFY AUDIO
            self.logger.info("[STAGE 3/7] VERIFY AUDIO")
            absolute_video_duration = self.music_provider._get_audio_duration(audio_path)
            self.logger.info(f"[OK] Absolute video duration: {absolute_video_duration}s\n")
            job_metadata["absolute_video_duration"] = absolute_video_duration

            job.stage = self.JAZZ_STAGES["VERIFY_AUDIO"]
            self.job_manager.update_job(job)

            self._maybe_transcribe_lyrics(job_dir, job_metadata, audio_path)

            stage_started = time.perf_counter()
            prompt_assets = self._prepare_prompt_assets(prompt_pair, job_dir, job_metadata)
            job_metadata['media_sourcing_seconds'] = round(time.perf_counter() - stage_started, 3)

            # Stage 4: DISCOVER IMAGES
            self.logger.info("[STAGE 4/7] DISCOVER IMAGES")
            image_files = self._select_background_image(
                job_dir,
                job_metadata,
                absolute_video_duration,
                prompt_assets["background_path"],
            )
            if not image_files:
                raise Exception("Failed to select background images")

            job.stage = self.JAZZ_STAGES["DISCOVER_IMAGES"]
            self.job_manager.update_job(job)
            self.logger.info(f"[OK] Selected {len(image_files)} background images\n")

            # Stage 5: BUILD TIMELINE
            self.logger.info("[STAGE 5/7] BUILD TIMELINE")
            self._build_timeline(
                image_files,
                audio_path,  # Passed audio_path, though absolute_video_duration could be computed inside or passed, let's keep audio_path
                job_dir,
                job_metadata
            )

            job.stage = self.JAZZ_STAGES["BUILD_TIMELINE"]
            self.job_manager.update_job(job)
            self.logger.info(f"[OK] Timeline built\n")

            if not self.context.get('content_plan'):
                from app.video.branding import session_metadata
                job_metadata.update(session_metadata(self.llm, job_id, target_duration_seconds / 60, self.context.get('concept', ''),
                                                     profile=self.context.get('profile'), channel=self.context.get('channel')))

            # Stage 6: APPLY MOTION & RENDER
            if self.cancel_requested or (job_dir / 'cancel.request').exists():
                raise RuntimeError('Cancelled by user')
            self.logger.info("[STAGE 6/7] APPLY MOTION & RENDER")
            job.stage = 'VIDEO_RENDERING'
            self.job_manager.update_job(job)
            video_path = self._render_video(job_dir, job_metadata, audio_path)
            if not video_path:
                raise Exception(job_metadata.get('render_error') or "Failed to render video")

            job.stage = self.JAZZ_STAGES["APPLY_MOTION_RENDER"]
            self.job_manager.update_job(job)
            self.logger.info(f"[OK] Video rendered: {video_path}\n")

            return self._finish_video(job, job_dir, job_metadata, video_path, audio_path, started_at)

        except Exception as e:
            self.logger.error(f"\nJAZZ GENERATION FAILED: {e}", exc_info=True)
            failed_at = datetime.now().astimezone()
            job_metadata["generation_status"] = "failed"
            job_metadata["completed_at"] = failed_at.isoformat()
            job_metadata["total_elapsed_seconds"] = round(
                (failed_at - started_at).total_seconds(), 3
            )
            write_json(job_dir / "metadata.json", job_metadata)
            job.metadata = job_metadata
            job.status = "failed"
            job.error_message = str(e)
            self.job_manager.update_job(job)
            return False

    def _finish_video(self, job, job_dir, job_metadata, video_path, audio_path, started_at):
        from app.studio.artifacts import name_final_video
        video_path = name_final_video(video_path, job_metadata, self.settings.channel_brand_name,
                                      self._probe_duration(video_path), job.id)
        video_path = self._mux_lyrics_track(job_dir, job_metadata, video_path)

        job.stage = 'VALIDATE_OUTPUT'
        self.job_manager.update_job(job)
        # Stage 7: VALIDATE & OUTPUT
        self.logger.info("[STAGE 7/7] VALIDATE & OUTPUT")
        if self._validate_output(job_dir, video_path, audio_path, job_metadata):
            self.logger.info("[OK] Output validation passed\n")
        else:
            raise Exception("Output validation failed")

        job.stage = self.JAZZ_STAGES["VALIDATE_OUTPUT"]
        self.job_manager.update_job(job)

        self._generate_metadata(job_dir, job_metadata)
        from app.studio.assets import verify_job_assets
        verify_job_assets(job_metadata)
        thumbnail_path = self._generate_thumbnail(job_dir, job_metadata)

        job.metadata = job_metadata
        self.job_manager.update_job(job)
        from app.studio.assets import qc_job
        qc_row = dict(video_path=str(video_path), thumbnail_path=str(thumbnail_path or ''),
                      title=job_metadata.get('youtube_title', ''), description=job_metadata.get('youtube_description', ''),
                      target_duration_seconds=job_metadata['target_duration_seconds'])
        qc = qc_job(job_dir, qc_row, job_metadata)
        job_metadata['qc_status'] = qc['status']
        if qc['status'] == 'fail':
            raise ValueError('Automated QC failed: ' + ', '.join(c['name'] for c in qc['checks'] if c['status'] == 'fail'))

        # Keep canonical job artifacts intact; export a channel-local final copy.
        export_dir = self.context.get('channel', {}).get('output_dir', 'jobs')
        if export_dir != 'jobs':
            from app.studio.profiles import Channel
            import shutil
            channel = Channel.model_validate(self.context['channel'])
            destination = Path(channel.output_dir) / job.id / Path(video_path).name
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(video_path, destination)
            job_metadata['channel_output_path'] = str(destination)

        from app.studio.artifacts import cleanup_job
        try:
            job_metadata['cleanup'] = cleanup_job(job_dir, job_metadata)
        except OSError as error:
            job_metadata['cleanup'] = {'warnings': [str(error)]}

        # Final status
        job.status = "completed_with_fallback" if job_metadata.get("fallback_used") else "completed"
        completed_at = datetime.now().astimezone()
        job_metadata["generation_status"] = job.status
        job_metadata["completed_at"] = completed_at.isoformat()
        job_metadata["total_elapsed_seconds"] = round(
            (completed_at - started_at).total_seconds(), 3
        )
        write_json(job_dir / "metadata.json", job_metadata)
        job.metadata = job_metadata
        self.job_manager.update_job(job)

        self.logger.info("=" * 60)
        self.logger.info(f"VIDEO GENERATION COMPLETE")
        self.logger.info("=" * 60)
        self.logger.info(f"Job ID:     {job.id}")
        self.logger.info(f"Video:      {video_path}")
        self.logger.info(f"Thumbnail:  {thumbnail_path if thumbnail_path else 'N/A'}")
        self.logger.info(f"Status:     {job.status.upper()}")
        self.logger.info("Total generation time: %.1fs", (completed_at - started_at).total_seconds())
        self.logger.info("=" * 60)

        return True


    def _select_music_files(
        self,
        job_dir: Path,
        job_metadata: Dict[str, Any],
            target_duration_seconds: float = 5400.0
    ) -> List[Dict[str, Any]]:
        """Select music files to reach target duration (default ~90 minutes).

        Args:
            job_dir: Job output directory
            job_metadata: Job metadata dict to update
            target_duration_seconds: Target total audio duration in seconds (5400 = 90 min)

        Returns:
            List of selected music files
        """
        try:
            available_files = self.music_provider.get_available_music_files()
            if self.context:
                from app.studio.store import StudioStore
                assignments = StudioStore().read()['assets']
                channel_id = self.context['channel']['id']
                assigned = [m for m in available_files if assignments.get(str(Path(m['path']).resolve()), {}).get('assigned_channel') == channel_id]
                available_files = assigned or [m for m in available_files if not assignments.get(str(Path(m['path']).resolve()), {}).get('assigned_channel')]
                if len(available_files) < 2:
                    raise ValueError('This channel needs at least two valid local music tracks; check its folder and music assignments')

            if not available_files:
                self.logger.error("No music files available")
                return []

            from app.providers.media_history import rotate
            # No audio processing: plain sequential concat, so no crossfade overlap math.
            crossfade_enabled = False
            crossfade = 0
            selected, actual = rotate(available_files, 'music', job_dir.name,
                                      target=target_duration_seconds, crossfade=crossfade)
            warning = None
            if actual + .1 < target_duration_seconds:
                warning = (f'Library cannot reach {target_duration_seconds/60:.1f} minutes with at most two uses per track. '
                           f'Rendering the available {actual/60:.1f} minutes.')
                self.logger.warning(warning)
            job_metadata.update(selected_music=[m['filename'] for m in selected],
                                selected_music_paths=[m['path'] for m in selected],
                                music_source_ids=[m['source_id'] for m in selected],
                                music_count=len(selected), music_source_count=len({m['source_id'] for m in selected}),
                                music_total_duration=actual, requested_duration_seconds=target_duration_seconds,
                                target_duration_seconds=actual, music_crossfade_seconds=crossfade,
                                audio_crossfade_enabled=crossfade_enabled,
                                music_selection_warning=warning, music_max_uses_per_track=2)
            return selected

        except Exception as e:
            raise ValueError(f"Music selection failed: {e}") from e

    def _reserve_prompt_pairs(self, video_count: int) -> List[Dict[str, Any]]:
        """Reserve the next prompt pair range durably before a batch starts."""
        if self.context:
            return [{'background': {'id': self.context['content_id'], 'title': self.context['concept'],
                     'prompt': self.context['profile']['visual_prompt'] + '. ' + self.context['concept']}} for _ in range(video_count)]
        project_root = Path(__file__).resolve().parents[2]
        backgrounds = self._load_prompt_records(
            Path(__file__).with_name("backgroundImagesPrompts.json"), "background"
        )
        state_path = project_root / "jobs" / "prompt_state.json"
        state_path.parent.mkdir(parents=True, exist_ok=True)
        state = {"background_prompt_index": 0}
        if state_path.exists():
            with open(state_path, "r", encoding="utf-8") as state_file:
                state.update(json.load(state_file))

        background_start = int(state["background_prompt_index"])
        if background_start + video_count > len(backgrounds):
            raise ValueError("Not enough unused background prompts for this batch")

        pairs = []
        for offset in range(video_count):
            background = deepcopy(backgrounds[background_start + offset])
            background['title'] = 'Midnight Bourbon Blues'
            background['prompt'] = ('Original cinematic vintage blues photograph, fictional soulful guitarist on the right, '
                                    'antique microphone, smoky lounge, rich monochrome with restrained amber light, '
                                    'dark negative space on the left for typography, 16:9, no text, no logos. '
                                    'Scene variation: ' + str(background['id']))
            pairs.append({"background": background})

        state["background_prompt_index"] = background_start + video_count
        write_json(state_path, state)
        self.logger.info(
            "Reserved background prompt indexes %s..%s",
            background_start + 1,
            background_start + video_count,
        )
        return pairs

    def _prepare_prompt_assets(
        self,
        prompt_pair: Dict[str, Any],
        job_dir: Path,
        job_metadata: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Assign local originals once, persisting before any expensive work."""
        from app.studio.assets import copy_thumbnail, asset_sha256, verify_job_assets
        from app.studio.store import read_json
        saved = read_json(job_dir / 'prompt_assets.json', {})
        assets = job_metadata.get('assets') or saved.get('assets')
        if not assets:
            channel = self.context.get('channel', {})
            background_mode = self.context.get('background_mode', 'image')
            job_metadata['background_mode'] = background_mode
            assets = {}
            if background_mode == 'video':
                bg_folder = Path(channel.get('background_dir', 'inputVideos'))
                assets['background'] = self._assign_loop_video(job_dir, bg_folder)
            else:
                candidates = LocalBackgroundProvider(Path(channel.get('background_dir', 'backgroundImages'))).get_available_images()
                if not candidates:
                    raise ValueError('No valid background images in configured folder')
                source = Path(random.choice(candidates)['path']).resolve()
                destination = (job_dir / 'background_images' / ('background' + source.suffix.lower())).resolve()
                assets['background'] = dict(source=str(source), path=str(destination), filename=source.name,
                                            sha256=asset_sha256(source), media='image')
            folder = channel.get('thumbnail_dir', 'thumbnail')
            candidates = LocalBackgroundProvider(Path(folder)).get_available_images()
            if not candidates:
                raise ValueError(f'No valid thumbnail images in configured folder: {folder}')
            source = Path(random.choice(candidates)['path']).resolve()
            destination = (job_dir / 'thumbnail' / ('thumbnail' + source.suffix.lower())).resolve()
            assets['thumbnail'] = dict(source=str(source), path=str(destination), filename=source.name,
                                       sha256=asset_sha256(source), media='image')
            # Persist assignments first so an interrupted copy cannot cause a new selection.
            write_json(job_dir / 'prompt_assets.json', {'assets': assets})
        for record in assets.values():
            source, destination = Path(record['source']), Path(record['path'])
            if asset_sha256(source) != record['sha256']:
                raise ValueError(f'Assigned source changed: {source}')
            if not destination.exists():
                copy_thumbnail(source, destination)
        job_metadata.update(assets=assets, thumbnail_style='original',
            thumbnail_source=assets['thumbnail']['source'], thumbnail_path=assets['thumbnail']['path'],
            background_source_path=assets['background']['source'],
            generated_background_path=assets['background']['path'], fallback_used=False, fallback_assets=[])
        verify_job_assets(job_metadata)
        write_json(job_dir / 'metadata.json', job_metadata)
        return dict(background_path=Path(assets['background']['path']),
                    thumbnail_path=Path(assets['thumbnail']['path']))

    VIDEO_BACKGROUND_FORMATS = {".mp4", ".mov", ".mkv", ".webm"}

    def _assign_loop_video(self, job_dir: Path, folder: Path) -> Dict[str, Any]:
        """Randomly assign one muted looping background clip from the channel's background_dir."""
        from app.studio.assets import asset_sha256
        candidates = []
        if folder.exists():
            for candidate in sorted(folder.iterdir()):
                if not candidate.is_file() or candidate.suffix.lower() not in self.VIDEO_BACKGROUND_FORMATS:
                    continue
                try:
                    info = self._probe_media(candidate)
                    streams = {s.get("codec_type") for s in info.get("streams", [])}
                    duration = float(info.get("format", {}).get("duration", 0))
                    if "video" in streams and duration >= 2:
                        candidates.append(candidate)
                except Exception as error:
                    self.logger.warning("Ignoring unusable loop clip %s: %s", candidate, error)
        if not candidates:
            raise ValueError(f"No usable looping video in {folder}. Add an MP4/MOV/MKV/WEBM clip of at least 2 seconds.")
        source = random.choice(candidates).resolve()
        destination = (job_dir / "background_images" / ("background_loop" + source.suffix.lower())).resolve()
        self.logger.info("Using looped video background (muted): %s", source.name)
        return dict(source=str(source), path=str(destination), filename=source.name,
                    sha256=asset_sha256(source), media='video')

    def _select_local_thumbnail(self) -> Path:
        """Choose one readable thumbnail at random from the user-managed folder."""
        thumbnail_dir = Path(self.context.get('channel', {}).get('thumbnail_dir', 'thumbnail'))
        candidates = []
        if thumbnail_dir.exists():
            for candidate in thumbnail_dir.iterdir():
                if not candidate.is_file() or candidate.suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp"}:
                    continue
                candidates.append(candidate)
        if not candidates:
            raise RuntimeError("No thumbnail files found in thumbnail/. Add a PNG, JPG, JPEG, or WEBP file there.")
        from app.providers.media_history import rotate
        chosen, _ = rotate([{'path': str(p.resolve())} for p in candidates], 'thumbnail_images', self.context.get('job_id', 'thumbnail'))
        selected = Path(chosen[0]['path'])
        self.logger.info("Using random local thumbnail: %s", selected)
        return selected

    def _load_prompt_records(self, prompt_path: Path, asset_type: str) -> List[Dict[str, Any]]:
        """Load and validate prompt records from a JSON array."""
        if not prompt_path.exists():
            raise FileNotFoundError(f"{asset_type.title()} prompt file not found: {prompt_path}")

        try:
            with open(prompt_path, "r", encoding="utf-8") as prompt_file:
                records = json.load(prompt_file)
        except json.JSONDecodeError as error:
            raise ValueError(f"Invalid {asset_type} prompt JSON: {prompt_path}") from error

        if not isinstance(records, list) or not records:
            raise ValueError(f"{asset_type.title()} prompt file must contain a non-empty JSON array")

        validated = []
        seen_ids = set()
        for index, record in enumerate(records):
            if not isinstance(record, dict) or any(
                field not in record or not str(record[field]).strip()
                for field in ("id", "title", "prompt")
            ):
                raise ValueError(
                    f"Invalid {asset_type} prompt at index {index}; each item needs id, title, and prompt"
                )
            if record["id"] in seen_ids:
                raise ValueError(f"Duplicate {asset_type} prompt ID: {record['id']}")
            seen_ids.add(record["id"])
            validated.append(record)

        return validated

    @staticmethod
    def _prompt_filename(record: Dict[str, Any], extension: str, thumbnail: bool = False) -> str:
        """Build a stable, filesystem-safe asset filename."""
        title = re.sub(r"[^A-Za-z0-9]+", "_", str(record["title"])).strip("_").lower()
        suffix = "_thumbnail" if thumbnail else ""
        return f"{record['id']}_{title}{suffix}.{extension}"

    def _generate_or_reuse_image(
        self,
        record: Dict[str, Any],
        output_path: Path,
        asset_type: str,
        job_metadata: Optional[Dict[str, Any]] = None,
    ) -> Path:
        """Generate one asset, with an explicit and recorded local fallback."""
        if output_path.exists() and output_path.stat().st_size > 0:
            try:
                from PIL import Image

                from app.providers.media_history import validate_background
                validate_background(output_path)
                self.logger.info("Reusing existing %s image: %s", asset_type, output_path)
                return output_path
            except Exception:
                self.logger.warning("Existing %s image is invalid; regenerating: %s", asset_type, output_path)

        # This pipeline is local-only, even if an old environment enables image APIs.
        generation_error = None
        fallback_dirs = (
            [Path(self.context.get('channel', {}).get('background_dir', 'backgroundImages')), Path(self.context.get('channel', {}).get('thumbnail_dir', 'thumbnail'))] if asset_type == "background"
            else [Path("thumbnails"), Path("output") / "thumbnails"]
        )
        candidates = [
            candidate for directory in fallback_dirs
            if directory.exists()
            for candidate in sorted(directory.iterdir())
            if candidate.is_file() and candidate.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}
        ]
        valid_candidates = []
        for candidate in candidates:
            try:
                from PIL import Image
                from app.providers.media_history import validate_background
                validate_background(candidate)
                valid_candidates.append(candidate)
            except Exception as error:
                self.logger.warning("Ignoring invalid fallback %s image %s: %s", asset_type, candidate, error)
        if valid_candidates:
            # Prefer the background directory, then exhaust its shuffled pool before reuse.
            primary = [p for p in valid_candidates if p.parent == fallback_dirs[0]] or valid_candidates
            from app.providers.media_history import rotate
            chosen, _ = rotate([{'path': str(p.resolve())} for p in primary], 'images', output_path.parent.parent.name)
            fallback_source = Path(chosen[0]['path'])
            if job_metadata is not None:
                job_metadata['background_source_path'] = str(fallback_source.resolve())
            shutil.copy2(fallback_source, output_path)
            if job_metadata is not None:
                job_metadata['image_source'] = 'local_library'
            self.logger.info("Using rotated local %s image: %s", asset_type, fallback_source)
            return output_path

        raise RuntimeError(
            f"No valid local {asset_type} image. Add a nonblank 1920x1080 landscape image to backgroundImages or thumbnail."
        )

    def _mux_lyrics_track(self, job_dir: Path, job_metadata: Dict[str, Any], video_path: Path) -> Path:
        """Mux transcribed lyrics as a toggleable subtitle track. Stream-copy only."""
        srt = Path(job_metadata.get("lyrics_srt_path") or job_dir / "lyrics.srt")
        if not job_metadata.get("lyrics_captions") or not srt.is_file():
            return video_path
        try:
            from app.utils.ffmpeg import find_ffmpeg
            import subprocess
            import tempfile
            fd, temporary = tempfile.mkstemp(dir=video_path.parent, suffix=".mp4")
            import os
            os.close(fd)
            result = subprocess.run(
                [str(find_ffmpeg()), "-v", "error", "-y", "-i", str(video_path), "-i", str(srt),
                 "-map", "0", "-map", "1", "-c", "copy", "-c:s", "mov_text", str(temporary)],
                capture_output=True, text=True, timeout=300, **no_window_flags())
            if result.returncode != 0 or not Path(temporary).is_file():
                raise RuntimeError(result.stderr[-1000:] or "subtitle mux failed")
            os.replace(temporary, video_path)
            vtt = job_dir / "lyrics.vtt"
            job_metadata["lyrics_muxed"] = True
            if vtt.is_file():
                job_metadata["lyrics_vtt_path"] = str(vtt.resolve())
            self.logger.info("[OK] Lyrics subtitle track muxed\n")
        except Exception as error:
            self.logger.warning("Lyrics mux failed; keeping video without subtitle track: %s", error)
            job_metadata["lyrics_muxed"] = False
        return video_path

    def _maybe_transcribe_lyrics(self, job_dir: Path, job_metadata: Dict[str, Any], audio_path: Path) -> None:
        """Optional local lyrics transcription. Graceful skip when nothing is sung."""
        context = getattr(self, "context", None) or {}
        job_metadata["lyrics_requested"] = bool(context.get("lyrics_captions", False))
        if not job_metadata["lyrics_requested"]:
            return
        existing = job_dir / "lyrics.srt"
        if existing.is_file() and existing.stat().st_size > 0:
            job_metadata.update(lyrics_srt_path=str(existing.resolve()),
                                lyrics_vtt_path=str((job_dir / "lyrics.vtt").resolve()),
                                lyrics_captions=True)
            return
        try:
            from app.audio.lyrics import transcribe_lyrics
            started = time.perf_counter()
            srt_path, count = transcribe_lyrics(audio_path, job_dir, self.settings.lyrics_model)
            job_metadata["lyrics_elapsed_seconds"] = round(time.perf_counter() - started, 3)
            if srt_path:
                job_metadata.update(lyrics_srt_path=str(srt_path.resolve()),
                                    lyrics_vtt_path=str((job_dir / "lyrics.vtt").resolve()),
                                    lyrics_segments=count, lyrics_captions=True)
                self.logger.info("[OK] Lyrics captions: %s segments\n", count)
            else:
                job_metadata.update(lyrics_captions=False,
                                    lyrics_skip_reason="no sung lyrics detected in the mix")
                self.logger.info("[OK] No sung lyrics detected; continuing without captions\n")
        except Exception as error:
            job_metadata.update(lyrics_captions=False, lyrics_skip_reason=str(error)[-300:])
            self.logger.warning("Lyrics transcription failed; continuing without captions: %s", error)
        write_json(job_dir / "metadata.json", job_metadata)

    def _select_background_image(
        self,
        job_dir: Path,
        job_metadata: Dict[str, Any],
        target_duration_seconds: float,
        preferred_image_path: Path,
    ) -> List[Dict[str, Any]]:
        """Use exactly one background for the whole video (still image or muted loop)."""
        preferred_image_path = Path(preferred_image_path)
        media = (job_metadata.get("assets", {}).get("background", {}).get("media", "image"))
        if media == "video":
            if not preferred_image_path.exists():
                self.logger.error("Assigned loop background is unavailable: %s", preferred_image_path)
                return []
            try:
                info = self._probe_media(preferred_image_path)
                video = next(s for s in info["streams"] if s.get("codec_type") == "video")
                width, height = int(video.get("width", 0)), int(video.get("height", 0))
            except Exception as error:
                self.logger.error("Loop background probe failed: %s", error)
                return []
            clip = {"path": str(preferred_image_path.resolve()), "filename": preferred_image_path.name,
                    "width": width, "height": height, "media": "video"}
            job_metadata["selected_images"] = [clip["filename"]]
            job_metadata["image_count"] = 1
            job_metadata["image_duration_seconds"] = target_duration_seconds
            with open(job_dir / "image_selection.json", "w", encoding="utf-8") as selection_file:
                json.dump(job_metadata["selected_images"], selection_file, indent=2)
            self.logger.info("Using one muted loop background for %.1f minutes: %s", target_duration_seconds / 60, clip["filename"])
            return [clip]
        if not preferred_image_path.exists() or not self.background_provider.validate_image(preferred_image_path):
            self.logger.error("Generated background image is unavailable: %s", preferred_image_path)
            return []
        width, height = self.background_provider._get_image_dimensions(preferred_image_path)
        image = {
            "path": str(preferred_image_path.resolve()),
            "filename": preferred_image_path.name,
            "width": width,
            "height": height,
        }
        job_metadata["selected_images"] = [Path(image["path"]).name]
        job_metadata["image_count"] = 1
        job_metadata["image_duration_seconds"] = target_duration_seconds
        with open(job_dir / "image_selection.json", "w", encoding="utf-8") as selection_file:
            json.dump(job_metadata["selected_images"], selection_file, indent=2)
        self.logger.info("Using one static background for %.1f minutes: %s", target_duration_seconds / 60, image["filename"])
        return [image]

    def _select_background_images_legacy(
        self,
        job_dir: Path,
        job_metadata: Dict[str, Any],
        target_duration_seconds: float = 5400.0,
        image_duration_seconds: float = 900.0,
        preferred_image_path: Optional[Path] = None,
    ) -> List[Dict[str, Any]]:
        """Select background images to rotate every 15-20 minutes.

        Args:
            job_dir: Job output directory
            job_metadata: Job metadata dict to update
            target_duration_seconds: Total video duration in seconds (~90 minutes)
            image_duration_seconds: Duration each image stays on screen (~15 minutes)

        Returns:
            List of selected image files
        """
        try:
            available_images = self.background_provider.get_available_images()

            if not available_images:
                self.logger.error("No images available in backgroundImages/ directory")
                return []

            # Calculate how many images we need for the 90-minute video
            # For example: 90 min / 15 min per image = 6 images
            num_images_needed = max(3, int(target_duration_seconds / image_duration_seconds))

            preferred_image = None
            if preferred_image_path:
                preferred_path = Path(preferred_image_path).resolve()
                preferred_image = next(
                    (image for image in available_images if Path(image["path"]).resolve() == preferred_path),
                    None,
                )

            remaining_images = [image for image in available_images if image is not preferred_image]
            remaining_count = num_images_needed - (1 if preferred_image else 0)

            # If we don't have enough unique images, allow repetition
            if len(remaining_images) < remaining_count:
                self.logger.warning(
                    f"Only {len(remaining_images)} unique images available, need {remaining_count}. "
                    f"Will allow image repetition."
                )
                image_files = random.choices(remaining_images or available_images, k=remaining_count)
            else:
                # Select without replacement
                image_files = random.sample(remaining_images, remaining_count)

            image_files = ([preferred_image] if preferred_image else []) + image_files

            # Log selections
            self.logger.info(f"Selected {len(image_files)} Background Images (rotating every ~{image_duration_seconds/60:.0f} min):")
            for i, img in enumerate(image_files, 1):
                self.logger.info(f"  {i}. {Path(img['path']).name}")

            # Update metadata
            job_metadata["selected_images"] = [Path(i["path"]).name for i in image_files]
            job_metadata["image_count"] = len(image_files)
            job_metadata["image_duration_seconds"] = image_duration_seconds

            # Save selections to job dir
            with open(job_dir / "image_selection.json", "w") as f:
                json.dump(job_metadata["selected_images"], f, indent=2)

            return image_files

        except Exception as e:
            self.logger.error(f"Image selection failed: {e}")
            return []

    def _concatenate_audio(self, track_paths, job_dir, job_metadata, target_duration_seconds):
        # Audio processing (crossfade/loudness/fades/silence removal) is removed
        # for now: songs are only concatenated sequentially, nothing else.
        from app.audio.local_timeline import assemble_tracks_fast
        output = job_dir / 'music' / 'audio_concatenated.aac'
        assemble_tracks_fast(track_paths, output, target_duration_seconds,
                             self.settings.ffmpeg_audio_bitrate, metadata=job_metadata)
        job_metadata.update(intro_fade_seconds=0, outro_fade_seconds=0, audio_fades_enabled=False,
                            audio_silence_removal_enabled=False,
                            audio_crossfade_enabled=False, audio_loudness_enabled=False,
                            audio_processing_mode='fast_concat')
        self.logger.info("Fast-concat audio only (no crossfade/loudness/fades/silence)")
        # NOTE (processing disabled, kept for reference):
        # from app.audio.local_timeline import assemble_tracks
        # assemble_tracks(track_paths, output, target_duration_seconds,
        #                 self.settings.music_crossfade_seconds, self.settings.ffmpeg_audio_bitrate,
        #                 self.settings.intro_fade_seconds, self.settings.outro_fade_seconds,
        #                 self.settings.audio_silence_removal_enabled,
        #                 self.settings.audio_silence_threshold_db,
        #                 self.settings.audio_silence_min_seconds,
        #                 self.settings.audio_silence_keep_seconds, metadata=job_metadata)
        job_metadata.update(audio_path=str(output), audio_duration=self._probe_duration(output))
        return output

    def _concatenate_audio_legacy(
        self,
        track_paths: List[str],
        job_dir: Path,
        job_metadata: Dict[str, Any],
        target_duration_seconds: float,
    ) -> Optional[Path]:
        """Concatenate music tracks with crossfade.

        Args:
            track_paths: Paths to music files
            job_dir: Job output directory
            job_metadata: Job metadata dict to update

        Returns:
            Path to concatenated audio file
        """
        started = time.perf_counter()
        try:
            output_path = job_dir / "music" / "audio_concatenated.aac"
            block_path = job_dir / "music" / "audio_base_block.aac"
            output_path.parent.mkdir(parents=True, exist_ok=True)

            # Build one short crossfaded block, then loop that block to the target.
            success = self.music_provider.concatenate_tracks(
                track_paths,
                block_path,
                crossfade_duration=self.settings.jazz_audio_crossfade_seconds,
            )

            if not success:
                return None

            from app.utils.ffmpeg import find_ffmpeg
            ffmpeg_path = find_ffmpeg()
            if not ffmpeg_path:
                return None
            cmd = [
                str(ffmpeg_path),
                "-stream_loop", "-1",
                "-i", str(block_path),
                "-af", f"atrim=duration={target_duration_seconds},asetpts=N/SR/TB",
                "-t", str(target_duration_seconds),
                "-vn",
                "-c:a", "aac",
                "-b:a", self.settings.ffmpeg_audio_bitrate,
                "-f", "ipod",
                "-y", str(output_path),
            ]
            self.logger.info("Looping %s-track audio block to %.1fs", len(track_paths), target_duration_seconds)
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=900, **no_window_flags())
            if result.returncode != 0:
                self.logger.error("Audio loop FFmpeg error: %s", result.stderr[-4000:])
                return None

            final_duration = self.music_provider._get_audio_duration(output_path)
            self.logger.info(f"Final audio duration: {final_duration/60:.1f} minutes ({final_duration:.1f}s)")
            self.logger.info("Audio assembly time: %.1fs", time.perf_counter() - started)

            job_metadata["audio_duration"] = final_duration
            job_metadata["audio_path"] = str(output_path)

            return output_path

        except Exception as e:
            self.logger.error(f"Audio concatenation failed: {e}")
            return None

    def _build_timeline(
        self,
        image_files: List[Dict[str, Any]],
        audio_path: Path,
        job_dir: Path,
        job_metadata: Dict[str, Any]
    ) -> bool:
        """Build video timeline with images and motion effects.

        Args:
            image_files: Selected background images
            audio_path: Path to concatenated audio
            job_dir: Job output directory
            job_metadata: Job metadata dict to update

        Returns:
            True if successful
        """
        try:
            # Use absolute duration if available, else fallback
            audio_duration = job_metadata.get("absolute_video_duration", self.music_provider._get_audio_duration(audio_path))

            if len(image_files) != 1:
                self.logger.error("Expected exactly one background image, got %s", len(image_files))
                return False
            image_duration = audio_duration

            self.logger.info(f"Building timeline:")
            self.logger.info(f"  Total duration: {audio_duration/60:.1f} minutes")
            self.logger.info("  Number of images: 1")
            self.logger.info(f"  Static image duration: {image_duration/60:.1f} minutes ({image_duration:.1f}s)")

            # Reset timeline builder
            self.timeline_builder = TimelineBuilder(
                fps=self.settings.video_fps,
                transition_seconds=0.0,
            )

            # Add the single background to timeline
            img_file = image_files[0]
            kind = img_file.get("media", "image")
            self.logger.info("  Background: %s (%0.1f min)", Path(img_file["path"]).name, image_duration / 60)
            self.timeline_builder.add_clip(img_file["path"], "video" if kind == "video" else "image", duration_seconds=image_duration)

            job_metadata["timeline_duration"] = self.timeline_builder.get_total_duration()
            self.logger.info(f"Timeline total: {job_metadata['timeline_duration']/60:.1f} minutes ({job_metadata['timeline_duration']:.1f}s)")

            return True

        except Exception as e:
            self.logger.error(f"Timeline building failed: {e}")
            return False

    @staticmethod
    def _segment_fade_filter(segment_duration, settings, apply_intro, apply_outro):
        """Whole-frame fades trimmed to one segment.

        Intro fade applies only on the first part, outro fade only on the
        last part, so chunk boundaries stay invisible.
        """
        filters = []
        if apply_intro and settings.intro_fade_seconds:
            intro = min(settings.intro_fade_seconds, segment_duration / 2)
            if intro:
                filters.append(f'fade=t=in:st=0:d={intro}')
        if apply_outro and settings.outro_fade_seconds:
            outro = min(settings.outro_fade_seconds, segment_duration / 2)
            if outro:
                start = max(0, segment_duration - outro - 1 / settings.video_fps)
                filters.append(f'fade=t=out:st={start:.6f}:d={outro}')
        return ','.join(filters)

    def _build_segment_command(
        self,
        ffmpeg_path,
        backend,
        codec_args,
        prepared_background,
        audio_path,
        waveform_path,
        watermark_path,
        subscribe_path,
        subscribe_prepared,
        drift,
        margin,
        direction,
        target_duration,
        segment_index,
        segment_duration,
        audio_offset,
        part_path,
        job_metadata,
        background_is_video=False,
        loop_phase=0.0,
    ):
        """Build the single-encode FFmpeg command for one render segment.

        Mirrors the original whole-video encode: looped still image from the
        start, audio sought to ``audio_offset`` via input ``-ss`` (before
        ``-i``), identical waveform/watermark/subscribe overlays, trimmed
        fades, ``-t segment_duration``. With a looping video background the
        clip itself is stream-looped (muted: only the music input is mapped)
        and each part starts at ``loop_phase`` so motion stays continuous
        across parts. Returns ``(cmd, part_path)`` where
        the part is ``job_dir/output/render_part_{index:03d}.mp4``.
        """
        from app.video.branding import effect_filter

        width, height, fps = self.settings.video_width, self.settings.video_height, self.settings.video_fps
        threads = str(self.settings.render_cpu_threads)
        repeat = f'loop=loop=-1:size=1:start=0,setpts=N/({fps}*TB)'
        if background_is_video:
            static_fit = (
                f'scale={width}:{height}:'
                'force_original_aspect_ratio=increase:flags=lanczos,'
                f'crop={width}:{height},setsar=1,format=yuv420p'
            )
        elif drift:
            # Absolute timeline time keeps slow-pan motion continuous across parts.
            progress = f'min((t+{audio_offset})/{target_duration},1)'
            x = f'{margin}*({progress})' if direction else f'{margin}*(1-({progress}))'
            static_fit = (
                f'scale={width + margin}:{height + margin}:'
                'force_original_aspect_ratio=increase:flags=lanczos,'
                f'crop={width + margin}:{height + margin},'
                'setsar=1,format=yuv420p,'
                f'loop=loop=-1:size=1:start=0,setpts=N/({fps}*TB)'
                f",crop={width}:{height}:x='{x}':y='{margin}/2'"
            )
        else:
            static_fit = (
                f'scale={width}:{height}:'
                'force_original_aspect_ratio=increase:flags=lanczos,'
                f'crop={width}:{height},setsar=1,format=yuv420p,'
                f'loop=loop=-1:size=1:start=0,setpts=N/({fps}*TB)'
            )
        effect = effect_filter(self.settings.visual_effect, self.settings.visual_effect_opacity)
        if not background_is_video and not drift and self.settings.visual_effect in ('vintage','warm_film','faded_film','noir','sepia','cool_cinematic'):
            static_fit = static_fit.replace(',' + repeat, effect + ',' + repeat)
        else:
            static_fit += effect

        cmd = [str(backend), '-filter_complex_threads', threads,
               '-filter_threads', threads, '-threads', threads]

        # Video input: a still always starts at frame 0; a looping muted clip
        # is stream-looped (its audio is never mapped) and each part seeks to
        # loop_phase so motion continues across segment boundaries.
        if background_is_video:
            cmd.extend(["-stream_loop", "-1"])
            if loop_phase > 0:
                cmd.extend(["-ss", str(loop_phase)])
            cmd.extend(["-i", str(prepared_background)])
        else:
            cmd.extend(["-framerate", str(fps), "-i", str(prepared_background)])

        # Audio input: input seeking (-ss BEFORE -i) jumps straight to this
        # segment's offset without decoding earlier audio.
        cmd.extend(['-threads', threads])
        if audio_offset > 0:
            cmd.extend(['-ss', str(audio_offset)])
        cmd.extend(["-i", str(audio_path)])

        # Cache the static base and watermark once, even when GIFs animate above it.
        cache_base = not drift and not background_is_video and self.settings.visual_effect not in ('old_film','film_grain')
        if cache_base:
            static_fit = static_fit.replace(',' + repeat, '')
        # One connected graph always retains the base video, regardless of overlays.
        filters = [f'[0:v]{static_fit}[base]']
        label = 'base'
        input_index = 2
        if watermark_path:
            cmd.extend(['-loop', '1', '-i', str(watermark_path)])
            mark_width = max(1, round(width * self.settings.watermark_width_ratio))
            right = max(8, round(width * self.settings.watermark_right_padding_ratio))
            bottom = max(8, round(height * self.settings.watermark_bottom_padding_ratio))
            filters.append(f'[{input_index}:v]scale={mark_width}:-1,format=rgba,colorchannelmixer=aa={self.settings.watermark_opacity}[mark]')
            filters.append(f'[{label}][mark]overlay=x=W-w-{right}:y=H-h-{bottom}:shortest=1[marked]')
            label = 'marked'
            input_index += 1
        if cache_base:
            filters.append(f'[{label}]format=yuv420p,{repeat}[base_live]')
            label = 'base_live'
            job_metadata['static_composite_cached'] = True
        if subscribe_path:
            cmd.extend(['-i', str(subscribe_path)])
            duration = min(self._probe_duration(subscribe_path), self.settings.subscribe_animation_duration)
            frames = max(1, int(duration * 15))
            interval = self.settings.subscribe_overlay_interval_seconds
            sw = max(1, round(width * self.settings.subscribe_overlay_width_ratio))
            left = max(8, round(width * self.settings.subscribe_overlay_left_padding_ratio))
            bottom = max(8, round(height * self.settings.subscribe_overlay_bottom_padding_ratio))
            if subscribe_prepared:
                preparation = 'format=rgba'
            else:
                ch = min(self.settings.subscribe_crop_height_ratio, 1-self.settings.subscribe_crop_top_ratio)
                cw = min(self.settings.subscribe_crop_width_ratio, 1-self.settings.subscribe_crop_left_ratio)
                key = 'format=rgba,colorkey=0xFFFFFF:0.015:0.02,' if self.settings.subscribe_white_key_enabled else ''
                preparation = (f'crop=iw*{cw}:ih*{ch}:iw*{self.settings.subscribe_crop_left_ratio}:ih*{self.settings.subscribe_crop_top_ratio},'
                               f'{key}scale={sw}:-1,format=rgba')
            filters.append(f"[{input_index}:v]trim=duration={duration},fps=15,{preparation},loop=loop=-1:size={frames}:start=0,"
                           f"setpts='(floor(N/{frames})*{interval}+mod(N,{frames})/15)/TB'[subscribe]")
            filters.append(f"[{label}][subscribe]overlay=x=W-w-{left}:y=H-h-{bottom}:enable='lt(mod(t\\,{interval})\\,{duration:.3f})'[subscribed]")
            label = 'subscribed'
            input_index += 1
        from app.video.visualizer import add_visualizer
        group = job_metadata.get('visualizer_group') if self.settings.visualizer_enabled else None
        label = add_visualizer(cmd, filters, label, group, input_index, audio_offset)
        filters.append(f'[{label}]copy[outv]')
        cmd.extend(['-filter_complex', ';'.join(filters), '-map', '[outv]'])
        vis_disk_ok = vis_sound_ok = bool(group)
        job_metadata['visualizer_enabled'] = bool(group)

        # Fade the composed frame. Intro only on part 0, outro only on the last part.
        part_count = job_metadata.get("_segment_part_count", 1)
        fades = self._segment_fade_filter(
            segment_duration, self.settings,
            apply_intro=(segment_index == 0),
            apply_outro=(segment_index == part_count - 1),
        )
        if fades:
            if '-filter_complex' in cmd:
                if '[finalvis]' in cmd:
                    final_label = '[finalvis]'
                elif '[finalv]' in cmd:
                    final_label = '[finalv]'
                else:
                    final_label = '[outv]'
                index = cmd.index('-filter_complex') + 1
                cmd[index] += f';{final_label}{fades}[faded]'
                cmd[cmd.index(final_label)] = '[faded]'
            else:
                cmd[cmd.index('-vf') + 1] += ',' + fades

        cmd.extend([
            "-map", "1:a",
            "-pix_fmt", "yuv420p",
            "-colorspace", "bt709",
            "-color_primaries", "bt709",
            "-color_trc", "bt709",
            "-c:a", "copy",
            "-movflags", "+faststart",
            "-t", str(segment_duration),
            "-r", str(fps),
            "-y",
            str(part_path),
        ])
        cmd[-1:-1] = list(codec_args)
        cmd[0] = str(backend)
        return cmd, part_path

    def _render_video(self, job_dir, job_metadata, audio_path):
        """Existing background copy loop plus optional independent visualizer overlay."""
        try:
            if (self.settings.video_width, self.settings.video_height) not in ((854, 480), (1280, 720), (1920, 1080)):
                raise ValueError('Choose a supported quality preset: 480p, 720p, 1080p')
            clips = self.timeline_builder.clips
            if len(clips) != 1:
                raise ValueError('Expected exactly one assigned background clip')
            from app.utils.ffmpeg import find_ffmpeg, find_ffprobe
            from app.video.short_loop import render_loop
            from app.video.branding import loop_branding
            started = time.perf_counter()
            branding = loop_branding(job_dir, self.settings, job_metadata)
            watermark_path = self._find_watermark() if self.settings.watermark_enabled else None
            if watermark_path:
                job_metadata['watermark_path'] = str(watermark_path)
                job_metadata['watermark_enabled'] = True
            job_metadata.update(visualizer_enabled=False, visualizer_group=None,
                                waveform_enabled=False, waveform_animated=False,
                                waveform_preview_path=None, subscribe_overlay_enabled=False,
                                song_panel_enabled=False, video_fades_enabled=False,
                                visual_effect=self.settings.visual_effect,
                                visual_effect_opacity=self.settings.visual_effect_opacity,
                                motion_mode=self.settings.studio_motion_mode)
            job_metadata.setdefault('visualization_config', {}).update(
                visualizer_enabled=self.settings.visualizer_enabled, waveform_enabled=False,
                subscribe_overlay_enabled=self.settings.subscribe_overlay_enabled)
            output = render_loop(self.settings, job_dir, job_metadata, Path(clips[0].asset_path),
                                 clips[0].asset_type == 'video', audio_path, branding,
                                 find_ffmpeg(), find_ffprobe(), watermark=watermark_path)
            job_metadata['render_elapsed_seconds'] = round(time.perf_counter()-started, 3)
            self.logger.info('Short encode / background copy loop / final mux: %s', job_metadata['render_timings'])
            return output
        except Exception as error:
            self.logger.error('Short-loop rendering failed: %s', error, exc_info=True)
            job_metadata['render_error'] = str(error)[-6000:]
            return None

    def _render_video_segmented_legacy(
        self,
        job_dir: Path,
        job_metadata: Dict[str, Any],
        audio_path: Path
    ) -> Optional[Path]:
        """Render final video in short segments, then stream-copy concat.

        Each part encodes at most ``RENDER_SEGMENT_SECONDS`` so no single
        FFmpeg encode spans the full target duration. Parts are joined with
        ``ffmpeg -f concat -safe 0 -c copy`` and validated as one output.

        Args:
            job_dir: Job output directory
            job_metadata: Job metadata dict to update
            audio_path: Path to concatenated audio

        Returns:
            Path to rendered video
        """
        try:
            if (self.settings.video_width, self.settings.video_height) != (1920, 1080):
                raise ValueError("Production renders require 1920x1080; update the video settings")
            output_path = job_dir / "output" / "rendering.mp4"
            output_path.parent.mkdir(parents=True, exist_ok=True)

            self.logger.info(f"Rendering video: {output_path}")
            self.logger.info(f"  Resolution: {self.settings.video_width}x{self.settings.video_height}")
            self.logger.info(f"  FPS: {self.settings.video_fps}")

            from app.utils.ffmpeg import find_ffmpeg
            import math
            import subprocess

            ffmpeg_path = find_ffmpeg()
            if not ffmpeg_path:
                self.logger.error("FFmpeg not found")
                return None

            clips = self.timeline_builder.clips

            if not clips:
                self.logger.error("No clips in timeline")
                return None

            if len(clips) != 1:
                self.logger.error("Expected one timeline clip, got %s", len(clips))
                return None
            clip = clips[0]
            target_duration = float(job_metadata.get("target_duration_seconds", self.settings.target_duration_minutes * 60))
            watermark_path = self._find_watermark()
            subscribe_path = self._find_subscribe_video()
            subscribe_prepared = False
            if subscribe_path:
                prepared = self._prepare_subscribe_overlay(subscribe_path)
                if prepared:
                    subscribe_path = prepared
                    subscribe_prepared = True
            # Astrofox remains a manual reference; automated jobs always use
            # the native time-domain layer, even with a legacy flag in .env.
            waveform_path = None
            try:
                preparation_started = time.perf_counter()
                # FFmpeg decodes/scales one frame, then repeats it in memory.
                # No edited background file is created.
                prepared_background = Path(clip.asset_path)
                drift = self.settings.studio_motion_mode == 'drift'
                margin = max(2, round(self.settings.video_width * .018)) if drift else 0
                direction = None
                if drift:
                    direction = int(hashlib.sha256(job_dir.name.encode()).hexdigest()[:2], 16) % 2
                    job_metadata['motion_direction'] = 'right' if direction else 'left'
                from app.video.branding import effect_filter
                job_metadata.update(channel_branding_enabled=False, song_panel_enabled=False)
                job_metadata.update(visual_effect=self.settings.visual_effect, visual_effect_opacity=self.settings.visual_effect_opacity)
                job_metadata['motion_mode'] = self.settings.studio_motion_mode
                from app.video.visualizer import prepare_visualizer
                group = prepare_visualizer(self.settings)
                job_metadata.update(visualizer_group=group, visualizer_enabled=bool(group),
                                    visualizer_style='gif', waveform_enabled=False,
                                    waveform_animated=False, waveform_preview_path=None)
                job_metadata.setdefault('visualization_config', {}).update(
                    waveform_enabled=False, visualizer_enabled=bool(group))
                job_metadata['overlay_preparation_seconds'] = round(time.perf_counter() - preparation_started, 3)
                job_metadata["watermark_enabled"] = bool(watermark_path)
                job_metadata["watermark_width_pixels"] = max(1, round(self.settings.video_width * self.settings.watermark_width_ratio)) if watermark_path else 0
                job_metadata["watermark_opacity"] = self.settings.watermark_opacity if watermark_path else 0
                if subscribe_path:
                    job_metadata["subscribe_overlay_enabled"] = True
                    job_metadata["subscribe_overlay_path"] = str(subscribe_path)
                    job_metadata["subscribe_overlay_interval_seconds"] = self.settings.subscribe_overlay_interval_seconds
                    job_metadata["subscribe_overlay_position"] = "bottom_right"
                    job_metadata["subscribe_source_crop"] = [
                        self.settings.subscribe_crop_left_ratio,
                        self.settings.subscribe_crop_top_ratio,
                        min(self.settings.subscribe_crop_width_ratio, 1 - self.settings.subscribe_crop_left_ratio),
                        min(self.settings.subscribe_crop_height_ratio, 1 - self.settings.subscribe_crop_top_ratio),
                    ]
                    job_metadata["subscribe_asset_cached"] = subscribe_prepared
                else:
                    job_metadata["subscribe_overlay_enabled"] = False

                # Chunk the target duration so each encode stays short.
                segment_seconds = int(getattr(self.settings, "render_segment_seconds", 600) or 600)
                segment_seconds = max(60, min(1800, segment_seconds))
                part_count = max(1, math.ceil(target_duration / segment_seconds))
                job_metadata["_segment_part_count"] = part_count
                segments = []
                for index in range(part_count):
                    offset = float(index * segment_seconds)
                    duration = min(float(segment_seconds), target_duration - offset)
                    segments.append((index, offset, duration))
                self.logger.info("Segmented render: %d part(s) of up to %ss for %.1fs total",
                                 part_count, segment_seconds, target_duration)

                from app.video.encoding import choose_render_backend, encoder_args, render_with_progress
                backend, encoder, probe_failures = choose_render_backend(ffmpeg_path, self.settings)
                job_metadata.update(video_encoder=encoder, encoder_probe_failures=probe_failures, render_executable=str(backend))
                codec_args = encoder_args(encoder, self.settings)
                self.logger.info("Rendering with %s at %s FPS, %sx%s", encoder, self.settings.video_fps,
                                 self.settings.video_width, self.settings.video_height)

                render_started_all = time.perf_counter()
                timeouts = []
                part_paths = []
                background_is_video = (clip.asset_type == "video")
                loop_clip_duration = 0.0
                if background_is_video:
                    if drift:
                        self.logger.info("Drift disabled for looping video background; the clip itself moves")
                        drift = False
                    try:
                        loop_clip_duration = self._probe_duration(Path(clip.asset_path))
                    except Exception as error:
                        self.logger.warning("Loop clip probe failed, phase restarts per part: %s", error)
                for segment_index, audio_offset, segment_duration in segments:
                    part_path = job_dir / "output" / f"render_part_{segment_index:03d}.mp4"
                    part_paths.append(part_path)
                    cmd, _ = self._build_segment_command(
                        ffmpeg_path, backend, codec_args,
                        prepared_background, audio_path, waveform_path,
                        watermark_path, subscribe_path, subscribe_prepared,
                        drift, margin, direction, target_duration,
                        segment_index, segment_duration, audio_offset,
                        part_path, job_metadata,
                        background_is_video=background_is_video,
                        loop_phase=(audio_offset % loop_clip_duration) if loop_clip_duration > 0 else 0.0,
                    )
                    # A changed toggle/filter/asset must never reuse an old segment.
                    inputs = []
                    for position, argument in enumerate(cmd[:-1]):
                        if argument == '-i':
                            path = Path(cmd[position+1])
                            stat = path.stat()
                            inputs.append([str(path.resolve()), stat.st_size, stat.st_mtime_ns])
                    signature = hashlib.sha256(json.dumps([cmd,inputs],sort_keys=True,default=str).encode()).hexdigest()
                    signature_path = part_path.with_suffix('.json')
                    if part_path.exists() and signature_path.is_file():
                        try:
                            existing = self._probe_duration(part_path)
                            saved_signature = json.loads(signature_path.read_text(encoding='utf-8')).get('signature')
                            if saved_signature == signature and abs(existing - segment_duration) <= 2:
                                self.logger.info("Reusing render part %d/%d: %s (%.1fs)",
                                                 segment_index + 1, part_count, part_path, existing)
                                continue
                        except Exception:
                            pass
                        try:
                            part_path.unlink()
                        except OSError:
                            pass
                    self.logger.info("Rendering part %d/%d: %.1fs at offset %.1fs",
                                     segment_index + 1, part_count, segment_duration, audio_offset)
                    # Once production starts, surface failures. A late GPU failure must not
                    # silently restart a long render on the CPU; retry keeps prepared media.
                    timeouts.append(render_with_progress(cmd, job_dir, segment_duration, self.settings))
                    write_json(signature_path, {'signature': signature})
                    resources_path = job_dir / 'render_resources.json'
                    if resources_path.is_file():
                        job_metadata.setdefault('render_segment_resources', []).append(dict(segment=segment_index, resources=json.loads(resources_path.read_text(encoding='utf-8'))))
                job_metadata['render_timeout_seconds'] = timeouts

                # Stream-copy concat: no re-encode, identical codec params per part.
                parts_file = job_dir / "output" / "render_parts.txt"
                with open(parts_file, "w") as handle:
                    for part in part_paths:
                        handle.write(f"file '{part.absolute()}'\n")
                concat_cmd = [
                    str(ffmpeg_path), "-f", "concat", "-safe", "0",
                    "-i", str(parts_file), "-c", "copy",
                    "-movflags", "+faststart", "-y", str(output_path),
                ]
                concat_result = subprocess.run(concat_cmd, capture_output=True, text=True, timeout=600, **no_window_flags())
                if concat_result.returncode != 0:
                    raise RuntimeError(f"Segment concat failed: {concat_result.stderr[-3000:]}")

                job_metadata["video_path"] = str(output_path)
                job_metadata['render_timeout_seconds'] = timeouts
                job_metadata['render_elapsed_seconds'] = round(time.perf_counter() - render_started_all, 3)
                job_metadata["video_duration_seconds"] = self._probe_duration(output_path)
                job_metadata.update(render_segmented=True, render_segment_seconds=segment_seconds,
                                    render_part_count=part_count)
                self.logger.info(f"Video rendered successfully: {output_path}")
                self.logger.info("Video rendering time: %.1fs", time.perf_counter() - render_started_all)

                # Full success only: remove parts so a retry reuses nothing stale.
                for part in part_paths:
                    try:
                        part.unlink()
                        part.with_suffix('.json').unlink(missing_ok=True)
                    except OSError:
                        pass
                try:
                    parts_file.unlink()
                except OSError:
                    pass
                return output_path
            finally:
                job_metadata.pop("_segment_part_count", None)
                if waveform_path and waveform_path.exists() and job_metadata.get('video_path'):
                    waveform_path.unlink()
                    self.logger.info("Removed temporary waveform video: %s", waveform_path)

        except Exception as e:
            self.logger.error(f"Video rendering failed: {e}", exc_info=True)
            job_metadata['render_error'] = str(e)[-6000:]
            return None

    def _render_with_astrofox(
        self,
        image_path: str,
        audio_path: Path,
        output_path: Path,
        target_duration: float,
        watermark_path: Optional[Path],
    ) -> Optional[Path]:
        """Render the visualizer through the headless Astrofox-compatible bridge."""
        import shutil
        import subprocess

        project_root = Path(__file__).resolve().parents[2]
        script_path = project_root / self.settings.astrofox_visualizer_script
        node_path = shutil.which("node")
        if not node_path or not script_path.exists():
            self.logger.info("Astrofox bridge unavailable; using legacy visualizer")
            return None

        command = [
            node_path,
            str(script_path),
            "--audio", str(audio_path),
            "--image", str(image_path),
            "--output", str(output_path),
            "--resolution", f"{self.settings.video_width}x{self.settings.video_height}",
            "--fps", str(self.settings.video_fps),
            "--duration", str(target_duration),
            "--preset", self.settings.ffmpeg_preset,
            "--crf", str(self.settings.ffmpeg_crf),
            "--audio-bitrate", self.settings.ffmpeg_audio_bitrate,
            "--glow-opacity", str(self.settings.astrofox_glow_opacity),
            "--vignette-opacity", str(self.settings.astrofox_vignette_opacity),
        ]
        if watermark_path:
            command.extend(["--watermark", str(watermark_path), "--watermark-opacity", str(self.settings.watermark_opacity)])

        self.logger.info("Rendering with Astrofox visualizer bridge")
        result = subprocess.run(command, capture_output=True, text=True, timeout=3600, **no_window_flags())
        if result.returncode != 0 or not output_path.exists():
            self.logger.warning("Astrofox bridge failed; using legacy visualizer: %s", result.stderr[-2000:])
            return None
        self.logger.info("Astrofox visualizer render complete")
        return output_path

    def _find_watermark(self) -> Optional[Path]:
        """Find an optional PNG watermark without making it a render dependency."""
        if not self.settings.watermark_enabled:
            return None
        channel = self.context.get('channel', {}) or {}
        watermark_dir = Path(channel.get('watermark_path', 'watermark'))
        if not watermark_dir.exists():
            self.logger.info("Watermark directory not found: %s; continuing without watermark", watermark_dir)
            return None
        for candidate in sorted(watermark_dir.glob("*.png")):
            try:
                from PIL import Image
                with Image.open(candidate) as image:
                    image.verify()
                self.logger.info("Using watermark: %s", candidate)
                return candidate
            except Exception as error:
                self.logger.warning("Ignoring invalid watermark %s: %s", candidate, error)
        self.logger.warning("No valid PNG watermark found in %s; continuing without watermark", watermark_dir)
        return None

    def _find_subscribe_video(self) -> Optional[Path]:
        """Find the optional user-supplied subscribe popup video."""
        if not self.settings.subscribe_overlay_enabled:
            return None
        subscribe_dir = Path("subscribeVideo")
        if not subscribe_dir.exists():
            self.logger.warning("Subscribe overlay is enabled but subscribeVideo/ does not exist")
            return None
        for candidate in sorted(subscribe_dir.iterdir()):
            if not candidate.is_file() or candidate.suffix.lower() not in {".mp4", ".mov", ".mkv", ".webm"}:
                continue
            try:
                if self._probe_duration(candidate) > 0:
                    self.logger.info("Using subscribe overlay video: %s", candidate)
                    return candidate
            except Exception as error:
                self.logger.warning("Ignoring invalid subscribe overlay %s: %s", candidate, error)
        self.logger.warning("Subscribe overlay is enabled but no valid video exists in subscribeVideo/")
        return None

    def _prepare_subscribe_overlay(self, source: Path) -> Optional[Path]:
        """Cache a short scaled RGBA CTA so long renders avoid repeated crop/key work."""
        try:
            from app.utils.ffmpeg import find_ffmpeg
            duration = min(self._probe_duration(source), self.settings.subscribe_animation_duration)
            width = max(1, round(self.settings.video_width * self.settings.subscribe_overlay_width_ratio))
            crop_height = min(self.settings.subscribe_crop_height_ratio, 1 - self.settings.subscribe_crop_top_ratio)
            crop_width = min(self.settings.subscribe_crop_width_ratio, 1 - self.settings.subscribe_crop_left_ratio)
            identity = json.dumps({
                "path": str(source.resolve()), "mtime": source.stat().st_mtime_ns,
                "width": width, "duration": duration,
                "cache_version": 2,
                "crop": [self.settings.subscribe_crop_left_ratio, self.settings.subscribe_crop_top_ratio,
                         crop_width, crop_height], "key": self.settings.subscribe_white_key_enabled,
            }, sort_keys=True).encode()
            cache = Path("jobs") / ".cache"
            cache.mkdir(parents=True, exist_ok=True)
            output = cache / f"subscribe_{hashlib.sha256(identity).hexdigest()[:16]}.mov"
            if output.is_file() and output.stat().st_size:
                return output
            filters = (
                f"crop=iw*{crop_width}:ih*{crop_height}:"
                f"iw*{self.settings.subscribe_crop_left_ratio}:ih*{self.settings.subscribe_crop_top_ratio},"
            )
            if self.settings.subscribe_white_key_enabled:
                filters += "format=rgba,colorkey=0xFFFFFF:0.015:0.02,"
            filters += f"scale={width}:-1,format=rgba"
            result = subprocess.run([
                str(find_ffmpeg()), "-v", "error", "-y", "-i", str(source),
                "-t", str(duration), "-vf", filters, "-r", "15", "-an",
                "-c:v", "qtrle", "-pix_fmt", "argb", str(output),
            ], capture_output=True, text=True, timeout=120, **no_window_flags())
            if result.returncode or not output.is_file() or not output.stat().st_size:
                output.unlink(missing_ok=True)
                raise RuntimeError(result.stderr[-1000:] or "FFmpeg returned no CTA asset")
            self.logger.info("Prepared reusable subscribe overlay: %s", output)
            return output
        except Exception as error:
            self.logger.warning("Could not prepare subscribe overlay; using source clip: %s", error)
            return None

    def _create_waveform_asset(self, audio_path: Path, job_dir: Path) -> Optional[Path]:
        """Create one clean, rounded-bar waveform PNG from the final audio stream."""
        waveform_path = job_dir / "waveform.png"
        width = max(160, int(self.settings.video_width * self.settings.waveform_width_ratio))
        height = max(24, int(self.settings.video_height * self.settings.waveform_height_ratio))
        bar_count = max(80, min(360, width // 4))
        try:
            from PIL import Image, ImageDraw
            import numpy as np
            from app.utils.ffmpeg import find_ffmpeg

            ffmpeg_path = find_ffmpeg()
            if not ffmpeg_path:
                return None
            probe_duration = self._probe_duration(audio_path)
            result = subprocess.run(
                [str(ffmpeg_path), "-v", "error", "-i", str(audio_path), "-ac", "1", "-ar", "8000", "-f", "s16le", "-"],
                capture_output=True,
                timeout=max(60, int(probe_duration / 10)),
             **no_window_flags())
            if result.returncode != 0 or not result.stdout:
                self.logger.error("Waveform audio analysis failed: %s", result.stderr[-1000:])
                return None
            samples = np.frombuffer(result.stdout, dtype=np.int16).astype(np.float32) / 32768.0
            window_size = max(1, len(samples) // bar_count)
            usable = samples[:window_size * bar_count].reshape(bar_count, window_size)
            amplitudes = np.sqrt(np.mean(usable * usable, axis=1))
            if len(amplitudes) >= 5:
                amplitudes = np.convolve(amplitudes, np.ones(5) / 5, mode="same")
            scale = max(float(np.percentile(amplitudes, 98)), 1e-4)
            amplitudes = np.clip(amplitudes / scale, 0.08, 1.0)

            color = self.settings.waveform_color.replace("0x", "#")
            if len(color) == 7:
                color += "D9"
            image = Image.new("RGBA", (width, height), (0, 0, 0, 0))
            draw = ImageDraw.Draw(image)
            center_y = height // 2
            bar_width = max(2, int(width / (bar_count * 2.2)))
            gap = max(2, int((width - bar_count * bar_width) / max(1, bar_count - 1)))
            max_half = max(4, int(height * 0.45))
            for index, amplitude in enumerate(amplitudes):
                x = int(index * (bar_width + gap))
                half = max(2, int(max_half * float(amplitude)))
                draw.rounded_rectangle((x, center_y - half, x + bar_width, center_y + half), radius=bar_width // 2, fill=color)
            image.save(waveform_path, "PNG", optimize=True)
            self.logger.info("Waveform asset generated: %s (%s bars)", waveform_path, bar_count)
            return waveform_path
        except Exception as error:
            self.logger.error("Waveform asset generation failed: %s", error, exc_info=True)
            return None

    def _probe_duration(self, media_path: Path) -> float:
        return float(self._probe_media(media_path)['format']['duration'])

    def _probe_media(self, media_path: Path) -> Dict[str, Any]:
        from app.utils.ffmpeg import probe_media
        return probe_media(media_path)

    def _generate_thumbnail(
        self,
        job_dir: Path,
        job_metadata: Dict[str, Any]
    ) -> Optional[Path]:
        """Associate the immutable assigned thumbnail with the job.

        Args:
            job_dir: Job output directory
            job_metadata: Job metadata dict to update

        Returns:
            Path to generated thumbnail
        """
        try:
            source_path = Path(job_metadata.get("assets", {}).get("thumbnail", {}).get("path") or job_metadata.get("thumbnail_path", ""))
            if not source_path.exists():
                self.logger.error("Assigned thumbnail is missing: %s", source_path)
                return None

            job_thumbnail_path = source_path
            job_metadata["thumbnail_path"] = str(job_thumbnail_path)
            write_json(job_dir / "metadata.json", job_metadata)
            self.logger.info(f"Original thumbnail assigned: {job_thumbnail_path}")
            return job_thumbnail_path

        except Exception as e:
            self.logger.error(f"Thumbnail association failed: {e}")
            return None

    def _generate_metadata(
        self,
        job_dir: Path,
        job_metadata: Dict[str, Any]
    ) -> bool:
        """Generate YouTube SEO metadata using Gemini.

        Args:
            job_dir: Job output directory
            job_metadata: Job metadata dict to update

        Returns:
            True if successful
        """
        try:
            self.logger.info("Generating YouTube metadata...")
            if self.context.get('content_plan'):
                job_metadata.update(self.context['content_plan']['metadata'])
                from app.studio.editorial import apply_tracklist
                apply_tracklist(job_metadata)
                write_json(job_dir / 'metadata.json', job_metadata)
                return True
            if job_metadata.get('session_titles'):
                from app.studio.editorial import apply_tracklist
                apply_tracklist(job_metadata)
                write_json(job_dir / 'metadata.json', job_metadata)
                return True
            if self.context:
                from app.studio.profiles import metadata_for
                job_metadata.update(metadata_for(self.context['profile'], self.context['channel'], self.context['concept'], round(job_metadata['target_duration_seconds'] / 60)))
                write_json(job_dir / 'metadata.json', job_metadata)
                return True

            # Generate title, description, tags
            duration_minutes = round(job_metadata.get("target_duration_seconds", 5400) / 60)
            prompt = f"""Generate YouTube metadata for a long-form jazz video ({duration_minutes} minutes):
- Smooth, relaxing jazz music
- Perfect for studying, working, or relaxation
- Cinematic background visuals

Provide ONLY valid JSON with these exact fields:
{{
  "title": "YouTube title (under 70 chars, SEO-friendly)",
  "description": "YouTube description (2-3 sentences)",
  "tags": ["tag1", "tag2", "tag3", "tag4", "tag5"],
  "thumbnail_text": "2-4 word text for thumbnail"
}}"""

            job_metadata.update(youtube_title=f"{duration_minutes} Minutes of Jazz for Focus & Study",
                                youtube_description=f"Enjoy {duration_minutes} minutes of instrumental jazz for focus, study and relaxation.",
                                youtube_tags=["jazz", "study music", "focus music"])
            response = self.llm._generate_with_retry(prompt)

            # Parse JSON response
            import json as json_module
            try:
                # Extract JSON from response
                json_start = response.find("{")
                json_end = response.rfind("}") + 1
                if json_start >= 0 and json_end > json_start:
                    json_str = response[json_start:json_end]
                    metadata = json_module.loads(json_str)

                    job_metadata["youtube_title"] = metadata.get("title", f"Jazz Music - {duration_minutes} Minutes")
                    job_metadata["youtube_description"] = metadata.get(
                        "description",
                        "Relaxing jazz music for focus, study, and work."
                    )
                    job_metadata["youtube_tags"] = metadata.get(
                        "tags",
                        ["jazz", "smooth jazz", "relaxation", "focus music"]
                    )
                    job_metadata["thumbnail_text"] = metadata.get(
                        "thumbnail_text",
                        "Jazz Music"
                    )

                    self.logger.info(f"Title: {job_metadata['youtube_title']}")
                    self.logger.info(f"Tags: {', '.join(job_metadata['youtube_tags'])}")

            except json_module.JSONDecodeError:
                self.logger.warning("Failed to parse metadata JSON, using defaults")
                job_metadata["youtube_title"] = f"Jazz Music - {duration_minutes} Minutes for Relaxation & Focus"
                job_metadata["youtube_description"] = (
                    f"Enjoy {duration_minutes} minutes of smooth, relaxing jazz music. Perfect for studying, working, "
                    "relaxation, or background listening. High-quality audio with ambient visuals."
                )
                job_metadata["youtube_tags"] = [
                    "jazz", "smooth jazz", "relaxation", "focus music", "study music"
                ]
                job_metadata["thumbnail_text"] = "Jazz After Dark"

            # Save metadata
            write_json(job_dir / "metadata.json", job_metadata)

            return True

        except Exception as e:
            self.logger.error(f"Metadata generation failed: {e}")
            return False

    def _validate_output(
        self,
        job_dir: Path,
        video_path: Path,
        audio_path: Path,
        job_metadata: Dict[str, Any],
    ) -> bool:
        """Validate generated video output.

        Args:
            job_dir: Job output directory
            video_path: Path to generated video
            audio_path: Path to concatenated audio

        Returns:
            True if validation passed
        """
        try:
            self.logger.info("Validating output...")

            # Check video file exists and is valid
            if not video_path.exists():
                self.logger.error(f"Video file not found: {video_path}")
                return False

            # Check audio file exists
            if not audio_path.exists():
                self.logger.error(f"Audio file not found: {audio_path}")
                return False

            # Check video file size (H.264 @ 1920x1080 ~= 20-30MB per 10 minutes)
            video_size_mb = video_path.stat().st_size / (1024 * 1024)
            self.logger.info(f"Video file size: {video_size_mb:.1f}MB")

            # Minimum reasonable size for generated video
            if video_size_mb <= 0:
                self.logger.error(f"Video file too small: {video_size_mb:.1f}MB")
                return False

            media_info = self._probe_media(video_path)
            stream_types = {stream.get("codec_type") for stream in media_info.get("streams", [])}
            if not {"video", "audio"}.issubset(stream_types):
                self.logger.error("Output is missing a video or audio stream: %s", stream_types)
                return False
            video_stream = next(stream for stream in media_info["streams"] if stream.get("codec_type") == "video")
            if video_stream.get("width") != self.settings.video_width or video_stream.get("height") != self.settings.video_height:
                self.logger.error("Unexpected video dimensions: %sx%s", video_stream.get("width"), video_stream.get("height"))
                return False
            video_duration = float(media_info.get("format", {}).get("duration", 0))
            audio_duration = self._probe_duration(audio_path)
            target = job_metadata['target_duration_seconds']
            tolerance = self.settings.audio_duration_tolerance_seconds
            if abs(video_duration - target) > tolerance or abs(audio_duration - target) > tolerance:
                self.logger.error('Output does not match requested duration')
                return False
            if abs(video_duration - audio_duration) > self.settings.audio_duration_tolerance_seconds:
                self.logger.error(
                    "Video/audio duration mismatch: video=%.2fs audio=%.2fs",
                    video_duration,
                    audio_duration,
                )
                return False
            selected_images = job_metadata.get("selected_images", [])
            if len(selected_images) != 1:
                self.logger.error("Static-image acceptance failed: selected image count=%s", len(selected_images))
                return False
            if job_metadata.get('render_architecture') != 'short_clip_copy_loop' and getattr(self.settings, "visualizer_enabled", False) and not job_metadata.get("visualizer_enabled"):
                self.logger.error("Looping visualizer was enabled but not recorded in job metadata")
                return False
            from app.studio.assets import asset_sha256
            for kind in ("thumbnail", "background"):
                assigned = (job_metadata.get("assets") or {}).get(kind, {})
                if not assigned:
                    continue
                source, copy = Path(assigned["source"]), Path(assigned["path"])
                if not copy.is_file() or asset_sha256(source) != asset_sha256(copy):
                    self.logger.error("Job %s copy does not match its assigned source: %s", kind, copy)
                    return False
                if asset_sha256(source) != assigned.get("sha256"):
                    self.logger.error("Job %s source changed after assignment: %s", kind, source)
                    return False
            if (job_metadata.get("assets") or {}).get("thumbnail"):
                job_metadata["thumbnail_sha256"] = job_metadata["assets"]["thumbnail"].get("sha256")

            self.logger.info(
                "Video validation passed: one static image, %.2fs video, %.2fs audio",
                video_duration,
                audio_duration,
            )
            return True

        except Exception as e:
            self.logger.error(f"Validation failed: {e}")
            return False

