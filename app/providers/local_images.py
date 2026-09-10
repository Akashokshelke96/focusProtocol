from __future__ import annotations
"""
Local Background Image Provider
Reads from D:\Long Form Video Generator\backgroundImages
"""
import os
from pathlib import Path
from typing import Optional
from app.config.logging_config import get_logger

logger = get_logger("providers.local_images")

SUPPORTED_FORMATS = {".jpg", ".jpeg", ".png", ".webp"}


class LocalImageProvider:
    """Loads background images from local folder."""

    def __init__(self, background_folder: Optional[str] = None):
        if background_folder:
            self.background_folder = Path(background_folder)
        else:
            # Default to D:\Long Form Video Generator\backgroundImages
            self.background_folder = Path(__file__).parent.parent.parent / "backgroundImages"

        self.logger = logger

    def list_available_images(self) -> list[Path]:
        """List all valid background images."""
        if not self.background_folder.exists():
            self.logger.error(f"Background folder not found: {self.background_folder}")
            return []

        images = []
        for file in self.background_folder.iterdir():
            if file.suffix.lower() in SUPPORTED_FORMATS:
                images.append(file)

        self.logger.info(f"Found {len(images)} background image(s)")
        return sorted(images)

    def select_images(self, count: int = 2) -> list[Path]:
        """Select N images for the video."""
        available = self.list_available_images()

        if len(available) < count:
            self.logger.error(f"Need {count} images, but only {len(available)} available")
            return available

        selected = available[:count]
        self.logger.info(f"Selected {len(selected)} image(s) for video")
        for img in selected:
            self.logger.info(f"  - {img.name}")

        return selected

    def get_image_info(self, image_path: Path) -> dict:
        """Get image dimensions and metadata."""
        try:
            from PIL import Image

            img = Image.open(image_path)
            width, height = img.size
            aspect_ratio = width / height if height > 0 else 0

            return {
                "path": image_path,
                "name": image_path.name,
                "width": width,
                "height": height,
                "aspect_ratio": aspect_ratio,
                "format": img.format,
            }

        except Exception as e:
            self.logger.error(f"Failed to read image info: {e}")
            return {
                "path": image_path,
                "name": image_path.name,
                "width": 0,
                "height": 0,
                "aspect_ratio": 0,
            }

    def prepare_image(self, image_path: Path, target_width: int = 1920, target_height: int = 1080) -> Optional[Path]:
        """Prepare image for video (crop/scale to 16:9 if needed)."""
        try:
            from PIL import Image

            self.logger.info(f"Preparing image: {image_path.name}")

            img = Image.open(image_path)
            width, height = img.size
            target_ratio = target_width / target_height  # 16:9 = 1.777...

            self.logger.info(f"  Original: {width}x{height}")

            # Calculate crop dimensions to match 16:9
            current_ratio = width / height
            if current_ratio > target_ratio:
                # Too wide, crop sides
                new_width = int(height * target_ratio)
                left = (width - new_width) // 2
                img = img.crop((left, 0, left + new_width, height))
                self.logger.info(f"  Cropped width: {new_width}x{height}")
            elif current_ratio < target_ratio:
                # Too tall, crop top/bottom
                new_height = int(width / target_ratio)
                top = (height - new_height) // 2
                img = img.crop((0, top, width, top + new_height))
                self.logger.info(f"  Cropped height: {width}x{new_height}")

            # Scale to target resolution
            img = img.resize((target_width, target_height), Image.Resampling.LANCZOS)
            self.logger.info(f"  Scaled to: {target_width}x{target_height}")

            return img

        except Exception as e:
            self.logger.error(f"Image preparation failed: {e}")
            return None
