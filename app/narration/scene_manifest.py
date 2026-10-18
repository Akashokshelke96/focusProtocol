"""Turns a timed script into a scene manifest (~200-260 shots + a thumbnail).

Scene timing is derived deterministically from the WhisperX alignment so
every image lands on the narration timeline. The LLM only authors the visual
prompt for each window (batched), which keeps the shot list reliable even
for a 240-scene video.
"""
from __future__ import annotations
import json
from typing import Any

from app.config.logging_config import get_logger
from app.config.settings import Settings
from app.narration.models import AlignmentResult, Scene, SceneManifest, ScriptPlan
from app.narration.prompts import (
    NARRATION_MANIFEST_BATCH_PROMPT,
    NARRATION_METADATA_PROMPT,
    NARRATION_THUMBNAIL_PROMPT,
)
from app.narration.text import clean

logger = get_logger("narration.manifest")


def compose_positive(style_prefix: str, prompt: str) -> str:
    """Combine the universal style prefix with a scene prompt."""
    prefix = (style_prefix or "").strip().rstrip(".")
    body = (prompt or "").strip().rstrip(".")
    if prefix and body:
        return f"{prefix}. {body}"
    return prefix or body


class SceneManifestBuilder:
    def __init__(self, settings: Settings, llm: Any):
        self.settings = settings
        self.llm = llm

    def build(
        self,
        script_plan: ScriptPlan,
        alignment: AlignmentResult,
        duration_seconds: float,
        narration_audio: str = "",
    ) -> SceneManifest:
        scene_count = self._scene_count(duration_seconds)
        windows = self._time_windows(alignment, duration_seconds, scene_count)
        prompts = self._generate_prompts(windows, script_plan.topic)
        scenes = [
            Scene(index=index, start=start, end=end, text=text,
                  prompt=prompts.get(index, self._fallback_prompt(text, script_plan.topic)),
                  seed=None)
            for index, (start, end, text) in enumerate(windows, start=1)
        ]
        thumbnail_prompt = self._thumbnail_prompt(script_plan)
        manifest = SceneManifest(
            topic=script_plan.topic,
            title=script_plan.title,
            narration_audio=narration_audio,
            target_duration_seconds=round(duration_seconds, 3),
            scene_seconds=self.settings.narration_scene_seconds,
            style_prefix=self.settings.narration_style_prefix,
            negative_prompt=self.settings.narration_negative_prompt,
            alignment_source=alignment.source,
            thumbnail_prompt=thumbnail_prompt,
            scenes=scenes,
        )
        logger.info("Scene manifest built: %s scenes over %.1fs", len(scenes), duration_seconds)
        return manifest

    def _scene_count(self, duration_seconds: float) -> int:
        raw = round(duration_seconds / max(0.1, self.settings.narration_scene_seconds))
        return max(self.settings.narration_min_scenes,
                   min(self.settings.narration_max_scenes, int(raw)))

    @staticmethod
    def _time_windows(alignment: AlignmentResult, duration_seconds: float,
                      scene_count: int) -> list[tuple[float, float, str]]:
        """Split the timeline into scene_count even windows, tagging overlapping text."""
        if duration_seconds <= 0:
            duration_seconds = max(1.0, scene_count * 2.5)
        segments = alignment.segments
        windows: list[tuple[float, float, str]] = []
        for index in range(scene_count):
            start = duration_seconds * index / scene_count
            end = duration_seconds * (index + 1) / scene_count
            parts = [
                segment.text for segment in segments
                if segment.text and segment.end > start and segment.start < end
            ]
            windows.append((round(start, 3), round(end, 3), clean(" ".join(parts))))
        return windows

    def _generate_prompts(self, windows: list[tuple[float, float, str]], topic: str) -> dict[int, str]:
        prompts: dict[int, str] = {}
        batch_size = self.settings.narration_manifest_batch_size
        for offset in range(0, len(windows), batch_size):
            batch = windows[offset:offset + batch_size]
            beats = [
                {"index": offset + position + 1, "text": text, "duration": round(end - start, 2)}
                for position, (start, end, text) in enumerate(batch)
            ]
            data = self._ask_for_prompts(beats, topic)
            if data:
                prompts.update(data)
            else:
                for beat in beats:
                    prompts.setdefault(beat["index"], self._fallback_prompt(beat["text"], topic))
            logger.info("Scene prompts: %s/%s", min(offset + batch_size, len(windows)), len(windows))
        return prompts

    def _ask_for_prompts(self, beats: list[dict], topic: str) -> dict[int, str]:
        prompt = NARRATION_MANIFEST_BATCH_PROMPT.format(
            style_prefix=self.settings.narration_style_prefix,
            beats=json.dumps(beats, ensure_ascii=False),
        )
        try:
            data = self.llm.generate_json(prompt)
        except Exception as error:
            logger.warning("Scene prompt batch failed (%s); using fallbacks", error)
            return {}
        records = data.get("scenes") if isinstance(data, dict) else data
        if not isinstance(records, list):
            logger.warning("Scene prompt batch returned an unexpected shape; using fallbacks")
            return {}
        prompts: dict[int, str] = {}
        for record in records:
            if not isinstance(record, dict):
                continue
            try:
                index = int(record["index"])
            except (KeyError, TypeError, ValueError):
                continue
            body = clean(str(record.get("prompt", "")))
            if body:
                prompts[index] = body
        return prompts

    @staticmethod
    def _fallback_prompt(text: str, topic: str) -> str:
        base = clean(text) or f"a cinematic documentary shot about {topic}"
        words = base.split()
        return " ".join(words[:24]) if words else f"cinematic documentary shot about {topic}"

    def _thumbnail_prompt(self, script_plan: ScriptPlan) -> str:
        prompt = NARRATION_THUMBNAIL_PROMPT.format(
            title=script_plan.title, topic=script_plan.topic,
            style_prefix=self.settings.narration_style_prefix,
        )
        try:
            data = self.llm.generate_json(prompt)
            if isinstance(data, dict) and data.get("prompt"):
                return clean(str(data["prompt"]))
        except Exception as error:
            logger.warning("Thumbnail prompt failed (%s); using topic fallback", error)
        return f"striking documentary thumbnail about {script_plan.topic}, single dominant subject, high contrast"

    def metadata(self, script_plan: ScriptPlan) -> dict[str, Any]:
        """Optional YouTube title/description/tags from the LLM."""
        prompt = NARRATION_METADATA_PROMPT.format(
            topic=script_plan.topic, title=script_plan.title,
            script_excerpt=script_plan.script[:1500],
        )
        try:
            data = self.llm.generate_json(prompt)
            if isinstance(data, dict):
                return data
        except Exception as error:
            logger.warning("Metadata generation failed (%s)", error)
        return {"title": script_plan.title, "description": script_plan.topic, "tags": []}
