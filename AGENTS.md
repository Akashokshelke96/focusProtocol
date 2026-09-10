# Coding Agent Guide

## Project Goal

This project generates long-form Focus Protocol jazz videos from local music, a single static background image, and FFmpeg. Preserve the working pipeline and make narrow, evidence-based changes.

## Current Architecture

- `app/config/settings.py`: Pydantic settings loaded from `.env`. It is the authoritative source for video dimensions, FPS, CRF, preset, target duration, audio looping, waveform, image API, and YouTube settings.
- `app/pipeline/long_form_jazz_orchestrator.py`: active long-form pipeline and job coordinator.
- `app/providers/local_music.py`: discovers local audio, probes duration, and crossfades the selected base tracks.
- `app/providers/local_background.py`: validates the single selected background image.
- `colab_image_service.py`: calls the configured Google Colab image API.
- `app/video/timeline.py`: stores the one-image timeline clip. Do not reintroduce motion or multiple image clips.
- `app/jobs/manager.py`: persists job stage, status, timestamps, error, and JSON metadata in SQLite.
- `app/api/jazz_api.py`: Flask API for generation, job history, status, live logs, component health, OAuth, and upload.
- `templates/jazz_dashboard.html`: existing dashboard UI and polling workflow.
- `app/config/logging_config.py`: console/file logging plus recent events exposed to the UI.

## Active Pipeline

```text
Job creation
  -> prompt reservation
  -> Colab background/thumbnail attempt
  -> explicit image fallback if needed
  -> select 3-4 local music source tracks
  -> crossfade one base audio block
  -> loop and trim block to target duration
  -> verify target-length audio
  -> select exactly one background image
  -> build one static timeline clip
  -> FFmpeg static image + audio + optional showwaves waveform
  -> FFprobe stream/dimension/duration validation
  -> metadata and thumbnail persistence
  -> completed or completed_with_fallback job
```

## Duration Rules

`TARGET_DURATION_MINUTES` is the default duration source. The UI/API may pass a per-request duration, which becomes the job's `target_duration_seconds`. That value must control audio looping/trimming, timeline duration, FFmpeg `-t`, waveform duration, and validation.

Never hard-code 90 minutes in active behavior. Existing fallback defaults in compatibility code must not override a job target.

## Audio Rules

Only `AUDIO_LOOP_TRACK_COUNT` tracks are selected, clamped to 2-4. The selected files are crossfaded once into `audio_base_block.aac`, then FFmpeg loops and trims that block into the existing `music/audio_concatenated.aac` output path. The final audio is timestamped through the existing AAC/MP4-compatible output mode so FFprobe reports reliable duration.

Do not restore the old pattern of selecting approximately 30 tracks. Preserve the existing crossfade behavior unless a test demonstrates a defect.

## Image Rules

Try Google Colab first when `COLAB_IMAGE_ENABLED=true` and `COLAB_IMAGE_API_URL` is configured. Validate the returned file. If generation fails, use a validated file from `backgroundImages`, then `thumbnails`. Log the exact reason and mark fallback metadata. Each video must use exactly one background image for its complete duration.

## Rendering Rules

The renderer uses one looped still-image input and one final audio input. Video settings are configurable through `.env`:

```text
VIDEO_WIDTH=1920
VIDEO_HEIGHT=1080
VIDEO_FPS=24
FFMPEG_PRESET=faster
FFMPEG_CRF=25
```

The waveform is generated once as a transparent PNG from the actual final audio stream. FFmpeg outputs mono PCM, Python/NumPy aggregates RMS amplitude into a few hundred windows, lightly smooths and normalizes them, and Pillow draws rounded capsule bars. That PNG is then overlaid on the static background. This avoids per-frame waveform image generation. Its width, height, bottom padding, and color are proportional/configurable:

```text
WAVEFORM_ENABLED=true
WAVEFORM_HEIGHT_RATIO=0.045
WAVEFORM_WIDTH_RATIO=0.50
WAVEFORM_BOTTOM_PADDING_RATIO=0.04
WAVEFORM_COLOR=0xFFFFFF
```

It is horizontally centered, approximately 50% of the video width, and placed within the lower 20 percent of the frame. Bars are deterministic, amplitude-derived, rounded, spaced, and symmetric around the centerline. Do not generate millions of PNG frames or replace FFmpeg with a new media framework.

## Watermark

An optional PNG watermark is discovered from `watermark/*.png`. The first valid PNG is scaled proportionally using `WATERMARK_WIDTH_RATIO`, opacity is controlled by `WATERMARK_OPACITY`, and it is overlaid in the bottom-right with proportional padding. Missing, empty, or invalid watermark directories never fail a render. No AI service is used for watermark handling.

The repository includes `watermark/watermark.png` for the Focus Protocol branding. The watermark is optional and is recorded as `watermark_enabled` in job metadata.

```text
WATERMARK_ENABLED=true
WATERMARK_WIDTH_RATIO=0.10
WATERMARK_RIGHT_PADDING_RATIO=0.02
WATERMARK_BOTTOM_PADDING_RATIO=0.02
WATERMARK_OPACITY=0.75
```

## Job Timing

The orchestrator writes `started_at`, `completed_at`, and `total_elapsed_seconds` to the existing job metadata. The elapsed value covers the full lifecycle from job initialization through validation, metadata, thumbnail, and final completion. Failed jobs also persist an end timestamp and elapsed duration. The dashboard displays this value in progress status, completed previews, and recent-job cards.

## Validation

A valid output must have:

- one video stream and one audio stream
- configured width and height
- target-length video/audio within configured tolerance
- exactly one selected background image
- valid playable MP4 output
- waveform metadata enabled when configured

Use FFprobe and the existing orchestrator validation. Never claim success solely because FFmpeg returned exit code 0.

## Testing

Compile touched Python modules first:

```powershell
python -m py_compile app/config/settings.py app/pipeline/long_form_jazz_orchestrator.py app/api/jazz_api.py
```

Run a real short pipeline through the same code path:

```powershell
$env:TARGET_DURATION_MINUTES="10"
python -c "from app.pipeline.long_form_jazz_orchestrator import LongFormJazzOrchestrator; from app.config.settings import get_settings; print(LongFormJazzOrchestrator(get_settings()).run(video_count=1, duration_minutes=10))"
```

Verify the resulting job's `metadata.json`, `audio/audio_concatenated.aac` equivalent, MP4 streams, duration, resolution, FPS, and validation log. The production path uses the same code with `duration_minutes=90`.

The verified 10-minute acceptance profile used `1280x720`, `15 FPS`, `ultrafast`, and `CRF 28`. Job `20260907_212909_video_001` produced 600.0-second audio and video, one image, waveform metadata, a playable MP4, and `total_elapsed_seconds=71.322`.

The waveform/watermark acceptance profile used `1280x720`, `15 FPS`, `ultrafast`, and `CRF 28`. Job `20260908_015040_video_001` produced 600.0-second audio and video, 160 rounded waveform bars, one static image, the Focus Protocol watermark, a playable MP4, and `total_elapsed_seconds=92.1`. A 1920x1080 short profile smoke test also passed with both overlays enabled.

## Change Discipline

Do not rewrite working services, move folders, rename public files, remove old fallbacks, or introduce another configuration system. Inspect the direct owner of behavior, make the smallest edit, run a focused validation, then run the relevant end-to-end test.
