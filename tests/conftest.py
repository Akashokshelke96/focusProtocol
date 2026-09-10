"""
Test configuration and fixtures
"""
import pytest
from pathlib import Path


@pytest.fixture
def tmp_test_dir(tmp_path):
    """Provide a temporary test directory."""
    return tmp_path


@pytest.fixture
def mock_settings():
    """Provide mock settings."""
    from app.config.settings import Settings

    settings = Settings()
    settings.gemini_api_key = "test_key"
    settings.pexels_api_key = "test_key"
    return settings
