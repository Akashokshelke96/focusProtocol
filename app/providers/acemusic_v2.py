from __future__ import annotations
"""
ACE-Step 1.5 API - Proper Integration
"""
import os
import time
import requests
from pathlib import Path
from typing import Optional
from app.config.logging_config import get_logger

logger = get_logger("providers.acemusic_v2")


class AceStepProvider:
    """ACE-Step 1.5 Music Generation Provider."""

    def __init__(self):
        self.api_key = os.getenv("ACE_MUSIC_API_KEY")
        self.base_url = os.getenv("ACE_MUSIC_BASE_URL", "https://api.acemusic.ai").rstrip("/")
        self.logger = logger

        if not self.api_key:
            self.logger.warning("ACE_MUSIC_API_KEY not configured")

    def generate_music(
        self,
        prompt: str,
        duration_seconds: int = 60,
        bpm: int = 75,
        num_samples: int = 1,
        thinking: bool = True,
        inference_steps: int = 32,
    ) -> list[dict]:
        """Generate music using ACE-Step API (async workflow)."""

        self.logger.info(f"ACE-Step: Generating {num_samples} samples ({duration_seconds}s at {bpm}BPM)")
        self.logger.info(f"Prompt: {prompt[:80]}...")

        if not self.api_key:
            self.logger.error("ACE_MUSIC_API_KEY not configured")
            return []

        try:
            # Step 1: Submit task
            task_ids = self._submit_task(
                prompt=prompt,
                duration_seconds=duration_seconds,
                bpm=bpm,
                num_samples=num_samples,
                thinking=thinking,
                inference_steps=inference_steps,
            )

            if not task_ids:
                return []

            self.logger.info(f"Tasks submitted: {task_ids}")

            # Step 2: Poll for results
            results = self._poll_results(task_ids, timeout_seconds=300)

            self.logger.info(f"Generated {len(results)} samples")
            return results

        except Exception as e:
            self.logger.error(f"Generation failed: {e}")
            return []

    def _submit_task(
        self,
        prompt: str,
        duration_seconds: int = 60,
        bpm: int = 75,
        num_samples: int = 1,
        thinking: bool = True,
        inference_steps: int = 32,
    ) -> list[str]:
        """Submit music generation task to ACE-Step."""

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        payload = {
            "ai_token": self.api_key,  # Also in body for compatibility
            "caption": prompt,
            "duration": duration_seconds,
            "bpm": bpm,
            "batch_size": num_samples,
            "thinking": thinking,
            "inference_steps": inference_steps,
            "model": "default",
        }

        try:
            self.logger.info(f"Submitting task to {self.base_url}/release_task")

            response = requests.post(
                f"{self.base_url}/release_task",
                json=payload,
                headers=headers,
                timeout=120,  # Increased timeout for longer generation
            )

            self.logger.info(f"Response: {response.status_code}")

            if response.status_code == 200:
                data = response.json()

                if data.get("code") == 200:
                    task_ids = data.get("data", {}).get("task_ids", [])
                    if isinstance(task_ids, str):
                        task_ids = [task_ids]
                    self.logger.info(f"Task IDs: {task_ids}")
                    return task_ids
                else:
                    self.logger.error(f"API Error: {data.get('error')}")
                    return []
            else:
                self.logger.error(f"HTTP {response.status_code}: {response.text[:200]}")
                return []

        except requests.Timeout:
            self.logger.error("Request timeout - ACE-Step server may be busy")
            return []
        except Exception as e:
            self.logger.error(f"Submit task failed: {e}")
            return []

    def _poll_results(self, task_ids: list[str], timeout_seconds: int = 300) -> list[dict]:
        """Poll for task completion and download results."""

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        results = []
        start_time = time.time()

        while time.time() - start_time < timeout_seconds:
            try:
                payload = {
                    "ai_token": self.api_key,
                    "task_ids": task_ids,
                }

                response = requests.post(
                    f"{self.base_url}/query_result",
                    json=payload,
                    headers=headers,
                    timeout=30,
                )

                if response.status_code == 200:
                    data = response.json()

                    if data.get("code") == 200:
                        tasks = data.get("data", {}).get("tasks", [])

                        for task in tasks:
                            status = task.get("status")
                            task_id = task.get("task_id")

                            if status == 1:  # Succeeded
                                self.logger.info(f"Task {task_id} completed")

                                # Extract audio URLs
                                audio_urls = task.get("audio_url", [])
                                if isinstance(audio_urls, str):
                                    audio_urls = [audio_urls]

                                for i, url in enumerate(audio_urls):
                                    results.append({
                                        "task_id": task_id,
                                        "sample_id": i,
                                        "url": url,
                                        "duration": task.get("duration"),
                                        "bpm": task.get("bpm"),
                                        "status": "completed",
                                    })

                            elif status == 2:  # Failed
                                self.logger.error(f"Task {task_id} failed: {task.get('error')}")
                            else:
                                self.logger.debug(f"Task {task_id} status: {status}")

                        # If all tasks done, return results
                        if all(t.get("status") in [1, 2] for t in tasks):
                            return results

                    time.sleep(5)  # Poll every 5 seconds

                else:
                    self.logger.error(f"Query failed: {response.status_code}")
                    time.sleep(5)

            except Exception as e:
                self.logger.error(f"Poll error: {e}")
                time.sleep(5)

        self.logger.warning(f"Timeout waiting for results")
        return results

    def download_audio(self, url: str, output_path: Path) -> bool:
        """Download generated audio."""
        try:
            output_path.parent.mkdir(parents=True, exist_ok=True)

            self.logger.info(f"Downloading: {url[:60]}...")

            response = requests.get(url, timeout=60)
            response.raise_for_status()

            with open(output_path, "wb") as f:
                f.write(response.content)

            size_mb = output_path.stat().st_size / (1024 * 1024)
            self.logger.info(f"Saved: {output_path.name} ({size_mb:.1f} MB)")
            return True

        except Exception as e:
            self.logger.error(f"Download failed: {e}")
            return False

    def health_check(self) -> bool:
        """Check if API is healthy."""
        try:
            response = requests.get(f"{self.base_url}/health", timeout=10)
            is_healthy = response.status_code == 200
            self.logger.info(f"Health check: {'OK' if is_healthy else 'FAILED'}")
            return is_healthy
        except Exception as e:
            self.logger.error(f"Health check failed: {e}")
            return False
