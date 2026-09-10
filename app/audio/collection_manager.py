"""
Master Audio Collection Manager
Centralizes all audio downloads and manages both episode-specific and library-wide storage
"""
import json
import shutil
from pathlib import Path
from typing import Optional, Dict, List, Any
from datetime import datetime
from app.config.logging_config import get_logger

logger = get_logger("audio.collection_manager")


class AudioMetadata:
    """Metadata for audio tracks in the master collection."""

    def __init__(
        self,
        track_id: str,
        filename: str,
        original_source: str,
        duration_seconds: float,
        genre: str = "Blues",
        mood: str = "Melancholic",
        tempo_bpm: int = 70,
        provider: str = "Unknown",
        provider_id: Optional[str] = None,
        tags: Optional[List[str]] = None,
    ):
        self.track_id = track_id
        self.filename = filename
        self.original_source = original_source
        self.duration_seconds = duration_seconds
        self.genre = genre
        self.mood = mood
        self.tempo_bpm = tempo_bpm
        self.provider = provider
        self.provider_id = provider_id
        self.tags = tags or []
        self.created_at = datetime.utcnow().isoformat()
        self.usage_count = 0
        self.episodes_used = []

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "track_id": self.track_id,
            "filename": self.filename,
            "original_source": self.original_source,
            "duration_seconds": self.duration_seconds,
            "genre": self.genre,
            "mood": self.mood,
            "tempo_bpm": self.tempo_bpm,
            "provider": self.provider,
            "provider_id": self.provider_id,
            "tags": self.tags,
            "created_at": self.created_at,
            "usage_count": self.usage_count,
            "episodes_used": self.episodes_used,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AudioMetadata":
        """Create from dictionary."""
        obj = cls(
            track_id=data["track_id"],
            filename=data["filename"],
            original_source=data["original_source"],
            duration_seconds=data["duration_seconds"],
            genre=data.get("genre", "Blues"),
            mood=data.get("mood", "Melancholic"),
            tempo_bpm=data.get("tempo_bpm", 70),
            provider=data.get("provider", "Unknown"),
            provider_id=data.get("provider_id"),
            tags=data.get("tags", []),
        )
        obj.created_at = data.get("created_at", obj.created_at)
        obj.usage_count = data.get("usage_count", 0)
        obj.episodes_used = data.get("episodes_used", [])
        return obj


class MasterAudioCollection:
    """
    Manages a centralized collection of all audio tracks.
    Automatically mirrors audio to both episode folders and master collection.
    """

    def __init__(self, base_path: Path = Path("media/audio")):
        """Initialize the master audio collection."""
        self.base_path = Path(base_path)
        self.master_path = self.base_path / "master_collection"
        self.episodes_path = self.base_path / "episodes"
        self.metadata_file = self.master_path / "collection_index.json"

        # Create directories
        self.master_path.mkdir(parents=True, exist_ok=True)
        self.episodes_path.mkdir(parents=True, exist_ok=True)

        # Organize by type
        self.genres_path = self.master_path / "by_genre"
        self.moods_path = self.master_path / "by_mood"
        self.providers_path = self.master_path / "by_provider"

        for path in [self.genres_path, self.moods_path, self.providers_path]:
            path.mkdir(parents=True, exist_ok=True)

        # Load or create collection index
        self.collection: Dict[str, AudioMetadata] = self._load_collection()
        logger.info(f"Master audio collection initialized at {self.master_path}")
        logger.info(f"Current collection: {len(self.collection)} tracks")

    def _load_collection(self) -> Dict[str, AudioMetadata]:
        """Load collection index from disk."""
        if self.metadata_file.exists():
            try:
                with open(self.metadata_file, "r") as f:
                    data = json.load(f)
                    return {
                        track_id: AudioMetadata.from_dict(meta)
                        for track_id, meta in data.items()
                    }
            except Exception as e:
                logger.warning(f"Failed to load collection index: {e}")
                return {}
        return {}

    def _save_collection(self) -> None:
        """Save collection index to disk."""
        try:
            data = {
                track_id: meta.to_dict() for track_id, meta in self.collection.items()
            }
            with open(self.metadata_file, "w") as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save collection index: {e}")

    def add_audio(
        self,
        source_path: Path,
        track_id: str,
        genre: str = "Blues",
        mood: str = "Melancholic",
        tempo_bpm: int = 70,
        provider: str = "Unknown",
        provider_id: Optional[str] = None,
        tags: Optional[List[str]] = None,
    ) -> Optional[AudioMetadata]:
        """
        Add audio to master collection and create symlinks/copies for episodes.

        Args:
            source_path: Path to source audio file
            track_id: Unique ID for this track
            genre: Genre classification
            mood: Mood/atmosphere description
            tempo_bpm: Tempo in beats per minute
            provider: Source provider (Suno, AceMusic, etc.)
            provider_id: Provider's track ID
            tags: Additional tags for categorization

        Returns:
            AudioMetadata object or None if failed
        """
        if not source_path.exists():
            logger.error(f"Source audio file not found: {source_path}")
            return None

        try:
            # Create master collection file
            filename = f"{track_id}_{source_path.name}"
            master_file = self.master_path / filename

            # Copy to master collection
            shutil.copy2(source_path, master_file)
            logger.info(f"Added to master collection: {master_file}")

            # Create metadata
            metadata = AudioMetadata(
                track_id=track_id,
                filename=filename,
                original_source=str(source_path),
                duration_seconds=self._get_audio_duration(master_file),
                genre=genre,
                mood=mood,
                tempo_bpm=tempo_bpm,
                provider=provider,
                provider_id=provider_id,
                tags=tags or [],
            )

            # Organize in master collection
            self._organize_in_collection(master_file, metadata)

            # Add to index
            self.collection[track_id] = metadata
            self._save_collection()

            logger.info(f"Successfully added track: {track_id}")
            return metadata

        except Exception as e:
            logger.error(f"Failed to add audio to collection: {e}")
            return None

    def _organize_in_collection(self, audio_file: Path, metadata: AudioMetadata) -> None:
        """Organize audio file into genre/mood/provider subdirectories."""
        try:
            # By genre
            genre_dir = self.genres_path / metadata.genre
            genre_dir.mkdir(exist_ok=True)
            genre_link = genre_dir / audio_file.name
            if not genre_link.exists():
                shutil.copy2(audio_file, genre_link)

            # By mood
            mood_dir = self.moods_path / metadata.mood.replace(" ", "_")
            mood_dir.mkdir(exist_ok=True)
            mood_link = mood_dir / audio_file.name
            if not mood_link.exists():
                shutil.copy2(audio_file, mood_link)

            # By provider
            provider_dir = self.providers_path / metadata.provider
            provider_dir.mkdir(exist_ok=True)
            provider_link = provider_dir / audio_file.name
            if not provider_link.exists():
                shutil.copy2(audio_file, provider_link)

            logger.info(
                f"Organized {audio_file.name} into genre/mood/provider collections"
            )
        except Exception as e:
            logger.warning(f"Failed to organize audio file: {e}")

    def add_to_episode(
        self, track_id: str, episode_id: str, episode_folder: Path
    ) -> Optional[Path]:
        """
        Copy audio from master collection to episode folder.

        Args:
            track_id: ID of track in master collection
            episode_id: Episode identifier
            episode_folder: Path to episode folder

        Returns:
            Path to copied file or None if failed
        """
        if track_id not in self.collection:
            logger.error(f"Track not found in collection: {track_id}")
            return None

        try:
            metadata = self.collection[track_id]
            master_file = self.master_path / metadata.filename

            if not master_file.exists():
                logger.error(f"Master file not found: {master_file}")
                return None

            # Create episode-specific folder
            episode_folder.mkdir(parents=True, exist_ok=True)

            # Copy to episode
            episode_file = episode_folder / metadata.filename
            shutil.copy2(master_file, episode_file)

            # Update metadata
            metadata.usage_count += 1
            if episode_id not in metadata.episodes_used:
                metadata.episodes_used.append(episode_id)
            self._save_collection()

            logger.info(
                f"Added {track_id} to episode {episode_id}: {episode_file}"
            )
            return episode_file

        except Exception as e:
            logger.error(f"Failed to add audio to episode: {e}")
            return None

    def get_by_mood(self, mood: str) -> List[AudioMetadata]:
        """Get all tracks with specific mood."""
        return [
            meta
            for meta in self.collection.values()
            if meta.mood.lower() == mood.lower()
        ]

    def get_by_genre(self, genre: str) -> List[AudioMetadata]:
        """Get all tracks with specific genre."""
        return [
            meta
            for meta in self.collection.values()
            if meta.genre.lower() == genre.lower()
        ]

    def get_by_provider(self, provider: str) -> List[AudioMetadata]:
        """Get all tracks from specific provider."""
        return [
            meta
            for meta in self.collection.values()
            if meta.provider.lower() == provider.lower()
        ]

    def get_by_tempo_range(self, min_bpm: int, max_bpm: int) -> List[AudioMetadata]:
        """Get tracks within tempo range."""
        return [
            meta
            for meta in self.collection.values()
            if min_bpm <= meta.tempo_bpm <= max_bpm
        ]

    def get_by_tags(self, tags: List[str]) -> List[AudioMetadata]:
        """Get tracks matching any of the provided tags."""
        return [
            meta
            for meta in self.collection.values()
            if any(tag in meta.tags for tag in tags)
        ]

    def search(
        self,
        mood: Optional[str] = None,
        genre: Optional[str] = None,
        provider: Optional[str] = None,
        min_tempo: Optional[int] = None,
        max_tempo: Optional[int] = None,
        tags: Optional[List[str]] = None,
    ) -> List[AudioMetadata]:
        """
        Advanced search with multiple filters.

        Returns:
            List of matching AudioMetadata objects
        """
        results = list(self.collection.values())

        if mood:
            results = [m for m in results if m.mood.lower() == mood.lower()]
        if genre:
            results = [m for m in results if m.genre.lower() == genre.lower()]
        if provider:
            results = [m for m in results if m.provider.lower() == provider.lower()]
        if min_tempo is not None and max_tempo is not None:
            results = [
                m for m in results if min_tempo <= m.tempo_bpm <= max_tempo
            ]
        if tags:
            results = [
                m for m in results if any(tag in m.tags for tag in tags)
            ]

        return results

    def get_collection_stats(self) -> Dict[str, Any]:
        """Get statistics about the collection."""
        total_duration = sum(m.duration_seconds for m in self.collection.values())
        genres = set(m.genre for m in self.collection.values())
        moods = set(m.mood for m in self.collection.values())
        providers = set(m.provider for m in self.collection.values())

        return {
            "total_tracks": len(self.collection),
            "total_duration_seconds": total_duration,
            "total_duration_hours": total_duration / 3600,
            "genres": sorted(list(genres)),
            "moods": sorted(list(moods)),
            "providers": sorted(list(providers)),
            "most_used_tracks": sorted(
                self.collection.values(),
                key=lambda m: m.usage_count,
                reverse=True,
            )[:10],
        }

    def export_collection_report(self, output_path: Path) -> bool:
        """Export collection report as JSON."""
        try:
            report = {
                "generated_at": datetime.utcnow().isoformat(),
                "statistics": self.get_collection_stats(),
                "tracks": [meta.to_dict() for meta in self.collection.values()],
            }
            output_path.parent.mkdir(parents=True, exist_ok=True)
            with open(output_path, "w") as f:
                json.dump(report, f, indent=2)
            logger.info(f"Collection report exported to {output_path}")
            return True
        except Exception as e:
            logger.error(f"Failed to export collection report: {e}")
            return False

    def _get_audio_duration(self, audio_path: Path) -> float:
        """Get duration of audio file in seconds."""
        try:
            import wave

            with wave.open(str(audio_path), "rb") as wav:
                frames = wav.getnframes()
                rate = wav.getframerate()
                return frames / rate
        except Exception:
            # Fallback if wave fails
            return 0.0
