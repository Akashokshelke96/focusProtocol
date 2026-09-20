"""
Local background image provider for long-form jazz videos.
Enhanced provider for selecting and preparing background images.
"""
from app.utils.ffmpeg import no_window_flags
import random
import subprocess
from pathlib import Path
from typing import Optional, List, Dict, Any
from app.config.logging_config import get_logger

logger = get_logger("providers.local_background")


class LocalBackgroundProvider:
    """Manages local background images for jazz video generation."""

    SUPPORTED_FORMATS = {".jpg", ".jpeg", ".png", ".webp"}

    def __init__(self, background_dir: Optional[Path] = None):
        """Initialize local background image provider.

        Args:
            background_dir: Directory containing background images.
                          Defaults to project root/backgroundImages
        """
        if background_dir is None:
            # Get absolute path to backgroundImages directory
            project_root = Path(__file__).parent.parent.parent
            background_dir = project_root / "backgroundImages"
        else:
            background_dir = Path(background_dir)

        self.background_dir = background_dir.absolute()
        self.background_dir.mkdir(parents=True, exist_ok=True)
        logger.info(f"Local background provider initialized: {self.background_dir}")

    def get_available_images(self) -> List[Dict[str, Any]]:
        """Scan background directory and return list of valid image files.

        Returns:
            List of dicts with image info: {path, filename, width, height}
        """
        images = []

        if not self.background_dir.exists():
            logger.warning(f"Background directory does not exist: {self.background_dir}")
            return images

        for file_path in self.background_dir.iterdir():
            if file_path.is_file() and file_path.suffix.lower() in self.SUPPORTED_FORMATS:
                try:
                    width, height = self._get_image_dimensions(file_path)
                    if width > 0 and height > 0:
                        images.append({
                            "path": str(file_path.absolute()),
                            "filename": file_path.name,
                            "width": width,
                            "height": height,
                        })
                        logger.debug(
                            f"Found image: {file_path.name} ({width}x{height})"
                        )
                except Exception as e:
                    logger.warning(f"Failed to inspect {file_path.name}: {e}")

        logger.info(f"Found {len(images)} valid background images in {self.background_dir}")
        return sorted(images, key=lambda x: x["filename"])

    def _get_image_dimensions(self, file_path: Path) -> tuple:
        """Get image dimensions using Python libraries.

        Args:
            file_path: Path to image file

        Returns:
            Tuple of (width, height)
        """
        try:
            # Try using PIL/Pillow
            try:
                from PIL import Image
                with Image.open(str(file_path)) as img:
                    img.load()
                    return img.width, img.height
            except ImportError:
                pass
            except Exception as e:
                logger.debug(f"PIL failed for {file_path.name}: {e}")

            # Fallback: use opencv
            try:
                import cv2
                img = cv2.imread(str(file_path))
                if img is not None:
                    height, width = img.shape[:2]
                    return width, height
            except ImportError:
                pass
            except Exception as e:
                logger.debug(f"OpenCV failed for {file_path.name}: {e}")

            # Fallback: assume 1920x1080 for valid image files
            logger.warning(f"Could not determine dimensions for {file_path.name}, assuming 1920x1080")
            return 0, 0

        except Exception as e:
            logger.error(f"Failed to get dimensions for {file_path.name}: {e}")
            return 0, 0

    def select_random_images(self, count: int = 3) -> List[Dict[str, Any]]:
        """Randomly select N background images.

        Args:
            count: Number of images to select (default 3)

        Returns:
            List of selected image dicts
        """
        available_images = self.get_available_images()

        if len(available_images) < count:
            logger.warning(
                f"Requested {count} images but only {len(available_images)} available. "
                f"Using all available images."
            )
            return available_images

        selected = random.sample(available_images, count)

        selected_names = [img["filename"] for img in selected]
        logger.info(f"Selected {count} random images: {selected_names}")

        return selected

    def prepare_image_for_video(
        self,
        image_path: Path,
        target_width: int = 1920,
        target_height: int = 1080,
        output_path: Optional[Path] = None,
    ) -> Optional[Path]:
        """Prepare image for video (scale/crop to 16:9 if needed).

        Args:
            image_path: Path to source image
            target_width: Target width (default 1920)
            target_height: Target height (default 1080)
            output_path: Path to save prepared image (default: image directory)

        Returns:
            Path to prepared image
        """
        try:
            if output_path is None:
                output_path = Path("media/images") / f"prepared_{Path(image_path).name}"

            output_path.parent.mkdir(parents=True, exist_ok=True)

            logger.info(f"Preparing image: {Path(image_path).name}")
            logger.info(f"  Target resolution: {target_width}x{target_height}")

            # Use FFmpeg to scale/crop image
            # Pad with black bars if needed to maintain aspect ratio
            cmd = [
                "ffmpeg",
                "-i", str(image_path),
                "-vf",
                (
                    f"scale={target_width}:{target_height}:force_original_aspect_ratio=decrease,"
                    f"pad={target_width}:{target_height}:(ow-iw)/2:(oh-ih)/2:color=black"
                ),
                "-y",
                str(output_path),
            ]

            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30, **no_window_flags())
            if result.returncode != 0:
                logger.error(f"FFmpeg image preparation failed: {result.stderr}")
                return None

            logger.info(f"Image prepared: {output_path}")
            return output_path

        except Exception as e:
            logger.error(f"Image preparation failed: {e}")
            return None

    def validate_image(self, image_path: Path) -> bool:
        """Validate that an image file is readable and has valid dimensions.

        Args:
            image_path: Path to image file

        Returns:
            True if image is valid
        """
        try:
            width, height = self._get_image_dimensions(image_path)
            if width > 0 and height > 0:
                logger.info(f"Image valid: {Path(image_path).name} ({width}x{height})")
                return True
            else:
                logger.warning(f"Image has invalid dimensions: {width}x{height}")
                return False

        except Exception as e:
            logger.error(f"Image validation failed: {e}")
            return False
