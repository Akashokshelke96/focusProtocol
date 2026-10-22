"""Reusable narration studio API and a real smoke-test entry point.

Examples::

    from app.narration.studio import NarrationStudio
    studio = NarrationStudio()
    studio.run("What did ancient humans actually do all day?", 10)

    python -m app.narration.studio --smoke-seconds 30 --topic "Roman roads"
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Optional

from PIL import Image

from app.config.logging_config import get_logger
from app.config.settings import Settings, get_settings
from app.narration.models import SceneManifest, ScriptPlan
from app.narration.orchestrator import NarrationOrchestrator
from app.utils.ffmpeg import probe_media

logger = get_logger("narration.studio")

SMOKE_SCRIPT = (
    "Most of us picture {topic} as a single frozen moment. The evidence tells a messier story. "
    "Imagine a morning camp beside a cold river. Smoke lifts through wet air while one person "
    "repairs a cracked tool and another sorts the night's roots into a woven basket. Nobody is "
    "in a hurry. A child carries water. An elder watches the tree line. By noon the group has "
    "moved a short distance, read the ground, and changed its plan. By evening the same hands "
    "have made fire, shared food, and told a story that will be repeated tomorrow. The past was "
    "not a photograph. It was a working day."
)


def _smoke_script(topic: str, seconds: float) -> str:
    """Trim the stock smoke narration so the real audio matches the radio.

    Without this, a 30-second smoke request would still synthesize the full
    two-minute script and generate far more scenes than the operator asked for.
    """
    text = SMOKE_SCRIPT.format(topic=topic)
    budget = max(25, int(round(seconds * 2.5)))  # ~150 spoken words per minute
    words = text.split()
    if len(words) <= budget:
        return text
    trimmed = " ".join(words[:budget]).rstrip(" ,;:")
    for mark in (".", "!", "?"):
        cut = trimmed.rfind(mark)
        if cut >= len(trimmed) * 0.55:
            return trimmed[:cut + 1]
    return trimmed + "."


class NarrationStudio:
    """Script-driven facade over the production orchestrator."""

    def __init__(self, settings: Optional[Settings] = None, llm: Any = None):
        self.settings = settings or get_settings()
        self.llm = llm
        self.last_job_id: Optional[str] = None

    # ---------------------------------------------------------------- public
    def run_topic(self, topic: str, duration_minutes: Optional[float] = None,
                  auto_approve: bool = True, count: int = 1) -> bool:
        orchestrator = NarrationOrchestrator(self.settings, llm=self.llm)
        ok = orchestrator.run(topic, duration_minutes=duration_minutes,
                              auto_approve=auto_approve, count=count)
        self.last_job_id = orchestrator.last_job_ids[-1] if orchestrator.last_job_ids else None
        return ok

    def run_script(self, plan: ScriptPlan, duration_minutes: float,
                   job_id: Optional[str] = None) -> bool:
        orchestrator = NarrationOrchestrator(self.settings, llm=self.llm)
        ok = orchestrator.run_script(plan, duration_minutes=duration_minutes, job_id=job_id)
        self.last_job_id = orchestrator.last_job_ids[-1] if orchestrator.last_job_ids else job_id
        return ok

    def resume(self, job_id: str) -> bool:
        orchestrator = NarrationOrchestrator(self.settings, llm=self.llm)
        ok = orchestrator.resume(job_id)
        self.last_job_id = job_id
        return ok

    def smoke_test(self, topic: str = "What did ancient humans actually do all day?",
                   seconds: float = 30.0, job_id: Optional[str] = None,
                   script: Optional[str] = None) -> dict[str, Any]:
        """Run the real production path on a tiny script and report hard checks.

        This exercises the same TTS, character-bible, reference, scene, render,
        thumbnail, and validation code as a full video. It does not mock the
        image backend.
        """
        seconds = max(10.0, min(90.0, float(seconds)))
        topic = (topic or "a documentary subject").strip()
        text = (script or _smoke_script(topic, seconds)).strip()
        plan = ScriptPlan(
            topic=topic,
            title=f"Smoke test: {topic}"[:90],
            script=text,
            word_count=len(text.split()),
            estimated_duration_seconds=round(len(text.split()) / 150.0 * 60, 2),
            approved=True,
        )
        smoke_settings = self.settings.model_copy(update={
            "narration_scene_seconds": 3.0,
            "narration_min_scenes": 1,
            "narration_max_scenes": 12,
            "narration_manifest_batch_size": 4,
            "narration_max_retries": 1,
            "narration_motion": "none",
            "narration_image_steps": 20,
            "narration_reference_steps": 24,
            "narration_export_enabled": False,
            "video_width": 1280,
            "video_height": 720,
            "video_fps": 15,
        })
        smoke_id = job_id or (
            f"smoke_{int(seconds):03d}_"
            f"{hashlib.sha256(topic.encode('utf-8')).hexdigest()[:8]}")
        orchestrator = NarrationOrchestrator(smoke_settings, llm=self.llm)
        ok = orchestrator.run_script(plan, duration_minutes=seconds / 60.0, job_id=smoke_id)
        self.last_job_id = orchestrator.last_job_ids[-1] if orchestrator.last_job_ids else smoke_id
        report = self.build_report(self.last_job_id)
        report["ok"] = bool(ok and report.get("checks", {}).get("all_passed"))
        return report

    def build_report(self, job_id: Optional[str]) -> dict[str, Any]:
        if not job_id:
            return {"ok": False, "error": "no job id"}
        job_dir = Path("jobs") / job_id
        metadata_path = job_dir / "metadata.json"
        metadata: dict[str, Any] = {}
        if metadata_path.is_file():
            try:
                metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                metadata = {}
        manifest_path = job_dir / "manifest" / "manifest.json"
        manifest: Optional[SceneManifest] = None
        if manifest_path.is_file():
            try:
                manifest = SceneManifest.model_validate_json(
                    manifest_path.read_text(encoding="utf-8"))
            except Exception:  # noqa: BLE001 - report what exists
                manifest = None
        video_path = Path(metadata.get("video_path") or job_dir / "output" / "rendered.mp4")
        thumbnail_path = Path(metadata.get("thumbnail_path") or job_dir / "thumbnail" / "thumbnail.png")
        checks: dict[str, Any] = {}
        checks["video_exists"] = video_path.is_file()
        checks["thumbnail_exists"] = thumbnail_path.is_file()
        checks["scene_count"] = len(manifest.scenes) if manifest else 0
        checks["scenes_with_images"] = (
            sum(1 for scene in manifest.scenes
                if scene.image_path and Path(scene.image_path).is_file())
            if manifest else 0)
        checks["all_scenes_have_images"] = bool(
            manifest and checks["scenes_with_images"] == len(manifest.scenes))
        checks["characters"] = len(manifest.character_bible.characters) if (
            manifest and manifest.character_bible) else 0
        checks["references"] = len(manifest.character_bible.reference_paths()) if (
            manifest and manifest.character_bible) else 0
        checks["all_characters_have_references"] = bool(
            manifest and manifest.character_bible
            and all(character.references for character in manifest.character_bible.characters))
        if video_path.is_file():
            try:
                info = probe_media(video_path)
                streams = info.get("streams", [])
                checks["video_streams"] = sum(
                    1 for stream in streams if stream.get("codec_type") == "video")
                checks["audio_streams"] = sum(
                    1 for stream in streams if stream.get("codec_type") == "audio")
                checks["duration_seconds"] = round(
                    float(info.get("format", {}).get("duration", 0.0)), 3)
                video = next((s for s in streams if s.get("codec_type") == "video"), {})
                checks["width"] = int(video.get("width", 0))
                checks["height"] = int(video.get("height", 0))
            except Exception as error:  # noqa: BLE001
                checks["probe_error"] = str(error)
        if thumbnail_path.is_file():
            try:
                with Image.open(thumbnail_path) as image:
                    checks["thumbnail_size"] = list(image.size)
            except Exception as error:  # noqa: BLE001
                checks["thumbnail_error"] = str(error)
        checks["all_passed"] = bool(
            checks.get("video_exists")
            and checks.get("thumbnail_exists")
            and checks.get("all_scenes_have_images")
            and checks.get("all_characters_have_references")
            and checks.get("video_streams") == 1
            and checks.get("audio_streams") == 1
            and checks.get("duration_seconds", 0) > 0
            and checks.get("width", 0) > 0
            and checks.get("height", 0) > 0
            and checks.get("thumbnail_size") == [
                self.settings.narration_thumbnail_width,
                self.settings.narration_thumbnail_height]
        )
        return {
            "job_id": job_id,
            "status": metadata.get("generation_status"),
            "video": str(video_path) if video_path.is_file() else "",
            "thumbnail": str(thumbnail_path) if thumbnail_path.is_file() else "",
            "image_backend": metadata.get("image_model"),
            "image_generation": metadata.get("image_generation", {}),
            "reference_generation": metadata.get("reference_generation", {}),
            "output_validation": metadata.get("output_validation", {}),
            "thumbnail_validation": metadata.get("thumbnail_validation", {}),
            "checks": checks,
        }


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Run the narration studio or its real smoke test")
    parser.add_argument("--topic", default="What did ancient humans actually do all day?")
    parser.add_argument("--minutes", type=float, default=None, help="Full-video duration")
    parser.add_argument("--script", default="",
                        help="Approved narration .txt file for a full run")
    parser.add_argument("--smoke-seconds", type=float, default=0,
                        help="Run the real smoke test for this many seconds (10-90)")
    parser.add_argument("--job-id", default="")
    parser.add_argument("--resume-job", default="",
                        help="Resume an existing approved job and reuse cached artifacts")
    parser.add_argument("--json", action="store_true", help="Print the smoke report as JSON")
    args = parser.parse_args(argv)

    studio = NarrationStudio()
    if args.resume_job:
        ok = studio.resume(args.resume_job)
        report = studio.build_report(args.resume_job)
        report["ok"] = bool(ok and report.get("checks", {}).get("all_passed"))
        print(json.dumps(report, indent=2))
        return 0 if report["ok"] else 1
    if args.smoke_seconds:
        report = studio.smoke_test(args.topic, args.smoke_seconds, job_id=args.job_id or None)
        print(json.dumps(report, indent=2))
        return 0 if report.get("ok") else 1
    if args.script:
        script_path = Path(args.script).expanduser()
        if not script_path.is_file():
            raise SystemExit(f"Script file not found: {script_path}")
        text = script_path.read_text(encoding="utf-8").strip()
        plan = ScriptPlan(
            topic=args.topic,
            title=args.topic[:90],
            script=text,
            word_count=len(text.split()),
            estimated_duration_seconds=round(len(text.split()) / 150.0 * 60, 2),
            approved=True,
        )
        ok = studio.run_script(plan, args.minutes, job_id=args.job_id or None)
        report = studio.build_report(studio.last_job_id)
        report["ok"] = bool(ok and report.get("checks", {}).get("all_passed"))
        print(json.dumps(report, indent=2))
        return 0 if report["ok"] else 1
    ok = studio.run_topic(args.topic, args.minutes)
    print(json.dumps({"ok": ok, "job_id": studio.last_job_id}, indent=2))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
