from __future__ import annotations
"""
Media Provider Abstraction
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Any


@dataclass
class MediaAsset:
    """Represents a downloaded media asset."""
    id: str
    provider: str
    query: str
    file_path: Path
    url: str
    duration_seconds: Optional[float] = None
    width: Optional[int] = None
    height: Optional[int] = None
    sha256: Optional[str] = None
    perceptual_hash: Optional[str] = None
    metadata: dict[str, Any] = None

    def __post_init__(self):
        if self.metadata is None:
            self.metadata = {}


class VideoProvider(ABC):
    """Abstract base for video providers."""

    @abstractmethod
    def search(self, query: str, orientation: str = "landscape") -> list[dict[str, Any]]:
        """Search for videos matching query."""
        pass

    @abstractmethod
    def download(self, video_id: str, output_path: Path) -> MediaAsset:
        """Download a video."""
        pass


class ImageProvider(ABC):
    """Abstract base for image providers."""

    @abstractmethod
    def search(self, query: str) -> list[dict[str, Any]]:
        """Search for images matching query."""
        pass

    @abstractmethod
    def download(self, image_id: str, output_path: Path) -> MediaAsset:
        """Download an image."""
        pass


class MusicProvider(ABC):
    """Abstract base for music providers."""

    @abstractmethod
    def generate(self, prompt: str) -> dict[str, Any]:
        """Generate music based on prompt."""
        pass

    @abstractmethod
    def download(self, track_id: str, output_path: Path) -> MediaAsset:
        """Download a music track."""
        pass
