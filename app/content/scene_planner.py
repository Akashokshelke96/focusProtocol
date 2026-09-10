from __future__ import annotations
"""
Scene planning
"""
from typing import Optional
from app.llm.base import LLMProvider
from app.content import SceneData
from app.config.logging_config import get_logger

logger = get_logger("content.planner")


class ScenePlanner:
    """Plans scenes with visual intent from narration."""

    def __init__(self, llm_provider: LLMProvider):
        """Initialize with LLM provider."""
        self.llm = llm_provider

    def plan_scenes(self, script: str) -> list[SceneData]:
        """Generate scene plan from script."""
        logger.info("Planning scenes from script")

        plan = self.llm.generate_scene_plan(script)

        scenes = []
        for scene_dict in plan.scenes:
            try:
                scene = SceneData(
                    id=scene_dict.get("id", 0),
                    start_seconds=scene_dict.get("start_seconds", 0),
                    end_seconds=scene_dict.get("end_seconds", 0),
                    duration_seconds=scene_dict.get("end_seconds", 0) - scene_dict.get("start_seconds", 0),
                    narration=scene_dict.get("narration", ""),
                    visual_goal=scene_dict.get("visual_goal", ""),
                    visual_type=scene_dict.get("visual_type", "video"),
                    pexels_query=scene_dict.get("pexels_query", ""),
                    pinterest_query=scene_dict.get("pinterest_query", ""),
                    mood=scene_dict.get("mood", ""),
                    keywords=scene_dict.get("keywords", []),
                    recommended_source=scene_dict.get("recommended_source", "either"),
                )
                scenes.append(scene)
            except Exception as e:
                logger.error(f"Failed to parse scene: {e}")
                continue

        logger.info(f"Planned {len(scenes)} scenes")
        return scenes
