"""Phased, resumable batch execution of the narrated pipeline on the pod.

Each video is checkpointed per stage in ``state.json`` so an interrupted run
can resume without repeating completed work. Audio models (Kokoro/WhisperX)
are released before the image phase so the image model owns VRAM on a
single-GPU pod.
"""
from __future__ import annotations
import json
import re
import shutil
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Optional

from app.config.logging_config import get_logger
from app.config.settings import Settings, get_settings
from app.narration.audio_engine import AudioEngine
from app.narration.character_bible import CharacterBibleBuilder, script_fingerprint
from app.narration.image_backends import ImageBackend, build_image_backend
from app.narration.image_generation import ImageGenerationService
from app.narration.llm import build_narration_llm
from app.narration.models import AlignmentResult, CharacterBible, SceneManifest, ScriptPlan
from app.narration.scene_manifest import SceneManifestBuilder
from app.narration.script_generator import ScriptGenerator
from app.narration.video_assembler import VideoAssembler
from app.utils.ffmpeg import probe_media
from app.youtube.state import write_json

logger = get_logger("narration.batch")


def _read_json(path: Path, default: Any) -> Any:
    path = Path(path)
    if not path.is_file():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return default

PHASES = ("SCRIPT", "TTS", "ALIGN", "BIBLE", "MANIFEST", "IMAGES", "RENDER", "PACKAGE")


def _slug(text: str, fallback: str = "video") -> str:
    cleaned = re.sub(r"[^A-Za-z0-9]+", "_", (text or "").strip()).strip("_").lower()
    return (cleaned[:60] or fallback)


class BatchEngine:
    """Executes an approved batch of narrated videos in phases."""

    def __init__(self, settings: Optional[Settings] = None, batch_dir: Optional[Path] = None,
                 llm: Any = None, progress_cb: Optional[Callable[[dict], None]] = None):
        self.settings = settings or get_settings()
        self.batch_dir = Path(batch_dir or Path(self.settings.narration_batch_workspace) / "batch")
        self.batch_dir.mkdir(parents=True, exist_ok=True)
        self.llm = llm or build_narration_llm(self.settings)
        self.script_generator = ScriptGenerator(self.settings, self.llm)
        self.manifest_builder = SceneManifestBuilder(self.settings, self.llm)
        self.assembler = VideoAssembler(self.settings)
        self.audio = AudioEngine(self.settings, self.batch_dir / "audio")
        self.progress_cb = progress_cb
        self.state_path = self.batch_dir / "state.json"
        self.state: dict[str, Any] = {}
        self._backend: Optional[ImageBackend] = None

    # ---------------------------------------------------------------- public
    def run(self, items: list[dict], batch_id: str = "") -> dict:
        """Execute every phase for every video; per-video failures are isolated."""
        self.state = _read_json(self.state_path, {}) or {}
        if not self.state.get("videos"):
            self.state = self._init_state(items, batch_id)
        self.state.update(status="running", error=None, phase=PHASES[0])
        self._save()
        started = time.perf_counter()

        for phase in PHASES:
            self.state["phase"] = phase
            self._save()
            logger.info("=== Batch phase: %s ===", phase)
            for video in self.state["videos"]:
                if video["stages"].get(phase) == "done":
                    continue
                try:
                    self._run_stage(phase, video)
                    video["stages"][phase] = "done"
                    video["error"] = None
                except Exception as error:  # noqa: BLE001 - isolate per video
                    logger.error("Video %s failed at %s: %s", video["index"], phase, error, exc_info=True)
                    video["stages"][phase] = "failed"
                    video["error"] = f"{phase}: {error}"
                self._save()

        all_done = all(all(s == "done" for s in v["stages"].values()) for v in self.state["videos"])
        self.state.update(
            status="completed" if all_done else "completed_with_errors",
            phase="DONE",
            elapsed_seconds=round(time.perf_counter() - started, 3),
            completed_at=datetime.utcnow().isoformat(),
        )
        self._save()
        if self._backend:
            self._backend.close()
        return self.state

    def resume(self, batch_id: str = "") -> dict:
        items = [{"topic": v["topic"], "script": v.get("script", ""),
                  "duration_minutes": v.get("duration_minutes")} for v in self.state.get("videos", [])]
        return self.run(items, batch_id or self.state.get("batch_id", ""))

    # ----------------------------------------------------------------- state
    def _init_state(self, items: list[dict], batch_id: str) -> dict:
        now = datetime.utcnow().isoformat()
        videos = []
        for index, item in enumerate(items):
            videos.append({
                "index": index,
                "id": f"{index + 1:03d}_{_slug(item.get('title') or item.get('topic', ''), 'video')}",
                "topic": item.get("topic", ""),
                "title": item.get("title", ""),
                "script": item.get("script", ""),
                "duration_minutes": float(item.get("duration_minutes") or self.settings.narration_target_duration_minutes),
                "stages": {phase: "pending" for phase in PHASES},
                "error": None,
                "audio_path": None, "alignment_path": None, "manifest_path": None,
                "character_bible_path": None, "character_bible_source": None,
                "video_path": None, "thumbnail_path": None, "thumbnail_image": None,
                "narration_duration_seconds": None, "image_stats": None,
            })
        return {
            "batch_id": batch_id or datetime.utcnow().strftime("%Y%m%d_%H%M%S"),
            "created_at": now, "updated_at": now, "status": "running", "phase": PHASES[0],
            "error": None, "videos": videos,
        }

    def _save(self) -> None:
        self.state["updated_at"] = datetime.utcnow().isoformat()
        write_json(self.state_path, self.state)
        if self.progress_cb:
            try:
                self.progress_cb(self.state)
            except Exception as error:  # pragma: no cover - progress is best effort
                logger.warning("progress callback failed: %s", error)

    def _video_dir(self, video: dict) -> Path:
        directory = self.batch_dir / "videos" / video["id"]
        directory.mkdir(parents=True, exist_ok=True)
        return directory

    # ---------------------------------------------------------------- stages
    def _run_stage(self, phase: str, video: dict) -> None:
        handler = {
            "SCRIPT": self._stage_script,
            "TTS": self._stage_tts,
            "ALIGN": self._stage_align,
            "BIBLE": self._stage_bible,
            "MANIFEST": self._stage_manifest,
            "IMAGES": self._stage_images,
            "RENDER": self._stage_render,
            "PACKAGE": self._stage_package,
        }[phase]
        handler(video)

    def _stage_script(self, video: dict) -> None:
        path = self._video_dir(video) / "script.json"
        if video.get("script"):
            plan = ScriptPlan(topic=video["topic"], title=video.get("title") or video["topic"],
                              script=video["script"], approved=True,
                              word_count=len(video["script"].split()))
        else:
            plan = self.script_generator.generate(video["topic"], video["duration_minutes"])
            plan.approved = True
        plan.word_count = len(plan.script.split())
        plan.estimated_duration_seconds = round(plan.word_count / 150.0 * 60, 2)
        write_json(path, plan.model_dump())
        video["script_path"] = str(path)
        video["title"] = plan.title or video.get("title") or video["topic"]

    def _stage_tts(self, video: dict) -> None:
        plan = self._load_script(video)
        wav = self._video_dir(video) / "audio" / "narration.wav"
        self.audio.synthesize(plan.script, wav)
        video["audio_path"] = str(wav)
        video["narration_duration_seconds"] = self._probe_seconds(wav)

    def _stage_align(self, video: dict) -> None:
        plan = self._load_script(video)
        wav = Path(video["audio_path"])
        duration = video.get("narration_duration_seconds") or self._probe_seconds(wav)
        alignment = self.audio.align(wav) or self.audio.estimate_alignment(plan.script, duration)
        path = self._video_dir(video) / "alignment.json"
        write_json(path, alignment.model_dump())
        video["alignment_path"] = str(path)
        video["alignment_source"] = alignment.source
        # Free the TTS/align models now that all narration is done.
        self.audio.unload_models()

    def _stage_manifest(self, video: dict) -> None:
        plan = self._load_script(video)
        alignment = self._load_alignment(video)
        bible = self._load_bible(video)
        duration = video.get("narration_duration_seconds") or self._probe_seconds(Path(video["audio_path"]))
        fingerprint = script_fingerprint(
            plan, self.settings.narration_style_prefix,
            self.settings.narration_creative_direction)
        manifest = self.manifest_builder.build(
            plan, alignment, duration, video["audio_path"],
            character_bible=bible,
            creative_direction=self.settings.narration_creative_direction,
            script_fingerprint=fingerprint,
        )
        self._write_manifest(video, manifest)

    def _stage_bible(self, video: dict) -> None:
        plan = self._load_script(video)
        builder = CharacterBibleBuilder(self.settings, self.llm)
        bible = builder.load_or_build(
            plan, self._video_dir(video),
            style_prefix=self.settings.narration_style_prefix,
            creative_direction=self.settings.narration_creative_direction,
        )
        path = builder.save(bible, self._video_dir(video))
        video["character_bible_path"] = str(path)
        video["character_bible_source"] = bible.source
        video["character_bible_fingerprint"] = bible.fingerprint

    def _stage_images(self, video: dict) -> None:
        manifest = self._load_manifest(video)
        image_dir = self._video_dir(video) / "images"
        service = ImageGenerationService(
            self.settings, self._image_backend(),
            on_log=lambda message: logger.info(message),
            on_progress=lambda done, total: logger.info("[Images %s/%s]", done, total),
        )
        bible = manifest.character_bible or self._load_bible(video)
        manifest.character_bible = bible
        builder = CharacterBibleBuilder(self.settings, self.llm)
        reference_stats = service.ensure_references(
            bible, self._video_dir(video),
            on_save=lambda current: builder.save(current, self._video_dir(video)))
        stats = service.generate_manifest(
            manifest, image_dir,
            on_save=lambda current: self._write_manifest(video, current))
        self._fill_missing(manifest)
        self._write_manifest(video, manifest)
        video["image_stats"] = {**stats.as_dict(), "references": reference_stats.generated}
        try:
            thumbnail = service.generate_thumbnail(
                manifest, self._video_dir(video) / "thumbnail")
        except Exception as error:  # noqa: BLE001 - fall back to a validated scene
            logger.warning("Thumbnail generation failed for %s: %s", video["id"], error)
            thumbnail = None
            video["thumbnail_error"] = str(error)[:500]
        video["thumbnail_image"] = str(thumbnail) if thumbnail else None
        if not thumbnail:
            fallback = next((scene.image_path for scene in manifest.scenes if scene.image_path), None)
            video["thumbnail_image"] = fallback
            video["thumbnail_fallback_reason"] = "thumbnail backend failed; used first scene"

    def _stage_render(self, video: dict) -> None:
        manifest = self._load_manifest(video)
        output_dir = self._video_dir(video) / "output"
        output_dir.mkdir(parents=True, exist_ok=True)
        video_path = output_dir / "rendered.mp4"
        self.assembler.assemble(manifest, Path(video["audio_path"]), video_path, output_dir)
        duration = video.get("narration_duration_seconds") or self._probe_seconds(Path(video["audio_path"]))
        self._validate(video_path, duration)
        video["video_path"] = str(video_path)
        if video.get("thumbnail_image"):
            manifest = self._load_manifest(video)
            thumb = self.assembler.make_thumbnail(
                Path(video["thumbnail_image"]),
                self._video_dir(video) / "thumbnail.png",
                manifest.thumbnail_text or "WHAT DID THEY DO?")
            video["thumbnail_path"] = str(thumb) if thumb else None
        if not video.get("thumbnail_path"):
            raise RuntimeError(
                "A separate 1280x720 thumbnail was not produced for this video")
        from PIL import Image
        with Image.open(video["thumbnail_path"]) as image:
            expected = (self.settings.narration_thumbnail_width,
                        self.settings.narration_thumbnail_height)
            if image.size != expected:
                raise RuntimeError(
                    f"Thumbnail is {image.size[0]}x{image.size[1]}, expected "
                    f"{expected[0]}x{expected[1]}")

    def _stage_package(self, video: dict) -> None:
        exports = self.batch_dir / "exports"
        exports.mkdir(parents=True, exist_ok=True)
        if not video.get("video_path") or not Path(video["video_path"]).is_file():
            raise RuntimeError("No rendered video is available to package")
        destination = exports / f"{video['id']}.mp4"
        shutil.copy2(video["video_path"], destination)
        video["export_video"] = str(destination)
        if video.get("thumbnail_path") and Path(video["thumbnail_path"]).is_file():
            destination = exports / f"{video['id']}_thumbnail.png"
            shutil.copy2(video["thumbnail_path"], destination)
            video["export_thumbnail"] = str(destination)

    # --------------------------------------------------------------- helpers
    def _image_backend(self) -> ImageBackend:
        if self._backend is None:
            self._backend = build_image_backend(
                self.settings, on_log=lambda message: logger.info(message))
            health = self._backend.health()
            if not health.get("reachable", False):
                raise RuntimeError(
                    f"Image backend {self._backend.name} is not available: "
                    f"{health.get('error', 'unknown error')}")
        return self._backend

    def _load_script(self, video: dict) -> ScriptPlan:
        return ScriptPlan.model_validate(_read_json(Path(video["script_path"]), {}))

    def _load_alignment(self, video: dict) -> AlignmentResult:
        return AlignmentResult.model_validate(_read_json(Path(video["alignment_path"]), {}))

    def _load_bible(self, video: dict) -> CharacterBible:
        path = video.get("character_bible_path")
        if path and Path(path).is_file():
            return CharacterBible.model_validate(_read_json(Path(path), {}))
        builder = CharacterBibleBuilder(self.settings, self.llm)
        return builder.load_or_build(self._load_script(video), self._video_dir(video))

    def _load_manifest(self, video: dict) -> SceneManifest:
        return SceneManifest.model_validate(_read_json(Path(video["manifest_path"]), {}))

    def _write_manifest(self, video: dict, manifest: SceneManifest) -> None:
        path = self._video_dir(video) / "manifest.json"
        write_json(path, manifest.model_dump())
        video["manifest_path"] = str(path)

    @staticmethod
    def _fill_missing(manifest: SceneManifest) -> None:
        missing = [str(scene.index) for scene in manifest.scenes
                   if not scene.image_path or not Path(scene.image_path).is_file()
                   or scene.validation_status == "failed"]
        if missing:
            raise RuntimeError(
                f"No usable image for {len(missing)} scene(s): {', '.join(missing[:12])}. "
                "Partial images are cached; resume the batch to continue.")

    def _validate(self, video_path: Path, expected_seconds: float) -> None:
        info = probe_media(video_path)
        streams = info.get("streams", [])
        videos = [stream for stream in streams if stream.get("codec_type") == "video"]
        audios = [stream for stream in streams if stream.get("codec_type") == "audio"]
        if len(videos) != 1 or len(audios) != 1:
            raise RuntimeError(
                f"Output must contain one video and one audio stream; found "
                f"{len(videos)} video and {len(audios)} audio")
        video = videos[0]
        if (int(video.get("width", 0)), int(video.get("height", 0))) != (
                self.settings.video_width, self.settings.video_height):
            raise RuntimeError("Output resolution does not match configuration")
        fps_raw = video.get("avg_frame_rate") or video.get("r_frame_rate") or "0/1"
        try:
            numerator, denominator = str(fps_raw).split("/", 1)
            fps = float(numerator) / max(1.0, float(denominator))
        except (TypeError, ValueError, ZeroDivisionError):
            fps = 0.0
        if abs(fps - self.settings.video_fps) > 0.2:
            raise RuntimeError(
                f"Output frame rate {fps:.3f} does not match configured {self.settings.video_fps}")
        duration = float(info.get("format", {}).get("duration", 0.0))
        audio_duration = float(audios[0].get("duration", 0.0) or 0.0)
        video_duration = float(video.get("duration", 0.0) or 0.0)
        tolerance = max(self.settings.audio_duration_tolerance_seconds, expected_seconds * 0.02)
        if abs(duration - expected_seconds) > tolerance:
            raise RuntimeError(f"Output duration {duration:.1f}s differs from narration {expected_seconds:.1f}s")
        if audio_duration and video_duration and abs(audio_duration - video_duration) > tolerance:
            raise RuntimeError(
                f"Video ({video_duration:.1f}s) and audio ({audio_duration:.1f}s) streams differ "
                f"by more than {tolerance:.1f}s")

    def _probe_seconds(self, media_path: Path) -> float:
        return float(probe_media(media_path).get("format", {}).get("duration", 0.0))
