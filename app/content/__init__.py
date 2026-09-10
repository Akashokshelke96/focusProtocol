from __future__ import annotations
"""
Content generation module
"""
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from app.llm.base import ContentPlan, ScenePlan


@dataclass
class GeneratedContent:
    """Represents generated content from LLM."""
    job_id: str
    topic: str
    title: str
    hook: str
    description: str
    script: str
    sections: list[dict[str, Any]] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    keywords: list[str] = field(default_factory=list)
    thumbnail_concept: str = ""
    created_at: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "job_id": self.job_id,
            "topic": self.topic,
            "title": self.title,
            "hook": self.hook,
            "description": self.description,
            "script": self.script,
            "sections": self.sections,
            "tags": self.tags,
            "keywords": self.keywords,
            "thumbnail_concept": self.thumbnail_concept,
            "created_at": self.created_at.isoformat(),
        }


@dataclass
class SceneData:
    """Represents a scene with visual plan."""
    id: int
    start_seconds: float
    end_seconds: float
    duration_seconds: float
    narration: str
    visual_goal: str
    visual_type: str  # video, image, mixed
    pexels_query: str
    pinterest_query: str
    mood: str
    keywords: list[str] = field(default_factory=list)
    recommended_source: str = "either"

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "id": self.id,
            "start_seconds": self.start_seconds,
            "end_seconds": self.end_seconds,
            "duration_seconds": self.duration_seconds,
            "narration": self.narration,
            "visual_goal": self.visual_goal,
            "visual_type": self.visual_type,
            "pexels_query": self.pexels_query,
            "pinterest_query": self.pinterest_query,
            "mood": self.mood,
            "keywords": self.keywords,
            "recommended_source": self.recommended_source,
        }
