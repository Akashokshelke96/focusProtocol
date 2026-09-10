"""
Unit tests for YouTube automation engine
"""
import pytest
import json
from pathlib import Path
from datetime import datetime
from app.config.settings import Settings
from app.media import MediaValidator, MediaDeduplicator
from app.content import SceneData, GeneratedContent
from app.jobs.manager import JobManager, JobStage


class TestMediaValidator:
    """Test media validation."""

    def test_sha256_calculation(self, tmp_path):
        """Test SHA-256 hash calculation."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("test content")

        sha256 = MediaValidator.calculate_sha256(test_file)
        assert len(sha256) == 64  # SHA-256 is 64 hex characters
        assert sha256 == MediaValidator.calculate_sha256(test_file)  # Deterministic

    def test_image_validation_fails_portrait(self, tmp_path):
        """Test that portrait images are rejected."""
        # Meet minimum dimensions so this exercises orientation rejection.
        try:
            from PIL import Image

            img = Image.new("RGB", (1920, 2560), color="red")
            img_path = tmp_path / "portrait.jpg"
            img.save(img_path)

            valid, reason = MediaValidator.validate_image(img_path)
            assert not valid
            assert "portrait" in reason.lower() or "orientation" in reason.lower()
        except ImportError:
            pytest.skip("PIL not available")

    def test_image_validation_passes_landscape(self, tmp_path):
        """Test that landscape images pass validation."""
        try:
            from PIL import Image

            img = Image.new("RGB", (1920, 1080), color="blue")
            img_path = tmp_path / "landscape.jpg"
            img.save(img_path)

            valid, reason = MediaValidator.validate_image(img_path)
            assert valid
            assert reason is None
        except ImportError:
            pytest.skip("PIL not available")


class TestMediaDeduplicator:
    """Test deduplication."""

    def test_exact_duplicate_detection(self):
        """Test exact hash duplicate detection."""
        dedup = MediaDeduplicator()

        sha256 = "abc123def456"
        is_new = dedup.register_exact(sha256, "asset_1")
        assert is_new

        is_new = dedup.register_exact(sha256, "asset_2")
        assert not is_new

    def test_perceptual_duplicate_detection(self):
        """Test perceptual hash duplicate detection."""
        dedup = MediaDeduplicator()

        phash = "perceptual_hash_123"
        is_new = dedup.register_perceptual(phash, "asset_1")
        assert is_new

        is_new = dedup.register_perceptual(phash, "asset_2")
        assert not is_new


class TestSceneData:
    """Test scene data models."""

    def test_scene_data_creation(self):
        """Test SceneData creation."""
        scene = SceneData(
            id=1,
            start_seconds=0,
            end_seconds=10,
            duration_seconds=10,
            narration="Test narration",
            visual_goal="Test visual",
            visual_type="video",
            pexels_query="test query",
            pinterest_query="test pinterest",
            mood="dark",
            keywords=["keyword1"],
            recommended_source="pexels",
        )

        assert scene.id == 1
        assert scene.duration_seconds == 10
        assert scene.narration == "Test narration"

    def test_scene_data_to_dict(self):
        """Test SceneData serialization."""
        scene = SceneData(
            id=1,
            start_seconds=0,
            end_seconds=10,
            duration_seconds=10,
            narration="Test",
            visual_goal="Test",
            visual_type="video",
            pexels_query="query",
            pinterest_query="query",
            mood="dark",
        )

        data = scene.to_dict()
        assert data["id"] == 1
        assert data["narration"] == "Test"
        assert isinstance(data, dict)


class TestGeneratedContent:
    """Test content generation models."""

    def test_content_creation(self):
        """Test GeneratedContent creation."""
        content = GeneratedContent(
            job_id="test_job",
            topic="Test Topic",
            title="Test Title",
            hook="Test Hook",
            description="Test Description",
            script="Test Script",
            sections=[],
            tags=["tag1"],
            keywords=["kw1"],
            thumbnail_concept="Test Concept",
        )

        assert content.job_id == "test_job"
        assert content.title == "Test Title"

    def test_content_to_dict(self):
        """Test GeneratedContent serialization."""
        content = GeneratedContent(
            job_id="test_job",
            topic="Test Topic",
            title="Test Title",
            hook="Test Hook",
            description="Test Description",
            script="Test Script",
        )

        data = content.to_dict()
        assert data["job_id"] == "test_job"
        assert "created_at" in data
        assert isinstance(data["created_at"], str)


class TestJobManager:
    """Test job management."""

    def test_job_creation(self, tmp_path):
        """Test job creation."""
        # Temporarily override database path
        import app.jobs.manager as jm

        original_path = jm.get_settings

        def mock_settings():
            settings = Settings()
            settings.database_path = str(tmp_path / "test.db")
            return settings

        jm.get_settings = mock_settings

        try:
            manager = JobManager()
            job = manager.create_job("test_job", "Test Topic", 10)

            assert job.id == "test_job"
            assert job.topic == "Test Topic"
            assert job.duration_minutes == 10
            assert job.stage == JobStage.CREATED.value

            # Verify we can retrieve it
            retrieved = manager.get_job("test_job")
            assert retrieved.id == "test_job"
            assert retrieved.topic == "Test Topic"

        finally:
            jm.get_settings = original_path

    def test_job_update(self, tmp_path):
        """Test job state updates."""
        import app.jobs.manager as jm

        original_path = jm.get_settings

        def mock_settings():
            settings = Settings()
            settings.database_path = str(tmp_path / "test.db")
            return settings

        jm.get_settings = mock_settings

        try:
            manager = JobManager()
            job = manager.create_job("test_job_2", "Test", 10)

            # Update stage
            job.stage = JobStage.CONTENT_GENERATED.value
            manager.update_job(job)

            # Verify update
            retrieved = manager.get_job("test_job_2")
            assert retrieved.stage == JobStage.CONTENT_GENERATED.value

        finally:
            jm.get_settings = original_path


class TestSettings:
    """Test configuration."""

    def test_settings_loading(self):
        """Test settings can be loaded."""
        settings = Settings()
        assert settings.video_width == 1920
        assert settings.video_height == 1080
        assert settings.video_fps == 24

    def test_settings_validation(self):
        """Test required API key validation."""
        settings = Settings()
        # API keys may or may not be set in test environment
        # Just verify the method works
        missing = settings.validate_required_keys()
        assert isinstance(missing, list)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
