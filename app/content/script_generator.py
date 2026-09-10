"""
Script and content generation
"""
from typing import Optional
from app.llm.base import LLMProvider, ContentPlan
from app.content import GeneratedContent
from app.config.logging_config import get_logger

logger = get_logger("content.generator")


class ContentGenerator:
    """Generates initial content plan from topic."""

    def __init__(self, llm_provider: LLMProvider):
        """Initialize with LLM provider."""
        self.llm = llm_provider

    def generate(
        self,
        job_id: str,
        topic: str,
        duration_minutes: int,
        style: str = "Cinematic educational documentary",
        tone: str = "Informative and engaging",
    ) -> GeneratedContent:
        """Generate content from topic."""
        logger.info(f"Generating content for: {topic}")

        plan = self.llm.generate_content_plan(
            topic=topic,
            duration_minutes=duration_minutes,
            style=style,
            tone=tone,
        )

        content = GeneratedContent(
            job_id=job_id,
            topic=topic,
            title=plan.title,
            hook=plan.hook,
            description=plan.description,
            script=plan.script,
            sections=plan.sections,
            tags=plan.tags,
            keywords=plan.keywords,
            thumbnail_concept=plan.thumbnail_concept,
        )

        logger.info(f"Content generated: {content.title}")
        return content
