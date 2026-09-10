"""
Long-form Jazz video orchestrator.
Specialized pipeline for generating 90-minute jazz videos without narration or captions.
"""
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
        prompt_pairs = self._reserve_prompt_pairs(video_count)

        for i in range(video_count):
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
        job_id = self.context.get('job_id') or datetime.now().strftime("%Y%m%d_%H%M%S_%f") + f"_video_{video_index + 1:03d}"
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
        job_metadata = {}
        if self.context:
            job_metadata.update(channel_id=self.context['channel']['id'], content_id=self.context['content_id'],
                                profile_snapshot=self.context['profile'], channel_snapshot=self.context['channel'])
        job_metadata['render_config'] = {key: getattr(self.settings, key) for key in ('video_width', 'video_height', 'video_fps', 'ffmpeg_preset', 'ffmpeg_crf')}
        job_metadata["target_duration_seconds"] = target_duration_seconds
        job_metadata["visualization_config"] = {
            key: value for key, value in self.settings.model_dump().items()
            if key.startswith(("waveform_", "watermark_", "subscribe_"))
        }
        started_at = datetime.now().astimezone()
        job_metadata["started_at"] = started_at.isoformat()
        pipeline_started = time.perf_counter()
        job.metadata = job_metadata
        self.job_manager.update_job(job)

        try:
            stage_started = time.perf_counter()
            prompt_assets = self._prepare_prompt_assets(prompt_pair, job_dir, job_metadata)
            job_metadata['media_sourcing_seconds'] = round(time.perf_counter() - stage_started, 3)

            # Stage 1: DISCOVER & VALIDATE
            self.logger.info("\n[STAGE 1/7] DISCOVER & VALIDATE")
            music_files = self._select_music_files(job_dir, job_metadata, target_duration_seconds)
            if not music_files:
                raise Exception("Failed to select music files")

            job.stage = self.JAZZ_STAGES["DISCOVER_VALIDATE"]
            self.job_manager.update_job(job)
            self.logger.info(f"[OK] Selected {len(music_files)} music files\n")

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

            # Stage 6: APPLY MOTION & RENDER
            self.logger.info("[STAGE 6/7] APPLY MOTION & RENDER")
            job.stage = 'VIDEO_RENDERING'
            self.job_manager.update_job(job)
            video_path = self._render_video(job_dir, job_metadata, audio_path)
            if not video_path:
                raise Exception("Failed to render video")

            job.stage = self.JAZZ_STAGES["APPLY_MOTION_RENDER"]
            self.job_manager.update_job(job)
            self.logger.info(f"[OK] Video rendered: {video_path}\n")

            # Stage 7: VALIDATE & OUTPUT
            self.logger.info("[STAGE 7/7] VALIDATE & OUTPUT")
            if self._validate_output(job_dir, video_path, audio_path, job_metadata):
                self.logger.info("[OK] Output validation passed\n")
            else:
                raise Exception("Output validation failed")

            job.stage = self.JAZZ_STAGES["VALIDATE_OUTPUT"]
            self.job_manager.update_job(job)

            self._generate_metadata(job_dir, job_metadata)
            thumbnail_path = self._generate_thumbnail(job_dir, job_metadata)

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
            self.logger.info(f"Job ID:     {job_id}")
            self.logger.info(f"Video:      {video_path}")
            self.logger.info(f"Thumbnail:  {thumbnail_path if thumbnail_path else 'N/A'}")
            self.logger.info(f"Status:     {job.status.upper()}")
            self.logger.info("Total generation time: %.1fs", time.perf_counter() - pipeline_started)
            self.logger.info("=" * 60)

            return True

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

            loop_count = max(2, min(4, self.settings.audio_loop_track_count))
            sequence = list(available_files)
            random.shuffle(sequence)
            selected = sequence[:min(loop_count, len(sequence))]
            raw_total = sum(track["duration"] for track in selected)
            crossfade_reduction = max(0, len(selected) - 1) * self.settings.jazz_audio_crossfade_seconds
            base_duration = raw_total - crossfade_reduction
            repetitions = max(1, int(target_duration_seconds / max(base_duration, 1)) + 1)
            final_duration = target_duration_seconds

            self.logger.info("Selected Music Tracks:")
            for i, track in enumerate(selected, 1):
                self.logger.info(f"  {i}. {track['filename']} ({track['duration']/60:.1f}m)")

            self.logger.info(
                f"\nAudio Selection Summary:"
                f"\n  Base tracks selected: {len(selected)}"
                f"\n  Raw total: {raw_total/60:.1f}m ({raw_total:.0f}s)"
                f"\n  Crossfade reduction: {crossfade_reduction:.0f}s"
                f"\n  Base block duration: {base_duration/60:.1f}m ({base_duration:.0f}s)"
                f"\n  Block repetitions: {repetitions}"
                f"\n  Target duration: {final_duration/60:.1f}m ({final_duration:.0f}s)"
            )

            # Update metadata
            job_metadata["selected_music"] = [m["filename"] for m in selected]
            job_metadata["music_total_duration_raw"] = raw_total
            job_metadata["music_base_block_duration"] = base_duration
            job_metadata["music_repetitions"] = repetitions
            job_metadata["music_total_duration"] = final_duration
            job_metadata["music_count"] = len(selected)
            job_metadata["music_source_count"] = len(selected)

            return selected

        except Exception as e:
            self.logger.error(f"Music selection failed: {e}", exc_info=True)
            return []

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
        """Generate exactly one background and one paired thumbnail for a run."""
        self._asset_fallbacks = []
        project_root = Path(__file__).resolve().parents[2]
        background_prompt = prompt_pair["background"]
        background_dir = job_dir / "background_images"
        thumbnail_dir = job_dir / "thumbnail"
        background_dir.mkdir(parents=True, exist_ok=True)
        thumbnail_dir.mkdir(parents=True, exist_ok=True)

        background_path = background_dir / "background.png"
        thumbnail_path = thumbnail_dir / "thumbnail.png"

        self.logger.info("Background prompt %s: %s", background_prompt["id"], background_prompt["title"])
        self._generate_or_reuse_image(background_prompt, background_path, "background", job_metadata)
        self.logger.info("Background image ready: %s", background_path)

        if self.context and self.context['channel']['thumbnail_style'] == 'branded':
            from app.studio.assets import make_thumbnail
            make_thumbnail(background_path, thumbnail_path, self.context['concept'], self.context['channel'])
            thumbnail_source = background_path
        else:
            thumbnail_source = self._select_local_thumbnail()
            shutil.copy2(thumbnail_source, thumbnail_path)
        self.logger.info("Thumbnail ready: %s", thumbnail_path)

        job_metadata["background_prompt"] = background_prompt
        job_metadata["thumbnail_source"] = str(thumbnail_source.resolve())
        job_metadata["generated_background_path"] = str(background_path)
        job_metadata["thumbnail_path"] = str(thumbnail_path)
        job_metadata["fallback_used"] = bool(self._asset_fallbacks)
        job_metadata["fallback_assets"] = list(self._asset_fallbacks)
        with open(job_dir / "prompt_assets.json", "w", encoding="utf-8") as metadata_file:
            json.dump(
                {
                    "background": background_prompt,
                    "thumbnail_source": str(thumbnail_source.resolve()),
                    "background_path": str(background_path),
                    "thumbnail_path": str(thumbnail_path),
                },
                metadata_file,
                indent=2,
            )

        return {
            "background_path": background_path,
            "thumbnail_path": thumbnail_path,
        }

    def _select_local_thumbnail(self) -> Path:
        """Choose one readable thumbnail at random from the user-managed folder."""
        thumbnail_dir = Path(self.context.get('channel', {}).get('thumbnail_dir', 'thumbnail'))
        candidates = []
        if thumbnail_dir.exists():
            for candidate in thumbnail_dir.iterdir():
                if not candidate.is_file() or candidate.suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp"}:
                    continue
                try:
                    from PIL import Image
                    with Image.open(candidate) as image:
                        image.verify()
                    candidates.append(candidate)
                except Exception as error:
                    self.logger.warning("Ignoring invalid local thumbnail %s: %s", candidate, error)
        if not candidates:
            raise RuntimeError("No valid thumbnail found in thumbnail/. Add a PNG, JPG, JPEG, or WEBP file there.")
        selected = random.choice(candidates)
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

                with Image.open(output_path) as image:
                    image.verify()
                self.logger.info("Reusing existing %s image: %s", asset_type, output_path)
                return output_path
            except Exception:
                self.logger.warning("Existing %s image is invalid; regenerating: %s", asset_type, output_path)

        generation_error = None
        try:
            if self.settings.colab_image_enabled and self.settings.colab_image_api_url:
                from colab_image_service import ColabImageService

                self.logger.info("Calling configured Colab image API for %s", asset_type)
                ColabImageService(
                    api_url=self.settings.colab_image_api_url,
                    timeout_seconds=self.settings.colab_image_timeout_seconds,
                    bypass_password=self.settings.colab_image_bypass_password,
                    api_key=self.settings.colab_image_api_key,
                ).generate_image(
                    positive_prompt=record["prompt"],
                    negative_prompt="blurry, low quality, distortion, text, watermark",
                    width=1280 if asset_type == "thumbnail" else self.settings.video_width,
                    height=720 if asset_type == "thumbnail" else self.settings.video_height,
                    steps=20,
                    seed=-1,
                    output_path=output_path,
                )
            elif self.settings.pollination_image_enabled:
                from pollination_service import generate_image

                generate_image(
                    record["prompt"],
                    model="flux",
                    width=1920 if asset_type == "background" else 1280,
                    height=1080 if asset_type == "background" else 720,
                    output_path=output_path,
                )
            else:
                raise RuntimeError("External image generation is disabled; using local assets")
            if not output_path.exists() or output_path.stat().st_size == 0:
                raise RuntimeError(f"{asset_type.title()} generation returned no file")
            from PIL import Image
            with Image.open(output_path) as image:
                image.verify()
            self.logger.info("%s image generated successfully: %s", asset_type.title(), output_path)
            return output_path
        except Exception as error:
            generation_error = re.sub(r'([?&](?:key|api_key|token)=)[^&\s)]+', r'\1[redacted]', str(error))
            self.logger.warning("%s image generation failed: %s", asset_type.title(), generation_error)

        fallback_dirs = (
            [Path(self.context.get('channel', {}).get('background_dir', 'backgroundImages')), Path(self.context.get('channel', {}).get('thumbnail_dir', 'thumbnails'))] if asset_type == "background"
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
                with Image.open(candidate) as image:
                    image.verify()
                valid_candidates.append(candidate)
            except Exception as error:
                self.logger.warning("Ignoring invalid fallback %s image %s: %s", asset_type, candidate, error)
        if valid_candidates:
            fallback_source = valid_candidates[0]
            shutil.copy2(fallback_source, output_path)
            fallback_message = f"{asset_type}: {fallback_source} ({generation_error})"
            self._asset_fallbacks.append(fallback_message)
            if job_metadata is not None:
                job_metadata.setdefault("fallback_errors", []).append(generation_error)
            self.logger.warning("%s generation failed; using existing %s image: %s", asset_type.title(), asset_type, fallback_source)
            return output_path

        raise RuntimeError(
            f"{asset_type.title()} generation failed and no valid fallback exists: {generation_error}"
        )

    def _select_background_image(
        self,
        job_dir: Path,
        job_metadata: Dict[str, Any],
        target_duration_seconds: float,
        preferred_image_path: Path,
    ) -> List[Dict[str, Any]]:
        """Use exactly one generated background for the whole video."""
        preferred_image_path = Path(preferred_image_path)
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

    def _concatenate_audio(
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
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=900)
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

            # Add each image to timeline
            img_file = image_files[0]
            self.logger.info("  Static image: %s (%0.1f min)", Path(img_file["path"]).name, image_duration / 60)
            self.timeline_builder.add_clip(img_file["path"], "image", duration_seconds=image_duration)

            job_metadata["timeline_duration"] = self.timeline_builder.get_total_duration()
            self.logger.info(f"Timeline total: {job_metadata['timeline_duration']/60:.1f} minutes ({job_metadata['timeline_duration']:.1f}s)")

            return True

        except Exception as e:
            self.logger.error(f"Timeline building failed: {e}")
            return False

    def _render_video(
        self,
        job_dir: Path,
        job_metadata: Dict[str, Any],
        audio_path: Path
    ) -> Optional[Path]:
        """Render final video.

        Args:
            job_dir: Job output directory
            job_metadata: Job metadata dict to update
            audio_path: Path to concatenated audio

        Returns:
            Path to rendered video
        """
        try:
            output_path = job_dir / "output" / "final_90min_video.mp4"
            output_path.parent.mkdir(parents=True, exist_ok=True)

            self.logger.info(f"Rendering video: {output_path}")
            self.logger.info(f"  Resolution: {self.settings.video_width}x{self.settings.video_height}")
            self.logger.info(f"  FPS: {self.settings.video_fps}")

            from app.utils.ffmpeg import find_ffmpeg
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
            static_fit = (
                f"scale={self.settings.video_width}:{self.settings.video_height}:"
                "force_original_aspect_ratio=increase:flags=lanczos:eval=init,"
                f"crop={self.settings.video_width}:{self.settings.video_height},setsar=1,format=yuv420p"
            )
            waveform_path = None
            try:
                preparation_started = time.perf_counter()
                # Decode, resize and crop the still once instead of at every output frame.
                from PIL import Image, ImageOps
                prepared_background = job_dir / 'render_background.png'
                drift = self.settings.studio_motion_mode == 'drift'
                margin = max(2, round(self.settings.video_width * .018)) if drift else 0
                with Image.open(clip.asset_path) as image:
                    ImageOps.fit(image.convert('RGB'), (self.settings.video_width + margin, self.settings.video_height + margin),
                                 method=Image.Resampling.LANCZOS).save(prepared_background)
                static_fit = 'setsar=1,format=yuv420p'
                if drift:
                    direction = int(hashlib.sha256(job_dir.name.encode()).hexdigest()[:2], 16) % 2
                    progress = f'min(t/{target_duration},1)'
                    x = f'{margin}*({progress})' if direction else f'{margin}*(1-({progress}))'
                    static_fit = f"crop={self.settings.video_width}:{self.settings.video_height}:x='{x}':y='{margin}/2'," + static_fit
                    job_metadata['motion_direction'] = 'right' if direction else 'left'
                job_metadata['motion_mode'] = self.settings.studio_motion_mode
                if self.settings.waveform_enabled:
                    from app.video.waveform import create_waveform
                    waveform_path, waveform_metadata = create_waveform(
                        audio_path, job_dir, self.settings, target_duration
                    )
                    job_metadata.update(waveform_metadata)
                    if not waveform_path:
                        self.logger.warning("Waveform generation failed; rendering without waveform")
                job_metadata['overlay_preparation_seconds'] = round(time.perf_counter() - preparation_started, 3)
                # Build FFmpeg command
                cmd = [str(ffmpeg_path)]

                # Add image inputs
                cmd.extend(["-loop", "1", "-framerate", str(self.settings.video_fps), "-i", str(prepared_background)])

                # Add audio input
                cmd.extend(["-i", str(audio_path)])

                if waveform_path:
                    cmd.extend(["-i", str(waveform_path)])
                if watermark_path:
                    cmd.extend(["-loop", "1", "-i", str(watermark_path)])
                if subscribe_path:
                    cmd.extend(["-i", str(subscribe_path)])

                if waveform_path:
                    wave_x, wave_y = job_metadata["waveform_overlay_xy"]
                    filter_complex = (
                        f"[0:v]{static_fit}[bg];"
                        f"[2:v]format=rgba[wave];"
                        f"[bg][wave]overlay=x={wave_x}:y={wave_y}:shortest=1:format=auto[with_wave];"
                    )
                    if watermark_path:
                        watermark_width = max(1, round(self.settings.video_width * self.settings.watermark_width_ratio))
                        watermark_right = max(8, int(self.settings.video_width * self.settings.watermark_right_padding_ratio))
                        watermark_bottom = max(8, int(self.settings.video_height * self.settings.watermark_bottom_padding_ratio))
                        opacity = max(0.0, min(1.0, self.settings.watermark_opacity))
                        filter_complex += (
                            f"[3:v]scale={watermark_width}:-1,format=rgba,colorchannelmixer=aa={opacity}[mark];"
                            f"[with_wave][mark]overlay=x=W-w-{watermark_right}:y=H-h-{watermark_bottom}:shortest=1[outv]"
                        )
                    else:
                        filter_complex += "[with_wave]copy[outv]"
                    cmd.extend(["-filter_complex", filter_complex, "-map", "[outv]"])
                    job_metadata["waveform_enabled"] = True
                    job_metadata["waveform_position"] = "centered_at_vertical_anchor"
                else:
                    if watermark_path:
                        watermark_width = max(1, round(self.settings.video_width * self.settings.watermark_width_ratio))
                        watermark_right = max(8, int(self.settings.video_width * self.settings.watermark_right_padding_ratio))
                        watermark_bottom = max(8, int(self.settings.video_height * self.settings.watermark_bottom_padding_ratio))
                        opacity = max(0.0, min(1.0, self.settings.watermark_opacity))
                        filter_complex = (
                            f"[0:v]{static_fit}[bg];[2:v]scale={watermark_width}:-1,format=rgba,"
                            f"colorchannelmixer=aa={opacity}[mark];"
                            f"[bg][mark]overlay=x=W-w-{watermark_right}:y=H-h-{watermark_bottom}:shortest=1[outv]"
                        )
                        cmd.extend(["-filter_complex", filter_complex, "-map", "[outv]"])
                    else:
                        if subscribe_path:
                            filter_complex = f"[0:v]{static_fit}[outv]"
                            cmd.extend(["-filter_complex", filter_complex, "-map", "[outv]"])
                        else:
                            cmd.extend(["-vf", static_fit, "-map", "0:v"])
                    job_metadata["waveform_enabled"] = False
                job_metadata["watermark_enabled"] = bool(watermark_path)
                job_metadata["watermark_width_pixels"] = watermark_width if watermark_path else 0
                job_metadata["watermark_opacity"] = self.settings.watermark_opacity if watermark_path else 0

                if subscribe_path:
                    subscribe_input_index = 2 + int(bool(waveform_path)) + int(bool(watermark_path))
                    subscribe_width = max(1, round(self.settings.video_width * self.settings.subscribe_overlay_width_ratio))
                    subscribe_left = max(8, round(self.settings.video_width * self.settings.subscribe_overlay_left_padding_ratio))
                    subscribe_bottom = max(8, round(self.settings.video_height * self.settings.subscribe_overlay_bottom_padding_ratio))
                    subscribe_duration = min(self._probe_duration(subscribe_path), self.settings.subscribe_animation_duration)
                    interval = self.settings.subscribe_overlay_interval_seconds
                    subscribe_frames = max(1, int(subscribe_duration * 15))
                    crop_height = min(self.settings.subscribe_crop_height_ratio, 1 - self.settings.subscribe_crop_top_ratio)
                    crop_top = self.settings.subscribe_crop_top_ratio
                    crop_width = min(self.settings.subscribe_crop_width_ratio, 1 - self.settings.subscribe_crop_left_ratio)
                    crop_left = self.settings.subscribe_crop_left_ratio
                    if subscribe_prepared:
                        subscribe_filters = "format=rgba,"
                    else:
                        white_key = "format=rgba,colorkey=0xFFFFFF:0.015:0.02," if self.settings.subscribe_white_key_enabled else ""
                        subscribe_filters = (
                            f"crop=iw*{crop_width}:ih*{crop_height}:iw*{crop_left}:ih*{crop_top},"
                            f"{white_key}scale={subscribe_width}:-1,format=rgba,"
                        )
                    filter_complex = (
                        f"{filter_complex};"
                        f"[{subscribe_input_index}:v]trim=duration={subscribe_duration},fps=15,"
                        f"{subscribe_filters}"
                        f"loop=loop=-1:size={subscribe_frames}:start=0,"
                        f"setpts='(floor(N/{subscribe_frames})*{interval}+mod(N,{subscribe_frames})/15)/TB'[subscribe];"
                        f"[outv][subscribe]overlay=x={subscribe_left}:y=H-h-{subscribe_bottom}:"
                        f"enable='lt(mod(t\\,{interval})\\,{subscribe_duration:.3f})'[finalv]"
                    )
                    cmd[cmd.index("-filter_complex") + 1] = filter_complex
                    cmd[cmd.index("[outv]")] = "[finalv]"
                    job_metadata["subscribe_overlay_enabled"] = True
                    job_metadata["subscribe_overlay_path"] = str(subscribe_path)
                    job_metadata["subscribe_overlay_interval_seconds"] = interval
                    job_metadata["subscribe_overlay_duration_seconds"] = subscribe_duration
                    job_metadata["subscribe_overlay_position"] = "bottom_left"
                    job_metadata["subscribe_source_crop"] = [crop_left, crop_top, crop_width, crop_height]
                    job_metadata["subscribe_asset_cached"] = subscribe_prepared
                else:
                    job_metadata["subscribe_overlay_enabled"] = False

                cmd.extend([
                "-map", "1:a",
                "-c:v", "libx264",
                "-pix_fmt", "yuv420p",
                "-preset", self.settings.ffmpeg_preset,
                "-crf", str(self.settings.ffmpeg_crf),
                "-tune", "stillimage",
                "-colorspace", "bt709",
                "-color_primaries", "bt709",
                "-color_trc", "bt709",
                "-c:a", "copy",
                "-movflags", "+faststart",
                "-shortest",
                "-t", str(target_duration),
                "-r", str(self.settings.video_fps),
                "-y",
                str(output_path),
                ])

                self.logger.debug(f"FFmpeg command: {' '.join(cmd)}")
                render_started = time.perf_counter()
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=3600)

                if result.returncode != 0:
                    self.logger.error("FFmpeg exited unexpectedly with code %s", result.returncode)
                    self.logger.error("FFmpeg stderr: %s", result.stderr[-4000:])
                    return None

                job_metadata["video_path"] = str(output_path)
                job_metadata['render_elapsed_seconds'] = round(time.perf_counter() - render_started, 3)
                job_metadata["video_duration_seconds"] = self._probe_duration(output_path)
                self.logger.info(f"Video rendered successfully: {output_path}")
                self.logger.info("Video rendering time: %.1fs", time.perf_counter() - render_started)

                return output_path
            finally:
                if waveform_path and waveform_path.exists():
                    waveform_path.unlink()
                    self.logger.info("Removed temporary waveform video: %s", waveform_path)

        except Exception as e:
            self.logger.error(f"Video rendering failed: {e}", exc_info=True)
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
        result = subprocess.run(command, capture_output=True, text=True, timeout=3600)
        if result.returncode != 0 or not output_path.exists():
            self.logger.warning("Astrofox bridge failed; using legacy visualizer: %s", result.stderr[-2000:])
            return None
        self.logger.info("Astrofox visualizer render complete")
        return output_path

    def _find_watermark(self) -> Optional[Path]:
        """Find an optional PNG watermark without making it a render dependency."""
        if not self.settings.watermark_enabled:
            return None
        watermark_dir = Path("watermark")
        if not watermark_dir.exists():
            self.logger.info("Watermark directory not found; continuing without watermark")
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
        self.logger.warning("No valid PNG watermark found; continuing without watermark")
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
            ], capture_output=True, text=True, timeout=120)
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
            )
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
        """Return media duration from ffprobe or raise a useful error."""
        from app.utils.ffmpeg import find_ffprobe
        import subprocess

        ffprobe_path = find_ffprobe()
        if not ffprobe_path:
            raise RuntimeError("ffprobe not found; cannot verify media duration")
        result = subprocess.run(
            [str(ffprobe_path), "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", str(media_path)],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0 or not result.stdout.strip():
            raise RuntimeError(f"ffprobe failed for {media_path}: {result.stderr.strip()}")
        return float(result.stdout.strip())

    def _probe_media(self, media_path: Path) -> Dict[str, Any]:
        """Return FFprobe stream and format information for validation."""
        from app.utils.ffmpeg import find_ffprobe

        ffprobe_path = find_ffprobe()
        if not ffprobe_path:
            raise RuntimeError("ffprobe not found; cannot validate media streams")
        result = subprocess.run(
            [str(ffprobe_path), "-v", "error", "-show_streams", "-show_format", "-of", "json", str(media_path)],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            raise RuntimeError(f"ffprobe failed for {media_path}: {result.stderr.strip()}")
        return json.loads(result.stdout)

    def _generate_thumbnail(
        self,
        job_dir: Path,
        job_metadata: Dict[str, Any]
    ) -> Optional[Path]:
        """Associate the already-generated Pollination thumbnail with the job.

        Args:
            job_dir: Job output directory
            job_metadata: Job metadata dict to update

        Returns:
            Path to generated thumbnail
        """
        try:
            source_path = Path(job_metadata.get("thumbnail_path", ""))
            if not source_path.exists():
                self.logger.error("Generated thumbnail is missing: %s", source_path)
                return None

            job_thumbnail_path = source_path
            job_metadata["thumbnail_path"] = str(job_thumbnail_path)
            write_json(job_dir / "metadata.json", job_metadata)
            self.logger.info(f"Thumbnail generated: {job_thumbnail_path}")
            return job_thumbnail_path

        except Exception as e:
            self.logger.error(f"Thumbnail generation failed: {e}")
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
            if self.settings.waveform_enabled and not job_metadata.get("waveform_enabled"):
                self.logger.error("Waveform was enabled but not recorded in job metadata")
                return False

            self.logger.info(
                "Video validation passed: one static image, %.2fs video, %.2fs audio",
                video_duration,
                audio_duration,
            )
            return True

        except Exception as e:
            self.logger.error(f"Validation failed: {e}")
            return False
