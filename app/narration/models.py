"""Typed data structures for the narrated pipeline."""
from __future__ import annotations
from typing import Optional
from pydantic import BaseModel, Field


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
    seed: Optional[int] = None
    image_path: Optional[str] = None
    attempts: int = 0

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
    negative_prompt: str = ""
    alignment_source: str = "estimated"
    thumbnail_prompt: str = ""
    scenes: list[Scene] = Field(default_factory=list)

    def total_image_duration(self) -> float:
        return sum(scene.duration for scene in self.scenes)
