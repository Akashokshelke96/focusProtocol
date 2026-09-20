# Local production pipeline — September 13, 2026

The studio keeps the existing Flask/SQLite/JSON/FFmpeg architecture. `settings.py` remains the configuration owner; `long_form_jazz_orchestrator.py` owns job execution; `service.py` coordinates content, QC, and publishing. New helpers isolate media history, crossfaded audio assembly, generated-file handling, and encoder progress. There is no new media framework or parallel render pool.

## Current behavior

- Full 1920×1080, 15 FPS, square pixels, H.264/yuv420p and copied final AAC audio. Backgrounds are fitted once with Lanczos without stretching, then FFmpeg loops the decoded frame. The optional subtle atmosphere filter and waveform remain animated.
- `VIDEO_ENCODER=auto` performs a real three-frame encode at the configured resolution: NVIDIA NVENC, AMD AMF, Intel QSV, then CPU. A runtime GPU failure retries once using CPU. NVENC uses VBR/CQ 18, AMF uses CQP 18, QSV uses global quality 18. CPU uses ultrafast/CRF 20. These are high-quality lossy settings, not a lossless guarantee; encoder quality scales are not identical.
- Real FFmpeg progress is persisted every five seconds in `render_progress.json`, with render logs in the job folder and progress shown in the video detail view. The deadline is `max(3600, duration_seconds * RENDER_TIMEOUT_MULTIPLIER + 600)`. Default multiplier 4 gives a 90-minute job 22,200 seconds, rather than the old one-hour limit. A 300-second frame-progress stall fails early with the FFmpeg error tail. Faststart gets a bounded finalization allowance.
- Waveform visual height is 30% of the frame, three times the previous 10% setting. Bars default to three pixels, with faster attack, slower release, a configurable 6% minimum visual amplitude, and a quiet contrast outline. The baseline is a visual floor, not a claim that silence contains sound. The actual audio amplitude still drives movement. Linear and circular styles share the same implementation; the full-size PNG preview is separate from playback controls.
- Background and thumbnail generation is entirely local. The active orchestrator never calls Colab or Pollinations, even with stale enabled flags. Backgrounds come from `backgroundImages`, with the configured `thumbnail` folder as fallback; optional thumbnail source images rotate independently. When no suitable thumbnail source exists, the chosen background supplies the final artwork.
- Images are selected unused-first, then least-recently-used, with content fingerprints and history in `jobs/media_usage.json`. The immediately preceding image cannot repeat; a one-image exhausted pool produces an actionable error. Corrupt, blank, washed-out, portrait, undersized and badly proportioned backgrounds are rejected. Background minimum is 1920×1080; dedicated thumbnail sources minimum is 1280×720. Technical validation cannot judge whether a scene aesthetically fits blues; curate permanent libraries accordingly.
- Music is shuffled with preference for least recently used sources. Decoded audio fingerprints prevent renamed identical copies from bypassing the maximum of two uses per video. Adjacent repeats are prohibited. Four-second crossfades are configurable between three and five seconds. Audio is decoded sequentially and crossfaded with bounded memory, then encoded once. If the library cannot reach the requested duration, the achievable duration controls all stages, with a warning in logs and the video detail view. No indefinite looping is used in the active path.
- The one canonical artwork is `thumbnail/thumbnail.png`. Job metadata, the studio preview, and the publishing queue use the same file. Editing replaces it atomically, marks remote artwork for retry, and removes legacy `studio_thumbnail.jpg`/`thumbnail.jpg` variants. No duplicate studio-specific thumbnail is created.
- Final names include channel, persistent episode number and rounded actual minutes, for example `bourbon_with_blues_ep_04_1min.mp4`. Exact measured seconds, title and episode also remain in metadata. Episode reservations survive restart and gaps are intentional when a job fails after reservation.
- Existing Camping With Blues branding, optional twelve editorial session titles, top-right play icon/name, atmosphere controls, automated QC and separate YouTube upload/processing/scheduled/published indicators remain available. Internal channel IDs and OAuth associations remain stable.

## Cleanup and controls

Successful QC triggers removal of known audio/render/CTA intermediates and redundant copied local backgrounds. Final video, canonical thumbnail, manifests, QC, small waveform preview and useful render logs remain. Permanent library files are never removed. A cleanup failure is recorded without invalidating a playable completed video.

The library has validated music/image import controls: up to 20 files and 512 MB per request. Existing files are never overwritten; duplicates are detected and name collisions receive a content suffix. Failed imports show individual reasons.

Publishing has **Clear All Generated Videos**; each video has **Delete local video**. Both first show exact file paths and sizes. Confirmation is tied to the current file list; stale/missing confirmation is rejected. Only direct generated job directories with manifests qualify. Active jobs, source-library overlaps, symlinks and Windows junctions block deletion. Stale registry entries whose folders are already missing are listed separately in the confirmation and can be cleared without blocking the valid jobs. The existing JSON store records deletion tombstones so SQLite history cannot resurrect removed jobs. YouTube videos are unaffected.

## Verification

Commands used:

```powershell
.venv/Scripts/python.exe -m py_compile app/config/settings.py app/pipeline/long_form_jazz_orchestrator.py app/api/jazz_api.py app/video/encoding.py app/video/waveform.py app/studio/api.py app/studio/assets.py app/studio/artifacts.py app/studio/import_media.py app/studio/service.py app/providers/media_history.py app/audio/local_timeline.py
.venv/Scripts/python.exe -m pytest tests -q
node --check static/studio.js
node tests/studio_publishing_ui.cjs
```

Acceptance results:

| Job | Actual duration | Resolution / FPS | Encoder | QC | Lifecycle |
| --- | --- | --- | --- | --- | --- |
| `painted_soul_short_20260913` | 59.917 s | 1920×1080 / 24 | CPU x264 | Pass | 110.689 s |
| `painted_soul_long_verified_20260913` | 599.917 s | 1920×1080 / 24 | CPU x264 | Pass | 564.940 s |
| `speed_short_20260913` | 59.933 s | 1920×1080 / 15 | AMD AMF | 18/18 pass | 95.338 s |
| `speed_long_20260913` | 599.933 s | 1920×1080 / 15 | AMD AMF | 18/18 pass | 400.148 s |
| `speed_final_20260913` | 59.933 s | 1920×1080 / 15 | AMD AMF, two filter threads | 18/18 pass | 83.578 s |

All files contain one H.264/yuv420p video stream and one AAC audio stream. The updated ten-minute run uses four sources, a different background from the preceding run, one canonical thumbnail, and passed beginning/middle/end decoding. It removed 29,312,652 bytes of redundant intermediates after QC, in addition to its temporary waveform video. Test jobs are excluded from publishing; Clear All's exact confirmation also includes their generated files.

The final active-suite run passed **77 tests in 7.97 seconds**. Python compilation, JavaScript syntax and UI handler checks passed. Tests cover real FFmpeg crossfades, duplicate music, persisted rotation, invalid media, API import, thumbnail bytes shared with publishing, deletion confirmation/source protection, cleanup, encoder fallback, real FFmpeg progress, injected stalls and immediate encoding failures. UI tests exercise rendering and action handlers without a browser. A focused five-second check of the same FFmpeg filter graph took 5.45 seconds with default filter threads and 2.95 seconds with two threads; the final one-minute pipeline validated this setting. Timings vary with scene, waveform style and machine load.

A full 90-minute output was **not** rendered in this session. The complete pipeline was exercised at one and ten minutes; the 90-minute timeout calculation and watchdog behavior were tested independently. No unmeasured 90-minute speed guarantee is made.

Unscoped `pytest -q` also collects the separate `OpenMontage` tree and obsolete root scripts. That command stops during collection on duplicate `tests.conftest` and missing legacy `librosa`; the active project's `tests` suite is the supported validation scope.

The installed browser tool references a missing browser-service runtime file, so a live browser walkthrough could not be completed. No test video was uploaded to YouTube; publishing tests mock remote calls. The configured LLM endpoint at localhost:8787 is offline, so acceptance runs used recorded local title fallback. Image APIs are intentionally disabled. The installed FFmpeg rejected NVIDIA encoding because its NVENC API requirement exceeds the installed driver; AMD hardware encoding succeeded. No driver change is required to use AMD automatic selection.

## Files changed for this upgrade

- Configuration: `.env` (public render/image options only), `.env.example`, `app/config/settings.py`, `app/studio/profiles.py`.
- Pipeline and sources: `app/pipeline/long_form_jazz_orchestrator.py`, new `app/providers/media_history.py`, new `app/audio/local_timeline.py`.
- Visuals and encoding: `app/video/waveform.py`, `app/video/branding.py`, new `app/video/encoding.py`.
- Studio and API: `app/api/jazz_api.py`, `app/studio/api.py`, `app/studio/service.py`, `app/studio/assets.py`, new `app/studio/artifacts.py`, new `app/studio/import_media.py`, `static/studio.js`, `static/studio.css`.
- Tests: `tests/test_branding.py`, `tests/studio_publishing_ui.cjs`, new `tests/test_production_hardening.py`, new `tests/test_encoding.py`.
- Documentation: `README.md`, `docs/bourbon-with-blues.md`, this document. Earlier branding/status work is documented in `docs/waveform-youtube-status-upgrade.md`; unrelated pre-existing edits are preserved.

Encoder/progress reference: [FFmpeg command documentation](https://ffmpeg.org/ffmpeg.html), [NVENC encoder source reference](https://www.ffmpeg.org/doxygen/trunk/nvenc__h264_8c.html). Actual availability is verified against the bundled FFmpeg, not inferred from encoder names.

Runtime verification: the studio was started on http://127.0.0.1:5001; dashboard, state and media endpoints returned HTTP 200. A read-only Clear All preview against the current workspace validated 56 generated job/history entries, including 41 already-missing folders; no deletion was executed. The user then started a 20-minute job named `tESTIG`. It was left running without interruption. Restart the studio after that job finishes to load the final stale-history deletion fix into the running process.
