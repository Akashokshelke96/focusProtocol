from __future__ import annotations
"""
ACE-Step Music Provider - Real Integration
"""
import json
import time
from pathlib import Path
from typing import Optional
from app.config.settings import Settings
from app.config.logging_config import get_logger

logger = get_logger("providers.acemusic")


class AceMusicProvider:
    """ACE-Step 1.5 music generation provider."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.api_key = settings.acemusic_api_key
        self.logger = logger

    def generate_music_candidates(
        self,
        music_prompt: str,
        count: int = 4,
        duration_seconds: int = 300,
    ) -> list[dict]:
        """Generate music candidates with ACE-Step."""
        self.logger.info(f"Generating {count} music candidates ({duration_seconds}s)")
        self.logger.info(f"Prompt: {music_prompt[:100]}...")

        try:
            import requests

            # ACE-Step API endpoint
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            }

            payload = {
                "prompt": music_prompt,
                "duration": duration_seconds,
                "num_samples": count,
                "quality": "high",
            }

            response = requests.post(
                "https://api.acemusic.io/v1/generate",
                headers=headers,
                json=payload,
                timeout=300,
            )

            if response.status_code == 200:
                data = response.json()
                candidates = data.get("samples", [])
                self.logger.info(f"✓ Generated {len(candidates)} candidates")
                return candidates
            else:
                self.logger.error(f"ACE-Step API error: {response.status_code}")
                return self._fallback_candidates(duration_seconds)

        except Exception as e:
            self.logger.warning(f"ACE-Step generation failed: {e}, using fallback")
            return self._fallback_candidates(duration_seconds)

    def _fallback_candidates(self, duration_seconds: int) -> list[dict]:
        """Return mock candidates for demo/fallback."""
        self.logger.info("Using mock candidates (ACE-Step not available)")
        return [
            {
                "id": f"mock_candidate_{i}",
                "url": f"https://example.com/music/mock_{i}.mp3",
                "duration": duration_seconds,
                "bpm": 70,
                "quality_score": 0.85,
            }
            for i in range(4)
        ]

    def validate_music_quality(self, audio_path: Path) -> dict:
        """Validate music quality."""
        self.logger.info(f"Validating: {audio_path}")

        try:
            import ffmpeg

            probe = ffmpeg.probe(str(audio_path))
            audio_stream = next(
                s for s in probe["streams"] if s["codec_type"] == "audio"
            )

            duration = float(probe["format"]["duration"])
            bitrate = int(audio_stream.get("bit_rate", 128000))

            # Quality checks
            checks = {
                "duration_valid": self.settings.music_min_duration_seconds
                <= duration
                <= self.settings.music_max_duration_seconds,
                "bitrate_valid": bitrate >= 192000,
                "channels": audio_stream.get("channels", 2),
                "sample_rate": int(audio_stream.get("sample_rate", 44100)),
            }

            is_valid = all(v for k, v in checks.items() if "valid" in k)
            self.logger.info(f"  Duration: {duration:.1f}s, Bitrate: {bitrate/1000:.0f}kbps")

            return {"valid": is_valid, "checks": checks, "duration": duration}

        except Exception as e:
            self.logger.error(f"Validation error: {e}")
            return {"valid": False, "error": str(e)}

    def download_candidate(self, candidate: dict, output_path: Path) -> bool:
        """Download music candidate."""
        try:
            import requests

            url = candidate.get("url")
            if not url:
                self.logger.error("No URL in candidate")
                return False

            self.logger.info(f"Downloading: {url}")
            response = requests.get(url, timeout=60)
            response.raise_for_status()

            output_path.parent.mkdir(parents=True, exist_ok=True)
            with open(output_path, "wb") as f:
                f.write(response.content)

            self.logger.info(f"✓ Saved to: {output_path}")
            return True

        except Exception as e:
            self.logger.error(f"Download failed: {e}")
            return False

    def select_best_candidate(
        self, candidates: list[dict], audio_files: list[Path]
    ) -> tuple[dict, Path]:
        """Select best candidate based on quality scores."""
        best_candidate = None
        best_audio = None
        best_score = 0

        for candidate, audio_file in zip(candidates, audio_files):
            quality = candidate.get("quality_score", 0.5)
            if quality > best_score:
                best_score = quality
                best_candidate = candidate
                best_audio = audio_file

        self.logger.info(f"Selected candidate with score: {best_score:.2f}")
        return best_candidate, best_audio
