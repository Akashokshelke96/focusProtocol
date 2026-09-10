"""
Treblo Music Generation API Provider
Generates high-quality music for Silent Dark Blues compilations
"""
import os
import requests
import time
from pathlib import Path
from typing import Optional, Dict, List
from app.config.logging_config import get_logger
from app.config.settings import Settings

logger = get_logger("providers.treblo")


class TrebloProvider:
    """Generate music using Treblo API."""

    def __init__(self):
        self.settings = Settings()
        self.api_key = os.getenv("TREBLO_API_KEY")
        self.api_url = "https://api.treblo.com/v1"
        self.logger = logger

        if not self.api_key:
            self.logger.warning("TREBLO_API_KEY not set in environment")

    def generate_music(
        self,
        prompt: str,
        duration_seconds: int = 1200,  # 20 minutes default
        title: str = None,
        style: str = "dark_blues",
    ) -> Dict:
        """Generate music track with Treblo API.

        Args:
            prompt: Detailed music generation prompt
            duration_seconds: Duration in seconds (default 1200 = 20 min)
            title: Title for the track
            style: Music style/genre

        Returns:
            Dict with generation_id, status, file_path (when ready)
        """
        if not self.api_key:
            self.logger.error("TREBLO_API_KEY not configured")
            return {"status": "error", "message": "API key not configured"}

        self.logger.info(f"Generating music: {title or 'Untitled'} ({duration_seconds}s)")

        try:
            # Create generation request
            payload = {
                "prompt": prompt,
                "duration": duration_seconds,
                "title": title or "Silent Dark Blues Track",
                "style": style,
                "quality": "high",
                "format": "mp3",
            }

            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            }

            response = requests.post(
                f"{self.api_url}/generations/v3",
                json=payload,
                headers=headers,
                timeout=30,
            )

            if response.status_code in [200, 201]:
                data = response.json()
                # Treblo v3 returns task_id
                task_id = data.get("task_id") or data.get("id")
                self.logger.info(f"Music generation started: {task_id}")

                return {
                    "status": "queued",
                    "generation_id": task_id,
                    "title": title,
                    "duration_seconds": duration_seconds,
                    "created_at": time.time(),
                }

            elif response.status_code == 429:
                self.logger.warning("Rate limited by Treblo API")
                return {"status": "rate_limited", "message": "API rate limit exceeded"}

            else:
                error_msg = response.text or f"HTTP {response.status_code}"
                self.logger.error(f"Music generation failed: {error_msg}")
                return {"status": "error", "message": error_msg}

        except requests.exceptions.Timeout:
            return {"status": "error", "message": "API timeout"}
        except Exception as e:
            self.logger.error(f"Music generation error: {e}")
            return {"status": "error", "message": str(e)}

    def get_generation_status(self, generation_id: str) -> Dict:
        """Check status of music generation.

        Args:
            generation_id: Task ID from generate_music()

        Returns:
            Dict with status, progress, and file_path (when complete)
        """
        if not self.api_key:
            return {"status": "error", "message": "API key not configured"}

        try:
            headers = {"Authorization": f"Bearer {self.api_key}"}

            # Treblo v3 uses /generations/{task_id}
            response = requests.get(
                f"{self.api_url}/generations/{generation_id}",
                headers=headers,
                timeout=10,
            )

            if response.status_code == 200:
                data = response.json()
                # v3 API response format
                status_map = {
                    "pending": "queued",
                    "processing": "processing",
                    "completed": "completed",
                    "failed": "failed"
                }
                status = status_map.get(data.get("status"), data.get("status"))
                progress = data.get("progress", 0)

                result = {
                    "status": status,
                    "progress": progress,
                    "generation_id": generation_id,
                }

                if status == "completed":
                    # v3 returns audio_url or output_url
                    result["file_url"] = data.get("audio_url") or data.get("output_url") or data.get("file_url")
                    result["duration_seconds"] = data.get("duration")
                    result["title"] = data.get("title")

                elif status == "failed":
                    result["error"] = data.get("error_message") or data.get("error")

                self.logger.debug(f"Generation status: {status} ({progress}%)")
                return result

            else:
                self.logger.error(f"Status check failed: HTTP {response.status_code}")
                return {"status": "error", "message": f"HTTP {response.status_code}"}

        except Exception as e:
            self.logger.error(f"Status check error: {e}")
            return {"status": "error", "message": str(e)}

    def download_music(self, file_url: str, output_path: Path) -> bool:
        """Download generated music file.

        Args:
            file_url: URL from completed generation
            output_path: Where to save the MP3

        Returns:
            True if successful
        """
        try:
            headers = {"Authorization": f"Bearer {self.api_key}"}

            response = requests.get(
                file_url,
                headers=headers,
                timeout=60,
                stream=True,
            )

            if response.status_code == 200:
                output_path.parent.mkdir(parents=True, exist_ok=True)
                with open(output_path, "wb") as f:
                    for chunk in response.iter_content(chunk_size=8192):
                        if chunk:
                            f.write(chunk)

                self.logger.info(f"Music downloaded: {output_path.name}")
                return True
            else:
                self.logger.error(f"Download failed: HTTP {response.status_code}")
                return False

        except Exception as e:
            self.logger.error(f"Download error: {e}")
            return False

    def poll_generation(
        self,
        generation_id: str,
        max_wait_seconds: int = 3600,
        poll_interval_seconds: int = 10,
    ) -> Optional[Dict]:
        """Poll until generation completes or times out.

        Args:
            generation_id: Generation ID
            max_wait_seconds: Maximum time to wait
            poll_interval_seconds: How often to check status

        Returns:
            Dict with completed generation data or None if timeout
        """
        start_time = time.time()
        poll_count = 0

        while time.time() - start_time < max_wait_seconds:
            status_result = self.get_generation_status(generation_id)

            if status_result.get("status") == "completed":
                self.logger.info(f"Generation completed after {poll_count} polls")
                return status_result

            elif status_result.get("status") == "failed":
                self.logger.error(f"Generation failed: {status_result.get('error')}")
                return None

            poll_count += 1
            progress = status_result.get("progress", 0)
            self.logger.info(f"[Poll {poll_count}] Progress: {progress}%")

            time.sleep(poll_interval_seconds)

        self.logger.error(f"Generation timeout after {max_wait_seconds}s")
        return None


def create_dark_blues_prompt(variation: int = 1) -> str:
    """Create a dark blues music generation prompt.

    Args:
        variation: Which variation (1-5) to create

    Returns:
        Detailed prompt for Treblo API
    """
    base = (
        "SLOW 76–80 BPM. Dark, smoky, sophisticated, masculine and calm. "
        "2 AM atmosphere — rain outside, dim room, black coffee, one person working alone with complete focus. "
        "INSTRUMENTS: ONLY 1–3. Warm, breathy tenor saxophone as the main instrument, "
        "with a very subtle upright bass underneath. Extremely sparse arrangement. "
        "VOCALS: Occasional deep male baritone, quietly spoken and intimate, with long instrumental gaps. "
        "Short, intelligent phrases about discipline, focus, patience and working alone. Never theatrical or motivational."
    )

    variations = {
        1: base + " Focus on saxophone with minimal bass.",
        2: base + " Emphasize the baritone vocals, intimate spoken delivery.",
        3: base + " Deep focus on the 2 AM solitude, minimal movement, hypnotic groove.",
        4: base + " Add subtle rain sounds in background, maintain saxophone focus.",
        5: base + " Late-night noir blues, saxophone-driven, deep male presence.",
    }

    return variations.get(variation, base)
