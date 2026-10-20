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
from app.llm.gemini import GeminiProvider
from app.narration.audio_engine import AudioEngine
from app.narration.comfy_client import ComfyUIClient
from app.narration.models import AlignmentResult, SceneManifest, ScriptPlan
from app.narration.scene_manifest import SceneManifestBuilder, compose_positive
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

PHASES = ("SCRIPT", "TTS", "ALIGN", "MANIFEST", "IMAGES", "RENDER", "PACKAGE")


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
        self.llm = llm or GeminiProvider(self.settings)
        self.script_generator = ScriptGenerator(self.settings, self.llm)
        self.manifest_builder = SceneManifestBuilder(self.settings, self.llm)
        self.assembler = VideoAssembler(self.settings)
        self.audio = AudioEngine(self.settings, self.batch_dir / "audio")
        self.progress_cb = progress_cb
        self.state_path = self.batch_dir / "state.json"
        self.state: dict[str, Any] = {}
        self._comfy: Optional[ComfyUIClient] = None

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
        if self._comfy:
            self._comfy.close()
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
                "video_path": None, "thumbnail_path": None, "narration_duration_seconds": None,
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
        duration = video.get("narration_duration_seconds") or self._probe_seconds(Path(video["audio_path"]))
        manifest = self.manifest_builder.build(plan, alignment, duration, video["audio_path"])
        self._write_manifest(video, manifest)

    def _stage_images(self, video: dict) -> None:
        manifest = self._load_manifest(video)
        image_dir = self._video_dir(video) / "images"
        requests_map: dict[str, dict] = {}
        base_seed = self.settings.narration_seed
        for scene in manifest.scenes:
            positive = compose_positive(manifest.style_prefix, scene.prompt, manifest.characters)
            negative = manifest.negative_prompt if self.settings.comfy_negative_prompt_enabled else ""
            scene_seed = (base_seed + scene.index) if base_seed else None
            workflow, seed = self._comfy_client().build_prompt(
                positive, negative, self.settings.video_width, self.settings.video_height,
                seed=scene_seed, filename_prefix=f"scene_{scene.index:04d}")
            scene.seed = seed
            requests_map[str(scene.index)] = workflow
        results = self._comfy_client().generate_batch(requests_map, image_dir=image_dir)
        for scene in manifest.scenes:
            paths = results.get(str(scene.index)) or []
            if paths:
                scene.image_path = str(paths[-1])
        self._fill_missing(manifest)
        # One dedicated thumbnail image from the thumbnail prompt.
        thumb_positive = compose_positive(manifest.style_prefix, manifest.thumbnail_prompt, manifest.characters)
        thumb_workflow, _ = self._comfy_client().build_prompt(
            thumb_positive, "", self.settings.video_width, self.settings.video_height,
            filename_prefix="thumbnail")
        thumb_results = self._comfy_client().generate_batch({"thumbnail": thumb_workflow},
                                                             image_dir=self._video_dir(video) / "thumbnail")
        thumbs = thumb_results.get("thumbnail") or []
        video["thumbnail_image"] = str(thumbs[-1]) if thumbs else None
        self._write_manifest(video, manifest)

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
            thumb = self.assembler.make_thumbnail(Path(video["thumbnail_image"]),
                                                  self._video_dir(video) / "thumbnail.png")
            video["thumbnail_path"] = str(thumb) if thumb else None

    def _stage_package(self, video: dict) -> None:
        exports = self.batch_dir / "exports"
        exports.mkdir(parents=True, exist_ok=True)
        if video.get("video_path") and Path(video["video_path"]).is_file():
            destination = exports / f"{video['id']}.mp4"
            shutil.copy2(video["video_path"], destination)
            video["export_video"] = str(destination)
        if video.get("thumbnail_path") and Path(video["thumbnail_path"]).is_file():
            destination = exports / f"{video['id']}_thumbnail.png"
            shutil.copy2(video["thumbnail_path"], destination)
            video["export_thumbnail"] = str(destination)

    # --------------------------------------------------------------- helpers
    def _comfy_client(self) -> ComfyUIClient:
        if self._comfy is None:
            self._comfy = ComfyUIClient(self.settings, on_log=lambda m: logger.info(m))
        return self._comfy

    def _load_script(self, video: dict) -> ScriptPlan:
        return ScriptPlan.model_validate(_read_json(Path(video["script_path"]), {}))

    def _load_alignment(self, video: dict) -> AlignmentResult:
        return AlignmentResult.model_validate(_read_json(Path(video["alignment_path"]), {}))

    def _load_manifest(self, video: dict) -> SceneManifest:
        return SceneManifest.model_validate(_read_json(Path(video["manifest_path"]), {}))

    def _write_manifest(self, video: dict, manifest: SceneManifest) -> None:
        path = self._video_dir(video) / "manifest.json"
        write_json(path, manifest.model_dump())
        video["manifest_path"] = str(path)

    @staticmethod
    def _fill_missing(manifest: SceneManifest) -> None:
        available = [scene for scene in manifest.scenes if scene.image_path]
        if not available:
            raise RuntimeError("ComfyUI produced no images for this video")
        fallback = available[0].image_path
        for scene in manifest.scenes:
            if not scene.image_path:
                scene.image_path = fallback
            else:
                fallback = scene.image_path

    def _validate(self, video_path: Path, expected_seconds: float) -> None:
        info = probe_media(video_path)
        streams = info.get("streams", [])
        kinds = {stream.get("codec_type") for stream in streams}
        if "video" not in kinds or "audio" not in kinds:
            raise RuntimeError("Output must contain one video and one audio stream")
        video = next(stream for stream in streams if stream.get("codec_type") == "video")
        if (int(video.get("width", 0)), int(video.get("height", 0))) != (
                self.settings.video_width, self.settings.video_height):
            raise RuntimeError("Output resolution does not match configuration")
        duration = float(info.get("format", {}).get("duration", 0.0))
        tolerance = max(self.settings.audio_duration_tolerance_seconds, expected_seconds * 0.02)
        if abs(duration - expected_seconds) > tolerance:
            raise RuntimeError(f"Output duration {duration:.1f}s differs from narration {expected_seconds:.1f}s")

    def _probe_seconds(self, media_path: Path) -> float:
        return float(probe_media(media_path).get("format", {}).get("duration", 0.0))
