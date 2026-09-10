"""
SEO & Metadata Generator for Silent Dark Blues
Generates titles, descriptions, tags, hashtags using Gemini
"""
import json
from typing import Optional
from app.config.logging_config import get_logger
from app.llm.gemini import GeminiProvider
from app.config.settings import Settings

logger = get_logger("youtube.metadata_generator")


class YouTubeMetadataGenerator:
    """Generate YouTube-optimized metadata for music compilations."""

    def __init__(self):
        self.settings = Settings()
        self.gemini = GeminiProvider(self.settings)
        self.logger = logger

    def generate_metadata(
        self,
        compilation_id: str,
        song_titles: list[str],
        total_duration_minutes: int,
        episode_number: int,
    ) -> dict:
        """Generate complete YouTube metadata for a compilation."""
        self.logger.info(f"Generating metadata for compilation {compilation_id}...")

        prompt = f"""
You are a YouTube content strategist for "Silent Dark Blues" - a channel with 3.6K subscribers
focused on dark blues, noir gentleman playlists, and contemplative music.

Generate YouTube-optimized metadata for a new compilation video with these details:
- Episode Number: {episode_number}
- Total Duration: {total_duration_minutes} minutes
- Song Count: {len(song_titles)}
- Channel Focus: Gentlemen's dark blues, late-night, sophisticated, masculine introspection

Generate in JSON format:
{{
  "title": "YouTube video title (60 chars max, SEO-focused, includes duration)",
  "description": "Full YouTube description (2000+ chars, includes timestamps, channel info, CTA)",
  "tags": ["tag1", "tag2", ...],  // 15-20 relevant tags
  "hashtags": ["#darkblues", "#gentlemanmusic", ...],  // 5-8 hashtags for description
  "chapters": [
    {{"start_time": "0:00", "title": "Chapter title"}},
    ...
  ],
  "seo_keywords": ["keyword1", "keyword2", ...],  // Internal tracking
  "cta_timestamp": "Last 30 seconds - call to action"
}}

Channel Context:
- Channel name: Silent Dark Blues
- Subscribers: 3.6K
- Niche: Gentlemen who walk alone, think deeply, move in silence
- Music style: Slow blues, noir atmosphere, contemplative
- Audience: Men seeking deep work music, late-night ambiance
- Video duration: {total_duration_minutes} minutes

IMPORTANT:
1. Title must be under 60 characters
2. Include duration in title (e.g., "... | 20 Minutes")
3. Description must include: channel mission, what to expect, timestamp chapters, subscribe CTA
4. Tags should target: dark blues, gentleman music, long-form music, study/focus music, noir
5. Do NOT use clickbait or misleading titles
6. Maintain channel's mature, sophisticated tone

Generate metadata that will rank well in YouTube search for music compilation viewers.
"""

        try:
            response = self.gemini._generate_with_retry(prompt)
            data = self.gemini._extract_json(response)

            self.logger.info(f"Metadata generated for episode {episode_number}")
            self.logger.info(f"  Title: {data.get('title', 'N/A')[:60]}")
            self.logger.info(f"  Tags: {len(data.get('tags', []))} tags")
            self.logger.info(f"  Hashtags: {len(data.get('hashtags', []))} hashtags")

            return data

        except Exception as e:
            self.logger.error(f"Metadata generation failed: {e}")
            return self._generate_fallback_metadata(episode_number, total_duration_minutes)

    def _generate_fallback_metadata(self, episode_number: int, duration: int) -> dict:
        """Generate fallback metadata if Gemini fails."""
        self.logger.warning("Using fallback metadata")

        title = f"Silent Dark Blues Playlist Vol.{episode_number} | {duration} Min Gentleman Music"
        description = f"""Welcome to Silent Dark Blues - Episode {episode_number}

A carefully curated {duration}-minute compilation of dark blues, noir atmosphere, and sophisticated gentleman music.

For men who walk alone, think deeply, and move in silence.

CHAPTERS:
0:00 - Intro
2:00 - Main Compilation
{duration-2}:00 - Outro

Subscribe for more dark blues, noir music, and late-night atmosphere.

Follow Silent Dark Blues:
YouTube: @SilentDarkBlues

#DarkBlues #GentlemanMusic #NoirPlaylist #LongFormMusic
"""

        return {
            "title": title[:60],
            "description": description,
            "tags": [
                "dark blues",
                "gentleman music",
                "noir playlist",
                "long form music",
                "study music",
                "focus music",
                "late night music",
                "blues playlist",
                "cinematic music",
                "contemplative",
            ],
            "hashtags": ["#DarkBlues", "#GentlemanMusic", "#NoirPlaylist", "#LongFormMusic"],
            "chapters": [
                {"start_time": "0:00", "title": "Intro"},
                {"start_time": "2:00", "title": "Main Compilation"},
            ],
            "seo_keywords": ["dark blues", "gentleman", "noir", "contemplative", "late-night"],
        }

    def format_for_youtube(self, metadata: dict) -> dict:
        """Format metadata for YouTube API upload."""
        return {
            "snippet": {
                "title": metadata.get("title", ""),
                "description": metadata.get("description", ""),
                "tags": metadata.get("tags", [])[:30],  # YouTube max 30 tags
                "categoryId": "10",  # Music category
                "defaultLanguage": "en",
                "defaultAudioLanguage": "en",
            },
            "status": {
                "privacyStatus": "public",
                "madeForKids": False,
            },
        }
