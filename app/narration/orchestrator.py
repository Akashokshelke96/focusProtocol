"""End-to-end narrated pipeline orchestrator.

Script (OpenRouter) -> local approval -> remote RunPod TTS + WhisperX ->
scene manifest -> ComfyUI images -> FFmpeg assembly -> validation/export.

Persists every stage through the shared JobManager so the existing
dashboard, job history and live logs keep working unchanged.
"""
from __future__ import annotations
import json
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from app.config.logging_config import get_logger
from app.config.settings import Settings, get_settings
from app.jobs.manager import JobManager
from app.llm.gemini import GeminiProvider
from app.narration.audio_engine import AudioEngine
from app.narration.comfy_client import ComfyUIClient
from app.narration.config import narration_dirs, require_remote
from app.narration.models import AlignmentResult, SceneManifest, ScriptPlan
from app.narration.scene_manifest import SceneManifestBuilder, compose_positive
from app.narration.script_generator import ScriptDeclined, ScriptGenerator
from app.narration.video_assembler import AssemblyError, VideoAssembler
from app.utils.ffmpeg import probe_media
from app.youtube.state import publishing_lock, write_json

logger = get_logger("narration.orchestrator")


class NarrationOrchestrator:
    def __init__(self, settings: Optional[Settings] = None, context: Optional[dict] = None):
        self.settings = settings or get_settings()
        self.context = context or {}
        self.job_manager = JobManager()
        self.llm = GeminiProvider(self.settings)
        self.script_generator = ScriptGenerator(self.settings, self.llm)
        self.manifest_builder = SceneManifestBuilder(self.settings, self.llm)
        self.assembler = VideoAssembler(self.settings)
        self.cancel_requested = False
        self.last_job_ids: list[str] = []
        self.logger = logger

    # ---------------------------------------------------------------- public
    def run(self, topic: str, duration_minutes: Optional[float] = None,
            auto_approve: bool = False, count: int = 1,
            resume_job_id: Optional[str] = None) -> bool:
        with publishing_lock(Path("jobs") / "generation"):
            if resume_job_id:
                return self.resume(resume_job_id)
            minutes = float(duration_minutes or self.settings.narration_target_duration_minutes)
            success = 0
            for index in range(max(1, count)):
                if self.cancel_requested:
                    break
                if self._run_single(topic, minutes, auto_approve, index):
                    success += 1
            return success == max(1, count)

    def resume(self, job_id: str) -> bool:
        """Continue an approved job from the remote stages without regenerating the script."""
        job = self.job_manager.get_job(job_id)
        if not job:
            raise ValueError(f"Job not found: {job_id}")
        job_dir = Path("jobs") / job_id
        plan = ScriptGenerator.load(job_dir)
        if not plan or not plan.approved:
            raise ValueError("Job has no approved script to resume; run it normally first")
        metadata = {**(job.metadata or {}), "generation_status": "running"}
        job.status, job.error_message = "running", None
        job.metadata = metadata
        self.job_manager.update_job(job)
        return self._execute(job, job_dir, metadata, plan,
                             float(job.duration_minutes or self.settings.narration_target_duration_minutes))

    # --------------------------------------------------------------- single
    def _run_single(self, topic: str, duration_minutes: float, auto_approve: bool, index: int) -> bool:
        job_id = self.context.get("job_id") or (
            datetime.now().strftime("%Y%m%d_%H%M%S_%f") + f"_narration_{index + 1:03d}")
        self.last_job_ids.append(job_id)
        target_seconds = int(duration_minutes * 60)
        job = self.job_manager.create_job(job_id, topic, int(duration_minutes))
        dirs = narration_dirs(Path("jobs") / job_id)
        started_at = datetime.now().astimezone()

        metadata: dict[str, Any] = dict(job.metadata or {})
        metadata.update(
            narration_mode=True,
            topic=topic,
            target_duration_seconds=target_seconds,
            started_at=started_at.isoformat(),
            render_config={
                key: getattr(self.settings, key) for key in (
                    "video_width", "video_height", "video_fps", "ffmpeg_preset",
                    "ffmpeg_crf", "narration_motion", "narration_motion_strength",
                    "comfy_steps", "comfy_cfg")
            },
        )
        job.metadata = metadata
        self.job_manager.update_job(job)

        try:
            self._stage(job, "SCRIPT")
            try:
                plan = self.script_generator.run_gate(topic, duration_minutes, dirs["job"],
                                                      auto_approve=auto_approve)
            except ScriptDeclined:
                metadata["generation_status"] = "cancelled"
                metadata["completed_at"] = datetime.now().astimezone().isoformat()
                job.status, job.error_message = "failed", "Script rejected by operator"
                write_json(dirs["job"] / "metadata.json", metadata)
                self.job_manager.update_job(job)
                return False
            metadata["script"] = {
                "title": plan.title, "path": str((dirs["script"] / "script.json").resolve()),
                "word_count": plan.word_count,
                "estimated_duration_seconds": plan.estimated_duration_seconds,
                "approved": plan.approved, "edited": plan.edited,
            }
            self.job_manager.update_job(job)
            return self._execute(job, dirs["job"], metadata, plan, duration_minutes)
        except Exception as error:  # noqa: BLE001 - persisted as a failed job
            self._fail(job, dirs["job"], metadata, started_at, error)
            return False

    # -------------------------------------------------------------- stages
    def _execute(self, job, job_dir: Path, metadata: dict, plan: ScriptPlan,
                 duration_minutes: float) -> bool:
        dirs = narration_dirs(job_dir)
        started_at = datetime.fromisoformat(metadata.get("started_at") or
                                            datetime.now().astimezone().isoformat())
        try:
            require_remote(self.settings)
            audio = AudioEngine(self.settings, dirs["audio"])

            self._stage(job, "REMOTE_CHECK")
            client = ComfyUIClient(self.settings, on_log=lambda message: logger.info(message))
            stats = client.health()
            metadata["comfy_system_stats"] = {
                key: stats.get(key) for key in ("system",) if isinstance(stats, dict)
            }
            self.job_manager.update_job(job)

            self._stage(job, "TTS")
            narration_path = dirs["audio"] / "narration.wav"
            audio.synthesize(plan.script, narration_path)
            duration_seconds = self._probe_seconds(narration_path)
            metadata["narration_audio"] = str(narration_path)
            metadata["narration_duration_seconds"] = duration_seconds
            self.job_manager.update_job(job)

            self._stage(job, "ALIGN")
            alignment = audio.align(narration_path) or audio.estimate_alignment(plan.script, duration_seconds)
            write_json(dirs["alignment"] / "alignment.json", alignment.model_dump())
            metadata["alignment_source"] = alignment.source
            metadata["alignment_segments"] = len(alignment.segments)
            self.job_manager.update_job(job)

            self._stage(job, "MANIFEST")
            manifest = self.manifest_builder.build(plan, alignment, duration_seconds, str(narration_path))
            write_json(dirs["manifest"] / "manifest.json", manifest.model_dump())
            metadata["scene_count"] = len(manifest.scenes)
            self.job_manager.update_job(job)

            self._stage(job, "IMAGES")
            self._generate_images(job, manifest, client, dirs["images"], metadata)
            self._fill_missing_images(manifest)
            write_json(dirs["manifest"] / "manifest.json", manifest.model_dump())
            self.job_manager.update_job(job)

            self._stage(job, "ASSEMBLE")
            output_path = dirs["output"] / "rendered.mp4"
            self.assembler.assemble(manifest, narration_path, output_path, dirs["output"])
            metadata["video_path"] = str(output_path)
            self.job_manager.update_job(job)

            self._stage(job, "THUMBNAIL")
            thumbnail_path = self._generate_thumbnail(job, manifest, client, dirs["thumbnail"])
            metadata["thumbnail_path"] = str(thumbnail_path) if thumbnail_path else ""

            self._stage(job, "VALIDATE")
            self._validate(output_path, duration_seconds, metadata)

            self._stage(job, "EXPORT")
            metadata["export"] = self.assembler.export(
                output_path, Path(thumbnail_path) if thumbnail_path else None, job.id)

            self._stage(job, "COMPLETE")
            fallback = manifest.alignment_source == "estimated" or bool(metadata.get("image_fallbacks"))
            job.status = "completed_with_fallback" if fallback else "completed"
            completed_at = datetime.now().astimezone()
            metadata.update(generation_status=job.status, completed_at=completed_at.isoformat(),
                            total_elapsed_seconds=round((completed_at - started_at).total_seconds(), 3))
            job.metadata = metadata
            write_json(job_dir / "metadata.json", metadata)
            self.job_manager.update_job(job)
            client.close()
            self.logger.info("Narration job %s finished: %s", job.id, job.status)
            return True
        except Exception as error:  # noqa: BLE001 - persisted as a failed job
            self._fail(job, job_dir, metadata, started_at, error)
            return False

    def _generate_images(self, job, manifest: SceneManifest, client: ComfyUIClient,
                         image_dir: Path, metadata: dict) -> None:
        requests_map: dict[str, dict] = {}
        for scene in manifest.scenes:
            positive = compose_positive(manifest.style_prefix, scene.prompt)
            negative = manifest.negative_prompt if self.settings.comfy_negative_prompt_enabled else ""
            workflow, seed = client.build_prompt(
                positive, negative, self.settings.video_width, self.settings.video_height,
                filename_prefix=f"scene_{scene.index:04d}")
            scene.seed = seed
            requests_map[str(scene.index)] = workflow

        total = len(requests_map)
        metadata["image_total"] = total
        failed_keys: list[str] = []

        def on_progress(done: int, _total: int) -> None:
            job.metadata["image_progress"] = {"done": done, "total": _total}
            self.logger.info("[Images %s/%s]", done, _total)

        def on_error(key: str, message: str) -> None:
            failed_keys.append(key)
            self.logger.warning("Scene %s failed: %s", key, message)

        results = client.generate_batch(requests_map, on_progress=on_progress,
                                        on_error=on_error, image_dir=image_dir)
        for scene in manifest.scenes:
            paths = results.get(str(scene.index)) or []
            if paths:
                scene.image_path = str(paths[-1])
        generated = sum(1 for scene in manifest.scenes if scene.image_path)
        metadata["image_count"] = generated
        if failed_keys:
            metadata["image_fallbacks"] = sorted(set(failed_keys))
        self.job_manager.update_job(job)

    @staticmethod
    def _fill_missing_images(manifest: SceneManifest) -> None:
        """Reuse the nearest generated image so every scene has a visual."""
        available = [scene for scene in manifest.scenes if scene.image_path]
        if not available:
            raise AssemblyError("ComfyUI produced no images; cannot assemble the video")
        fallback = available[0].image_path
        for scene in manifest.scenes:
            if not scene.image_path:
                scene.image_path = fallback
            else:
                fallback = scene.image_path

    def _generate_thumbnail(self, job, manifest: SceneManifest, client: ComfyUIClient,
                            thumbnail_dir: Path) -> Optional[Path]:
        positive = compose_positive(manifest.style_prefix, manifest.thumbnail_prompt)
        negative = manifest.negative_prompt if self.settings.comfy_negative_prompt_enabled else ""
        workflow, _seed = client.build_prompt(
            positive, negative, self.settings.video_width, self.settings.video_height,
            filename_prefix="thumbnail")
        results = client.generate_batch({"thumbnail": workflow}, image_dir=thumbnail_dir)
        images = results.get("thumbnail") or []
        if not images:
            self.logger.warning("Thumbnail generation failed; continuing without one")
            return None
        return self.assembler.make_thumbnail(images[-1], thumbnail_dir / "thumbnail.png")

    def _validate(self, video_path: Path, expected_seconds: float, metadata: dict) -> None:
        info = probe_media(video_path)
        streams = info.get("streams", [])
        kinds = {stream.get("codec_type") for stream in streams}
        if "video" not in kinds or "audio" not in kinds:
            raise AssemblyError("Output must contain one video and one audio stream")
        video = next(stream for stream in streams if stream.get("codec_type") == "video")
        width, height = int(video.get("width", 0)), int(video.get("height", 0))
        if (width, height) != (self.settings.video_width, self.settings.video_height):
            raise AssemblyError(
                f"Output resolution {width}x{height} != configured "
                f"{self.settings.video_width}x{self.settings.video_height}")
        duration = float(info.get("format", {}).get("duration", 0.0))
        tolerance = max(self.settings.audio_duration_tolerance_seconds, expected_seconds * 0.02)
        if abs(duration - expected_seconds) > tolerance:
            raise AssemblyError(
                f"Output duration {duration:.1f}s differs from narration {expected_seconds:.1f}s "
                f"by more than {tolerance:.1f}s")
        metadata["output_validation"] = {
            "width": width, "height": height, "duration_seconds": round(duration, 3),
            "streams": sorted(kind for kind in kinds if kind),
        }
        self.logger.info("Validation passed: %sx%s %.1fs", width, height, duration)

    # --------------------------------------------------------------- helpers
    def _stage(self, job, stage: str) -> None:
        job.stage = stage
        self.job_manager.update_job(job)
        self.logger.info("[STAGE] %s", stage)

    def _probe_seconds(self, audio_path: Path) -> float:
        info = probe_media(audio_path)
        return float(info.get("format", {}).get("duration", 0.0))

    def _fail(self, job, job_dir: Path, metadata: dict, started_at: datetime, error: Exception) -> None:
        self.logger.error("Narration generation failed: %s", error, exc_info=True)
        failed_at = datetime.now().astimezone()
        metadata.update(generation_status="failed", completed_at=failed_at.isoformat(),
                        total_elapsed_seconds=round((failed_at - started_at).total_seconds(), 3),
                        error_message=str(error))
        job.metadata = metadata
        job.status = "failed"
        job.error_message = str(error)
        write_json(Path(job_dir) / "metadata.json", metadata)
        self.job_manager.update_job(job)
