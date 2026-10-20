from __future__ import annotations
"""
Gemini LLM Provider Implementation
"""
import json
import re
import os
from typing import Any
import requests
from app.config.settings import Settings
from app.config.prompts import (
    CONTENT_GENERATION_PROMPT,
    SCENE_PLANNING_PROMPT,
    MUSIC_DIRECTION_PROMPT,
    METADATA_GENERATION_PROMPT,
    THUMBNAIL_CONCEPT_PROMPT,
)
from app.llm.base import (
    LLMProvider,
    ContentPlan,
    ScenePlan,
    MusicDirection,
    YoutubeMetadata,
)
from app.config.logging_config import get_logger

logger = get_logger("llm.gemini")


class GeminiProvider(LLMProvider):
    """Gemini LLM provider implementation using OpenRouter."""

    OPENROUTER_API_URL = "https://openrouter.ai/api/v1/chat/completions"

    def __init__(self, settings: Settings):
        """Initialize Gemini provider."""
        # Try GEMINI_API_KEY first, then fall back to OPENROUTER_API_KEY
        api_key = settings.gemini_api_key or os.getenv("OPENROUTER_API_KEY")

        if not api_key and settings.llm_provider != 'omniroute':
            raise ValueError("GEMINI_API_KEY or OPENROUTER_API_KEY not configured")

        self.api_key = api_key
        self.settings = settings
        # Detect if using OpenRouter
        self.is_openrouter = "sk-or-" in (api_key or '')

        logger.info(f"Gemini provider initialized (OpenRouter: {self.is_openrouter})")

    def _extract_json(self, response: str) -> dict[str, Any]:
        """Extract JSON from response."""
        response = response.strip()
        if response.startswith("```"):
            response = re.sub(r"^```(?:json)?\n", "", response)
            response = re.sub(r"\n```$", "", response)

        try:
            return json.loads(response)
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse JSON: {response[:200]}...")
            raise ValueError(f"Invalid JSON from LLM: {str(e)}")

    def generate_json(self, prompt: str) -> Any:
        """Run a raw prompt and return its parsed JSON payload.

        Shared entry point for sibling pipelines (e.g. the narrated pipeline)
        that need structured LLM output without a dedicated method.
        """
        return self._extract_json(self._generate_with_retry(prompt))

    def _generate_with_retry(self, prompt: str, max_retries: int = 3) -> str:
        """Generate content with retry logic."""
        for attempt in range(max_retries):
            try:
                if self.settings.llm_provider == 'omniroute':
                    return self._call_omniroute(prompt)
                if self.is_openrouter:
                    return self._call_openrouter(prompt)
                else:
                    return self._call_gemini(prompt)
            except Exception as e:
                logger.warning(f"Attempt {attempt + 1} failed: {str(e)}")
                if attempt == max_retries - 1:
                    raise
                import time
                time.sleep(2 ** attempt)  # Exponential backoff
                continue

    def _call_omniroute(self, prompt: str) -> str:
        base = self.settings.omniroute_base_url.rstrip('/')
        if not base.endswith('/v1'):
            base += '/v1'
        headers = {'Content-Type': 'application/json'}
        if self.settings.omniroute_api_key:
            headers['Authorization'] = 'Bearer ' + self.settings.omniroute_api_key
        response = requests.post(base + '/chat/completions', headers=headers, json={
            'model': self.settings.omniroute_model,
            'messages': [{'role': 'user', 'content': prompt}],
            'max_tokens': 8000, 'stream': False,
        }, timeout=90)
        response.raise_for_status()
        # Some OmniRoute routes return SSE even for stream=false.
        if response.text.lstrip().startswith('data:'):
            chunks = []
            for line in response.text.splitlines():
                if line.startswith('data:') and line[5:].strip() != '[DONE]':
                    event = json.loads(line[5:].strip())
                    for choice in event.get('choices', []):
                        chunks.append(choice.get('delta', {}).get('content') or '')
            result = ''.join(chunks)
        else:
            result = response.json()['choices'][0]['message']['content']
        if not result:
            raise ValueError('OmniRoute returned no content; check the configured model route')
        return result

    def _call_openrouter(self, prompt: str) -> str:
        """Call OpenRouter API."""
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "http://localhost",
            "X-Title": "YouTube Automation Engine",
        }

        payload = {
            "model": "openai/gpt-4o-mini",  # Using GPT-4o Mini via OpenRouter
            "messages": [
                {
                    "role": "user",
                    "content": prompt,
                }
            ],
            "temperature": 0.7,
            "top_p": 0.9,
            "max_tokens": 8000,
        }

        response = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers=headers,
            json=payload,
            timeout=60,
        )
        response.raise_for_status()

        data = response.json()
        return data["choices"][0]["message"]["content"]

    def _call_gemini(self, prompt: str) -> str:
        """Call Google Gemini REST API directly (no SDK dependency)."""
        model = self.settings.gemini_model or "gemini-2.5-flash"
        response = requests.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
            headers={"Content-Type": "application/json", "x-goog-api-key": self.api_key},
            json={
                "contents": [{"role": "user", "parts": [{"text": prompt}]}],
                "generationConfig": {
                    "temperature": 0.7,
                    "topP": 0.9,
                    "maxOutputTokens": 8000,
                },
            },
            timeout=90,
        )
        response.raise_for_status()
        candidate = (response.json().get("candidates") or [{}])[0]
        parts = candidate.get("content", {}).get("parts", [])
        text = "".join(part.get("text", "") for part in parts if not part.get("thought"))
        if not text:
            raise ValueError(f"Gemini returned no text ({candidate.get('finishReason', 'unknown')})")
        return text

    def generate_content_plan(
        self,
        topic: str,
        duration_minutes: int,
        style: str = "Cinematic educational documentary",
        tone: str = "Informative and engaging",
    ) -> ContentPlan:
        """Generate initial content plan."""
        logger.info(f"Generating content plan for: {topic}")

        prompt = CONTENT_GENERATION_PROMPT.format(
            topic=topic,
            duration_minutes=duration_minutes,
            style=style,
            tone=tone,
        )

        response_text = self._generate_with_retry(prompt)
        data = self._extract_json(response_text)

        try:
            plan = ContentPlan(**data)
            logger.info(
                f"Content plan generated: {plan.title} "
                f"({len(plan.sections)} sections)"
            )
            return plan
        except Exception as e:
            logger.error(f"Failed to create ContentPlan: {str(e)}")
            raise

    def generate_scene_plan(self, script: str) -> ScenePlan:
        """Generate scene breakdown with visual intent."""
        logger.info("Generating scene plan")

        prompt = SCENE_PLANNING_PROMPT.format(script=script)
        response_text = self._generate_with_retry(prompt)
        data = self._extract_json(response_text)

        try:
            plan = ScenePlan(**data)
            logger.info(f"Scene plan generated: {len(plan.scenes)} scenes")
            return plan
        except Exception as e:
            logger.error(f"Failed to create ScenePlan: {str(e)}")
            raise

    def generate_music_direction(self, content: str) -> MusicDirection:
        """Generate music direction."""
        logger.info("Generating music direction")

        prompt = MUSIC_DIRECTION_PROMPT.format(content=content[:1000])
        response_text = self._generate_with_retry(prompt)
        data = self._extract_json(response_text)

        try:
            direction = MusicDirection(**data)
            logger.info(
                f"Music direction generated: {direction.mood}, "
                f"{direction.tempo} tempo"
            )
            return direction
        except Exception as e:
            logger.error(f"Failed to create MusicDirection: {str(e)}")
            raise

    def generate_youtube_metadata(
        self,
        title: str,
        description: str,
        script: str,
    ) -> YoutubeMetadata:
        """Generate YouTube metadata."""
        logger.info("Generating YouTube metadata")

        prompt = METADATA_GENERATION_PROMPT.format(
            title=title,
            description=description,
            script=script[:1000],
        )

        response_text = self._generate_with_retry(prompt)
        data = self._extract_json(response_text)

        try:
            metadata = YoutubeMetadata(**data)
            logger.info(f"YouTube metadata generated")
            return metadata
        except Exception as e:
            logger.error(f"Failed to create YoutubeMetadata: {str(e)}")
            raise

    def generate_thumbnail_concept(self, title: str, topic: str) -> dict[str, Any]:
        """Generate thumbnail concept."""
        logger.info("Generating thumbnail concept")

        prompt = THUMBNAIL_CONCEPT_PROMPT.format(title=title, topic=topic)
        response_text = self._generate_with_retry(prompt)
        data = self._extract_json(response_text)

        logger.info("Thumbnail concept generated")
        return data

    def generate_music_prompt(self, channel_profile: dict) -> str:
        """Generate music prompt from channel profile."""
        logger.info("Generating music prompt from profile")

        from app.config.prompts import MUSIC_GENERATION_PROMPT

        prompt = MUSIC_GENERATION_PROMPT

        response_text = self._generate_with_retry(prompt)
        data = self._extract_json(response_text)

        music_prompt = data.get("music_prompt", "Dark blues instrumental, 70 BPM, gentleman's club atmosphere")
        logger.info(f"Music prompt generated: {music_prompt[:100]}...")
        return music_prompt

    def generate_hero_image_prompts(
        self, channel_profile: dict, num_images: int = 6
    ) -> list[dict]:
        """Generate hero image prompts from channel profile (profile-constrained)."""
        logger.info(f"Generating {num_images} hero image prompts from profile")

        from app.config.prompts import HERO_IMAGE_PROMPTS_GENERATION

        prompt = HERO_IMAGE_PROMPTS_GENERATION

        response_text = self._generate_with_retry(prompt)
        data = self._extract_json(response_text)

        hero_images = data.get("hero_images", [])
        logger.info(f"Generated {len(hero_images)} hero image prompts")
        return hero_images
