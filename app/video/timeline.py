from __future__ import annotations
"""
Timeline and motion engine
"""
from dataclasses import dataclass
from typing import Optional
from app.config.logging_config import get_logger

logger = get_logger("video.timeline")


@dataclass
class TimelineClip:
    """Represents a clip in the timeline."""
    start_seconds: float
    end_seconds: float
    asset_path: str
    asset_type: str  # video, image
    duration_seconds: float
    transition_type: str = "crossfade"
    transition_duration: float = 1.5


class TimelineBuilder:
    """Builds video timeline from assets."""

    def __init__(self, fps: int = 30, transition_seconds: float = 1.5):
        """Initialize timeline builder."""
        self.fps = fps
        self.transition_seconds = transition_seconds
        self.clips = []
        logger.info(f"Timeline builder initialized: {fps}fps")

    def add_clip(
        self,
        asset_path: str,
        asset_type: str,
        duration_seconds: float,
    ) -> TimelineClip:
        """Add a clip to the timeline."""
        if self.clips:
            start = self.clips[-1].end_seconds
        else:
            start = 0.0

        end = start + duration_seconds

        clip = TimelineClip(
            start_seconds=start,
            end_seconds=end,
            asset_path=asset_path,
            asset_type=asset_type,
            duration_seconds=duration_seconds,
            transition_duration=self.transition_seconds,
        )

        self.clips.append(clip)
        logger.debug(f"Added clip: {asset_path} [{start:.1f}s - {end:.1f}s]")
        return clip

    def get_total_duration(self) -> float:
        """Get total timeline duration."""
        if not self.clips:
            return 0.0
        return self.clips[-1].end_seconds

    def to_list(self) -> list[dict]:
        """Convert to list representation."""
        return [
            {
                "start": clip.start_seconds,
                "end": clip.end_seconds,
                "duration": clip.duration_seconds,
                "asset": clip.asset_path,
                "type": clip.asset_type,
                "transition": clip.transition_type,
            }
            for clip in self.clips
        ]


class MotionEngine:
    """Handles Ken Burns-style motion for still images."""

    MOTIONS = {
        "zoom_in": {"scale": [1.0, 1.3], "pan": "center"},
        "zoom_out": {"scale": [1.3, 1.0], "pan": "center"},
        "left_to_right": {"scale": [1.0, 1.0], "pan": "left_to_right"},
        "right_to_left": {"scale": [1.0, 1.0], "pan": "right_to_left"},
        "top_to_bottom": {"scale": [1.0, 1.0], "pan": "top_to_bottom"},
        "bottom_to_top": {"scale": [1.0, 1.0], "pan": "bottom_to_top"},
    }

    @staticmethod
    def get_motion_filter(
        motion_type: str,
        duration_seconds: float,
        width: int = 1920,
        height: int = 1080,
    ) -> str:
        """Generate FFmpeg filter for motion."""
        logger.info(f"Generating motion: {motion_type}")

        if motion_type not in MotionEngine.MOTIONS:
            logger.warning(f"Unknown motion type: {motion_type}, using default")
            motion_type = "zoom_in"

        motion = MotionEngine.MOTIONS[motion_type]

        # Generate Ken Burns effect (zoom + pan)
        scale_start, scale_end = motion["scale"]
        fps = 30
        num_frames = int(duration_seconds * fps)

        # Simple zoom interpolation
        zoom_expr = f"min({scale_end}, {scale_start} + ({scale_end} - {scale_start}) * n / {num_frames})"

        # Pan effect
        pan_mapping = {
            "center": f"(w - iw * {zoom_expr}) / 2 : (h - ih * {zoom_expr}) / 2",
            "left_to_right": f"(n / {num_frames}) * (w - iw * {zoom_expr}) : (h - ih * {zoom_expr}) / 2",
            "right_to_left": f"((1 - n / {num_frames}) * (w - iw * {zoom_expr})) : (h - ih * {zoom_expr}) / 2",
            "top_to_bottom": f"(w - iw * {zoom_expr}) / 2 : (n / {num_frames}) * (h - ih * {zoom_expr})",
            "bottom_to_top": f"(w - iw * {zoom_expr}) / 2 : ((1 - n / {num_frames}) * (h - ih * {zoom_expr}))",
        }

        pan = pan_mapping.get(motion["pan"], pan_mapping["center"])

        # Generate filter: scale -> crop -> pad
        filter_str = (
            f"scale=iw*{zoom_expr}:ih*{zoom_expr},"
            f"crop={width}:{height}:{pan}"
        )

        return filter_str
