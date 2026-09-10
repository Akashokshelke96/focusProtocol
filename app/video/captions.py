"""
Caption generation from narration
"""
from pathlib import Path
from typing import Optional
import re
from app.config.settings import Settings
from app.config.logging_config import get_logger

logger = get_logger("video.captions")


class CaptionGenerator:
    """Generates captions from narration."""

    def __init__(self, settings: Settings, max_words: int = 5):
        """Initialize caption generator."""
        self.settings = settings
        self.max_words = max_words
        logger.info(f"Caption generator initialized (max {max_words} words)")

    def generate_srt(
        self,
        narration: str,
        audio_duration_seconds: float,
    ) -> str:
        """Generate SRT subtitle file."""
        logger.info("Generating captions")

        # Split narration into sentences
        sentences = re.split(r'(?<=[.!?])\s+', narration.strip())
        if not sentences:
            logger.warning("No sentences found in narration")
            return ""

        # Estimate timing based on word count
        words = narration.split()
        total_words = len(words)
        words_per_second = total_words / max(audio_duration_seconds, 1.0)

        srt_content = []
        caption_index = 1
        word_index = 0

        for sentence in sentences:
            sentence_words = sentence.split()
            if not sentence_words:
                continue

            # Group words into captions (max_words per caption)
            for i in range(0, len(sentence_words), self.max_words):
                caption_words = sentence_words[i : i + self.max_words]
                caption_text = " ".join(caption_words)

                # Calculate timing
                start_time = word_index / words_per_second
                word_index += len(caption_words)
                end_time = word_index / words_per_second

                # Clamp to audio duration
                end_time = min(end_time, audio_duration_seconds)

                # Format timecode
                start_tc = self._format_timecode(start_time)
                end_tc = self._format_timecode(end_time)

                srt_content.append(f"{caption_index}\n{start_tc} --> {end_tc}\n{caption_text}\n")
                caption_index += 1

        logger.info(f"Generated {caption_index - 1} caption segments")
        return "\n".join(srt_content)

    def _format_timecode(self, seconds: float) -> str:
        """Format seconds as SRT timecode."""
        total_seconds = int(seconds)
        milliseconds = int((seconds - total_seconds) * 1000)

        hours = total_seconds // 3600
        minutes = (total_seconds % 3600) // 60
        seconds_part = total_seconds % 60

        return f"{hours:02d}:{minutes:02d}:{seconds_part:02d},{milliseconds:03d}"

    def write_srt(self, srt_content: str, output_path: Path) -> bool:
        """Write SRT file."""
        try:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            with open(output_path, "w", encoding="utf-8") as f:
                f.write(srt_content)

            logger.info(f"SRT file written: {output_path}")
            return True

        except Exception as e:
            logger.error(f"Failed to write SRT: {e}")
            return False
