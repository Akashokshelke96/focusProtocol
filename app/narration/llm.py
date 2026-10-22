"""Narration-specific LLM routing with honest provider/model fallbacks.

The shared ``GeminiProvider`` is intentionally left untouched: the rest of the
application depends on its existing behaviour. This module resolves the keys
that are actually available to the narration pipeline (including the
``*_NARRATOR`` aliases), tries an ordered list of models, and returns parsed
JSON. It never claims that a text model can generate images.
"""
from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass
from typing import Any, Optional

import requests

from app.config.logging_config import get_logger
from app.config.settings import Settings

logger = get_logger("narration.llm")


class NarrationLLMError(RuntimeError):
    """Raised when every configured narration LLM route fails."""


def extract_json(text: str) -> Any:
    """Parse JSON from a model response, tolerating prose or code fences."""
    if not isinstance(text, str) or not text.strip():
        raise ValueError("LLM returned an empty response")
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass
    decoder = json.JSONDecoder()
    for opener in ("{", "["):
        start = cleaned.find(opener)
        if start < 0:
            continue
        try:
            parsed, _end = decoder.raw_decode(cleaned[start:])
            return parsed
        except json.JSONDecodeError:
            continue
    raise ValueError(f"LLM response was not valid JSON: {cleaned[:240]!r}")


@dataclass(frozen=True)
class LLMRoute:
    provider: str
    base_url: str
    api_key: str
    models: tuple[str, ...]
    extra_headers: tuple[tuple[str, str], ...] = ()


def _dedupe(values: list[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        value = (value or "").strip()
        if value and value not in seen:
            seen.add(value)
            ordered.append(value)
    return tuple(ordered)


def _model_list(settings: Settings, primary: str, fallbacks: str) -> tuple[str, ...]:
    explicit = (settings.narration_llm_model or "").strip()
    values = [explicit, primary]
    values.extend((fallbacks or "").split(","))
    return _dedupe(values)


def resolve_routes(settings: Settings) -> list[LLMRoute]:
    """Resolve every usable narration LLM route without leaking key values."""
    preferred = (settings.narration_llm_provider or "auto").strip().lower()
    gemini_key = (settings.narration_gemini_api_key or "").strip()
    shared_gemini = (settings.gemini_api_key or "").strip()
    openrouter_key = (
        settings.narration_openrouter_api_key
        or os.getenv("OPENROUTER_API_KEY_NARRATOR", "")
        or os.getenv("OPENROUTER_API_KEY", "")
        or ""
    ).strip()
    if not openrouter_key and shared_gemini.startswith("sk-or-"):
        openrouter_key = shared_gemini
    if not gemini_key and shared_gemini.startswith("AIza"):
        gemini_key = shared_gemini

    omniroute_key = (
        settings.narration_omniroute_api_key
        or settings.omniroute_api_key
        or os.getenv("OMNIROUTE_API_KEY_NARRATOR", "")
        or os.getenv("OMNIROUTE_API_KEY", "")
        or ""
    ).strip()

    openrouter_models = _model_list(
        settings, settings.narration_openrouter_model, settings.narration_llm_fallback_models)
    routes: dict[str, LLMRoute] = {}

    if openrouter_key:
        routes["openrouter"] = LLMRoute(
            provider="openrouter",
            base_url="https://openrouter.ai/api/v1",
            api_key=openrouter_key,
            models=openrouter_models,
            extra_headers=(
                ("HTTP-Referer", "https://localhost/narration-studio"),
                ("X-Title", "Focus Protocol Narration Studio"),
            ),
        )
    if gemini_key:
        routes["gemini"] = LLMRoute(
            provider="gemini",
            base_url="https://generativelanguage.googleapis.com/v1beta",
            api_key=gemini_key,
            models=_dedupe([settings.narration_llm_model, settings.gemini_model]),
        )
    if omniroute_key or (settings.omniroute_base_url and preferred == "omniroute"):
        base = (settings.omniroute_base_url or "").rstrip("/")
        if base and not base.endswith("/v1"):
            base += "/v1"
        routes["omniroute"] = LLMRoute(
            provider="omniroute",
            base_url=base,
            api_key=omniroute_key,
            models=_dedupe([settings.narration_llm_model, settings.omniroute_model]),
        )

    if preferred == "auto":
        ordered = [name for name in ("openrouter", "gemini", "omniroute") if name in routes]
    else:
        ordered = [preferred] if preferred in routes else []
        ordered += [name for name in ("openrouter", "gemini", "omniroute") if name in routes and name not in ordered]
    return [routes[name] for name in ordered]


class NarrationLLM:
    """Small OpenAI-compatible/Gemini client with per-model fallback."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.routes = resolve_routes(settings)
        self.timeout = max(15, int(settings.narration_llm_timeout_seconds))
        self.retries = max(0, int(settings.narration_llm_max_retries))

    # ------------------------------------------------------------------ public
    @property
    def available(self) -> bool:
        return bool(self.routes)

    def describe(self) -> dict[str, Any]:
        return {
            "routes": [
                {"provider": route.provider, "models": list(route.models)}
                for route in self.routes
            ]
        }

    def generate_json(self, prompt: str) -> Any:
        if not self.routes:
            raise NarrationLLMError(
                "No narration LLM credential found. Set OPENROUTER_API_KEY_NARRATOR, "
                "GEMINI_API_KEY_NARRATOR, OMNIROUTE_API_KEY_NARRATOR, or a valid "
                "OPENROUTER_API_KEY/GEMINI_API_KEY. Text models do not generate images."
            )
        errors: list[str] = []
        for route in self.routes:
            if not route.models:
                continue
            for model in route.models:
                try:
                    text = self._complete(route, model, prompt)
                    payload = extract_json(text)
                    return payload
                except Exception as error:  # noqa: BLE001 - try the next route/model
                    message = str(error).replace(route.api_key, "<redacted>") if route.api_key else str(error)
                    errors.append(f"{route.provider}/{model}: {message[:240]}")
                    logger.warning("Narration LLM route failed (%s/%s): %s",
                                   route.provider, model, message[:240])
        raise NarrationLLMError("All narration LLM routes failed: " + " | ".join(errors[-6:]))

    # ----------------------------------------------------------------- request
    def _complete(self, route: LLMRoute, model: str, prompt: str) -> str:
        last_error: Optional[Exception] = None
        for attempt in range(self.retries + 1):
            try:
                if route.provider == "gemini":
                    return self._call_gemini(route, model, prompt)
                return self._call_openai_compatible(route, model, prompt)
            except requests.HTTPError as error:
                status = error.response.status_code if error.response is not None else 0
                last_error = error
                if status not in (408, 409, 425, 429, 500, 502, 503, 504):
                    raise
            except (requests.RequestException, ValueError) as error:
                last_error = error
            if attempt < self.retries:
                time.sleep(min(8.0, 1.5 * (2 ** attempt)))
        raise last_error or NarrationLLMError("LLM request failed")

    def _call_openai_compatible(self, route: LLMRoute, model: str, prompt: str) -> str:
        headers = {"Content-Type": "application/json"}
        if route.api_key:
            headers["Authorization"] = f"Bearer {route.api_key}"
        for key, value in route.extra_headers:
            headers[key] = value
        response = requests.post(
            f"{route.base_url.rstrip('/')}/chat/completions",
            headers=headers,
            json={
                "model": model,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.7,
                "top_p": 0.9,
                "max_tokens": 8000,
                "stream": False,
            },
            timeout=self.timeout,
        )
        if response.status_code >= 400:
            raise requests.HTTPError(
                f"HTTP {response.status_code}: {response.text[:300]}", response=response)
        payload = response.json()
        choices = payload.get("choices") or []
        if not choices:
            raise ValueError(f"{route.provider} returned no choices")
        content = (choices[0].get("message") or {}).get("content") or ""
        if not content:
            raise ValueError(f"{route.provider} returned empty content")
        return content

    def _call_gemini(self, route: LLMRoute, model: str, prompt: str) -> str:
        response = requests.post(
            f"{route.base_url}/models/{model}:generateContent",
            headers={"Content-Type": "application/json", "x-goog-api-key": route.api_key},
            json={
                "contents": [{"role": "user", "parts": [{"text": prompt}]}],
                "generationConfig": {
                    "temperature": 0.7,
                    "topP": 0.9,
                    "maxOutputTokens": 8000,
                },
            },
            timeout=self.timeout,
        )
        if response.status_code >= 400:
            raise requests.HTTPError(
                f"HTTP {response.status_code}: {response.text[:300]}", response=response)
        payload = response.json()
        candidate = (payload.get("candidates") or [{}])[0]
        parts = (candidate.get("content") or {}).get("parts") or []
        text = "".join(part.get("text", "") for part in parts if not part.get("thought"))
        if not text:
            raise ValueError(
                f"Gemini returned no text ({candidate.get('finishReason', 'unknown')})")
        return text


def build_narration_llm(settings: Settings) -> NarrationLLM:
    return NarrationLLM(settings)
