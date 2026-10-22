"""Turns a timed script into a scene manifest (~240 shots for 10 minutes).

Scene timing is derived deterministically from the WhisperX alignment so
every image lands on the narration timeline. The LLM only authors the visual
prompt for each window (batched), which keeps the shot list reliable even for
a multi-hour video.
"""
from __future__ import annotations
import json
import re
from typing import Any, Optional

from app.config.logging_config import get_logger
from app.config.settings import Settings
from app.narration.models import (
    AlignmentResult,
    CharacterBible,
    Scene,
    SceneManifest,
    ScriptPlan,
)
from app.narration.prompts import (
    NARRATION_MANIFEST_BATCH_PROMPT,
    NARRATION_METADATA_PROMPT,
    NARRATION_THUMBNAIL_PROMPT,
)
from app.narration.text import clean, split_sentences

logger = get_logger("narration.manifest")

_PERSON_WORDS = (
    "man", "woman", "men", "women", "person", "people", "child", "children",
    "hunter", "forager", "craftsperson", "worker", "farmer", "elder", "family",
    "group", "crowd", "traveler", "researcher", "guide", "figure", "someone",
)


def compact_style(style_prefix: str, max_words: int = 18) -> str:
    """Keep the part of a long style lock that SDXL's CLIP encoder can use.

    SDXL truncates prompts at 77 tokens. Spending that budget on a 60-word
    style paragraph hides the actual scene or reference description, so keep
    the first sentence and cap it to a compact visual-style phrase.
    """
    text = " ".join((style_prefix or "").split())
    if not text:
        return ""
    sentence = re.split(r"(?<=[.!?])\s+", text, maxsplit=1)[0]
    words = sentence.split()
    if len(words) > max_words:
        words = words[:max_words]
    return " ".join(words).strip().rstrip(".,;:")


def compose_positive(style_prefix: str, prompt: str, characters: str = "") -> str:
    """Combine a compact style, the specific prompt, and cast identity.

    The specific prompt is placed before the long identity text because CLIP
    truncates at 77 tokens. Scene action and reference-view details must
    survive; IP-Adapter reference images carry the face/wardrobe identity.
    """
    parts = [
        compact_style(style_prefix),
        (prompt or "").strip().rstrip("."),
        (characters or "").strip().rstrip("."),
    ]
    return ". ".join(part for part in parts if part)


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
        character_bible: Optional[CharacterBible] = None,
        creative_direction: str = "",
        script_fingerprint: str = "",
    ) -> SceneManifest:
        scene_count = self._scene_count(duration_seconds)
        windows = self._time_windows(
            alignment, duration_seconds, scene_count,
            self.settings.narration_scene_seconds,
        )
        records = self._generate_prompts(windows, script_plan.topic, character_bible)
        scenes = [
            Scene(
                index=index,
                start=start,
                end=end,
                text=text,
                prompt=str(records.get(index, {}).get("prompt") or self._fallback_prompt(
                    text, script_plan.topic)),
                negative_prompt=str(records.get(index, {}).get("negative_prompt") or ""),
                character_ids=list(records.get(index, {}).get("character_ids") or []),
                seed=None,
            )
            for index, (start, end, text) in enumerate(windows, start=1)
        ]
        thumbnail_prompt, thumbnail_text, thumbnail_ids = self._thumbnail_details(
            script_plan, character_bible)
        style_prefix = (character_bible.style_lock if character_bible else "") or (
            self.settings.narration_style_prefix)
        manifest = SceneManifest(
            topic=script_plan.topic,
            title=script_plan.title,
            narration_audio=narration_audio,
            target_duration_seconds=round(duration_seconds, 3),
            scene_seconds=self.settings.narration_scene_seconds,
            style_prefix=style_prefix,
            characters=character_bible.identity_text() if character_bible else self.settings.narration_characters,
            character_bible=character_bible,
            image_backend=self.settings.narration_image_backend,
            script_fingerprint=script_fingerprint,
            creative_direction=creative_direction,
            negative_prompt=self.settings.narration_negative_prompt,
            alignment_source=alignment.source,
            thumbnail_prompt=thumbnail_prompt,
            thumbnail_text=thumbnail_text,
            thumbnail_character_ids=thumbnail_ids,
            scenes=scenes,
        )
        logger.info("Scene manifest built: %s scenes over %.1fs", len(scenes), duration_seconds)
        return manifest

    def _scene_count(self, duration_seconds: float) -> int:
        raw = round(duration_seconds / max(0.1, self.settings.narration_scene_seconds))
        return max(self.settings.narration_min_scenes,
                   min(self.settings.narration_max_scenes, int(raw)))

    @staticmethod
    def _time_windows(
        alignment: AlignmentResult,
        duration_seconds: float,
        scene_count: int,
        target_seconds: float = 2.5,
    ) -> list[tuple[float, float, str]]:
        """Group aligned speech into shots without duplicating or cutting sentences.

        WhisperX segments are treated as semantic units. Short adjacent units are
        combined to reach the target shot length; long segments are split at
        sentence or word boundaries, with timestamps apportioned by word count.
        """
        if duration_seconds <= 0:
            duration_seconds = max(1.0, scene_count * target_seconds)
        target = max(0.5, min(target_seconds or duration_seconds / max(1, scene_count),
                              duration_seconds / max(1, scene_count) * 1.5))
        units: list[tuple[float, float, str]] = []

        for segment in alignment.segments:
            text = clean(segment.text)
            if not text:
                continue
            start = max(0.0, float(segment.start))
            end = min(duration_seconds, max(start, float(segment.end)))
            if end <= start:
                continue
            sentences = split_sentences(text) or [text]
            if len(sentences) == 1 and end - start > target * 1.55:
                # Use word-level alignment when available; otherwise split this
                # unusually long utterance by clauses, then by words as a last resort.
                timed_words = [word for word in segment.words if clean(word.word)]
                if timed_words:
                    chunks: list[list[str]] = []
                    current: list[str] = []
                    chunk_start = start
                    for word in timed_words:
                        current.append(clean(word.word))
                        punctuation = word.word.rstrip().endswith(('.', '!', '?', ',', ';', ':'))
                        if word.end - chunk_start >= target and (
                            punctuation or word.end - chunk_start >= target * 1.35
                        ):
                            chunks.append(current)
                            current = []
                            chunk_start = float(word.end)
                    if current:
                        chunks.append(current)
                    sentences = [clean(" ".join(chunk)) for chunk in chunks]
                else:
                    clauses = [part.strip() for part in text.replace(";", ",").split(",") if part.strip()]
                    if len(clauses) > 1:
                        sentences = clauses
                    else:
                        words = text.split()
                        chunk_count = max(2, round((end - start) / target))
                        words_per_chunk = max(1, (len(words) + chunk_count - 1) // chunk_count)
                        sentences = [clean(" ".join(words[offset:offset + words_per_chunk]))
                                     for offset in range(0, len(words), words_per_chunk)]

            weights = [max(1, len(sentence.split())) for sentence in sentences]
            total_weight = sum(weights)
            cursor = start
            for position, (sentence, weight) in enumerate(zip(sentences, weights)):
                sentence_end = end if position == len(sentences) - 1 else cursor + (end - start) * weight / total_weight
                units.append((cursor, sentence_end, sentence))
                cursor = sentence_end

        if not units:
            return [(0.0, round(duration_seconds, 3), "")]

        # Combine neighboring sentence units until the target is reached. Preserve
        # narration order and include the full audio extent in the first/last shot.
        groups: list[list[tuple[float, float, str]]] = []
        group: list[tuple[float, float, str]] = []
        group_start = units[0][0]
        for unit in units:
            if group:
                elapsed = group[-1][1] - group_start
                next_duration = unit[1] - unit[0]
                if elapsed >= target * 0.72 and elapsed + next_duration > target * 1.35:
                    groups.append(group)
                    group = []
                    group_start = unit[0]
            group.append(unit)
            elapsed = unit[1] - group_start
            if elapsed >= target:
                groups.append(group)
                group = []
                if unit is not units[-1]:
                    group_start = unit[1]
        if group:
            if groups and (group[-1][1] - group[0][0]) < target * 0.55:
                groups[-1].extend(group)
            else:
                groups.append(group)

        windows: list[tuple[float, float, str]] = []
        cursor = 0.0
        for group in groups:
            start = cursor
            end = max(start, group[-1][1])
            text = clean(" ".join(unit[2] for unit in group))
            windows.append((round(start, 3), round(end, 3), text))
            cursor = end
        windows[-1] = (windows[-1][0], round(duration_seconds, 3), windows[-1][2])
        return windows

    def _generate_prompts(self, windows: list[tuple[float, float, str]], topic: str,
                          bible: Optional[CharacterBible] = None) -> dict[int, dict[str, Any]]:
        records: dict[int, dict[str, Any]] = {}
        batch_size = self.settings.narration_manifest_batch_size
        for offset in range(0, len(windows), batch_size):
            batch = windows[offset:offset + batch_size]
            beats = []
            for position, (start, end, text) in enumerate(batch):
                absolute_index = offset + position
                beats.append({
                    "index": absolute_index + 1,
                    "text": text,
                    "duration": round(end - start, 2),
                    "previous_beat": windows[absolute_index - 1][2] if absolute_index else "",
                    "next_beat": windows[absolute_index + 1][2]
                    if absolute_index + 1 < len(windows) else "",
                })
            data = self._ask_for_prompts(beats, topic, bible)
            if data:
                records.update(data)
            for beat in beats:
                records.setdefault(beat["index"], {
                    "prompt": self._fallback_prompt(beat["text"], topic),
                    "character_ids": self._fallback_character_ids(beat["text"], bible),
                    "negative_prompt": "",
                })
            logger.info("Scene prompts: %s/%s", min(offset + batch_size, len(windows)), len(windows))
        return records

    def _ask_for_prompts(self, beats: list[dict], topic: str,
                         bible: Optional[CharacterBible] = None) -> dict[int, dict[str, Any]]:
        roster = "none"
        if bible and bible.characters:
            roster = json.dumps([
                {"id": character.id, "name": character.name, "role": character.role,
                 "identity": character.anchor()}
                for character in bible.characters
            ], ensure_ascii=False)
        prompt = NARRATION_MANIFEST_BATCH_PROMPT.format(
            style_prefix=self.settings.narration_style_prefix,
            characters=roster,
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
        by_name = {character.name.lower(): character.id
                   for character in (bible.characters if bible else [])}
        valid_ids = set(bible.ids()) if bible else set()
        parsed: dict[int, dict[str, Any]] = {}
        for record in records:
            if not isinstance(record, dict):
                continue
            try:
                index = int(record["index"])
            except (KeyError, TypeError, ValueError):
                continue
            body = clean(str(record.get("prompt", "")))
            if not body:
                continue
            character_ids: list[str] = []
            raw_ids = record.get("character_ids") or record.get("characters") or []
            if isinstance(raw_ids, str):
                raw_ids = [part.strip() for part in raw_ids.split(",")]
            for raw in raw_ids if isinstance(raw_ids, list) else []:
                candidate = str(raw or "").strip()
                candidate = by_name.get(candidate.lower(), candidate)
                if candidate in valid_ids and candidate not in character_ids:
                    character_ids.append(candidate)
            if not character_ids and bible:
                character_ids = self._fallback_character_ids(body, bible)
            parsed[index] = {
                "prompt": body,
                "character_ids": character_ids,
                "negative_prompt": clean(str(record.get("negative_prompt", ""))),
            }
        return parsed

    @staticmethod
    def _fallback_character_ids(text: str, bible: Optional[CharacterBible]) -> list[str]:
        """Only attach a cast member when the beat actually describes people."""
        if not bible or not bible.characters:
            return []
        lowered = f" {text.lower()} "
        named = [character.id for character in bible.characters
                 if f" {character.name.lower()} " in lowered]
        if named:
            return named[:2]
        if any(f" {word} " in lowered or f" {word}s " in lowered for word in _PERSON_WORDS):
            primary = next((character for character in bible.characters
                            if character.role == "primary"), bible.characters[0])
            return [primary.id]
        return []

    @staticmethod
    def _fallback_prompt(text: str, topic: str) -> str:
        base = clean(text) or f"a cinematic documentary shot about {topic}"
        words = base.split()
        return " ".join(words[:24]) if words else f"cinematic documentary shot about {topic}"

    def _thumbnail_prompt(self, script_plan: ScriptPlan) -> str:
        return self._thumbnail_details(script_plan)[0]

    def _thumbnail_details(
        self, script_plan: ScriptPlan, bible: Optional[CharacterBible] = None,
    ) -> tuple[str, str, list[str]]:
        roster = bible.identity_text() if bible else self.settings.narration_characters
        prompt = NARRATION_THUMBNAIL_PROMPT.format(
            title=script_plan.title, topic=script_plan.topic,
            style_prefix=(bible.style_lock if bible else "") or self.settings.narration_style_prefix,
            characters=roster or "no recurring character required",
        )
        fallback_ids = [bible.characters[0].id] if bible and bible.characters else []
        try:
            data = self.llm.generate_json(prompt)
            if isinstance(data, dict) and data.get("prompt"):
                overlay = clean(str(data.get("text") or script_plan.title)).upper()[:48]
                ids: list[str] = []
                valid = set(bible.ids()) if bible else set()
                raw_ids = data.get("character_ids") or []
                if isinstance(raw_ids, str):
                    raw_ids = [part.strip() for part in raw_ids.split(",")]
                for raw in raw_ids if isinstance(raw_ids, list) else []:
                    if str(raw) in valid and str(raw) not in ids:
                        ids.append(str(raw))
                return clean(str(data["prompt"])), overlay, ids or fallback_ids
        except Exception as error:
            logger.warning("Thumbnail prompt failed (%s); using topic fallback", error)
        return (
            f"striking cinematic documentary thumbnail about {script_plan.topic}, single "
            "dominant subject, strong foreground/background contrast, open space across the top",
            "WHAT DID THEY DO?",
            fallback_ids,
        )

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
