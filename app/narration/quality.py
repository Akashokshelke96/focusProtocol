"""Deterministic image-quality checks for generated scenes and references.

These checks are deliberately conservative. They catch undecodable files,
blank frames, and accidental duplicates without pretending to be a full
aesthetic reviewer. Identity similarity is advisory and only runs when the
image backend exposes a CLIP image encoder.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional, Sequence

from PIL import Image, ImageStat

from app.config.settings import Settings

IdentityScorer = Callable[[Path, Sequence[str]], Optional[float]]


def dhash(image: Image.Image, size: int = 8) -> int:
    """64-bit difference hash; robust to resizing and mild compression."""
    grey = image.convert("L").resize((size + 1, size), Image.Resampling.LANCZOS)
    pixels = list(grey.getdata())
    value = 0
    for row in range(size):
        offset = row * (size + 1)
        for column in range(size):
            value = (value << 1) | (1 if pixels[offset + column] > pixels[offset + column + 1] else 0)
    return value


def hamming(left: int, right: int) -> int:
    return int(left ^ right).bit_count()


def _entropy(image: Image.Image) -> float:
    histogram = image.convert("L").resize((256, 256), Image.Resampling.BILINEAR).histogram()
    total = sum(histogram) or 1
    entropy = 0.0
    for count in histogram:
        if count:
            probability = count / total
            entropy -= probability * math.log2(probability)
    return entropy


def _stddev(image: Image.Image) -> float:
    stats = ImageStat.Stat(image.convert("RGB").resize((256, 256), Image.Resampling.BILINEAR))
    return sum(stats.stddev) / max(1, len(stats.stddev))


@dataclass
class ImageQuality:
    path: Path
    width: int = 0
    height: int = 0
    fmt: str = ""
    stddev: float = 0.0
    entropy: float = 0.0
    dhash: int = 0
    identity_similarity: Optional[float] = None
    hard_failures: list[str] = field(default_factory=list)
    soft_flags: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.hard_failures

    @property
    def flags(self) -> list[str]:
        return list(self.hard_failures) + list(self.soft_flags)


class QualityChecker:
    """Validates decoded pixels, not just file existence."""

    def __init__(self, settings: Settings):
        self.settings = settings

    def inspect(self, path: Path, min_width: int = 512, min_height: int = 320) -> ImageQuality:
        path = Path(path)
        quality = ImageQuality(path=path)
        if not path.is_file() or path.stat().st_size < 1024:
            quality.hard_failures.append("missing_or_empty")
            return quality
        try:
            with Image.open(path) as image:
                image.load()
                quality.width, quality.height = image.size
                quality.fmt = image.format or ""
                quality.stddev = round(_stddev(image), 3)
                quality.entropy = round(_entropy(image), 3)
                quality.dhash = dhash(image)
        except Exception:  # noqa: BLE001 - PIL raises several decode errors
            quality.hard_failures.append("undecodable")
            return quality
        if quality.width < min_width or quality.height < min_height:
            quality.hard_failures.append(f"too_small:{quality.width}x{quality.height}")
        if not self.settings.narration_quality_enabled:
            return quality
        if quality.stddev < self.settings.narration_quality_min_stddev:
            quality.hard_failures.append(f"flat_image:stddev={quality.stddev:.1f}")
        if quality.entropy < self.settings.narration_quality_min_entropy:
            quality.hard_failures.append(f"low_detail:entropy={quality.entropy:.2f}")
        return quality

    def check_scene(
        self,
        path: Path,
        character_ids: Sequence[str],
        reference_paths: Sequence[str],
        identity_scorer: Optional[IdentityScorer] = None,
        previous_hashes: Optional[Sequence[tuple[int, int]]] = None,
        min_width: int = 512,
        min_height: int = 320,
    ) -> ImageQuality:
        quality = self.inspect(path, min_width=min_width, min_height=min_height)
        if not quality.ok:
            return quality

        if previous_hashes and self.settings.narration_quality_enabled:
            for other_index, other_hash in previous_hashes:
                distance = hamming(quality.dhash, other_hash)
                if distance <= self.settings.narration_duplicate_hamming_threshold:
                    quality.soft_flags.append(f"duplicate_of_scene_{other_index}:distance={distance}")
                    break

        if (character_ids and reference_paths and identity_scorer
                and self.settings.narration_identity_check_enabled):
            try:
                similarity = identity_scorer(Path(path), reference_paths)
            except Exception:  # noqa: BLE001 - identity is advisory only
                similarity = None
            if similarity is not None:
                quality.identity_similarity = round(float(similarity), 4)
                if quality.identity_similarity < self.settings.narration_identity_min_similarity:
                    quality.soft_flags.append(
                        f"identity_low:{quality.identity_similarity:.3f}"
                        f"<{self.settings.narration_identity_min_similarity:.2f}")
        return quality


def validate_image_file(path: Path, settings: Settings,
                        min_width: int = 512, min_height: int = 320) -> ImageQuality:
    return QualityChecker(settings).inspect(path, min_width=min_width, min_height=min_height)
