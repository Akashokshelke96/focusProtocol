"""Standalone client for the Google Colab image-generation tunnel.

This module is intentionally independent from the 90-minute video pipeline.
Set COLAB_IMAGE_API_URL to the current public tunnel URL before using it.
"""
from __future__ import annotations

import base64
import os
from pathlib import Path
from typing import Any, Optional

import requests

DEFAULT_API_URL = ""


class ColabImageService:
    """Call the Colab /generate endpoint and save its base64 image response."""

    def __init__(
        self,
        api_url: Optional[str] = None,
        timeout_seconds: int = 180,
        bypass_password: Optional[str] = None,
        api_key: Optional[str] = None,
    ):
        self.api_url = api_url or os.getenv("COLAB_IMAGE_API_URL", DEFAULT_API_URL)
        self.timeout_seconds = timeout_seconds
        self.bypass_password = bypass_password or os.getenv("COLAB_IMAGE_BYPASS_PASSWORD", "")
        self.api_key = api_key or os.getenv("COLAB_IMAGE_API_KEY", "") or os.getenv("COLAB_API_KEY", "")
        if not self.api_url:
            raise RuntimeError("COLAB_IMAGE_API_URL is not configured")

    def generate_image(
        self,
        positive_prompt: str,
        negative_prompt: str = "",
        width: int = 1280,
        height: int = 720,
        steps: int = 20,
        seed: int = -1,
        output_path: Optional[Path] = None,
    ) -> dict[str, Any]:
        """Generate one image and optionally save it locally.

        Raises RuntimeError with the upstream response for tunnel or Colab errors.
        Returns the response metadata plus ``output_path`` when a file is saved.
        """
        payload = {
            "positive_prompt": positive_prompt,
            "negative_prompt": negative_prompt,
            "width": width,
            "height": height,
            "steps": steps,
            "seed": seed,
        }
        headers = {
            "Content-Type": "application/json",
            "Bypass-Tunnel-Reminder": "true",
        }
        if self.bypass_password:
            headers["X-Localtunnel-Password"] = self.bypass_password
        if self.api_key:
            headers["X-API-Key"] = self.api_key

        try:
            response = requests.post(
                self.api_url,
                json=payload,
                headers=headers,
                timeout=self.timeout_seconds,
            )
        except requests.RequestException as error:
            raise RuntimeError(f"Could not reach Colab image API: {error}") from error

        if response.status_code != 200:
            detail = response.text[:1000].strip()
            raise RuntimeError(
                f"Colab image API returned HTTP {response.status_code}: {detail}"
            )

        try:
            data = response.json()
            image_base64 = data["image_base64"]
        except (ValueError, KeyError, TypeError) as error:
            raise RuntimeError("Colab response did not contain image_base64 JSON data") from error

        encoded_image = image_base64.split(",", 1)[-1]
        try:
            image_bytes = base64.b64decode(encoded_image, validate=True)
        except (ValueError, base64.binascii.Error) as error:
            raise RuntimeError("Colab response contained invalid base64 image data") from error

        result = dict(data)
        result["output_path"] = None
        if output_path is not None:
            output_path = Path(output_path)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_bytes(image_bytes)
            result["output_path"] = str(output_path)

        return result


if __name__ == "__main__":
    output = Path("jobs") / "colab_image_test.png"
    result = ColabImageService().generate_image(
        positive_prompt="A cinematic shot of a futuristic neon city, rain reflections, cybernetic aesthetics, 8k masterpiece",
        negative_prompt="blurry, low quality, distortion, text",
        output_path=output,
    )
    print(f"Success! Seed used: {result.get('seed')}")
    print(f"Image saved to: {output}")
