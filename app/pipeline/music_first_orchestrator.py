from __future__ import annotations
"""
Music-First Pipeline Orchestrator - Episode 1 Generation
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
from app.media import MediaValidator
from app.media.style_scorer import VisualStyleScorer
from app.jobs.manager import JobManager, JobState, JobStage
from app.audio import AudioMixer
from app.video.timeline import TimelineBuilder, MotionEngine
from app.video.renderer import FFmpegRenderer
from app.video.metadata import ThumbnailGenerator, MetadataGenerator

logger = get_logger("pipeline.orchestrator")


class MusicFirstOrchestrator:
    """Music-first pipeline orchestrator for dark blues channel."""

    def __init__(self, settings: Optional[Settings] = None):
        self.settings = settings or get_settings()
        self.job_manager = JobManager()
        self.logger = logger
        self.channel_profile = self.settings.get_channel_profile()

        # Initialize providers
        try:
            self.llm = GeminiProvider(self.settings)
        except ValueError as e:
            self.logger.error(f"LLM initialization failed: {e}")
            raise

        self.pexels = None
        self.pinterest = None
        self.acemusic = None

        try:
            self.pexels = PexelsVideoProvider(self.settings)
        except ValueError as e:
            self.logger.warning(f"Pexels initialization failed: {e}")

        try:
            self.pinterest = PinterestProvider(self.settings)
        except Exception as e:
            self.logger.warning(f"Pinterest initialization failed: {e}")

        try:
            self.acemusic = AceMusicProvider(self.settings)
        except Exception as e:
            self.logger.warning(f"AceMusic initialization failed: {e}")

        # Initialize processors
        self.media_validator = MediaValidator()
        self.style_scorer = VisualStyleScorer(self.settings)
        self.audio_mixer = AudioMixer(self.settings)
        self.timeline_builder = TimelineBuilder(
            fps=self.settings.video_fps,
            transition_seconds=self.settings.video_transition_seconds,
        )
        self.renderer = FFmpegRenderer(self.settings)
        self.thumbnail_generator = ThumbnailGenerator()
        self.metadata_generator = MetadataGenerator()

        self.logger.info("Music-First Pipeline Orchestrator initialized")

    def run(self, duration_minutes: Optional[int] = None) -> bool:
        """Execute music-first pipeline."""
        if duration_minutes is None:
            duration_minutes = self.settings.default_video_duration_minutes

        job_id = datetime.now().strftime("%Y%m%d_%H%M%S") + "_episode_1"

        self.logger.info(f"\n{'='*60}")
        self.logger.info(f"SILENT DARK BLUES - EPISODE 1")
        self.logger.info(f"{'='*60}")
        self.logger.info(f"Job ID: {job_id}")
        self.logger.info(f"Duration: {duration_minutes} minutes")
        self.logger.info(f"{'='*60}\n")

        job = self.job_manager.create_job(job_id, "Silent Dark Blues Episode 1", duration_minutes)
        job_dir = Path("jobs") / job_id
        job_dir.mkdir(parents=True, exist_ok=True)

        try:
            # STAGE 1: Music Generation (PRIMARY)
            self.logger.info("[STAGE 1/6] MUSIC GENERATION")
            music_path = self._stage_music_generation(job_dir, duration_minutes)
            if not music_path:
                raise Exception("Music generation failed")
            job.stage = JobStage.AUDIO_READY.value
            self.job_manager.update_job(job)
            self.logger.info("")

            # STAGE 2: Get Music Duration
            self.logger.info("[STAGE 2/6] ANALYZE MUSIC DURATION")
            music_duration = self._get_audio_duration(music_path)
            self.logger.info(f"  Music duration: {music_duration:.1f}s\n")

            # STAGE 3: Generate Hero Image Prompts (PROFILE-CONSTRAINED)
            self.logger.info("[STAGE 3/6] HERO IMAGE GENERATION")
            hero_prompts = self._stage_hero_image_prompts(music_duration)
            self.logger.info(f"  ✓ Generated {len(hero_prompts)} hero image prompts\n")

            # STAGE 4: Source Hero Images
            self.logger.info("[STAGE 4/6] SOURCE HERO IMAGES")
            hero_images = self._stage_source_hero_images(job_dir, hero_prompts)
            self.logger.info(f"  ✓ Sourced {len(hero_images)} hero images\n")

            # STAGE 5: Build Timeline (MUSIC-DRIVEN)
            self.logger.info("[STAGE 5/6] BUILD TIMELINE")
            timeline = self._stage_build_timeline(hero_images, music_duration)
            self.logger.info(f"  ✓ Timeline built: {len(timeline)} clips\n")

            # STAGE 6: Render Final Video
            self.logger.info("[STAGE 6/6] RENDER FINAL VIDEO")
            output_path = self._stage_render_video(
                job_dir, hero_images, music_path, timeline
            )

            job.stage = JobStage.VIDEO_COMPLETE.value
            self.job_manager.update_job(job)

            self.logger.info(f"\n{'='*60}")
            self.logger.info("EPISODE 1 COMPLETE")
            self.logger.info(f"{'='*60}")
            self.logger.info(f"Output: {output_path}")
            self.logger.info(f"Status: SUCCESS")
            self.logger.info(f"{'='*60}\n")

            job.status = "completed"
            self.job_manager.update_job(job)

            return True

        except Exception as e:
            self.logger.error(f"\nPIPELINE FAILED: {e}", exc_info=True)
            job.status = "failed"
            job.error_message = str(e)
            self.job_manager.update_job(job)
            return False

    def _stage_music_generation(self, job_dir: Path, duration_minutes: int) -> Optional[Path]:
        """Generate music using ACE-Step or fallback to mock."""
        try:
            # Get music prompt from Gemini (profile-constrained)
            self.logger.info("  Generating music prompt...")
            music_prompt = self.llm.generate_music_prompt(self.channel_profile)

            # Generate music candidates
            duration_seconds = duration_minutes * 60
            self.logger.info(f"  Generating music ({duration_seconds}s)...")
            candidates = self.acemusic.generate_music_candidates(
                music_prompt,
                count=4,
                duration_seconds=duration_seconds,
            )

            if not candidates:
                raise Exception("No music candidates generated")

            # Download candidates
            candidate_files = []
            for i, candidate in enumerate(candidates):
                music_file = job_dir / "music" / f"candidate_{i}.wav"
                if self.acemusic.download_candidate(candidate, music_file):
                    candidate_files.append(music_file)
                else:
                    # Use mock music generator if download fails
                    from app.audio.mock_generator import generate_mock_music
                    if generate_mock_music(music_file, duration_seconds):
                        candidate_files.append(music_file)

            if not candidate_files:
                # Ultimate fallback: generate mock music directly
                from app.audio.mock_generator import generate_mock_music
                music_file = job_dir / "music" / "episode_1.wav"
                if generate_mock_music(music_file, duration_seconds):
                    candidate_files.append(music_file)
                else:
                    raise Exception("Failed to generate any music")

            # Validate and select best
            self.logger.info(f"  Validating {len(candidate_files)} candidates...")
            best_candidate, best_audio = self.acemusic.select_best_candidate(
                candidates, candidate_files
            )

            self.logger.info(f"  ✓ Music selected: {best_audio.name}")
            return best_audio

        except Exception as e:
            self.logger.error(f"Music generation failed: {e}")
            return None

    def _get_audio_duration(self, audio_path: Path) -> float:
        """Get audio file duration."""
        try:
            import ffmpeg

            probe = ffmpeg.probe(str(audio_path))
            return float(probe["format"]["duration"])
        except Exception as e:
            self.logger.error(f"Failed to get duration: {e}")
            return 300.0  # Fallback to 5 minutes

    def _stage_hero_image_prompts(self, music_duration: float) -> list[dict]:
        """Generate hero image prompts from channel profile."""
        try:
            self.logger.info("  Generating hero image prompts from profile...")

            # Calculate number of images needed
            shot_duration = self.settings.shot_duration_optimal_seconds
            num_images = int(music_duration / shot_duration)
            num_images = max(5, min(8, num_images))

            prompts = self.llm.generate_hero_image_prompts(
                self.channel_profile, num_images
            )

            return prompts
        except Exception as e:
            self.logger.error(f"Hero prompt generation failed: {e}")
            return self._fallback_hero_prompts()

    def _fallback_hero_prompts(self) -> list[dict]:
        """Fallback hero image prompts from profile."""
        return [
            {
                "id": 1,
                "prompt": "1920s British gentleman in dark suit and fedora, smoking cigarette, looking out window at rain, low-key rim lighting, dark charcoal and navy color palette, moody film noir aesthetic",
                "search_query": "gentleman noir smoking window rain 1920s fedora dark",
            },
            {
                "id": 2,
                "prompt": "Sophisticated man holding whiskey glass in dim pub, cigarette smoke visible, warm amber lamp light, dark wood and brass details, introspective expression, vintage 1930s ambience",
                "search_query": "gentleman pub whiskey noir vintage 1930s smoking",
            },
            {
                "id": 3,
                "prompt": "Gentleman in waistcoat and suspenders, standing by desk with cigarette smoke backlit, cool blue-gray noir color grading, leather chair visible, melancholic atmosphere",
                "search_query": "gentleman office desk noir smoking 1920s desk",
            },
            {
                "id": 4,
                "prompt": "Man in suit smoking at bar counter in dimly lit gentleman's club, rim-lit face from side light, dark shadows, sophisticated moody atmosphere, vintage aesthetic",
                "search_query": "gentleman bar noir smoking vintage club atmosphere",
            },
            {
                "id": 5,
                "prompt": "Gentleman in leather armchair at night, smoking cigar, lamplight creating dramatic shadows, dark blue-black background, contemplative isolated mood, film noir style",
                "search_query": "gentleman armchair noir smoking contemplative vintage",
            },
        ]

    def _stage_source_hero_images(self, job_dir: Path, prompts: list[dict]) -> list[dict]:
        """Source hero images - try Pinterest, fallback to Pexels atmospheric."""
        hero_images = []

        for prompt in prompts:
            self.logger.info(f"  Sourcing: {prompt['id']}...")
            image_path = job_dir / "images" / f"hero_{prompt['id']}.jpg"

            # Try Pinterest first
            if self.pinterest:
                try:
                    results = self.pinterest.search(prompt["search_query"], per_page=1)
                    if results:
                        if self.pinterest.download(results[0], image_path):
                            score = self.style_scorer.score_image(image_path)
                            if score >= self.settings.visual_style_score_threshold:
                                self.logger.info(
                                    f"    ✓ Pinterest (score: {score:.2f})"
                                )
                                hero_images.append(
                                    {
                                        "id": prompt["id"],
                                        "path": str(image_path),
                                        "source": "pinterest",
                                        "style_score": score,
                                    }
                                )
                                continue
                except Exception as e:
                    self.logger.warning(f"    Pinterest failed: {e}")

            # Fallback to Pexels atmospheric
            if self.pexels:
                try:
                    results = self.pexels.search(prompt["search_query"], per_page=5)
                    if results:
                        for video in results:
                            if self.pexels.download(video, image_path):
                                score = self.style_scorer.score_image(image_path)
                                if score >= self.settings.visual_style_score_threshold:
                                    self.logger.info(f"    ✓ Pexels (score: {score:.2f})")
                                    hero_images.append(
                                        {
                                            "id": prompt["id"],
                                            "path": str(image_path),
                                            "source": "pexels",
                                            "style_score": score,
                                        }
                                    )
                                    break
                except Exception as e:
                    self.logger.warning(f"    Pexels failed: {e}")

            # Generate placeholder if sourcing failed
            if not any(i["id"] == prompt["id"] for i in hero_images):
                self._create_placeholder_image(image_path)
                self.logger.info(f"    ✓ Placeholder created")
                hero_images.append(
                    {
                        "id": prompt["id"],
                        "path": str(image_path),
                        "source": "placeholder",
                        "style_score": 0.5,
                    }
                )

        return hero_images

    def _create_placeholder_image(self, output_path: Path) -> None:
        """Create dark noir placeholder image."""
        from PIL import Image, ImageDraw

        output_path.parent.mkdir(parents=True, exist_ok=True)

        img = Image.new("RGB", (1920, 1080), color=(20, 20, 30))
        draw = ImageDraw.Draw(img)

        # Add gradient effect
        for y in range(1080):
            shade = int(20 + (y / 1080) * 40)
            draw.line([(0, y), (1920, y)], fill=(shade, shade, shade + 20))

        img.save(output_path, "JPEG", quality=95)

    def _stage_build_timeline(self, hero_images: list[dict], music_duration: float) -> list[dict]:
        """Build timeline with long shot durations."""
        timeline = []
        total_time = 0

        for i, image in enumerate(hero_images):
            # Distribute remaining time evenly
            remaining_time = music_duration - total_time
            remaining_clips = len(hero_images) - i

            shot_duration = remaining_time / remaining_clips
            shot_duration = max(
                self.settings.shot_duration_min_seconds,
                min(self.settings.shot_duration_max_seconds, shot_duration),
            )

            timeline.append(
                {
                    "id": i,
                    "image_path": image["path"],
                    "start_time": total_time,
                    "duration": shot_duration,
                    "motion": "subtle_zoom",
                    "motion_strength": self.settings.motion_strength,
                }
            )

            total_time += shot_duration

        self.logger.info(f"  Timeline: {len(timeline)} clips, {total_time:.1f}s total")
        return timeline

    def _stage_render_video(
        self,
        job_dir: Path,
        hero_images: list[dict],
        music_path: Path,
        timeline: list[dict],
    ) -> Path:
        """Render final video with FFmpeg."""
        try:
            output_path = job_dir / "output" / "episode_1.mp4"
            output_path.parent.mkdir(parents=True, exist_ok=True)

            self.logger.info(f"  Rendering to: {output_path}")

            # Use renderer to create video
            success = self.renderer.render_timeline(
                timeline,
                str(music_path),
                str(output_path),
                width=self.settings.video_width,
                height=self.settings.video_height,
                fps=self.settings.video_fps,
            )

            if success:
                self.logger.info("  ✓ Render complete")
                return output_path
            else:
                raise Exception("Render failed")

        except Exception as e:
            self.logger.error(f"Render failed: {e}")
            raise
