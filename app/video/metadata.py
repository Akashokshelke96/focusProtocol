from __future__ import annotations
"""
Thumbnail and metadata generation
"""
import json
from pathlib import Path
from typing import Any, Optional
from PIL import Image, ImageDraw, ImageFont
from app.config.logging_config import get_logger

logger = get_logger("video.metadata")


class ThumbnailGenerator:
    """Generates YouTube thumbnails."""

    THUMBNAIL_WIDTH = 1280
    THUMBNAIL_HEIGHT = 720

    def __init__(self):
        """Initialize thumbnail generator."""
        logger.info("Thumbnail generator initialized")

    def create_thumbnail(
        self,
        background_image: Path,
        title_text: str,
        output_path: Path,
    ) -> bool:
        """Create a thumbnail with text overlay."""
        logger.info(f"Creating thumbnail: {title_text}")

        try:
            # Open background image
            img = Image.open(background_image)
            img = img.resize((self.THUMBNAIL_WIDTH, self.THUMBNAIL_HEIGHT), Image.Resampling.LANCZOS)

            draw = ImageDraw.Draw(img)

            # Try to use a nice font, fall back to default
            try:
                font = ImageFont.truetype("arial.ttf", 60)
            except:
                font = ImageFont.load_default()

            # Add semi-transparent background for text
            margin = 20
            text_height = 80
            draw.rectangle(
                [margin, self.THUMBNAIL_HEIGHT - text_height - margin,
                 self.THUMBNAIL_WIDTH - margin, self.THUMBNAIL_HEIGHT - margin],
                fill=(0, 0, 0, 180),
            )

            # Draw text
            text_x = margin + 10
            text_y = self.THUMBNAIL_HEIGHT - text_height

            draw.text(
                (text_x, text_y),
                title_text,
                fill=(255, 255, 255),
                font=font,
            )

            # Save
            output_path.parent.mkdir(parents=True, exist_ok=True)
            img.save(output_path, "JPEG", quality=95)

            logger.info(f"Thumbnail saved: {output_path}")
            return True

        except Exception as e:
            logger.error(f"Thumbnail creation failed: {e}")
            return False


class MetadataGenerator:
    """Generates YouTube metadata files."""

    def __init__(self):
        """Initialize metadata generator."""
        logger.info("Metadata generator initialized")

    def create_sources_file(
        self,
        assets: list[dict[str, Any]],
        output_path: Path,
    ) -> bool:
        """Create sources.json file."""
        logger.info("Creating sources file")

        try:
            sources = {
                "assets": assets,
                "total_count": len(assets),
            }

            output_path.parent.mkdir(parents=True, exist_ok=True)
            with open(output_path, "w") as f:
                json.dump(sources, f, indent=2)

            logger.info(f"Sources file created: {output_path}")
            return True

        except Exception as e:
            logger.error(f"Failed to create sources file: {e}")
            return False

    def create_metadata_file(
        self,
        title: str,
        description: str,
        tags: list[str],
        keywords: list[str],
        output_path: Path,
    ) -> bool:
        """Create metadata.json file."""
        logger.info("Creating metadata file")

        try:
            metadata = {
                "title": title,
                "description": description,
                "tags": tags,
                "keywords": keywords,
            }

            output_path.parent.mkdir(parents=True, exist_ok=True)
            with open(output_path, "w") as f:
                json.dump(metadata, f, indent=2)

            logger.info(f"Metadata file created: {output_path}")
            return True

        except Exception as e:
            logger.error(f"Failed to create metadata file: {e}")
            return False
