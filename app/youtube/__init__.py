from __future__ import annotations
"""
YouTube OAuth and upload
"""
from pathlib import Path
from typing import Optional
from app.config.settings import Settings
from app.config.logging_config import get_logger
from app.youtube.oauth import YouTubeService

logger = get_logger("youtube.uploader")


class YouTubeUploader:
    """Handles YouTube upload via OAuth."""

    def __init__(self, settings: Settings):
        """Initialize uploader."""
        if not settings.youtube_upload_enabled:
            logger.info("YouTube upload is disabled")

        self.settings = settings
        logger.info("YouTube uploader initialized")

    def upload(
        self,
        video_path: Path,
        title: str,
        description: str,
        tags: list[str],
    ) -> bool:
        """Upload video to YouTube."""
        if not self.settings.youtube_upload_enabled:
            logger.warning("YouTube upload is disabled")
            return False

        logger.info(f"Uploading to YouTube: {title}")
        try:
            from app.youtube.publishing import PublishingQueue, DONE
            queue = PublishingQueue(self.settings)
            job_id = queue.add_manual(video_path, title=title, description=description, tags=tags)
            queue.publish(job_id=job_id)
            return any(row['job_id'] == job_id and row.get('publishing_verified_at') and row['youtube_status'] in DONE for row in queue.scan())
        except Exception as error:
            logger.error("YouTube upload failed: %s", error, exc_info=True)
            return False
