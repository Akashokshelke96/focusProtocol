"""End-to-end narrated pipeline orchestrator.

Script (LLM) -> local approval -> TTS + WhisperX/Piper -> persistent character
bible + reference images -> semantic scene manifest -> reference-conditioned
image generation -> FFmpeg assembly -> validation/export.

Every stage is persisted through the shared JobManager so the existing
dashboard, job history and live logs keep working unchanged. Image generation
is incremental: a resumed job reuses the character bible, manifest, references,
and every scene image whose cache key still matches.
"""
from __future__ import annotations
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from PIL import Image

from app.config.logging_config import get_logger
from app.config.settings import Settings, get_settings
from app.jobs.manager import JobManager
from app.narration.audio_engine import AudioEngine
from app.narration.character_bible import CharacterBibleBuilder, script_fingerprint
from app.narration.config import image_model_label, narration_dirs, require_remote
from app.narration.image_backends import ImageBackend, build_image_backend
from app.narration.image_generation import ImageGenerationService
from app.narration.llm import build_narration_llm
from app.narration.models import AlignmentResult, SceneManifest, ScriptPlan
from app.narration.scene_manifest import SceneManifestBuilder
from app.narration.script_generator import ScriptDeclined, ScriptGenerator
from app.narration.video_assembler import AssemblyError, VideoAssembler
from app.utils.ffmpeg import probe_media
from app.youtube.state import publishing_lock, write_json

logger = get_logger("narration.orchestrator")


class NarrationOrchestrator:
    def __init__(self, settings: Optional[Settings] = None, context: Optional[dict] = None,
                 llm: Any = None):
        self.settings = settings or get_settings()
        self.context = context or {}
        self.job_manager = JobManager()
        self.llm = llm or build_narration_llm(self.settings)
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
        if resume_job_id:
            return self.resume(resume_job_id)
        with publishing_lock(Path("jobs") / "generation"):
            minutes = float(duration_minutes or self.settings.narration_target_duration_minutes)
            success = 0
            for index in range(max(1, count)):
                if self.cancel_requested:
                    break
                if self._run_single(topic, minutes, auto_approve, index):
                    success += 1
            return success == max(1, count)

    def run_script(self, plan: ScriptPlan, duration_minutes: Optional[float] = None,
                   job_id: Optional[str] = None) -> bool:
        """Run an already-approved script through the production pipeline.

        Used by the reusable studio and the Colab smoke test so both exercise
        exactly the same code path as the dashboard.
        """
        plan.approved = True
        minutes = float(duration_minutes or self.settings.narration_target_duration_minutes)
        with publishing_lock(Path("jobs") / "generation"):
            return self._run_plan(plan, minutes, job_id)

    def resume(self, job_id: str) -> bool:
        """Continue an approved job, reusing every valid cached artifact."""
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

        metadata = self._base_metadata(job, topic, target_seconds, started_at)
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
            metadata["script"] = self._script_metadata(plan, dirs["script"] / "script.json")
            self.job_manager.update_job(job)
            return self._execute(job, dirs["job"], metadata, plan, duration_minutes)
        except Exception as error:  # noqa: BLE001 - persisted as a failed job
            self._fail(job, dirs["job"], metadata, started_at, error)
            return False

    def _run_plan(self, plan: ScriptPlan, duration_minutes: float,
                  job_id: Optional[str]) -> bool:
        job_id = job_id or self.context.get("job_id") or (
            datetime.now().strftime("%Y%m%d_%H%M%S_%f") + "_narration_001")
        self.last_job_ids.append(job_id)
        target_seconds = int(duration_minutes * 60)
        job = self.job_manager.create_job(job_id, plan.topic, int(duration_minutes))
        dirs = narration_dirs(Path("jobs") / job_id)
        started_at = datetime.now().astimezone()
        metadata = self._base_metadata(job, plan.topic, target_seconds, started_at)
        self.script_generator.save(plan, dirs["job"])
        metadata["script"] = self._script_metadata(plan, dirs["script"] / "script.json")
        job.metadata = metadata
        self.job_manager.update_job(job)
        try:
            return self._execute(job, dirs["job"], metadata, plan, duration_minutes)
        except Exception as error:  # noqa: BLE001 - persisted as a failed job
            self._fail(job, dirs["job"], metadata, started_at, error)
            return False

    def _base_metadata(self, job, topic: str, target_seconds: int,
                       started_at: datetime) -> dict[str, Any]:
        metadata: dict[str, Any] = dict(job.metadata or {})
        metadata.update(
            narration_mode=True,
            topic=topic,
            target_duration_seconds=target_seconds,
            started_at=started_at.isoformat(),
            image_backend=self.settings.narration_image_backend,
            image_model=image_model_label(self.settings),
            render_config={
                key: getattr(self.settings, key) for key in (
                    "video_width", "video_height", "video_fps", "ffmpeg_preset",
                    "ffmpeg_crf", "narration_motion", "narration_motion_strength",
                    "narration_image_width", "narration_image_height",
                    "narration_image_steps", "narration_ip_adapter_scale",
                    "narration_scene_seconds")
            },
        )
        job.metadata = metadata
        self.job_manager.update_job(job)
        return metadata

    @staticmethod
    def _script_metadata(plan: ScriptPlan, path: Path) -> dict[str, Any]:
        return {
            "title": plan.title, "path": str(path.resolve()),
            "word_count": plan.word_count,
            "estimated_duration_seconds": plan.estimated_duration_seconds,
            "approved": plan.approved, "edited": plan.edited,
        }

    # -------------------------------------------------------------- stages
    def _execute(self, job, job_dir: Path, metadata: dict, plan: ScriptPlan,
                 duration_minutes: float) -> bool:
        dirs = narration_dirs(job_dir)
        started_at = datetime.fromisoformat(metadata.get("started_at") or
                                            datetime.now().astimezone().isoformat())
        backend: Optional[ImageBackend] = None
        try:
            require_remote(self.settings)
            audio = AudioEngine(self.settings, dirs["audio"])

            self._stage(job, "BACKEND_CHECK")
            backend = build_image_backend(
                self.settings, on_log=lambda message: self.logger.info(message))
            metadata["image_backend"] = backend.name
            health = backend.health()
            metadata["image_backend_health"] = health
            self.job_manager.update_job(job)
            if not health.get("reachable", False):
                raise RuntimeError(
                    f"Image backend {backend.name} is not available: "
                    f"{health.get('error', 'unknown error')}")

            self._stage(job, "TTS")
            narration_path = dirs["audio"] / "narration.wav"
            audio.synthesize(plan.script, narration_path)
            duration_seconds = self._probe_seconds(narration_path)
            metadata["narration_audio"] = str(narration_path)
            metadata["narration_duration_seconds"] = duration_seconds
            self.job_manager.update_job(job)

            self._stage(job, "ALIGN")
            alignment = audio.align(narration_path) or audio.estimate_alignment(
                plan.script, duration_seconds)
            write_json(dirs["alignment"] / "alignment.json", alignment.model_dump())
            metadata["alignment_source"] = alignment.source
            metadata["alignment_segments"] = len(alignment.segments)
            self.job_manager.update_job(job)
            audio.unload_models()

            self._stage(job, "CHARACTERS")
            bible_builder = CharacterBibleBuilder(self.settings, self.llm)
            style = self.settings.narration_style_prefix
            direction = self.settings.narration_creative_direction
            fingerprint = script_fingerprint(plan, style, direction)
            bible = bible_builder.load_or_build(
                plan, job_dir, style_prefix=style, creative_direction=direction)
            metadata["character_bible"] = {
                "path": str((dirs["characters"] / "character_bible.json").resolve()),
                "fingerprint": bible.fingerprint,
                "source": bible.source,
                "style_lock": bible.style_lock,
                "characters": [
                    {"id": character.id, "name": character.name, "role": character.role,
                     "seed": character.seed}
                    for character in bible.characters
                ],
            }
            self.job_manager.update_job(job)

            image_service = ImageGenerationService(
                self.settings, backend,
                on_log=lambda message: self.logger.info(message),
                on_progress=self._image_progress(job),
            )
            self._stage(job, "REFERENCES")
            reference_stats = image_service.ensure_references(
                bible, job_dir,
                on_save=lambda current: bible_builder.save(current, job_dir))
            metadata["reference_generation"] = reference_stats.as_dict()
            metadata["reference_images"] = [
                {"character_id": character.id, "view": reference.view, "path": reference.path}
                for character in bible.characters for reference in character.references
            ]
            self.job_manager.update_job(job)

            self._stage(job, "MANIFEST")
            manifest = self._load_or_build_manifest(
                plan, alignment, duration_seconds, str(narration_path), dirs["manifest"],
                bible, fingerprint, job_dir)
            write_json(dirs["manifest"] / "manifest.json", manifest.model_dump())
            metadata["scene_count"] = len(manifest.scenes)
            metadata["manifest_path"] = str((dirs["manifest"] / "manifest.json").resolve())
            self.job_manager.update_job(job)

            self._stage(job, "IMAGES")
            stats = image_service.generate_manifest(
                manifest, dirs["images"],
                on_save=lambda current: write_json(
                    dirs["manifest"] / "manifest.json", current.model_dump()))
            self._fill_missing_images(manifest)
            write_json(dirs["manifest"] / "manifest.json", manifest.model_dump())
            metadata["image_generation"] = stats.as_dict()
            metadata["image_count"] = sum(1 for scene in manifest.scenes if scene.image_path)
            review = [scene.index for scene in manifest.scenes
                      if scene.validation_status == "needs_review"]
            if review:
                metadata["images_needs_review"] = review
            self.job_manager.update_job(job)

            self._stage(job, "ASSEMBLE")
            output_path = dirs["output"] / "rendered.mp4"
            self.assembler.assemble(manifest, narration_path, output_path, dirs["output"])
            metadata["video_path"] = str(output_path)
            self.job_manager.update_job(job)

            self._stage(job, "THUMBNAIL")
            thumbnail_path, thumbnail_meta = self._make_thumbnail(
                manifest, image_service, dirs["thumbnail"])
            metadata["thumbnail"] = thumbnail_meta
            metadata["thumbnail_path"] = str(thumbnail_path) if thumbnail_path else ""

            self._stage(job, "VALIDATE")
            self._validate(output_path, duration_seconds, metadata)
            self._validate_thumbnail(thumbnail_path, metadata)

            self._stage(job, "EXPORT")
            metadata["export"] = self.assembler.export(
                output_path, Path(thumbnail_path) if thumbnail_path else None, job.id)

            self._stage(job, "COMPLETE")
            fallback = (
                manifest.alignment_source == "estimated"
                or bool(metadata.get("images_needs_review"))
                or bool(thumbnail_meta.get("fallback_reason"))
                or bible.source == "fallback"
            )
            job.status = "completed_with_fallback" if fallback else "completed"
            completed_at = datetime.now().astimezone()
            metadata.update(generation_status=job.status, completed_at=completed_at.isoformat(),
                            total_elapsed_seconds=round((completed_at - started_at).total_seconds(), 3))
            job.metadata = metadata
            write_json(job_dir / "metadata.json", metadata)
            self.job_manager.update_job(job)
            self.logger.info("Narration job %s finished: %s", job.id, job.status)
            return True
        except Exception as error:  # noqa: BLE001 - persisted as a failed job
            self._fail(job, job_dir, metadata, started_at, error)
            return False
        finally:
            if backend is not None:
                backend.close()

    def _load_or_build_manifest(
        self,
        plan: ScriptPlan,
        alignment: AlignmentResult,
        duration_seconds: float,
        narration_path: str,
        manifest_dir: Path,
        bible,
        fingerprint: str,
        job_dir: Path,
    ) -> SceneManifest:
        path = Path(manifest_dir) / "manifest.json"
        if self.settings.narration_manifest_reuse and path.is_file():
            try:
                existing = SceneManifest.model_validate_json(path.read_text(encoding="utf-8"))
                bible_fp = existing.character_bible.fingerprint if existing.character_bible else ""
                if (existing.script_fingerprint == fingerprint
                        and bible_fp == bible.fingerprint
                        and abs(existing.target_duration_seconds - duration_seconds) <= 1.0
                        and existing.scenes):
                    existing.character_bible = bible
                    existing.narration_audio = narration_path
                    self.logger.info("Reusing %s-scene manifest from a previous attempt",
                                     len(existing.scenes))
                    return existing
            except Exception as error:  # noqa: BLE001 - stale cache is rebuilt
                self.logger.warning("Ignoring stale scene manifest: %s", error)
        manifest = self.manifest_builder.build(
            plan, alignment, duration_seconds, narration_path,
            character_bible=bible,
            creative_direction=self.settings.narration_creative_direction,
            script_fingerprint=fingerprint,
        )
        write_json(Path(manifest_dir) / "manifest.json", manifest.model_dump())
        return manifest

    def _make_thumbnail(self, manifest: SceneManifest, image_service: ImageGenerationService,
                        thumbnail_dir: Path) -> tuple[Optional[Path], dict[str, Any]]:
        meta: dict[str, Any] = {}
        try:
            source = image_service.generate_thumbnail(manifest, thumbnail_dir)
        except Exception as error:  # noqa: BLE001 - fall back to a validated scene
            self.logger.warning("Thumbnail image generation failed: %s", error)
            meta["generation_error"] = str(error)[:500]
            source = None
        if source is None:
            fallback = next((Path(scene.image_path) for scene in manifest.scenes
                             if scene.image_path and Path(scene.image_path).is_file()), None)
            if fallback is None:
                meta["error"] = "no thumbnail image and no fallback scene"
                return None, meta
            meta["fallback_reason"] = "thumbnail backend failed; used the first scene image"
            source = fallback
        source_path = Path(source)
        headline = manifest.thumbnail_text or "WHAT DID THEY DO?"
        output = self.assembler.make_thumbnail(source_path, thumbnail_dir / "thumbnail.png", headline)
        if output:
            meta["headline"] = headline
            meta["source"] = str(source_path)
        return output, meta

    def _image_progress(self, job):
        def callback(done: int, total: int) -> None:
            job.metadata["image_progress"] = {"done": done, "total": total}
            self.logger.info("[Images %s/%s]", done, total)
        return callback

    @staticmethod
    def _fill_missing_images(manifest: SceneManifest) -> None:
        """Reject incomplete image sets instead of silently showing the wrong scene."""
        missing = [str(scene.index) for scene in manifest.scenes
                   if not scene.image_path or not Path(scene.image_path).is_file()
                   or scene.validation_status == "failed"]
        if missing:
            preview = ", ".join(missing[:12])
            suffix = "…" if len(missing) > 12 else ""
            raise AssemblyError(
                f"No usable scene-specific image was produced for {len(missing)} scene(s) "
                f"({preview}{suffix}). The pipeline stopped instead of rendering unrelated "
                "repeated images. Fix the backend, then resume the same job; valid scenes are cached."
            )

    def _validate(self, video_path: Path, expected_seconds: float, metadata: dict) -> None:
        info = probe_media(video_path)
        streams = info.get("streams", [])
        videos = [stream for stream in streams if stream.get("codec_type") == "video"]
        audios = [stream for stream in streams if stream.get("codec_type") == "audio"]
        if len(videos) != 1 or len(audios) != 1:
            raise AssemblyError(
                f"Output must contain exactly one video and one audio stream; "
                f"found {len(videos)} video and {len(audios)} audio"
            )
        video = videos[0]
        width, height = int(video.get("width", 0)), int(video.get("height", 0))
        if (width, height) != (self.settings.video_width, self.settings.video_height):
            raise AssemblyError(
                f"Output resolution {width}x{height} != configured "
                f"{self.settings.video_width}x{self.settings.video_height}")
        fps_raw = video.get("avg_frame_rate") or video.get("r_frame_rate") or "0/1"
        try:
            numerator, denominator = fps_raw.split("/", 1)
            fps = float(numerator) / max(1.0, float(denominator))
        except (TypeError, ValueError, ZeroDivisionError):
            fps = 0.0
        if abs(fps - self.settings.video_fps) > 0.2:
            raise AssemblyError(
                f"Output frame rate {fps:.3f} != configured {self.settings.video_fps}")
        duration = float(info.get("format", {}).get("duration", 0.0))
        audio_duration = float(audios[0].get("duration", 0.0) or 0.0)
        video_duration = float(video.get("duration", 0.0) or 0.0)
        tolerance = max(self.settings.audio_duration_tolerance_seconds, expected_seconds * 0.02)
        if abs(duration - expected_seconds) > tolerance:
            raise AssemblyError(
                f"Output duration {duration:.1f}s differs from narration {expected_seconds:.1f}s "
                f"by more than {tolerance:.1f}s")
        if audio_duration and video_duration and abs(audio_duration - video_duration) > tolerance:
            raise AssemblyError(
                f"Video ({video_duration:.1f}s) and audio ({audio_duration:.1f}s) streams "
                f"differ by more than {tolerance:.1f}s; the visual track may be truncating audio")
        metadata["output_validation"] = {
            "width": width, "height": height, "fps": round(fps, 3),
            "duration_seconds": round(duration, 3),
            "video_duration_seconds": round(video_duration, 3),
            "audio_duration_seconds": round(audio_duration, 3),
            "streams": ["audio", "video"],
        }
        self.logger.info("Validation passed: %sx%s %.1fs", width, height, duration)

    def _validate_thumbnail(self, thumbnail_path: Optional[Path], metadata: dict) -> None:
        if not thumbnail_path:
            metadata["thumbnail_validation"] = {"ok": False, "error": "not generated"}
            raise AssemblyError(
                f"A separate {self.settings.narration_thumbnail_width}x"
                f"{self.settings.narration_thumbnail_height} thumbnail was not produced")
        try:
            with Image.open(thumbnail_path) as image:
                size = image.size
        except Exception as error:  # noqa: BLE001 - corrupt output
            raise AssemblyError(f"Thumbnail is not decodable: {error}") from error
        if size != (self.settings.narration_thumbnail_width,
                    self.settings.narration_thumbnail_height):
            raise AssemblyError(
                f"Thumbnail is {size[0]}x{size[1]}, expected "
                f"{self.settings.narration_thumbnail_width}x{self.settings.narration_thumbnail_height}")
        metadata["thumbnail_validation"] = {"ok": True, "width": size[0], "height": size[1]}

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
