from __future__ import annotations
"""
YouTube Automation Engine - Configuration Management
"""
import os
import json
from pathlib import Path
from typing import Optional
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field, field_validator, model_validator


class Settings(BaseSettings):
    """Centralized configuration from environment variables."""

    model_config = SettingsConfigDict(env_file=".env", case_sensitive=False, extra="ignore")

    # API Keys
    gemini_api_key: str = Field(default="", alias="GEMINI_API_KEY")
    pexels_api_key: str = Field(default="", alias="PEXELS_API_KEY")
    acemusic_api_key: str = Field(default="", alias="ACEMUSIC_API_KEY")

    # Feature Flags
    pinterest_enabled: bool = Field(default=True, alias="PINTEREST_ENABLED")
    acemusic_enabled: bool = Field(default=True, alias="ACEMUSIC_ENABLED")
    youtube_upload_enabled: bool = Field(default=False, alias="YOUTUBE_UPLOAD_ENABLED")
    captions_enabled: bool = Field(default=False, alias="CAPTIONS_ENABLED")
    narration_enabled: bool = Field(default=False, alias="NARRATION_ENABLED")
    motion_enabled: bool = Field(default=True, alias="MOTION_ENABLED")
    motion_blur_enabled: bool = Field(default=False, alias="MOTION_BLUR_ENABLED")
    studio_motion_mode: str = Field(default='static', pattern='^(static|drift)$', alias='STUDIO_MOTION_MODE')
    debug: bool = Field(default=False, alias="DEBUG")

    channel_brand_name: str = Field(default="Camping With Blues", alias="CHANNEL_BRAND_NAME")
    song_panel_enabled: bool = Field(default=False, alias="SONG_PANEL_ENABLED")
    visual_effect: str = Field(default="old_film", pattern="^(none|old_film|vintage|warm_film|faded_film|noir|sepia|cool_cinematic|film_grain|soft_vignette)$", alias="VISUAL_EFFECT")
    visual_effect_opacity: float = Field(default=.06, ge=0, le=.3, alias="VISUAL_EFFECT_OPACITY")
    waveform_style: str = Field(default="linear", pattern="^(linear|circular)$", alias="WAVEFORM_STYLE")
    waveform_visual_height_ratio: float = Field(default=.30, ge=.04, le=.3, alias="WAVEFORM_VISUAL_HEIGHT_RATIO")
    waveform_scale: float = Field(default=2, ge=1, le=2, alias="WAVEFORM_SCALE")

    # Video Dimensions & Quality (Tier 2 Optimization)
    quality_preset: str = Field(default='1080p', pattern='^(480p|720p|1080p)$', alias='QUALITY_PRESET')
    video_width: int = Field(default=1920, alias="VIDEO_WIDTH")
    video_height: int = Field(default=1080, alias="VIDEO_HEIGHT")
    video_fps: int = Field(default=30, alias="VIDEO_FPS")
    ffmpeg_preset: str = Field(default="ultrafast", alias="FFMPEG_PRESET")
    video_encoder: str = Field(default='auto', pattern='^(auto|libx264|h264_nvenc|h264_amf|h264_qsv)$', alias='VIDEO_ENCODER')
    video_encoder_quality: int = Field(default=18, ge=0, le=40, alias='VIDEO_ENCODER_QUALITY')
    render_cpu_threads: int = Field(default=2, ge=1, le=16, alias='RENDER_CPU_THREADS')
    render_max_concurrent: int = Field(default=1, ge=1, le=4, alias='RENDER_MAX_CONCURRENT')
    render_cpu_high_percent: float = Field(default=90, ge=50, le=100, alias='RENDER_CPU_HIGH_PERCENT')
    render_pressure_seconds: int = Field(default=30, ge=10, le=300, alias='RENDER_PRESSURE_SECONDS')
    render_gpu_max_temperature: int = Field(default=85, ge=65, le=100, alias='RENDER_GPU_MAX_TEMPERATURE')
    intro_fade_seconds: float = Field(default=2, ge=0, le=10, alias='INTRO_FADE_SECONDS')
    outro_fade_seconds: float = Field(default=3, ge=0, le=10, alias='OUTRO_FADE_SECONDS')
    audio_silence_removal_enabled: bool = Field(default=True, alias='AUDIO_SILENCE_REMOVAL_ENABLED')
    audio_silence_threshold_db: float = Field(default=-52, le=-20, ge=-80, alias='AUDIO_SILENCE_THRESHOLD_DB')
    audio_silence_min_seconds: float = Field(default=3, ge=1, le=20, alias='AUDIO_SILENCE_MIN_SECONDS')
    audio_silence_keep_seconds: float = Field(default=0.25, ge=0, le=2, alias='AUDIO_SILENCE_KEEP_SECONDS')
    render_timeout_multiplier: float = Field(default=4, ge=1, le=20, alias='RENDER_TIMEOUT_MULTIPLIER')
    render_stall_timeout_seconds: int = Field(default=300, ge=30, alias='RENDER_STALL_TIMEOUT_SECONDS')
    render_segment_seconds: int = Field(default=600, ge=60, le=1800, alias="RENDER_SEGMENT_SECONDS")
    ffmpeg_crf: int = Field(default=20, alias="FFMPEG_CRF")
    ffmpeg_audio_bitrate: str = Field(default="320k", alias="FFMPEG_AUDIO_BITRATE")
    target_duration_minutes: int = Field(default=90, alias="TARGET_DURATION_MINUTES")
    waveform_enabled: bool = Field(default=True, alias="WAVEFORM_ENABLED")
    waveform_animated: bool = Field(default=False, alias="WAVEFORM_ANIMATED")
    waveform_height_ratio: float = Field(default=0.03, gt=0, le=0.15, alias="WAVEFORM_HEIGHT_RATIO")
    waveform_width_ratio: float = Field(default=0.50, gt=0, le=1, alias="WAVEFORM_WIDTH_RATIO")
    waveform_vertical_position_ratio: float = Field(default=0.80, ge=0.1, le=0.9, alias="WAVEFORM_VERTICAL_POSITION_RATIO")
    waveform_bar_width: int = Field(default=3, ge=1, le=8, alias="WAVEFORM_BAR_WIDTH")
    waveform_min_amplitude: float = Field(default=.06, ge=0, le=.2, alias='WAVEFORM_MIN_AMPLITUDE')
    waveform_opacity: float = Field(default=0.90, ge=0, le=1, alias="WAVEFORM_OPACITY")
    waveform_filter_enabled: bool = Field(default=True, alias="WAVEFORM_FILTER_ENABLED")
    waveform_bottom_padding_ratio: float = Field(default=0.054, alias="WAVEFORM_BOTTOM_PADDING_RATIO")
    waveform_color: str = Field(default="0x000000", alias="WAVEFORM_COLOR")
    lyrics_model: str = Field(default="base.en", alias="LYRICS_MODEL")
    astrofox_visualizer_enabled: bool = Field(default=False, alias="ASTROFOX_VISUALIZER_ENABLED")
    astrofox_visualizer_script: str = Field(default="render-astrofox.js", alias="ASTROFOX_VISUALIZER_SCRIPT")
    astrofox_glow_opacity: float = Field(default=0.22, alias="ASTROFOX_GLOW_OPACITY")
    astrofox_vignette_opacity: float = Field(default=0.22, alias="ASTROFOX_VIGNETTE_OPACITY")
    watermark_enabled: bool = Field(default=True, alias="WATERMARK_ENABLED")
    watermark_width_ratio: float = Field(default=0.016667, alias="WATERMARK_WIDTH_RATIO")
    watermark_right_padding_ratio: float = Field(default=0.02, alias="WATERMARK_RIGHT_PADDING_RATIO")
    watermark_bottom_padding_ratio: float = Field(default=0.02, alias="WATERMARK_BOTTOM_PADDING_RATIO")
    watermark_opacity: float = Field(default=0.35, alias="WATERMARK_OPACITY")
    visualizer_enabled: bool = Field(default=False, alias="VISUALIZER_ENABLED")
    visualizer_loop_width_ratio: float = Field(default=0.21875, gt=0, le=0.5, alias="VISUALIZER_LOOP_WIDTH_RATIO")
    visualizer_left_padding_ratio: float = Field(default=0.03125, ge=0, le=0.2, alias="VISUALIZER_LEFT_PADDING_RATIO")
    visualizer_loop_bottom_padding_ratio: float = Field(default=0.055556, ge=0, le=0.2, alias="VISUALIZER_LOOP_BOTTOM_PADDING_RATIO")
    visualizer_music_disk_path: str = Field(default="asset/music-disk.gif", alias="VISUALIZER_MUSIC_DISK_PATH")
    visualizer_soundwave_path: str = Field(default="asset/soundwave.gif", alias="VISUALIZER_SOUNDWAVE_PATH")
    visualizer_combined_width_ratio: float = Field(default=0.25, gt=0, le=0.5, alias="VISUALIZER_COMBINED_WIDTH_RATIO")
    visualizer_bottom_padding_ratio: float = Field(default=0.02, ge=0, le=0.2, alias="VISUALIZER_BOTTOM_PADDING_RATIO")
    visualizer_right_padding_ratio: float = Field(default=0.01, ge=0, le=0.1, alias="VISUALIZER_RIGHT_PADDING_RATIO")
    visualizer_opacity: float = Field(default=1.0, ge=0, le=1, alias="VISUALIZER_OPACITY")
    subscribe_overlay_enabled: bool = Field(default=False, alias="SUBSCRIBE_OVERLAY_ENABLED")
    subscribe_animation_duration: float = Field(default=4, gt=0, le=15, alias="SUBSCRIBE_ANIMATION_DURATION")
    subscribe_crop_height_ratio: float = Field(default=1, gt=0, le=1, alias="SUBSCRIBE_CROP_HEIGHT_RATIO")
    subscribe_crop_top_ratio: float = Field(default=0, ge=0, lt=1, alias="SUBSCRIBE_CROP_TOP_RATIO")
    subscribe_crop_width_ratio: float = Field(default=1, gt=0, le=1, alias="SUBSCRIBE_CROP_WIDTH_RATIO")
    subscribe_crop_left_ratio: float = Field(default=0, ge=0, lt=1, alias="SUBSCRIBE_CROP_LEFT_RATIO")
    subscribe_white_key_enabled: bool = Field(default=False, alias="SUBSCRIBE_WHITE_KEY_ENABLED")
    subscribe_overlay_interval_seconds: int = Field(default=480, ge=60, alias="SUBSCRIBE_OVERLAY_INTERVAL_SECONDS")
    subscribe_overlay_width_ratio: float = Field(default=0.30, gt=0, le=0.5, alias="SUBSCRIBE_OVERLAY_WIDTH_RATIO")
    subscribe_overlay_left_padding_ratio: float = Field(default=0.02, ge=0, le=0.2, alias="SUBSCRIBE_OVERLAY_LEFT_PADDING_RATIO")
    subscribe_overlay_bottom_padding_ratio: float = Field(default=0.02, ge=0, le=0.2, alias="SUBSCRIBE_OVERLAY_BOTTOM_PADDING_RATIO")

    music_crossfade_seconds: float = Field(default=4, ge=3, le=5, alias="MUSIC_CROSSFADE_SECONDS")

    # Duration
    default_video_duration_minutes: int = Field(default=10, alias="DEFAULT_VIDEO_DURATION_MINUTES")
    test_video_duration_minutes: int = Field(default=5, alias="TEST_VIDEO_DURATION_MINUTES")

    # Hero Image & Shot Duration (Music Channel)
    shot_duration_min_seconds: int = Field(default=30, alias="SHOT_DURATION_MIN_SECONDS")
    shot_duration_max_seconds: int = Field(default=75, alias="SHOT_DURATION_MAX_SECONDS")
    shot_duration_optimal_seconds: int = Field(default=45, alias="SHOT_DURATION_OPTIMAL_SECONDS")
    hero_images_per_video: int = Field(default=6, alias="HERO_IMAGES_PER_VIDEO")

    # Motion Settings (Music Channel - Subtle)
    motion_strength: float = Field(default=0.15, alias="MOTION_STRENGTH")

    # Image Requirements
    image_min_width: int = Field(default=1920, alias="IMAGE_MIN_WIDTH")
    image_min_height: int = Field(default=1080, alias="IMAGE_MIN_HEIGHT")
    image_target_aspect_ratio: float = Field(default=1.7777, alias="IMAGE_TARGET_ASPECT_RATIO")
    image_aspect_tolerance: float = Field(default=0.08, alias="IMAGE_ASPECT_TOLERANCE")

    # Visual Style Scoring (Music Channel)
    visual_style_score_threshold: float = Field(default=0.60, alias="VISUAL_STYLE_SCORE_THRESHOLD")

    # Music Generation (ACE-Step)
    music_bpm_min: int = Field(default=55, alias="MUSIC_BPM_MIN")
    music_bpm_max: int = Field(default=80, alias="MUSIC_BPM_MAX")
    music_candidates_per_generation: int = Field(default=4, alias="MUSIC_CANDIDATES_PER_GENERATION")
    music_min_duration_seconds: int = Field(default=240, alias="MUSIC_MIN_DURATION_SECONDS")
    music_max_duration_seconds: int = Field(default=360, alias="MUSIC_MAX_DURATION_SECONDS")

    # Video Requirements
    video_min_duration_seconds: float = Field(default=3.0, alias="VIDEO_MIN_DURATION_SECONDS")

    # Captions
    caption_max_words: int = Field(default=5, alias="CAPTION_MAX_WORDS")

    # Timing
    video_transition_seconds: float = Field(default=1.5, alias="VIDEO_TRANSITION_SECONDS")
    audio_crossfade_seconds: float = Field(default=4.0, alias="AUDIO_CROSSFADE_SECONDS")

    # Audio Levels
    music_volume: float = Field(default=0.15, alias="MUSIC_VOLUME")
    narration_volume: float = Field(default=1.0, alias="NARRATION_VOLUME")
    ducking_db: float = Field(default=-6.0, alias="DUCKING_DB")

    # YouTube OAuth
    youtube_client_secrets_file: str = Field(default="youtube_token.json", alias="YOUTUBE_CLIENT_SECRETS_FILE")
    youtube_token_file: str = Field(default="jobs/youtube_token.json", alias="YOUTUBE_TOKEN_FILE")
    youtube_auto_schedule_enabled: bool = Field(default=True, alias="YOUTUBE_AUTO_SCHEDULE_ENABLED")
    youtube_videos_per_day: int = Field(default=2, ge=1, le=24, alias="YOUTUBE_VIDEOS_PER_DAY")
    youtube_schedule_time_1: str = Field(default="09:00", alias="YOUTUBE_SCHEDULE_TIME_1")
    youtube_schedule_time_2: str = Field(default="18:00", alias="YOUTUBE_SCHEDULE_TIME_2")
    youtube_schedule_times: str = Field(default="", alias="YOUTUBE_SCHEDULE_TIMES")
    youtube_timezone: str = Field(default="Asia/Kolkata", alias="YOUTUBE_TIMEZONE")
    youtube_privacy_status: str = Field(default="private", alias="YOUTUBE_PRIVACY_STATUS")
    youtube_category: str = Field(default="10", alias="YOUTUBE_CATEGORY")
    youtube_language: str = Field(default="en", alias="YOUTUBE_LANGUAGE")
    youtube_processing_poll_interval: int = Field(default=30, ge=10, alias="YOUTUBE_PROCESSING_POLL_INTERVAL")
    youtube_processing_timeout: int = Field(default=1800, ge=1, alias="YOUTUBE_PROCESSING_TIMEOUT")
    llm_provider: str = Field(default="gemini", alias="LLM_PROVIDER")
    omniroute_base_url: str = Field(default="http://localhost:8787", alias="OMNIROUTE_BASE_URL")
    omniroute_model: str = Field(default="auto/best-fast", alias="OMNIROUTE_MODEL")
    omniroute_api_key: str = Field(default="", alias="OMNIROUTE_API_KEY")
    youtube_client_id: str = Field(default="", alias="YOUTUBE_CLIENT_ID")
    youtube_client_secret: str = Field(default="", alias="YOUTUBE_CLIENT_SECRET")
    youtube_redirect_uri: str = Field(default="http://localhost:5001/callback", alias="YOUTUBE_REDIRECT_URI")

    # Logging
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")

    # Retry
    max_retries: int = Field(default=3, alias="MAX_RETRIES")
    retry_backoff_seconds: int = Field(default=2, alias="RETRY_BACKOFF_SECONDS")

    # Database
    database_path: str = Field(default="jobs/registry.db", alias="DATABASE_PATH")

    # Channel Profile
    channel_profile_path: str = Field(default="config/channel_profile.json", alias="CHANNEL_PROFILE_PATH")
    _channel_profile: Optional[dict] = None

    # Long-Form Jazz Settings
    jazz_mode_enabled: bool = Field(default=True, alias="JAZZ_MODE_ENABLED")
    jazz_target_duration_minutes: int = Field(default=90, alias="JAZZ_TARGET_DURATION_MINUTES")
    jazz_music_tracks: int = Field(default=3, alias="JAZZ_MUSIC_TRACKS")
    jazz_background_images: int = Field(default=3, alias="JAZZ_BACKGROUND_IMAGES")
    jazz_audio_crossfade_seconds: float = Field(default=2.0, alias="JAZZ_AUDIO_CROSSFADE_SECONDS")
    jazz_image_motion_strength: float = Field(default=0.08, alias="JAZZ_IMAGE_MOTION_STRENGTH")
    jazz_test_duration_minutes: int = Field(default=3, alias="JAZZ_TEST_DURATION_MINUTES")

    # External image generation
    colab_image_api_url: str = Field(default="", alias="COLAB_IMAGE_API_URL")
    colab_image_bypass_password: str = Field(default="", alias="COLAB_IMAGE_BYPASS_PASSWORD")
    colab_image_api_key: str = Field(default="", alias="COLAB_IMAGE_API_KEY")
    colab_image_timeout_seconds: int = Field(default=180, alias="COLAB_IMAGE_TIMEOUT_SECONDS")
    colab_image_enabled: bool = Field(default=False, alias="COLAB_IMAGE_ENABLED")
    
    pollination_image_enabled: bool = Field(default=False, alias="POLLINATION_IMAGE_ENABLED")

    # Audio Optimization (Tier 1)
    audio_loop_track_count: int = Field(default=3, alias="AUDIO_LOOP_TRACK_COUNT")
    audio_enable_looping: bool = Field(default=True, alias="AUDIO_ENABLE_LOOPING")
    audio_duration_tolerance_seconds: float = Field(default=5.0, alias="AUDIO_DURATION_TOLERANCE_SECONDS")

    def get_channel_profile(self) -> dict:
        """Load channel profile from JSON."""
        if self._channel_profile is None:
            profile_path = Path(self.channel_profile_path)
            if not profile_path.exists():
                raise FileNotFoundError(f"Channel profile not found: {profile_path}")
            with open(profile_path, "r") as f:
                self._channel_profile = json.load(f)
        return self._channel_profile

    @field_validator("gemini_api_key", "pexels_api_key", mode="before")
    @classmethod
    def validate_api_keys(cls, v: Optional[str]) -> str:
        """Validate that required API keys are not logged."""
        if v:
            # Mask for logging
            return v
        return ""

    @field_validator("youtube_privacy_status")
    @classmethod
    def validate_youtube_privacy(cls, value: str) -> str:
        value = value.lower().strip()
        if value not in {"private", "unlisted", "public"}:
            raise ValueError("YOUTUBE_PRIVACY_STATUS must be private, unlisted, or public")
        return value

    @model_validator(mode='after')
    def apply_explicit_quality_preset(self):
        # Old saved settings without a preset retain their exact dimensions/quality.
        if 'quality_preset' in self.model_fields_set:
            for key, value in self.quality_values(self.quality_preset).items():
                object.__setattr__(self, key, value)
        return self

    @staticmethod
    def quality_values(preset):
        profiles = {'1080p': (1920, 1080, 23, 23, '192k'),
                    '720p': (1280, 720, 23, 23, '160k'),
                    '480p': (854, 480, 24, 24, '128k')}
        if preset not in profiles:
            raise ValueError('Choose 480p, 720p, or 1080p')
        w, h, crf, cq, audio = profiles[preset]
        return dict(video_width=w, video_height=h, ffmpeg_crf=crf,
                    video_encoder_quality=cq, ffmpeg_audio_bitrate=audio, ffmpeg_preset='ultrafast')

    def with_quality_preset(self, preset):
        return self.model_copy(update=dict(quality_preset=preset, **self.quality_values(preset)))

    def validate_required_keys(self) -> list[str]:
        """Check which required API keys are missing."""
        missing = []
        if not self.gemini_api_key and self.llm_provider != 'omniroute':
            missing.append("GEMINI_API_KEY")
        if not self.pexels_api_key:
            missing.append("PEXELS_API_KEY")
        return missing


def get_settings() -> Settings:
    """Load and cache settings."""
    return Settings()


# Project Paths
def get_project_root() -> Path:
    """Get project root directory."""
    return Path(__file__).parent.parent


def get_app_dir() -> Path:
    """Get app directory."""
    return get_project_root() / "app"


def get_jobs_dir() -> Path:
    """Get jobs directory."""
    return get_project_root() / "jobs"


def get_media_dir() -> Path:
    """Get media directory."""
    return get_project_root() / "media"


def get_output_dir() -> Path:
    """Get output directory."""
    return get_project_root() / "output"


def ensure_directories() -> None:
    """Create required directories if they don't exist."""
    for directory in [get_jobs_dir(), get_media_dir(), get_output_dir()]:
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "videos").mkdir(exist_ok=True)
        (directory / "images").mkdir(exist_ok=True)
        (directory / "music").mkdir(exist_ok=True)
        (directory / "thumbnails").mkdir(exist_ok=True)
