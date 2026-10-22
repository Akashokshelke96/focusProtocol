"""Typed data structures for the narrated pipeline."""
from __future__ import annotations
from typing import Optional
from pydantic import BaseModel, Field


class CharacterReference(BaseModel):
    """A canonical image that anchors one recurring character."""

    view: str = "full_body"
    path: str = ""
    prompt: str = ""
    seed: Optional[int] = None
    width: int = 0
    height: int = 0
    created_at: str = ""


class CharacterSpec(BaseModel):
    """Immutable identity contract for a recurring character.

    ``identity`` and ``wardrobe`` must stay stable for the whole video;
    only pose, expression, framing, lighting, and environment may change.
    """

    id: str
    name: str
    role: str = "recurring"
    identity: str
    wardrobe: str = ""
    distinguishing_features: str = ""
    palette: str = ""
    reference_prompt: str = ""
    portrait_prompt: str = ""
    forbidden_changes: list[str] = Field(default_factory=list)
    allowed_changes: list[str] = Field(
        default_factory=lambda: ["pose", "expression", "camera angle", "lighting", "environment"]
    )
    seed: Optional[int] = None
    references: list[CharacterReference] = Field(default_factory=list)

    def anchor(self) -> str:
        """Compact identity text injected into every scene prompt."""
        parts = [self.identity, self.wardrobe, self.distinguishing_features]
        return ". ".join(part.strip().rstrip(".") for part in parts if part and part.strip()) + "."

    def reference_paths(self) -> list[str]:
        return [reference.path for reference in self.references if reference.path]


class CharacterBible(BaseModel):
    """Persistent cast, wardrobe, and style lock for one video."""

    version: int = 1
    fingerprint: str = ""
    style_lock: str = ""
    characters: list[CharacterSpec] = Field(default_factory=list)
    source: str = "llm"
    created_at: str = ""
    notes: str = ""

    def by_id(self, character_id: str) -> Optional[CharacterSpec]:
        return next((item for item in self.characters if item.id == character_id), None)

    def ids(self) -> list[str]:
        return [item.id for item in self.characters]

    def identity_text(self, character_ids: Optional[list[str]] = None) -> str:
        if character_ids is None:
            selected = list(self.characters)
        else:
            wanted = set(character_ids)
            selected = [item for item in self.characters if item.id in wanted]
        return " ".join(item.anchor() for item in selected).strip()

    def reference_paths(self, character_ids: Optional[list[str]] = None) -> list[str]:
        if character_ids is None:
            selected = list(self.characters)
        else:
            wanted = set(character_ids)
            selected = [item for item in self.characters if item.id in wanted]
        paths: list[str] = []
        for item in selected:
            for path in item.reference_paths():
                if path not in paths:
                    paths.append(path)
        return paths


class ScriptPlan(BaseModel):
    """A narration script plus its approval state."""

    topic: str
    title: str = ""
    hook: str = ""
    script: str
    word_count: int = 0
    estimated_duration_seconds: float = 0.0
    approved: bool = False
    edited: bool = False


class WordTiming(BaseModel):
    word: str = ""
    start: float = 0.0
    end: float = 0.0
    score: float = 0.0


class AlignSegment(BaseModel):
    start: float = 0.0
    end: float = 0.0
    text: str = ""
    words: list[WordTiming] = Field(default_factory=list)


class AlignmentResult(BaseModel):
    """Word/sentence timing for the narration audio."""

    segments: list[AlignSegment] = Field(default_factory=list)
    language: str = ""
    duration_seconds: float = 0.0
    source: str = "whisperx"  # "whisperx" | "estimated"

    def sentences(self) -> list[AlignSegment]:
        return self.segments


class Scene(BaseModel):
    """One visual with an absolute time window on the narration timeline."""

    index: int
    start: float
    end: float
    text: str = ""
    prompt: str
    negative_prompt: str = ""
    character_ids: list[str] = Field(default_factory=list)
    seed: Optional[int] = None
    image_path: Optional[str] = None
    attempts: int = 0
    validation_status: str = "pending"  # pending | passed | needs_review | failed
    quality_flags: list[str] = Field(default_factory=list)
    cache_key: str = ""
    backend: str = ""

    @property
    def duration(self) -> float:
        return max(0.0, self.end - self.start)


class SceneManifest(BaseModel):
    """The complete generation plan consumed by the ComfyUI client and renderer."""

    topic: str
    title: str = ""
    narration_audio: str = ""
    target_duration_seconds: float = 0.0
    scene_seconds: float = 2.5
    style_prefix: str = ""
    characters: str = ""
    character_bible: Optional[CharacterBible] = None
    image_backend: str = ""
    script_fingerprint: str = ""
    creative_direction: str = ""
    negative_prompt: str = ""
    alignment_source: str = "estimated"
    thumbnail_prompt: str = ""
    thumbnail_text: str = ""
    thumbnail_source: str = ""
    thumbnail_character_ids: list[str] = Field(default_factory=list)
    scenes: list[Scene] = Field(default_factory=list)

    def total_image_duration(self) -> float:
        return sum(scene.duration for scene in self.scenes)

    def identity_for(self, character_ids: Optional[list[str]] = None) -> str:
        """Identity anchor for a scene (or the thumbnail) from the bible."""
        if self.character_bible:
            return self.character_bible.identity_text(character_ids)
        return self.characters

    def references_for(self, character_ids: Optional[list[str]] = None) -> list[str]:
        if self.character_bible:
            return self.character_bible.reference_paths(character_ids)
        return []

