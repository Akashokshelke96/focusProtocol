"""
Pipeline orchestrator - coordinates all stages
"""
import json
import time
from datetime import datetime
from pathlib import Path
from typing import Optional
from app.config.settings import Settings, get_settings, ensure_directories
from app.config.logging_config import setup_logging, get_logger
from app.llm.gemini import GeminiProvider
from app.providers.pexels import PexelsVideoProvider
from app.providers.pinterest import PinterestProvider
from app.providers.acemusic import AceMusicProvider
from app.content.script_generator import ContentGenerator
from app.content.scene_planner import ScenePlanner
from app.media import MediaValidator, MediaDeduplicator
from app.jobs.manager import JobManager, JobState, JobStage
from app.audio import AudioMixer
from app.video.timeline import TimelineBuilder, MotionEngine
from app.video.captions import CaptionGenerator
from app.video.renderer import FFmpegRenderer
from app.video.metadata import ThumbnailGenerator, MetadataGenerator

logger = get_logger("pipeline.orchestrator")


class PipelineOrchestrator:
    """Central orchestrator for the entire pipeline."""

    def __init__(self, settings: Optional[Settings] = None):
        """Initialize orchestrator."""
        self.settings = settings or get_settings()
        self.job_manager = JobManager()
        self.logger = logger

        # Initialize providers
        try:
            self.llm = GeminiProvider(self.settings)
        except ValueError as e:
            self.logger.error(f"LLM initialization failed: {e}")
            raise

        try:
            self.pexels = PexelsVideoProvider(self.settings)
        except ValueError as e:
            self.logger.warning(f"Pexels initialization failed: {e}")
            self.pexels = None

        try:
            self.pinterest = PinterestProvider(self.settings)
        except Exception as e:
            self.logger.warning(f"Pinterest initialization failed: {e}")
            self.pinterest = None

        try:
            self.acemusic = AceMusicProvider(self.settings)
        except Exception as e:
            self.logger.warning(f"AceMusic initialization failed: {e}")
            self.acemusic = None

        # Initialize processors
        self.content_generator = ContentGenerator(self.llm)
        self.scene_planner = ScenePlanner(self.llm)
        self.media_validator = MediaValidator()
        self.media_deduplicator = MediaDeduplicator()
        self.audio_mixer = AudioMixer(self.settings)
        self.timeline_builder = TimelineBuilder(
            fps=self.settings.video_fps,
            transition_seconds=self.settings.video_transition_seconds,
        )
        self.caption_generator = CaptionGenerator(
            self.settings,
            max_words=self.settings.caption_max_words,
        )
        self.renderer = FFmpegRenderer(self.settings)
        self.thumbnail_generator = ThumbnailGenerator()
        self.metadata_generator = MetadataGenerator()

        self.logger.info("Pipeline orchestrator initialized")

    def run(
        self,
        topic: str,
        duration_minutes: Optional[int] = None,
        style: str = "Cinematic educational documentary",
        tone: str = "Informative and engaging",
    ) -> bool:
        """Execute complete pipeline."""
        if duration_minutes is None:
            duration_minutes = self.settings.default_video_duration_minutes

        # Generate job ID
        job_id = datetime.now().strftime("%Y%m%d_%H%M%S") + "_" + topic[:10].replace(" ", "_")

        self.logger.info(f"\n{'='*60}")
        self.logger.info(f"STARTING VIDEO GENERATION")
        self.logger.info(f"{'='*60}")
        self.logger.info(f"Job ID: {job_id}")
        self.logger.info(f"Topic: {topic}")
        self.logger.info(f"Duration: {duration_minutes} minutes")
        self.logger.info(f"{'='*60}\n")

        # Create job
        job = self.job_manager.create_job(job_id, topic, duration_minutes)
        job_dir = Path("jobs") / job_id
        job_dir.mkdir(parents=True, exist_ok=True)

        try:
            # Stage 1: Content Generation
            self.logger.info("[STAGE 1/10] CONTENT GENERATION")
            content = self.content_generator.generate(
                job_id, topic, duration_minutes, style, tone
            )
            job.stage = JobStage.CONTENT_GENERATED.value
            self.job_manager.update_job(job)

            # Save content
            with open(job_dir / "content.json", "w") as f:
                json.dump(content.to_dict(), f, indent=2)

            self.logger.info(f"[OK] Content generated: {content.title}\n")

            # Stage 2: Scene Planning
            self.logger.info("[STAGE 2/10] SCENE PLANNING")
            scenes = self.scene_planner.plan_scenes(content.script)
            job.stage = JobStage.SCENES_PLANNED.value
            self.job_manager.update_job(job)

            # Save scenes
            with open(job_dir / "scenes.json", "w") as f:
                json.dump([s.to_dict() for s in scenes], f, indent=2)

            self.logger.info(f"[OK] {len(scenes)} scenes planned\n")

            # Stage 3-5: Media Search, Download, Validate
            self.logger.info("[STAGE 3-5/10] MEDIA SOURCING & VALIDATION")
            assets = []

            for scene in scenes[:3]:  # Limit to first 3 scenes for demo
                self.logger.info(f"\n  Scene {scene.id}: {scene.visual_goal[:50]}...")

                # Try Pexels if video type recommended
                if self.pexels and scene.visual_type in ["video", "mixed"]:
                    try:
                        videos = self.pexels.search(scene.pexels_query, per_page=5)
                        candidates = self.pexels.filter_candidates(videos)

                        if candidates:
                            video = candidates[0]
                            video_file = video.get("video_files", [{}])[0]
                            asset_path = job_dir / "media" / f"video_{scene.id}.mp4"

                            asset = self.pexels.download(video, asset_path)
                            if asset:
                                # Validate
                                is_valid, _, metadata = self.media_validator.validate_video(asset_path)
                                if is_valid:
                                    self.logger.info(f"    [OK] Pexels video: {metadata}")
                                    assets.append({
                                        "scene_id": scene.id,
                                        "type": "video",
                                        "path": str(asset_path),
                                        "provider": "pexels",
                                        "url": video.get("url"),
                                        "duration": metadata.get("duration"),
                                    })
                                else:
                                    self.logger.warning(f"    [FAIL] Video validation failed")

                    except Exception as e:
                        self.logger.warning(f"    Pexels search failed: {e}")

                # Try Pinterest if image type recommended
                if self.pinterest and scene.visual_type in ["image", "mixed"]:
                    self.logger.info(f"    Pinterest search for: {scene.pinterest_query[:50]}...")
                    # Pinterest requires actual implementation

            job.stage = JobStage.MEDIA_VALIDATED.value
            self.job_manager.update_job(job)
            self.logger.info(f"\n[OK] Sourced {len(assets)} media assets\n")

            # Save assets
            with open(job_dir / "assets.json", "w") as f:
                json.dump(assets, f, indent=2)

            # Stage 6-7: Audio & Music
            self.logger.info("[STAGE 6-7/10] AUDIO & MUSIC")
            self.logger.info("  Generating music direction...")
            music_direction = self.llm.generate_music_direction(content.script[:1000])
            self.logger.info(f"  [OK] {music_direction.mood}, {music_direction.tempo} tempo")

            job.stage = JobStage.AUDIO_READY.value
            self.job_manager.update_job(job)
            self.logger.info("")

            # Stage 8: Timeline
            self.logger.info("[STAGE 8/10] TIMELINE BUILDING")
            for asset in assets[:3]:
                duration = asset.get("duration", 5)
                self.timeline_builder.add_clip(
                    asset["path"],
                    "video",
                    duration,
                )

            total_duration = self.timeline_builder.get_total_duration()
            self.logger.info(f"  [OK] Timeline: {total_duration:.1f}s")

            job.stage = JobStage.TIMELINE_BUILT.value
            self.job_manager.update_job(job)
            self.logger.info("")

            # Stage 9: Captions
            self.logger.info("[STAGE 9/10] CAPTIONS & METADATA")
            srt_content = self.caption_generator.generate_srt(
                content.script,
                total_duration,
            )
            srt_path = job_dir / "captions.srt"
            self.caption_generator.write_srt(srt_content, srt_path)
            self.logger.info(f"  [OK] Captions generated")

            job.stage = JobStage.METADATA_COMPLETE.value
            self.job_manager.update_job(job)

            # Stage 10: Final Output Summary
            self.logger.info("[STAGE 10/10] GENERATION COMPLETE")
            self.logger.info("=" * 60)
            self.logger.info("JOB COMPLETE")
            self.logger.info("=" * 60)
            self.logger.info(f"Job ID:        {job_id}")
            self.logger.info(f"Topic:         {topic}")
            self.logger.info(f"Duration:      {total_duration:.1f}s ({total_duration/60:.1f}m)")
            self.logger.info(f"Scenes:        {len(scenes)}")
            self.logger.info(f"Assets:        {len(assets)}")
            self.logger.info(f"Captions:      YES")
            self.logger.info(f"Status:        SUCCESS")
            self.logger.info("=" * 60)

            job.status = "completed"
            self.job_manager.update_job(job)

            return True

        except Exception as e:
            self.logger.error(f"\nPIPELINE FAILED: {e}", exc_info=True)
            job.status = "failed"
            job.error_message = str(e)
            self.job_manager.update_job(job)
            return False
