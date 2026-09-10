from __future__ import annotations
"""
Pexels Video Provider
"""
import requests
from pathlib import Path
from typing import Any, Optional
import time
from app.providers.base import VideoProvider, MediaAsset
from app.config.settings import Settings
from app.config.logging_config import get_logger

logger = get_logger("providers.pexels")


class PexelsVideoProvider(VideoProvider):
    """Pexels video provider implementation."""

    BASE_URL = "https://api.pexels.com/videos/search"
    DOWNLOAD_BASE_URL = "https://www.pexels.com/video"

    def __init__(self, settings: Settings):
        """Initialize Pexels provider."""
        if not settings.pexels_api_key:
            raise ValueError("PEXELS_API_KEY not configured")

        self.api_key = settings.pexels_api_key
        self.settings = settings
        self.session = requests.Session()
        self.session.headers.update({"Authorization": self.api_key})
        logger.info("Pexels provider initialized")

    def search(
        self,
        query: str,
        orientation: str = "landscape",
        per_page: int = 15,
    ) -> list[dict[str, Any]]:
        """Search for videos on Pexels."""
        logger.info(f"Searching Pexels: {query}")

        try:
            response = self.session.get(
                self.BASE_URL,
                params={
                    "query": query,
                    "orientation": orientation,
                    "per_page": per_page,
                    "page": 1,
                },
                timeout=10,
            )
            response.raise_for_status()

            data = response.json()
            videos = data.get("videos", [])
            logger.info(f"Found {len(videos)} Pexels videos")

            return videos

        except requests.exceptions.RequestException as e:
            logger.error(f"Pexels search error: {str(e)}")
            raise

    def _select_best_video_file(self, video: dict[str, Any]) -> Optional[dict[str, Any]]:
        """Select the best quality video file from available options."""
        video_files = video.get("video_files", [])
        if not video_files:
            return None

        # Filter for 16:9 landscape, HD or higher
        candidates = []
        for vf in video_files:
            width = vf.get("width", 0)
            height = vf.get("height", 0)

            # Prefer landscape
            if width < height:
                continue

            # Prefer 1920x1080 or higher
            if width >= self.settings.video_width and height >= self.settings.video_height:
                candidates.append(vf)

        if candidates:
            # Sort by resolution (largest first)
            candidates.sort(key=lambda x: x.get("width", 0) * x.get("height", 0), reverse=True)
            return candidates[0]

        # Fallback to any landscape
        for vf in video_files:
            if vf.get("width", 0) >= vf.get("height", 0):
                return vf

        # Last resort
        return video_files[0] if video_files else None

    def download(self, video: dict[str, Any], output_path: Path) -> Optional[MediaAsset]:
        """Download a Pexels video."""
        video_file = self._select_best_video_file(video)
        if not video_file:
            logger.warning(f"No suitable video file found")
            return None

        url = video_file.get("link")
        if not url:
            logger.warning("Video URL missing")
            return None

        try:
            logger.info(f"Downloading: {url}")
            response = self.session.get(url, timeout=30, stream=True)
            response.raise_for_status()

            # Write file
            output_path.parent.mkdir(parents=True, exist_ok=True)
            with open(output_path, "wb") as f:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)

            logger.info(f"Downloaded to {output_path}")

            # Create asset
            asset = MediaAsset(
                id=str(video.get("id", "")),
                provider="pexels",
                query="",
                file_path=output_path,
                url=url,
                width=video_file.get("width"),
                height=video_file.get("height"),
                metadata={
                    "video_id": video.get("id"),
                    "photographer": video.get("user", {}).get("name"),
                    "photographer_url": video.get("user", {}).get("url"),
                },
            )

            return asset

        except requests.exceptions.RequestException as e:
            logger.error(f"Download failed: {str(e)}")
            if output_path.exists():
                output_path.unlink()
            return None

    def filter_candidates(self, videos: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Filter videos to usable candidates."""
        candidates = []

        for video in videos:
            # Must have video files
            if not video.get("video_files"):
                continue

            # Check for landscape orientation
            video_file = self._select_best_video_file(video)
            if not video_file:
                continue

            width = video_file.get("width", 0)
            height = video_file.get("height", 0)

            # Check aspect ratio
            if height > 0:
                aspect_ratio = width / height
                target = self.settings.image_target_aspect_ratio
                tolerance = self.settings.image_aspect_tolerance

                if not (target - tolerance <= aspect_ratio <= target + tolerance):
                    logger.debug(
                        f"Video {video.get('id')} has aspect ratio "
                        f"{aspect_ratio:.2f}, skipping"
                    )
                    continue

            candidates.append(video)

        logger.info(f"Filtered to {len(candidates)} usable candidates")
        return candidates
