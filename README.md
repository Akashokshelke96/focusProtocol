# YouTube Automation Engine

The active local music-video pipeline is documented in [Production hardening and render settings](docs/production-hardening.md) and [Camping With Blues branding](docs/bourbon-with-blues.md). These documents supersede the legacy topic/narration workflow below for the studio.

Generate professional YouTube videos automatically from topics using Gemini LLM, Pexels, Pinterest, AceMusic, and FFmpeg.

## Features

- **AI-Powered Content**: Gemini generates scripts, scene plans, and metadata
- **Stock Footage Integration**: Pexels for videos, Pinterest for images
- **Background Music**: AceMusic music generation and library management
- **Professional Output**: Ken Burns motion, captions, smooth transitions
- **Resumable Jobs**: Save and resume interrupted generations
- **Metadata Generation**: YouTube titles, descriptions, tags, thumbnails

## Architecture

```
Content Generation → Scene Planning → Media Sourcing → Audio Mix
        ↓                   ↓              ↓              ↓
    Gemini LLM      Visual Intent    Pexels/Pinterest  AceMusic
                                           ↓
                                    Validation & Dedup
                                           ↓
Timeline Build → Motion & Transitions → Captions → FFmpeg Render
     ↓                  ↓                  ↓            ↓
Calendar          Ken Burns         SRT Format      H.264 + AAC
                  Crossfade
                                           ↓
                              Metadata & Thumbnail
                                           ↓
                                  Final MP4 + JSON
```

## Requirements

- Python 3.10+
- FFmpeg and FFprobe
- API Keys:
  - Gemini API (required)
  - Pexels API (required)
  - AceMusic API (optional)
  - YouTube OAuth credentials (for upload only)

## Installation

### 1. Clone and setup

```bash
cd youtube_automation
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Install FFmpeg

**Windows**:
```bash
# Using Chocolatey
choco install ffmpeg

# Or download from https://ffmpeg.org/download.html
```

**macOS**:
```bash
brew install ffmpeg
```

**Linux (Ubuntu)**:
```bash
sudo apt-get install ffmpeg
```

### 3. Configure environment

```bash
cp .env.example .env
# Edit .env with your API keys
```

Get API keys:
- **Gemini API**: https://makersuite.google.com/app/apikey
- **Pexels API**: https://www.pexels.com/api/
- **AceMusic API**: https://acemusic.io/api

## Configuration

Edit `.env`:

```env
# Required
GEMINI_API_KEY=your_key_here
PEXELS_API_KEY=your_key_here

# Optional
ACEMUSIC_API_KEY=your_key_here
PINTEREST_ENABLED=true

# Video Settings
VIDEO_WIDTH=1920
VIDEO_HEIGHT=1080
VIDEO_FPS=30

# Duration
DEFAULT_VIDEO_DURATION_MINUTES=10
TEST_VIDEO_DURATION_MINUTES=3

# Captions
CAPTIONS_ENABLED=true
CAPTION_MAX_WORDS=5

# Audio
MUSIC_VOLUME=0.15
NARRATION_VOLUME=1.0

# YouTube (disable for testing)
YOUTUBE_UPLOAD_ENABLED=false
```

## Usage

### Generate a video

```bash
python main.py generate --topic "The Psychology of Procrastination"
```

With options:
```bash
python main.py generate \
  --topic "How Discipline Changes Your Life" \
  --duration 10 \
  --style "Documentary" \
  --tone "Serious and educational"
```

### Test mode (3 minutes)

```bash
python main.py generate --topic "Test Topic" --test
```

### List jobs

```bash
python main.py list-jobs --limit 20
```

### Resume a job

```bash
python main.py resume JOB_ID_HERE
```

### Validate job output

```bash
python main.py validate JOB_ID_HERE
```

## Project Structure

```
youtube_automation/
├── app/
│   ├── config/              # Configuration, settings, prompts
│   ├── llm/                 # Gemini LLM provider
│   ├── providers/           # Pexels, Pinterest, AceMusic
│   ├── content/             # Content & scene generation
│   ├── media/               # Validation, deduplication
│   ├── audio/               # Mixing, normalization
│   ├── video/               # Timeline, motion, captions, renderer
│   ├── youtube/             # YouTube upload
│   ├── jobs/                # Job management & state
│   └── pipeline/            # Central orchestrator
├── jobs/                    # Job storage & database
├── media/                   # Downloaded assets
│   ├── videos/
│   ├── images/
│   ├── music/
│   └── thumbnails/
├── output/                  # Final videos
├── tests/                   # Unit tests
├── main.py                  # CLI entry point
├── requirements.txt
├── .env.example
└── README.md
```

## How It Works

### 1. Content Generation

Gemini generates:
- Video title
- Hook (opening 10 seconds)
- Full narration script
- Scene breakdown
- YouTube metadata
- Thumbnail concept

### 2. Scene Planning

Each narration segment gets:
- Visual goal (what should appear)
- Pexels search query (specific and descriptive)
- Pinterest query (for artwork/historical)
- Mood and keywords
- Recommended source (video/image/mixed)

### 3. Media Sourcing

- Search Pexels for video clips
- Filter by resolution, aspect ratio, orientation
- Download and validate
- Detect duplicates (SHA-256 + perceptual hash)
- Fallback to Pinterest for images

### 4. Audio Processing

- Generate background music direction
- Source or generate music tracks
- Mix narration + music
- Apply audio ducking if needed
- Normalize levels

### 5. Video Assembly

- Build timeline from assets
- Apply Ken Burns motion to still images
- Create smooth crossfade transitions
- Generate captions from narration
- Synchronize with audio timing

### 6. Rendering

FFmpeg renders final output:
- H.264 video codec
- AAC audio codec
- 1920x1080, 30fps (configurable)
- Embedded subtitles

### 7. Metadata & Publishing

- Generate YouTube-optimized title
- Create formatted description
- Extract tags and keywords
- Compose thumbnail graphic
- Optional: Upload to YouTube

## First Test

Run a 3-minute test generation:

```bash
python main.py generate --topic "The Psychology of Procrastination" --test
```

This will:
1. Generate content using Gemini ✓
2. Plan scenes ✓
3. Search Pexels ✓
4. Download and validate videos ✓
5. Generate music direction ✓
6. Build timeline ✓
7. Generate captions ✓
8. Create metadata ✓

Output appears in: `output/[JOB_ID]/final.mp4`

## Troubleshooting

### API Keys

```
Error: Missing required API keys: GEMINI_API_KEY, PEXELS_API_KEY
```

**Fix**: Set API keys in `.env` file

### FFmpeg not found

```
FileNotFoundError: ffmpeg not found
```

**Fix**: Install FFmpeg (see Installation section)

### JSON parsing errors

```
Error: Invalid JSON from Gemini
```

**Fix**: Retry with a simpler topic. Gemini sometimes returns malformed JSON.

### Pexels rate limits

```
HTTP 429 Too Many Requests
```

**Fix**: Wait a bit, system implements exponential backoff. Check your Pexels quota.

### No suitable media found

```
Warning: No suitable video file found
```

**Fix**: The search query was too specific. Try a broader topic or different phrasing.

## Testing

Run unit tests:

```bash
python -m pytest tests/ -v
```

Run specific test:

```bash
python -m pytest tests/test_media.py -v
```

## Performance

Typical generation times (10-minute video):

- Content generation: 30-60 seconds
- Scene planning: 20-30 seconds
- Media sourcing: 2-5 minutes (Pexels API calls)
- Audio mixing: 30-60 seconds
- Timeline building: 10-20 seconds
- Captions generation: 5-10 seconds
- Video rendering: 3-10 minutes (FFmpeg)

**Total: ~10-20 minutes per video**

## Limitations

- Pinterest integration requires web scraping (not officially supported)
- AceMusic music generation is mocked (requires actual API integration)
- YouTube upload requires OAuth setup
- Concurrent job generation not yet supported
- Resume functionality planned but not implemented

## Future Enhancements

- [ ] Real Pinterest API or alternative image provider
- [ ] AceMusic integration completion
- [ ] YouTube OAuth and upload flow
- [ ] Concurrent job queue
- [ ] Resume from any stage
- [ ] Advanced image composition
- [ ] Voice-over narration generation
- [ ] Multi-language support
- [ ] Custom music library management
- [ ] Advanced color grading

## Development

### Add a new provider

1. Create new class in `app/providers/`
2. Inherit from `VideoProvider` or `ImageProvider`
3. Implement `search()` and `download()` methods
4. Register in orchestrator

### Add a new stage

1. Create new module in `app/`
2. Implement stage logic
3. Update `app/pipeline/orchestrator.py`
4. Add `JobStage` enum value

### Running in debug mode

```bash
DEBUG=true python main.py generate --topic "Debug Test" --test
```

## License

MIT License

## Support

For issues, feature requests, or questions:

1. Check the Troubleshooting section
2. Review logs in `jobs/app_*.log`
3. Check job state: `python main.py list-jobs`

## Contributing

Pull requests welcome. Please:

1. Test changes thoroughly
2. Run `pytest` before submitting
3. Follow existing code style
4. Document significant changes
