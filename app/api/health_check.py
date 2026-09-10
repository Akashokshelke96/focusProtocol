"""
Health Check System - Validates all dependent APIs and systems
"""
import json
from datetime import datetime
from pathlib import Path
import requests
from app.config.logging_config import get_logger
from app.config.settings import Settings

logger = get_logger("api.health_check")


class HealthChecker:
    """Check health of all dependent systems and APIs."""

    def __init__(self):
        self.settings = Settings()
        self.checks = {}

    def check_all(self) -> dict:
        """Run all health checks."""
        logger.info("Running comprehensive health checks...")

        results = {
            "timestamp": datetime.utcnow().isoformat(),
            "status": "checking",
            "checks": {
                "gemini": self._check_gemini(),
                "suno": self._check_suno(),
                "local_images": self._check_local_images(),
                "ffmpeg": self._check_ffmpeg(),
                "output_directory": self._check_output_dir(),
                "mega_library": self._check_mega_library(),
            }
        }

        # Overall status
        all_passed = all(
            check.get("status") == "healthy"
            for check in results["checks"].values()
        )
        results["status"] = "healthy" if all_passed else "degraded"

        return results

    def _check_gemini(self) -> dict:
        """Check Gemini API connectivity and key validity."""
        try:
            from app.llm.gemini import GeminiProvider

            gemini = GeminiProvider(self.settings)

            # Try a simple test call
            test_prompt = "Respond with 'OK' only."
            response = gemini._generate_with_retry(test_prompt)

            if response:
                return {
                    "status": "healthy",
                    "message": "Gemini API connected and responding",
                    "provider": "OpenRouter",
                    "model": "claude-3.5-sonnet"
                }
            else:
                return {
                    "status": "error",
                    "message": "Gemini API not responding",
                    "provider": "OpenRouter"
                }
        except Exception as e:
            return {
                "status": "error",
                "message": f"Gemini API check failed: {str(e)}",
                "details": str(e)
            }

    def _check_suno(self) -> dict:
        """Check Suno API connectivity and account status."""
        try:
            from app.providers.suno import SunoProvider

            suno = SunoProvider()

            # Check API key existence
            if not suno.api_key:
                return {
                    "status": "error",
                    "message": "Suno API key not configured"
                }

            # Try to connect to Suno API
            response = requests.get(
                "https://api.sunoapi.org/api/v1/credit",
                headers={"Authorization": f"Bearer {suno.api_key}"},
                timeout=5
            )

            if response.status_code == 200:
                data = response.json()
                credits = data.get("data", {}).get("credits", 0)
                return {
                    "status": "healthy",
                    "message": "Suno API connected",
                    "credits": credits,
                    "endpoint": "https://api.sunoapi.org"
                }
            elif response.status_code == 429:
                return {
                    "status": "warning",
                    "message": "Insufficient Suno credits",
                    "http_code": 429
                }
            else:
                return {
                    "status": "warning",
                    "message": f"Suno API returned {response.status_code}",
                    "http_code": response.status_code
                }

        except requests.exceptions.Timeout:
            return {
                "status": "error",
                "message": "Suno API timeout - connection issue"
            }
        except Exception as e:
            return {
                "status": "error",
                "message": f"Suno API check failed: {str(e)}",
                "details": str(e)
            }

    def _check_local_images(self) -> dict:
        """Check local image folder and file count."""
        try:
            image_folder = Path("backgroundImages")

            if not image_folder.exists():
                return {
                    "status": "error",
                    "message": "Background images folder not found",
                    "path": str(image_folder.absolute())
                }

            # Count supported image files
            supported_ext = {'.jpg', '.jpeg', '.png', '.webp'}
            images = [f for f in image_folder.iterdir()
                     if f.suffix.lower() in supported_ext]

            if not images:
                return {
                    "status": "warning",
                    "message": "No background images found",
                    "path": str(image_folder.absolute())
                }

            return {
                "status": "healthy",
                "message": f"{len(images)} background images available",
                "count": len(images),
                "path": str(image_folder.absolute())
            }

        except Exception as e:
            return {
                "status": "error",
                "message": f"Image folder check failed: {str(e)}"
            }

    def _check_ffmpeg(self) -> dict:
        """Check FFmpeg availability."""
        try:
            import subprocess

            result = subprocess.run(
                ["ffmpeg", "-version"],
                capture_output=True,
                timeout=5
            )

            if result.returncode == 0:
                version_line = result.stdout.decode().split('\n')[0]
                return {
                    "status": "healthy",
                    "message": "FFmpeg installed and available",
                    "version": version_line
                }
            else:
                return {
                    "status": "error",
                    "message": "FFmpeg check failed",
                    "return_code": result.returncode
                }

        except FileNotFoundError:
            return {
                "status": "error",
                "message": "FFmpeg not found in PATH"
            }
        except Exception as e:
            return {
                "status": "error",
                "message": f"FFmpeg check failed: {str(e)}"
            }

    def _check_output_dir(self) -> dict:
        """Check output directory writable."""
        try:
            output_dir = Path("output")
            output_dir.mkdir(parents=True, exist_ok=True)

            # Try to write a test file
            test_file = output_dir / ".health_check"
            test_file.write_text("test")
            test_file.unlink()

            return {
                "status": "healthy",
                "message": "Output directory writable",
                "path": str(output_dir.absolute())
            }
        except Exception as e:
            return {
                "status": "error",
                "message": f"Output directory check failed: {str(e)}"
            }

    def _check_mega_library(self) -> dict:
        """Check mega library directory."""
        try:
            lib_dir = Path("mega_compilation_library")
            lib_dir.mkdir(parents=True, exist_ok=True)

            # Count episodes
            episodes = list(lib_dir.glob("episode_*"))

            return {
                "status": "healthy",
                "message": f"Mega library ready ({len(episodes)} episodes)",
                "episodes": len(episodes),
                "path": str(lib_dir.absolute())
            }
        except Exception as e:
            return {
                "status": "error",
                "message": f"Mega library check failed: {str(e)}"
            }


def run_health_checks() -> dict:
    """Quick health check runner."""
    checker = HealthChecker()
    return checker.check_all()
