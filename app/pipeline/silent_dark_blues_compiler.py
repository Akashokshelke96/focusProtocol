"""
Silent Dark Blues - 20-Minute Compilation Pipeline
Gemini → Song Prompts → Suno Generation → Song Storage → Compilation → Visualizer
"""
import json
import os
from pathlib import Path
from datetime import datetime
from typing import Optional
import librosa
import soundfile as sf
from PIL import Image
import numpy as np

from app.config.logging_config import get_logger
from app.llm.gemini import GeminiProvider
from app.config.settings import Settings
from app.providers.suno import SunoProvider
from app.providers.local_images import LocalImageProvider

logger = get_logger("pipeline.silent_dark_blues")


class SilentDarkBluesCompiler:
    """End-to-end compilation pipeline for Silent Dark Blues."""

    def __init__(self):
        self.settings = Settings()
        self.gemini = GeminiProvider(self.settings)
        self.suno = SunoProvider()
        self.images = LocalImageProvider()

        # Paths
        self.root_dir = Path(__file__).parent.parent.parent
        self.mega_library_dir = self.root_dir / "mega_compilation_library"
        self.output_dir = self.root_dir / "output"
        self.run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.run_dir = self.output_dir / f"compilation_{self.run_id}"

        # Create directories
        self.mega_library_dir.mkdir(parents=True, exist_ok=True)
        self.run_dir.mkdir(parents=True, exist_ok=True)

        self.manifest = {
            "run_id": self.run_id,
            "created_at": datetime.utcnow().isoformat(),
            "target_duration_minutes": 20,
            "songs": [],
            "images_used": [],
            "total_duration_seconds": 0,
        }

    def generate_song_prompts(self, num_songs: int = 4) -> list[str]:
        """Generate vocal song prompts inspired by Silent Dark Blues."""
        logger.info(f"Generating {num_songs} song prompts using Gemini...")

        prompt = f"""
You are a music producer for "Silent Dark Blues" - a YouTube channel featuring dark, sophisticated blues music with vocal performances.

The channel features:
- Slow, introspective vocal performances (5-6 minutes each)
- Masculine, mature vocal character
- Themes: silence, dignity, loss, strength, self-reliance, the quiet man
- Emotional tone: melancholic, contemplative, noir atmosphere
- Musical style: dark blues/jazz, late-night sophisticated, gentleman's club vibes
- No upbeat, EDM, or contemporary pop

Generate {num_songs} ORIGINAL unique vocal song generation prompts for Suno AI.
Each prompt should:
1. Be completely original (not copy existing songs)
2. Inspire a 5-6 minute vocal blues song
3. Capture the Silent Dark Blues aesthetic
4. Include specific instrumental suggestions (e.g., smooth jazz guitar, subtle strings, smoky horns)
5. Describe the vocal performance style and emotional arc
6. Suggest thematic content around masculine introspection, dignity, or quiet strength

Format as JSON:
{{
  "songs": [
    {{
      "number": 1,
      "title": "Song title concept",
      "prompt": "Detailed music generation prompt for Suno..."
    }},
    ...
  ]
}}

IMPORTANT: Generate completely original concepts. Do NOT reference or copy existing songs.
"""

        response = self.gemini._generate_with_retry(prompt)
        try:
            data = self.gemini._extract_json(response)
            songs = data.get("songs", [])
            prompts = [song["prompt"] for song in songs]
            logger.info(f"Generated {len(prompts)} prompts")

            # Store prompts in manifest
            for song in songs:
                self.manifest["songs"].append({
                    "number": song["number"],
                    "title": song["title"],
                    "prompt": song["prompt"],
                    "suno_id": None,
                    "duration_seconds": 0,
                    "file_path": None,
                    "status": "pending",
                })

            return prompts
        except Exception as e:
            logger.error(f"Failed to parse prompts: {e}")
            return []

    def generate_songs(self, prompts: list[str]) -> list[dict]:
        """Generate songs from prompts using Suno API."""
        logger.info(f"Generating {len(prompts)} songs from Suno...")
        generated_songs = []

        for i, prompt in enumerate(prompts, 1):
            logger.info(f"[{i}/{len(prompts)}] Generating song...")

            try:
                results = self.suno.generate_music(prompt, duration_seconds=330)

                if results:
                    for result in results:
                        logger.info(f"Got song: {result.get('title', 'Untitled')}")
                        generated_songs.append(result)
                else:
                    logger.warning(f"No results for prompt {i}")

            except Exception as e:
                logger.error(f"Failed to generate song {i}: {e}")
                continue

        logger.info(f"Total songs generated: {len(generated_songs)}")
        return generated_songs

    def validate_and_download_songs(self, songs: list[dict]) -> list[dict]:
        """Validate songs and download audio files."""
        logger.info(f"Validating {len(songs)} songs...")
        valid_songs = []

        for i, song in enumerate(songs, 1):
            try:
                url = song.get("url")
                title = song.get("title", f"song_{i}")
                task_id = song.get("task_id", f"unknown_{i}")

                if not url:
                    logger.warning(f"Song {i} has no URL, skipping")
                    continue

                # Download audio
                filename = f"song_{i:02d}_{task_id[:8]}.mp3"
                filepath = self.run_dir / filename

                if self.suno.download_audio(url, filepath):
                    # Get actual duration
                    duration = self._get_audio_duration(filepath)

                    song_data = {
                        "number": i,
                        "title": title,
                        "task_id": task_id,
                        "url": url,
                        "file_path": str(filepath),
                        "duration_seconds": duration,
                        "status": "downloaded",
                    }
                    valid_songs.append(song_data)
                    logger.info(f"Song {i}: {duration:.1f}s")
                else:
                    logger.error(f"Failed to download song {i}")

            except Exception as e:
                logger.error(f"Validation error for song {i}: {e}")
                continue

        logger.info(f"Valid songs: {len(valid_songs)}")
        return valid_songs

    def _get_audio_duration(self, filepath: Path) -> float:
        """Get actual audio duration in seconds."""
        try:
            y, sr = librosa.load(str(filepath), sr=None)
            duration = librosa.get_duration(y=y, sr=sr)
            return duration
        except Exception as e:
            logger.error(f"Failed to get duration: {e}")
            return 0.0

    def store_in_mega_library(self, songs: list[dict]) -> None:
        """Store songs in mega compilation library."""
        logger.info(f"Storing {len(songs)} songs in mega library...")

        episode_dir = self.mega_library_dir / f"episode_{self.run_id}"
        episode_dir.mkdir(parents=True, exist_ok=True)

        for song in songs:
            try:
                src_path = Path(song["file_path"])
                dst_path = episode_dir / src_path.name

                import shutil
                shutil.copy2(src_path, dst_path)
                logger.info(f"Stored: {dst_path.name}")

            except Exception as e:
                logger.error(f"Failed to store song: {e}")

    def select_images_for_songs(self, num_songs: int) -> list[Path]:
        """Select images from local folder (one per song)."""
        logger.info(f"Selecting {num_songs} images...")
        available_images = self.images.list_available_images()

        if len(available_images) < num_songs:
            logger.warning(f"Only {len(available_images)} images available, need {num_songs}")
            # Cycle through available images if not enough
            selected = []
            for i in range(num_songs):
                selected.append(available_images[i % len(available_images)])
            return selected

        selected = available_images[:num_songs]

        for i, img_path in enumerate(selected, 1):
            logger.info(f"Image {i}: {img_path.name}")
            self.manifest["images_used"].append(img_path.name)

        return selected

    def compile_songs_into_video(self, songs: list[dict], images: list[Path]) -> Path:
        """Compile songs and images into a video."""
        logger.info("Compiling songs and images into video...")

        try:
            from moviepy.editor import (
                AudioFileClip,
                ImageClip,
                concatenate_videoclips,
                CompositeAudioClip,
            )

            # Load audio clips
            audio_clips = []
            for song in songs:
                audio = AudioFileClip(song["file_path"])
                audio_clips.append(audio)

            # Concatenate audio
            final_audio = concatenate_videoclips(audio_clips, method="chain")
            total_duration = final_audio.duration
            logger.info(f"Total audio duration: {total_duration:.1f}s")

            self.manifest["total_duration_seconds"] = total_duration

            # Create video with images and audio
            video_clips = []
            current_time = 0

            for i, (song, image_path) in enumerate(zip(songs, images)):
                song_duration = song["duration_seconds"]

                # Prepare image
                prepared_img = self.images.prepare_image(image_path, 1920, 1080)
                if prepared_img is None:
                    logger.error(f"Failed to prepare image {i}")
                    continue

                # Create image clip
                img_array = np.array(prepared_img)
                clip = ImageClip(img_array).set_duration(song_duration)
                video_clips.append(clip)

                logger.info(f"Image {i} → Song {i} ({song_duration:.1f}s)")

                current_time += song_duration

            # Concatenate video
            if not video_clips:
                logger.error("No video clips to concatenate")
                return None

            video = concatenate_videoclips(video_clips)
            video = video.set_audio(final_audio)

            # Export
            output_path = self.run_dir / "compilation_raw.mp4"
            logger.info(f"Exporting video to {output_path}...")

            video.write_videofile(
                str(output_path),
                fps=30,
                codec="libx264",
                audio_codec="aac",
                verbose=False,
                logger=None,
            )

            logger.info(f"Video created: {output_path}")
            return output_path

        except Exception as e:
            logger.error(f"Compilation failed: {e}")
            import traceback
            traceback.print_exc()
            return None

    def add_visualizer(self, video_path: Path) -> Path:
        """Add audio-reactive visualizer to video."""
        logger.info("Adding audio visualizer...")

        try:
            from moviepy.editor import VideoFileClip, VideoClip
            from PIL import ImageDraw

            video = VideoFileClip(str(video_path))
            fps = video.fps
            duration = video.duration

            # Extract audio features
            audio_path = video_path.parent / "temp_audio.wav"
            video.audio.write_audiofile(str(audio_path), verbose=False, logger=None)

            features, sr = self._extract_audio_features(audio_path, fps=int(fps))
            frame_idx = [0]

            def make_frame_with_visualizer(t):
                """Generate frame with visualizer overlay."""
                frame_num = int(t * fps)
                if frame_num >= len(features):
                    frame_num = len(features) - 1

                original_frame = video.get_frame(t)
                amplitudes = features[frame_num]

                # Create visualizer frame
                viz_frame = self._create_soundbar_frame(amplitudes, video.w, video.h)

                # Composite
                orig_img = Image.fromarray((original_frame * 255).astype(np.uint8))
                viz_img = Image.fromarray(viz_frame, 'RGBA')
                orig_img.paste(viz_img, (0, 0), viz_img)

                frame_idx[0] += 1
                if frame_idx[0] % int(fps * 10) == 0:
                    logger.info(f"Processing frame {frame_idx[0]}/{int(duration * fps)}")

                return np.array(orig_img).astype(np.uint8)

            final_video = VideoClip(make_frame_with_visualizer, duration=duration)
            final_video = final_video.set_fps(fps)
            final_video = final_video.set_audio(video.audio)

            output_path = self.run_dir / "compilation_with_visualizer.mp4"
            logger.info(f"Rendering video with visualizer...")

            final_video.write_videofile(
                str(output_path),
                fps=fps,
                codec="libx264",
                audio_codec="aac",
                verbose=False,
                logger=None,
            )

            logger.info(f"Final video created: {output_path}")
            return output_path

        except Exception as e:
            logger.error(f"Visualizer failed: {e}")
            import traceback
            traceback.print_exc()
            return None

    def _extract_audio_features(self, audio_path: str, fps: int = 30) -> tuple:
        """Extract audio features for visualizer."""
        logger.info("Extracting audio features...")

        y, sr = librosa.load(audio_path, sr=None)
        duration = librosa.get_duration(y=y, sr=sr)

        D = librosa.stft(y)
        S = np.abs(D) ** 2
        mel_S = librosa.feature.melspectrogram(S=S, sr=sr, n_mels=7)
        mel_S_db = librosa.power_to_db(mel_S, ref=np.max)
        mel_S_normalized = (mel_S_db - mel_S_db.min()) / (mel_S_db.max() - mel_S_db.min() + 1e-6)

        num_frames = int(duration * fps)
        time_frames = np.linspace(0, mel_S_normalized.shape[1] - 1, num_frames)

        features = np.zeros((num_frames, 7))
        for i in range(7):
            features[:, i] = np.interp(time_frames, np.arange(mel_S_normalized.shape[1]), mel_S_normalized[i])

        logger.info(f"Extracted {num_frames} frames with 7 frequency bands")
        return features, sr

    def _create_soundbar_frame(self, amplitudes: np.ndarray, frame_width: int = 1920, frame_height: int = 1080) -> np.ndarray:
        """Create soundbar visualizer frame."""
        img = Image.new('RGBA', (frame_width, frame_height), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)

        num_bars = 7
        bar_width = 40
        max_bar_height = 200
        gap = 20

        total_width = num_bars * bar_width + (num_bars - 1) * gap
        start_x = (frame_width - total_width) // 2
        bar_bottom_y = int(frame_height * 0.7)

        for i, amplitude in enumerate(amplitudes):
            x = start_x + i * (bar_width + gap)
            bar_height = int(amplitude * max_bar_height)
            y_top = bar_bottom_y - bar_height
            y_bottom = bar_bottom_y

            r = int(0 + amplitude * 100)
            g = int(200 + amplitude * 55)
            b = int(255)

            draw.rectangle(
                [x, y_top, x + bar_width, y_bottom],
                fill=(r, g, b, 200),
                outline=(255, 255, 255, 150),
                width=2
            )

        return np.array(img)

    def create_excel_manifest(self) -> Path:
        """Create Excel production manifest."""
        logger.info("Creating Excel production manifest...")

        try:
            import openpyxl
            from openpyxl.styles import Font, PatternFill, Alignment

            wb = openpyxl.Workbook()
            ws = wb.active
            ws.title = "Production Manifest"

            # Header
            headers = [
                "Run ID",
                "Song #",
                "Title",
                "Prompt (First 100 chars)",
                "Suno Task ID",
                "Duration (sec)",
                "File Path",
                "Status",
                "Included in Compilation",
            ]

            for col, header in enumerate(headers, 1):
                cell = ws.cell(row=1, column=col)
                cell.value = header
                cell.font = Font(bold=True, color="FFFFFF")
                cell.fill = PatternFill(start_color="000000", end_color="000000", fill_type="solid")
                cell.alignment = Alignment(horizontal="center")

            # Data rows
            for row, song in enumerate(self.manifest["songs"], 2):
                ws.cell(row=row, column=1).value = self.run_id
                ws.cell(row=row, column=2).value = song.get("number", "")
                ws.cell(row=row, column=3).value = song.get("title", "")
                ws.cell(row=row, column=4).value = song.get("prompt", "")[:100]
                ws.cell(row=row, column=5).value = song.get("suno_id", "")
                ws.cell(row=row, column=6).value = song.get("duration_seconds", 0)
                ws.cell(row=row, column=7).value = song.get("file_path", "")
                ws.cell(row=row, column=8).value = song.get("status", "")
                ws.cell(row=row, column=9).value = "Yes" if song.get("file_path") else "No"

            # Summary
            summary_row = len(self.manifest["songs"]) + 3
            ws.cell(row=summary_row, column=1).value = "Total Duration (min):"
            ws.cell(row=summary_row, column=2).value = self.manifest["total_duration_seconds"] / 60

            ws.column_dimensions['A'].width = 20
            ws.column_dimensions['B'].width = 10
            ws.column_dimensions['C'].width = 30
            ws.column_dimensions['D'].width = 40
            ws.column_dimensions['E'].width = 20
            ws.column_dimensions['F'].width = 15
            ws.column_dimensions['G'].width = 40
            ws.column_dimensions['H'].width = 15
            ws.column_dimensions['I'].width = 20

            output_path = self.run_dir / "production_manifest.xlsx"
            wb.save(str(output_path))
            logger.info(f"Excel manifest created: {output_path}")
            return output_path

        except Exception as e:
            logger.error(f"Failed to create Excel: {e}")
            return None

    def save_manifest_json(self) -> Path:
        """Save manifest as JSON."""
        output_path = self.run_dir / "manifest.json"
        with open(output_path, "w") as f:
            json.dump(self.manifest, f, indent=2)
        logger.info(f"Manifest saved: {output_path}")
        return output_path

    def run(self) -> dict:
        """Execute complete pipeline."""
        logger.info("")
        logger.info("=" * 80)
        logger.info("SILENT DARK BLUES - 20-MINUTE COMPILATION PIPELINE")
        logger.info("=" * 80)
        logger.info("")

        try:
            # Step 1: Generate prompts
            logger.info("[1/7] GENERATING SONG PROMPTS")
            prompts = self.generate_song_prompts(num_songs=4)
            if not prompts:
                logger.error("No prompts generated")
                return {"status": "failed", "reason": "No prompts generated"}
            logger.info("")

            # Step 2: Generate songs
            logger.info("[2/7] GENERATING SONGS FROM SUNO")
            generated_songs = self.generate_songs(prompts)
            if not generated_songs:
                logger.error("No songs generated")
                return {"status": "failed", "reason": "No songs generated"}
            logger.info("")

            # Step 3: Validate and download
            logger.info("[3/7] VALIDATING AND DOWNLOADING SONGS")
            valid_songs = self.validate_and_download_songs(generated_songs)
            if not valid_songs:
                logger.error("No valid songs")
                return {"status": "failed", "reason": "No valid songs"}
            logger.info("")

            # Step 4: Store in mega library
            logger.info("[4/7] STORING IN MEGA LIBRARY")
            self.store_in_mega_library(valid_songs)
            logger.info("")

            # Step 5: Select images
            logger.info("[5/7] SELECTING BACKGROUND IMAGES")
            images = self.select_images_for_songs(len(valid_songs))
            if not images:
                logger.error("No images selected")
                return {"status": "failed", "reason": "No images selected"}
            logger.info("")

            # Step 6: Compile video
            logger.info("[6/7] COMPILING VIDEO WITH SONGS AND IMAGES")
            video_path = self.compile_songs_into_video(valid_songs, images)
            if not video_path:
                logger.error("Video compilation failed")
                return {"status": "failed", "reason": "Video compilation failed"}
            logger.info("")

            # Step 7: Add visualizer
            logger.info("[7/7] ADDING AUDIO VISUALIZER")
            final_video = self.add_visualizer(video_path)
            if not final_video:
                logger.error("Visualizer addition failed")
                return {"status": "failed", "reason": "Visualizer failed"}
            logger.info("")

            # Create manifests
            logger.info("CREATING PRODUCTION MANIFESTS")
            self.create_excel_manifest()
            self.save_manifest_json()
            logger.info("")

            # Summary
            logger.info("=" * 80)
            logger.info("COMPILATION COMPLETE")
            logger.info("=" * 80)
            logger.info("")
            logger.info(f"Run ID: {self.run_id}")
            logger.info(f"Songs Generated: {len(valid_songs)}")
            logger.info(f"Total Duration: {self.manifest['total_duration_seconds'] / 60:.1f} minutes")
            logger.info(f"Output Directory: {self.run_dir}")
            logger.info(f"Final Video: {final_video.name}")
            logger.info(f"Mega Library: {self.mega_library_dir}")
            logger.info("")

            return {
                "status": "success",
                "run_id": self.run_id,
                "videos_generated": len(valid_songs),
                "total_duration_minutes": self.manifest["total_duration_seconds"] / 60,
                "output_dir": str(self.run_dir),
                "final_video": str(final_video),
                "mega_library": str(self.mega_library_dir),
            }

        except Exception as e:
            logger.error(f"Pipeline failed: {e}")
            import traceback
            traceback.print_exc()
            return {"status": "failed", "error": str(e)}
