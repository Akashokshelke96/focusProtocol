"""
YouTube Automation Engine - Main Package
"""
from app.config.settings import Settings, get_settings, ensure_directories
from app.config.logging_config import setup_logging, get_logger

__version__ = "0.1.0"
__all__ = ["Settings", "get_settings", "ensure_directories", "setup_logging", "get_logger"]
