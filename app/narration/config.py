"""Narration config helpers derived from the shared Settings object.

No second configuration system is introduced: this module only interprets
the ``narration_*`` and ``comfy_*`` fields already defined in
``app/config/settings.py`` and produces derived paths / endpoint URLs.
"""
from __future__ import annotations
import json
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlsplit, urlunsplit

from app.config.settings import Settings

# Default node->input wiring for the shipped ComfyUI template
# (workflows/sd_txt2img_api.json). Override with COMFY_INPUT_MAP JSON when
# your own workflow uses different node ids.
DEFAULT_COMFY_INPUT_MAP: dict[str, list[str]] = {
    "positive_prompt": ["4", "text"],
    "negative_prompt": ["5", "text"],
    "seed": ["3", "seed"],
    "steps": ["3", "steps"],
    "cfg": ["3", "cfg"],
    "sampler_name": ["3", "sampler_name"],
    "scheduler": ["3", "scheduler"],
    "width": ["2", "width"],
    "height": ["2", "height"],
    "filename_prefix": ["7", "filename_prefix"],
}

JOB_SUBDIRS = (
    "script",
    "audio",
    "alignment",
    "characters",
    "references",
    "manifest",
    "images",
    "thumbnail",
    "output",
)


def narration_dirs(job_dir: Path) -> dict[str, Path]:
    """Create and return the canonical subdirectories for a narration job."""
    job_dir = Path(job_dir)
    paths = {"job": job_dir}
    for name in JOB_SUBDIRS:
        directory = job_dir / name
        directory.mkdir(parents=True, exist_ok=True)
        paths[name] = directory
    return paths


def _merge_input_map(parsed: dict) -> dict[str, list[str]]:
    merged = {key: list(value) for key, value in DEFAULT_COMFY_INPUT_MAP.items()}
    for key, value in parsed.items():
        if isinstance(value, (list, tuple)) and len(value) == 2:
            merged[key] = [str(value[0]), str(value[1])]
    return merged


def resolve_comfy_input_map(settings: Settings, workflow_path: Optional[Path] = None) -> dict[str, list[str]]:
    """Resolve the node wiring: explicit COMFY_INPUT_MAP > workflow sidecar > defaults.

    A ``<workflow>.map.json`` file next to the workflow (e.g.
    ``flux_schnell_api.map.json``) lets each shipped template carry its own
    node ids without requiring an env override.
    """
    raw = (settings.comfy_input_map or "").strip()
    if raw:
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as error:
            raise ValueError(f"COMFY_INPUT_MAP is not valid JSON: {error}") from error
        if not isinstance(parsed, dict):
            raise ValueError("COMFY_INPUT_MAP must be a JSON object")
        return _merge_input_map(parsed)

    if workflow_path:
        sidecar = Path(workflow_path).with_suffix(".map.json")
        if sidecar.is_file():
            try:
                parsed = json.loads(sidecar.read_text(encoding="utf-8"))
                if isinstance(parsed, dict):
                    return _merge_input_map(parsed)
            except (json.JSONDecodeError, OSError) as error:
                raise ValueError(f"Invalid ComfyUI input-map sidecar {sidecar}: {error}") from error

    return {key: list(value) for key, value in DEFAULT_COMFY_INPUT_MAP.items()}


def derive_ws_url(settings: Settings) -> str:
    """Return the ComfyUI WebSocket URL, deriving it from the base URL if needed."""
    if settings.comfy_ws_url:
        return settings.comfy_ws_url
    base = (settings.comfy_base_url or "").strip()
    if not base:
        return ""
    parts = urlsplit(base)
    scheme = "wss" if parts.scheme == "https" else "ws"
    path = parts.path.rstrip("/") + "/ws"
    return urlunsplit((scheme, parts.netloc, path, "", ""))


def target_word_range(duration_minutes: float) -> tuple[int, int, int]:
    """Word budget (min, target, max) for a spoken duration at ~150 wpm."""
    target = int(round(duration_minutes * 150))
    return int(target * 0.9), target, int(target * 1.12)


def require_remote(settings: Settings) -> None:
    """Validate that the configured pipeline can actually reach its backends.

    Local Piper/Diffusers runs are valid without ``NARRATION_REMOTE_ENABLED``;
    only a backend that needs a URL is rejected when that URL is missing.
    """
    problems: list[str] = []
    if settings.narration_tts_backend == "http" and not settings.narration_tts_url:
        problems.append("NARRATION_TTS_URL is empty (or use NARRATION_TTS_BACKEND=piper_local)")
    if settings.narration_tts_backend == "piper_local":
        if not settings.narration_piper_model:
            problems.append("NARRATION_PIPER_MODEL is empty")
        elif not Path(settings.narration_piper_model).is_file():
            problems.append(f"NARRATION_PIPER_MODEL does not exist: {settings.narration_piper_model}")
    if settings.narration_image_backend == "comfyui" and not settings.comfy_base_url:
        problems.append("COMFY_BASE_URL is empty (or use NARRATION_IMAGE_BACKEND=diffusers)")
    if settings.narration_image_backend == "diffusers" and not settings.narration_image_model:
        problems.append("NARRATION_IMAGE_MODEL is empty")
    if problems:
        raise RuntimeError(
            "The narrated pipeline is not configured: " + "; ".join(problems)
            + ". Set NARRATION_REMOTE_ENABLED=true when using RunPod URLs."
        )


def image_model_label(settings: Settings) -> str:
    """Human-readable backend/model label used in job metadata."""
    if settings.narration_image_backend == "diffusers":
        return f"diffusers:{settings.narration_image_model}+{settings.narration_ip_adapter_weight}"
    return f"comfyui:{settings.comfy_workflow_path}"


def remote_health_targets(settings: Settings) -> dict[str, str]:
    """Endpoints the API health check can probe, one URL per remote service."""
    return {
        "comfyui": settings.comfy_base_url,
        "tts": settings.narration_tts_url,
        "alignment": settings.narration_align_url,
    }
