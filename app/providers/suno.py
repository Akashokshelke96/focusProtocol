from __future__ import annotations
"""
Suno API Music Generation Provider - COMPLETE IMPLEMENTATION
Supports both callback and polling modes
"""
import os
import time
import requests
import json
from pathlib import Path
from typing import Optional
from app.config.logging_config import get_logger

logger = get_logger("providers.suno")


class SunoProvider:
    """Suno API music generation provider with callback support."""

    def __init__(self, callback_url: Optional[str] = None):
        self.api_key = os.getenv("SUNO_API_KEY")
        self.base_url = "https://api.sunoapi.org"
        self.callback_url = callback_url or "https://api.example.com/callback"
        self.logger = logger

        if not self.api_key:
            self.logger.error("SUNO_API_KEY not configured")

    def generate_music(
        self,
        prompt: str,
        duration_seconds: int = 30,
    ) -> list[dict]:
        """Generate music using Suno API."""
        self.logger.info(f"Suno: Generating music ({duration_seconds}s)")
        self.logger.info(f"Prompt: {prompt[:80]}...")

        if not self.api_key:
            self.logger.error("SUNO_API_KEY not configured")
            return []

        try:
            task_id = self._submit_generation(
                prompt=prompt,
                duration_seconds=duration_seconds,
            )

            if not task_id:
                self.logger.error("Failed to submit generation task")
                return []

            self.logger.info(f"Task submitted: {task_id}")

            # Use polling since callback URL is placeholder
            results = self._poll_completion(task_id, timeout_seconds=300)

            self.logger.info(f"Generated {len(results)} track(s)")
            return results

        except Exception as e:
            self.logger.error(f"Generation failed: {e}")
            return []

    def _submit_generation(
        self,
        prompt: str,
        duration_seconds: int = 30,
    ) -> Optional[str]:
        """Submit a generation request to Suno API."""
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        # For V5_5 model, duration can be specified (10-30s)
        # For other models, duration is auto-calculated from prompt/context
        use_v5_5 = False  # Use V4_5ALL which has better structure

        payload = {
            "customMode": True,
            "instrumental": True,
            "model": "V4_5ALL",  # V4_5ALL has better song structure
            "prompt": prompt,
            "style": "Blues",
            "negativeTags": "Vocals, Rap, EDM, Upbeat",
            "styleWeight": 0.7,
            "weirdnessConstraint": 0.5,
            "callBackUrl": self.callback_url,
        }

        # Duration only for V5_5
        if use_v5_5:
            payload["model"] = "V5_5"
            duration = min(max(10, duration_seconds), 30)
            payload["duration"] = duration

        try:
            endpoint = f"{self.base_url}/api/v1/generate"
            self.logger.info(f"Submitting to {endpoint}")
            self.logger.info(f"Model: {payload['model']}")
            if use_v5_5:
                self.logger.info(f"Duration: {payload.get('duration')} seconds")

            response = requests.post(
                endpoint,
                json=payload,
                headers=headers,
                timeout=60,
            )

            self.logger.info(f"Response status: {response.status_code}")

            if response.status_code in [200, 201]:
                data = response.json()
                self.logger.info(f"Response: {json.dumps(data)[:200]}")

                if data.get("code") == 200 and data.get("data"):
                    task_id = data["data"].get("taskId")
                    if task_id:
                        self.logger.info(f"Task ID: {task_id}")
                        return task_id

                self.logger.error(f"API Error: {data.get('msg', 'Unknown')}")
                return None
            else:
                self.logger.error(f"HTTP {response.status_code}")
                self.logger.error(f"Response: {response.text[:300]}")
                return None

        except requests.Timeout:
            self.logger.error("Request timeout")
            return None
        except Exception as e:
            self.logger.error(f"Submit failed: {e}")
            return None

    def _poll_completion(
        self,
        task_id: str,
        timeout_seconds: int = 300,
    ) -> list[dict]:
        """Poll Suno API for task completion."""
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        results = []
        start_time = time.time()
        poll_count = 0

        self.logger.info(f"Polling for task completion (timeout: {timeout_seconds}s)...")

        while time.time() - start_time < timeout_seconds:
            try:
                poll_count += 1
                elapsed = int(time.time() - start_time)
                self.logger.info(f"Poll #{poll_count} ({elapsed}s elapsed)...")

                query_url = f"{self.base_url}/api/v1/get_music_details"
                payload = {"taskId": task_id}

                response = requests.post(
                    query_url,
                    json=payload,
                    headers=headers,
                    timeout=30,
                )

                if response.status_code in [200, 201]:
                    data = response.json()

                    if data.get("code") == 200 and data.get("data"):
                        tasks = data["data"]
                        if not isinstance(tasks, list):
                            tasks = [tasks]

                        for task in tasks:
                            status = task.get("status", "unknown")
                            current_task_id = task.get("taskId", task_id)

                            self.logger.info(f"Task status: {status}")

                            if status == "complete" or status == "succeeded":
                                self.logger.info(f"Task {current_task_id} completed!")

                                # Extract audio URLs from result
                                audio_url = task.get("audio_url")
                                if audio_url:
                                    results.append({
                                        "task_id": current_task_id,
                                        "url": audio_url,
                                        "duration": task.get("duration", 30),
                                        "title": task.get("title", ""),
                                        "status": "completed",
                                    })
                                    self.logger.info(f"Audio URL: {audio_url[:80]}...")

                                return results

                            elif status in ["submitted", "processing"]:
                                self.logger.info(f"Still processing... ({elapsed}s)")

                            elif status in ["error", "failed"]:
                                self.logger.error(f"Task failed: {task.get('error', 'Unknown')}")
                                return results

                    else:
                        self.logger.debug(f"Waiting for task to appear...")

                    time.sleep(3)

                else:
                    self.logger.error(f"Query failed: {response.status_code}")
                    time.sleep(3)

            except Exception as e:
                self.logger.error(f"Poll error: {e}")
                time.sleep(3)

        self.logger.warning(f"Timeout after {timeout_seconds}s, returning {len(results)} completed tasks")
        return results

    def download_audio(self, url: str, output_path: Path) -> bool:
        """Download generated audio from Suno."""
        try:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            self.logger.info(f"Downloading: {url[:80]}...")

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
