from __future__ import annotations
"""
LLM Provider Abstraction
"""
from abc import ABC, abstractmethod
from typing import Optional, Any
from pydantic import BaseModel


class ContentPlan(BaseModel):
    """Structured content plan output from LLM."""
    title: str
    hook: str
    description: str
    script: str
    sections: list[dict[str, Any]]
    tags: list[str]
    keywords: list[str]
    thumbnail_concept: str


class ScenePlan(BaseModel):
    """Scene breakdown with visual intent."""
    scenes: list[dict[str, Any]]


class MusicDirection(BaseModel):
    """Music generation direction."""
    mood: str
    style: str
    tempo: str
    intensity: str
    instrumentation: str
    generation_prompts: list[str]
    notes: str


class YoutubeMetadata(BaseModel):
    """YouTube metadata."""
    title: str
    description: str
    tags: list[str]
    category: str
    keywords: list[str]
    thumbnail_text: Optional[str]
    search_queries: str


class LLMProvider(ABC):
    """Abstract base for LLM providers."""

    @abstractmethod
    def generate_content_plan(
        self,
        topic: str,
        duration_minutes: int,
        style: str,
        tone: str,
    ) -> ContentPlan:
        """Generate initial content plan."""
        pass

    @abstractmethod
    def generate_scene_plan(self, script: str) -> ScenePlan:
        """Generate scene breakdown with visual intent."""
        pass

    @abstractmethod
    def generate_music_direction(self, content: str) -> MusicDirection:
        """Generate music direction."""
        pass

    @abstractmethod
    def generate_youtube_metadata(
        self,
        title: str,
        description: str,
        script: str,
    ) -> YoutubeMetadata:
        """Generate YouTube metadata."""
        pass

    @abstractmethod
    def generate_thumbnail_concept(self, title: str, topic: str) -> dict[str, Any]:
        """Generate thumbnail concept."""
        pass
