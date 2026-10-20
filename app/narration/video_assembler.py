"""FFmpeg assembly for the narrated pipeline.

Builds a silent visual track from the manifest's timed images (either a
single re-encoded concat pass or per-scene Ken Burns clips), muxes the
narration audio, renders a thumbnail, and exports the final deliverables.
Reuses the project's FFmpeg discovery utilities.
"""
from __future__ import annotations
import shutil
import subprocess
from pathlib import Path
from typing import Callable, Optional

from app.config.logging_config import get_logger
from app.config.settings import Settings
from app.narration.models import SceneManifest, Scene
from app.utils.ffmpeg import find_ffmpeg, no_window_flags

logger = get_logger("narration.assembler")


class AssemblyError(RuntimeError):
    """Raised when FFmpeg fails to produce the narrated video."""


class VideoAssembler:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.ffmpeg = find_ffmpeg()
        if not self.ffmpeg:
            raise AssemblyError("FFmpeg not found; install it or add it to PATH")

    # ---------------------------------------------------------------- public
    def assemble(self, manifest: SceneManifest, narration_audio: Path, output_path: Path,
                 work_dir: Path, on_progress: Optional[Callable[[int, int], None]] = None) -> Path:
        scenes = [scene for scene in manifest.scenes if scene.image_path and Path(scene.image_path).is_file()]
        if not scenes:
            raise AssemblyError("No generated scene images are available to assemble")
        work_dir = Path(work_dir)
        work_dir.mkdir(parents=True, exist_ok=True)
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        if self.settings.narration_motion == "kenburns":
            visual = self._render_kenburns(scenes, work_dir, on_progress)
        else:
            visual = self._render_concat(scenes, work_dir, on_progress)

        self._mux(str(visual), str(narration_audio), str(output_path))
        logger.info("Assembled narration video: %s", output_path)
        return output_path

    def make_thumbnail(self, image_path: Path, output_path: Path) -> Optional[Path]:
        image_path = Path(image_path)
        if not image_path.is_file():
            logger.warning("Thumbnail source missing: %s", image_path)
            return None
        width, height = 1280, 720
        filter_chain = (
            f"scale={width}:{height}:force_original_aspect_ratio=increase,"
            f"crop={width}:{height},format=rgb24"
        )
        cmd = [str(self.ffmpeg), "-y", "-i", str(image_path), "-vf", filter_chain,
               "-frames:v", "1", str(output_path)]
        self._run(cmd)
        return Path(output_path)

    def export(self, video_path: Path, thumbnail_path: Optional[Path], job_id: str) -> dict:
        """Copy deliverables into the configured export directory."""
        if not self.settings.narration_export_enabled or not self.settings.narration_export_dir:
            return {}
        destination = Path(self.settings.narration_export_dir) / job_id
        destination.mkdir(parents=True, exist_ok=True)
        exported: dict[str, str] = {}
        final_video = destination / "final_video_1080p.mp4"
        shutil.copy2(video_path, final_video)
        exported["video"] = str(final_video)
        if thumbnail_path and Path(thumbnail_path).is_file():
            final_thumb = destination / "thumbnail.png"
            shutil.copy2(thumbnail_path, final_thumb)
            exported["thumbnail"] = str(final_thumb)
        logger.info("Exported deliverables to %s", destination)
        return exported

    # --------------------------------------------------------------- render
    def _render_concat(self, scenes: list[Scene], work_dir: Path,
                       on_progress: Optional[Callable[[int, int], None]]) -> Path:
        """Single re-encode pass using the concat demuxer with per-image durations."""
        if on_progress:
            on_progress(0, len(scenes))
        list_path = work_dir / "concat.txt"
        lines = []
        for scene in scenes:
            lines.append(f"file '{Path(scene.image_path).resolve().as_posix()}'")
            lines.append(f"duration {max(0.04, scene.duration):.3f}")
        # Repeat the final image so the concat demuxer honors its duration.
        lines.append(f"file '{Path(scenes[-1].image_path).resolve().as_posix()}'")
        list_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

        visual = work_dir / "visual.mp4"
        width, height, fps = self.settings.video_width, self.settings.video_height, self.settings.video_fps
        filter_chain = (
            f"fps={fps},scale={width}:{height}:force_original_aspect_ratio=decrease,"
            f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=black,setsar=1,format=yuv420p"
        )
        cmd = [str(self.ffmpeg), "-y", "-f", "concat", "-safe", "0", "-i", str(list_path),
               "-vf", filter_chain, *self._codec_args(), "-an", str(visual)]
        self._run(cmd)
        if on_progress:
            on_progress(len(scenes), len(scenes))
        return visual

    def _render_kenburns(self, scenes: list[Scene], work_dir: Path,
                         on_progress: Optional[Callable[[int, int], None]]) -> Path:
        """Render one subtle Ken Burns clip per scene, then concat (stream copy)."""
        clips_dir = work_dir / "clips"
        clips_dir.mkdir(parents=True, exist_ok=True)
        width, height, fps = self.settings.video_width, self.settings.video_height, self.settings.video_fps
        strength = max(0.0, self.settings.narration_motion_strength)
        max_zoom = 1.0 + min(0.25, strength)
        clip_paths: list[Path] = []

        for position, scene in enumerate(scenes):
            duration = max(0.4, scene.duration)
            frames = max(1, int(round(duration * fps)))
            rate = (max_zoom - 1.0) / frames if frames else 0.0
            zoom = f"min(zoom+{rate:.6f},{max_zoom:.4f})"
            pan = position % 4
            if pan == 0:
                x, y = "(iw-iw/zoom)/2", "(ih-ih/zoom)/2"
            elif pan == 1:
                x, y = f"(iw-iw/zoom)*(on/{frames})", "(ih-ih/zoom)/2"
            elif pan == 2:
                x, y = "(iw-iw/zoom)/2", f"(ih-ih/zoom)*(on/{frames})"
            else:
                x, y = f"(iw-iw/zoom)*(1-on/{frames})", "(ih-ih/zoom)/2"

            zoompan = (
                f"scale={width * 2}:{height * 2}:force_original_aspect_ratio=increase,"
                f"crop={width * 2}:{height * 2},"
                f"zoompan=z='{zoom}':x='{x}':y='{y}':d={frames}:s={width}x{height}:fps={fps},"
                f"format=yuv420p,setsar=1"
            )
            clip = clips_dir / f"scene_{scene.index:04d}.mp4"
            cmd = [str(self.ffmpeg), "-y", "-loop", "1", "-i", str(scene.image_path),
                   "-vf", zoompan, "-t", f"{duration:.3f}", "-r", str(fps),
                   *self._codec_args(), "-an", str(clip)]
            self._run(cmd)
            clip_paths.append(clip)
            if on_progress:
                on_progress(position + 1, len(scenes))

        list_path = work_dir / "clips.txt"
        list_path.write_text(
            "\n".join(f"file '{p.resolve().as_posix()}'" for p in clip_paths) + "\n", encoding="utf-8")
        visual = work_dir / "visual.mp4"
        self._run([str(self.ffmpeg), "-y", "-f", "concat", "-safe", "0", "-i", str(list_path),
                   "-c", "copy", str(visual)])
        return visual

    def _mux(self, visual: str, narration_audio: str, output_path: str) -> None:
        cmd = [str(self.ffmpeg), "-y", "-i", visual, "-i", narration_audio,
               "-map", "0:v:0", "-map", "1:a:0",
               "-c:v", "copy", "-c:a", "aac", "-b:a", self.settings.ffmpeg_audio_bitrate,
               "-shortest", "-movflags", "+faststart", output_path]
        self._run(cmd)

    def _codec_args(self) -> list[str]:
        encoder = (self.settings.narration_video_encoder or self.settings.video_encoder or "libx264").lower()
        preset = self.settings.ffmpeg_preset
        crf = str(self.settings.ffmpeg_crf)
        quality = str(self.settings.video_encoder_quality)
        if encoder in ("auto", "libx264", ""):
            return ["-c:v", "libx264", "-preset", preset, "-crf", crf, "-pix_fmt", "yuv420p"]
        if encoder == "h264_nvenc":
            return ["-c:v", "h264_nvenc", "-preset", "p4", "-tune", "hq", "-rc", "vbr",
                    "-cq", quality, "-pix_fmt", "yuv420p"]
        if encoder == "h264_qsv":
            return ["-c:v", "h264_qsv", "-global_quality", quality, "-pix_fmt", "nv12"]
        if encoder == "h264_amf":
            return ["-c:v", "h264_amf", "-quality", "balanced", "-rc", "cqp",
                    "-qp_i", quality, "-qp_p", quality, "-pix_fmt", "yuv420p"]
        return ["-c:v", "libx264", "-preset", preset, "-crf", crf, "-pix_fmt", "yuv420p"]

    def _run(self, cmd: list[str]) -> None:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=7200, **no_window_flags())
        if result.returncode != 0:
            raise AssemblyError(f"FFmpeg failed: {result.stderr[-1500:]}")
