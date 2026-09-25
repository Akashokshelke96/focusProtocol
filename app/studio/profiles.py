"""Validated, reusable channel and content profiles; credentials stay server-side."""
from datetime import datetime, time
from pathlib import Path
from zoneinfo import ZoneInfo
from pydantic import BaseModel, Field, field_validator


class ContentProfile(BaseModel):
    id: str
    name: str
    niche: str
    listening_intent: str
    genres: list[str]
    visual_prompt: str
    title_pattern: str = '{concept} | {minutes} Min {niche}'
    description_pattern: str = '{concept}. {minutes} minutes of {niche} for {intent}.\n\nSubscribe to {channel} for more sessions.'
    tags: list[str] = []
    category: str = '10'
    preferred_keywords: list[str] = Field(default_factory=list, max_length=20)
    editorial_voice: str = 'Atmospheric, specific, mature and natural; clear search intent without keyword stuffing'
    avoid_phrases: list[str] = Field(default_factory=list, max_length=30)


DEFAULT_PROFILES = [
    ContentProfile(id='blues', name='Camping With Blues', niche='Slow Whiskey Blues', listening_intent='late-night relaxation, reading and reflection', genres=['slow blues', 'whiskey blues'], visual_prompt='Vintage monochrome blues lounge, soulful fictional guitarist on the right, antique microphone, smoky amber light, dark negative space on the left, original cinematic photograph, no text or logos', tags=['whiskey blues', 'slow blues', 'blues guitar', 'late night blues']),
    ContentProfile(id='jazz', name='Cinematic Jazz', niche='Instrumental Jazz', listening_intent='focus, reading and quiet evenings', genres=['smooth jazz', 'lounge'], visual_prompt='Warm cinematic lounge, amber lamps, elegant interiors, atmospheric night lighting', tags=['smooth jazz', 'instrumental jazz', 'focus music', 'relaxing jazz']),
    ContentProfile(id='dreamy', name='Dreamy Music', niche='Dreamy Music', listening_intent='unwinding and late-night listening', genres=['dream pop', 'ambient'], visual_prompt='Dreamlike pastel night sky, soft rose light, serene bedroom, cinematic composition', tags=['dreamy music', 'chill music', 'night playlist']),
    ContentProfile(id='bollywood', name='Bollywood', niche='Bollywood Music', listening_intent='relaxing and enjoying Indian melodies', genres=['Bollywood', 'Indian instrumental'], visual_prompt='Elegant Indian courtyard, warm lanterns, cinematic monsoon evening', tags=['Bollywood music', 'Indian melodies', 'Hindi music']),
    ContentProfile(id='study', name='Deep Study', niche='Study Music', listening_intent='deep work, studying and concentration', genres=['ambient', 'minimal piano'], visual_prompt='Quiet minimalist study room, soft daylight, books, peaceful cinematic composition', tags=['study music', 'concentration music', 'deep work']),
]

THEMES = {
    'cinematic': {'name': 'Cinematic Jazz', 'waveform_height_ratio': .03, 'waveform_width_ratio': .50, 'waveform_opacity': .9, 'waveform_color': '0x000000'},
    'dreamy': {'name': 'Dreamy', 'waveform_height_ratio': .025, 'waveform_width_ratio': .42, 'waveform_opacity': .9, 'waveform_color': '0x000000'},
    'minimal': {'name': 'Minimal', 'waveform_height_ratio': .02, 'waveform_width_ratio': .4, 'waveform_opacity': .9, 'waveform_color': '0x000000'},
    'lounge': {'name': 'Dark Lounge', 'waveform_height_ratio': .025, 'waveform_width_ratio': .45, 'waveform_opacity': .9, 'waveform_color': '0x000000'},
}
PRESETS = {
    'configured': {},
    'preview': {'video_width': 1920, 'video_height': 1080},
    'balanced': {'video_width': 1920, 'video_height': 1080},
}


class Channel(BaseModel):
    id: str = Field(pattern=r'^[a-z0-9_-]{1,64}$')
    name: str = Field(min_length=1, max_length=80)
    profile_id: str = 'blues'
    youtube_channel_id: str = ''
    youtube_account: str = ''
    timezone: str = 'Asia/Kolkata'
    videos_per_day: int = Field(default=2, ge=1, le=24)
    upload_times: list[str] = ['09:00', '18:00']
    theme: str = 'cinematic'
    visualizer_enabled: bool = True
    waveform_style: str = Field(default='linear', pattern='^(linear|circular)$')
    song_panel_enabled: bool = False
    visual_effect: str = Field(default='old_film', pattern='^(none|old_film|vintage|warm_film|faded_film|noir|sepia|cool_cinematic|film_grain|soft_vignette)$')
    visual_effect_opacity: float = Field(default=.06, ge=0, le=.3)
    motion_mode: str = Field(default='drift', pattern='^(static|drift)$')
    render_preset: str = 'configured'
    duration_minutes: int = Field(default=90, ge=1, le=180)
    music_dir: str = 'music'
    background_dir: str = 'backgroundImages'
    thumbnail_dir: str = 'thumbnail'
    watermark_path: str = 'watermark'
    output_dir: str = 'jobs'
    ui_palette: str = Field(default='forest', pattern='^(forest|midnight|plum|ember)$')
    thumbnail_style: str = 'branded'
    thumbnail_color: str = '#E8C990'
    watermark_enabled: bool = True
    subscribe_enabled: bool = False  # Preserve old channel defaults.
    subscribe_overlay_interval_seconds: int = Field(default=180, ge=1)
    subscribe_overlay_width_ratio: float = Field(default=.17, gt=0, le=.5)
    subscribe_overlay_file: str = ''
    auto_generate: bool = False
    auto_publish: bool = False
    daily_target: int = Field(default=2, ge=1, le=20)
    backlog_limit: int = Field(default=6, ge=1, le=50)

    @field_validator('timezone')
    @classmethod
    def valid_zone(cls, value):
        ZoneInfo(value)
        return value

    @field_validator('upload_times')
    @classmethod
    def valid_times(cls, values):
        for value in values:
            if time.fromisoformat(value).tzinfo:
                raise ValueError('Use local clock times without an offset')
        if len(set(values)) != len(values):
            raise ValueError('Upload times must be distinct')
        return sorted(values)

    @field_validator('music_dir', 'background_dir', 'thumbnail_dir', 'watermark_path', 'output_dir')
    @classmethod
    def local_folder(cls, value):
        root = Path.cwd().resolve()
        path = (root / value).resolve()
        if not path.is_relative_to(root) or any(part.startswith('.') for part in path.relative_to(root).parts):
            raise ValueError('Choose a media folder inside this project')
        return str(path.relative_to(root))


def channel_settings(settings, channel):
    result = settings.model_copy(deep=True)
    result.youtube_timezone = channel['timezone']
    result.youtube_videos_per_day = channel['videos_per_day']
    result.youtube_schedule_times = ','.join(channel['upload_times'])
    result.youtube_auto_schedule_enabled = True
    if channel['id'] != 'focus-protocol':
        result.youtube_token_file = str(Path('jobs/studio/credentials') / channel['id'] / 'token.json')
        result.youtube_client_id = ''
        result.youtube_client_secret = ''
        result.youtube_client_secrets_file = str(Path('jobs/studio/credentials') / channel['id'] / 'client_secrets.json')
    else:
        credentials = Path('jobs/studio/credentials/focus-protocol/client_secrets.json')
        if credentials.is_file():
            result.youtube_client_secrets_file = str(credentials)
    return result


def metadata_for(profile, channel, concept, minutes):
    values = dict(concept=concept, minutes=minutes, niche=profile['niche'], intent=profile['listening_intent'], channel=channel['name'])
    title = profile['title_pattern'].format(**values).replace('<', '').replace('>', '')[:100]
    description = profile['description_pattern'].format(**values).replace('<', '').replace('>', '')[:1200]
    return dict(youtube_title=title, youtube_description=description, youtube_tags=profile['tags'][:12],
                thumbnail_text=' '.join(concept.split()[:4]), category=profile['category'], metadata_source='content_profile')
