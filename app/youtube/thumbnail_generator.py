"""
Thumbnail Generator for Silent Dark Blues
Auto-creates branded thumbnails using background images with vibrant text overlay
"""
import random
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
import numpy as np
from app.config.logging_config import get_logger

logger = get_logger("youtube.thumbnail_generator")


class ThumbnailGenerator:
    """Generate YouTube thumbnails using background images with vibrant text overlay."""

    def __init__(self):
        self.logger = logger
        self.thumbnail_size = (1280, 720)  # YouTube standard thumbnail size
        self.bg_folder = Path("backgroundImages")
        self.text_color = (255, 255, 100)  # Vibrant yellow
        self.text_stroke = (220, 30, 40)   # Red stroke/accent

    def _get_background_images(self):
        """Get list of available background images."""
        if not self.bg_folder.exists():
            self.logger.warning(f"Background images folder not found: {self.bg_folder}")
            return []

        supported_ext = {'.jpg', '.jpeg', '.png', '.webp'}
        images = [f for f in self.bg_folder.iterdir()
                 if f.suffix.lower() in supported_ext]

        return images

    def generate_thumbnail(
        self,
        episode_number: int,
        duration_minutes: int,
        title_text: str = None,
        background_image: Path = None,
    ) -> Path:
        """Generate a thumbnail using background image with vibrant text overlay."""
        self.logger.info(f"Generating thumbnail for episode {episode_number}...")

        # Get background image
        if not background_image:
            available_images = self._get_background_images()
            if not available_images:
                self.logger.error("No background images available")
                raise FileNotFoundError("No background images found in backgroundImages folder")
            background_image = random.choice(available_images)
            self.logger.info(f"Selected background: {background_image.name}")

        # Load and process background image
        try:
            bg_img = Image.open(background_image).convert("RGB")
            bg_img = bg_img.resize(self.thumbnail_size, Image.Resampling.LANCZOS)

            # Darken the background slightly for text visibility
            overlay = Image.new("RGBA", self.thumbnail_size, (0, 0, 0, 80))
            bg_img = bg_img.convert("RGBA")
            bg_img = Image.alpha_composite(bg_img, overlay)
            img = bg_img.convert("RGB")

            self.logger.info(f"Background image processed: {self.thumbnail_size}")
        except Exception as e:
            self.logger.error(f"Failed to process background image: {e}")
            raise

        draw = ImageDraw.Draw(img)

        # Add main vibrant text overlay: "Improve Productivity - Music"
        self._add_main_text(draw)

        # Add episode number (smaller, top-right)
        self._add_episode_badge(draw, episode_number)

        # Add duration badge (bottom-right)
        self._add_duration_badge(draw, duration_minutes)

        # Save thumbnail
        output_path = self._get_output_path(episode_number)
        img.save(str(output_path), quality=95)

        self.logger.info(f"Thumbnail created: {output_path.name}")
        return output_path

    def _add_main_text(self, draw: ImageDraw.ImageDraw) -> None:
        """Add large vibrant main text: 'Improve Productivity - Music'."""
        try:
            font = self._get_font(size=90, bold=True)
        except:
            font = ImageFont.load_default()

        text = "Improve Productivity\n- Music"

        # Get text bounding box
        text_bbox = draw.multiline_textbbox((0, 0), text, font=font)
        text_width = text_bbox[2] - text_bbox[0]
        text_height = text_bbox[3] - text_bbox[1]

        # Center horizontally, position vertically (middle of image)
        x = (self.thumbnail_size[0] - text_width) // 2
        y = (self.thumbnail_size[1] - text_height) // 2

        # Draw text with stroke (outline) for visibility
        stroke_width = 3
        for adj_x in range(-stroke_width, stroke_width + 1):
            for adj_y in range(-stroke_width, stroke_width + 1):
                draw.multiline_text(
                    (x + adj_x, y + adj_y),
                    text,
                    fill=self.text_stroke,
                    font=font,
                    align="center"
                )

        # Draw main text on top
        draw.multiline_text(
            (x, y),
            text,
            fill=self.text_color,
            font=font,
            align="center"
        )

        self.logger.info("Main text overlay added")

    def _add_episode_badge(self, draw: ImageDraw.ImageDraw, episode_number: int) -> None:
        """Add episode number badge to top-right corner."""
        try:
            font = self._get_font(size=36, bold=True)
        except:
            font = ImageFont.load_default()

        episode_text = f"EP {episode_number:02d}"

        text_bbox = draw.textbbox((0, 0), episode_text, font=font)
        text_width = text_bbox[2] - text_bbox[0]
        text_height = text_bbox[3] - text_bbox[1]

        # Position at top-right with padding
        padding = 20
        x = self.thumbnail_size[0] - text_width - padding
        y = padding

        # Draw semi-transparent background box
        box_padding = 10
        draw.rectangle(
            [x - box_padding, y - box_padding, x + text_width + box_padding, y + text_height + box_padding],
            fill=(0, 0, 0, 180),
            outline=self.text_stroke,
            width=2
        )

        # Draw text
        draw.text((x, y), episode_text, fill=self.text_color, font=font)

    def _add_duration_badge(self, draw: ImageDraw.ImageDraw, duration_minutes: int) -> None:
        """Add duration badge to bottom-right corner."""
        try:
            font = self._get_font(size=32, bold=True)
        except:
            font = ImageFont.load_default()

        duration_text = f"{duration_minutes}:00"

        text_bbox = draw.textbbox((0, 0), duration_text, font=font)
        text_width = text_bbox[2] - text_bbox[0]
        text_height = text_bbox[3] - text_bbox[1]

        # Position at bottom-right with padding
        padding = 20
        x = self.thumbnail_size[0] - text_width - padding
        y = self.thumbnail_size[1] - text_height - padding

        # Draw semi-transparent background box
        box_padding = 10
        draw.rectangle(
            [x - box_padding, y - box_padding, x + text_width + box_padding, y + text_height + box_padding],
            fill=(0, 0, 0, 180),
            outline=self.text_stroke,
            width=2
        )

        # Draw text
        draw.text((x, y), duration_text, fill=self.text_color, font=font)

    def _get_font(self, size: int = 32, bold: bool = False) -> ImageFont.FreeTypeFont:
        """Get TrueType font if available, otherwise default."""
        try:
            font_name = "arialbd.ttf" if bold else "arial.ttf"
            font_paths = [
                Path("C:\\Windows\\Fonts") / font_name,
                Path("/usr/share/fonts/truetype/dejavu") / f"DejaVuSans{'-Bold' if bold else ''}.ttf",
            ]

            for font_path in font_paths:
                if font_path.exists():
                    return ImageFont.truetype(str(font_path), size)

            raise FileNotFoundError("No TrueType font found")
        except:
            self.logger.warning("Using default font")
            return ImageFont.load_default()

    def _get_output_path(self, episode_number: int) -> Path:
        """Get output path for thumbnail in EPISODES folder structure."""
        # Create episodes folder structure
        episodes_dir = Path("output") / "EPISODES"
        episode_dir = episodes_dir / f"episode_{episode_number:03d}"
        episode_dir.mkdir(parents=True, exist_ok=True)

        return episode_dir / f"thumbnail.jpg"

    def batch_generate_thumbnails(self, episode_count: int, titles: list[str] = None) -> list[Path]:
        """Generate thumbnails for multiple episodes."""
        self.logger.info(f"Batch generating {episode_count} thumbnails...")

        thumbnails = []
        for i in range(1, episode_count + 1):
            title = titles[i - 1] if titles and i <= len(titles) else None
            try:
                thumb = self.generate_thumbnail(
                    episode_number=i,
                    duration_minutes=20,
                    title_text=title,
                )
                thumbnails.append(thumb)
            except Exception as e:
                self.logger.error(f"Failed to generate thumbnail {i}: {e}")

        self.logger.info(f"Generated {len(thumbnails)}/{episode_count} thumbnails")
        return thumbnails

