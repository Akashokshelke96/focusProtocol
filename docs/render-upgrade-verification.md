# Render upgrade verification — 20 September 2026

Implemented the top-right YouTube icon, cached media discovery/probes, hidden subprocesses, three quality presets, and an eight-minute subscribe cycle. Final loop and mux commands remain stream-copy, with no filters or additional inputs.

## Architecture and behavior

- `loop_branding()` draws a red rounded play icon before the top-right channel text. Its height matches the font's H cap-height. Combined icon + gap + text width determines positioning. The 1080p top/right margins remain 25 pixels; lower resolutions scale the entire branding proportionally. Bottom-right branding is text-only. Metadata records combined, text, and icon bounds. Pixel tests passed at all three sizes.
- Static backgrounds encode a single six-second clip rather than ten identical waveform cycles. Moving/drifting backgrounds retain the existing sixty-second cycle. This is the main video performance improvement; it does not change FPS or encoding quality.
- Subscribe uses option (c): encode a six-second variant with a four-second fading card, then concatenate packet copies into a 480-second cycle. Static backgrounds need only twelve seconds of total encoded video (six normal + six reminder). For a sixty-second moving background, a keyframe-aligned copy supplies the normal 54-second tail. Explicit six-second keyframes make that split reliable. No full-duration encoding is introduced.
- Subscribe appears at 0–4s, 480–484s, 960–964s, etc., bottom-right above the existing text mark. It respects `SUBSCRIBE_OVERLAY_ENABLED`. The bottom-left waveform and top-right branding remain. Sidecar overlays were rejected because they would not be burned into the uploaded MP4; encoding all 480 seconds was unnecessarily expensive.
- `QUALITY_PRESET` accepts 480p, 720p, 1080p. Dashboard request -> API validation -> settings -> renderer/branding/visualizer is tested. Default is 1080p. Old settings without an explicit preset retain their existing dimensions/quality; job snapshots now also include preset and audio bitrate. Existing job resume restores its saved settings.
- The preset sets CPU preset `ultrafast`; NVENC retains its established `p4` hardware preset. `yuv420p` and `+faststart` are retained.

## Profile: real three-minute jobs

Task 2 measurements use unchanged 1920x1080, 15 FPS, CRF 20, NVENC CQ 18, and 320 kbps AAC. The baseline preparation ran first; a helper-import error during concurrent editing required finishing that same job with resume. Therefore the baseline numbers below are separately measured stages, not an uninterrupted total. The after job completed in 67.19 seconds. Inputs were selected by the normal media rotation; this is not a controlled identical-input microbenchmark.

| Stage | Baseline seconds | After seconds |
|---|---:|---:|
| Music discovery/selection | 98.754 | 0.808 |
| Audio assembly + verification | 15.485 | 18.136 |
| Silence scan within assembly | 0.310 | 0.382 |
| Artwork preparation | 12.922 | 13.427 |
| Short-clip encode | 71.196 | 11.232 |
| Packet-copy loop | 1.455 | 3.598 |
| Packet-copy mux | 0.928 | 2.438 |
| Output validation | 0.241 | 0.200 |
| QC | 2.933 | 1.754 |
| Music fingerprinting (nested in discovery) | 0.114 | 0.099 |

Discovery was probing 253 valid tracks on every job. Durations now persist in `jobs/music_duration_cache.json`, invalidated by path, size, modification time and creation time. The after measurement uses a warm cache; first discovery and changed files still require probes. General validation probes have a bounded in-process stat-keyed cache. Encoder selection caches successful probes for five minutes and clears on render failure.

Silence removal already scans in bounded chunks. Its clean-track exit was reached, but copied the entire PCM unnecessarily; the caller now uses that original PCM directly. Audio parallel decoding was not introduced: the measured bottlenecks were discovery and repeated short-clip encoding, and additional decode processes would increase memory/disk pressure for little demonstrated gain. Crossfades, fades, sample rate, channels and target duration are unchanged.

QC still checks hashes, stream properties, duration and three input-seeked decode samples. No QC gate was removed. Artwork SHA passes were under 0.15 seconds per job; fingerprinting already caches unchanged sources. The video fingerprint at the end of QC is a stat tuple, not a full MP4 SHA scan.

Baseline short-encode monitoring: 548 MB average / 584 MB peak FFmpeg RAM; 69% average host CPU, 108 MB observed VRAM. `pressure_throttled=false`; it was bounded to the configured two cores, not throttled to one. The optimized job also reported no pressure throttling. Timing differences in copy/mux reflect host load/I/O; those commands remain copies.

## Quality and file size

All three below reuse the same real background and 180-second audio master, include the new branding, waveform and subscribe, and pass existing stream/duration/QC checks. Audio was converted to each preset bitrate for comparison. Original source images and thumbnails passed SHA verification.

| Preset | Dimensions | CRF / NVENC CQ | Audio | MP4 size (decimal MB) | Render seconds |
|---|---|---|---|---:|---:|
| 1080p | 1920x1080 | 23 / 23 | 192k | 19.46 | 22.296 |
| 720p | 1280x720 | 23 / 23 | 160k | 12.45 | 20.795 |
| 480p | 854x480 | 24 / 24 | 128k | 7.95 | 18.628 |

The same-source baseline was 50.00 MB at CQ 18 / 320k audio: the new 1080p file is about 61% smaller. This is a three-minute sample, not a guarantee of a particular size for all 45-minute videos. Inspected actual decoded frames at all three sizes. The icon and lettering remain legible; the 1080p sample shows no obvious new compression artifacts. Lower resolutions naturally retain less fine detail. These are visual checks, not a VMAF or lossless-quality claim.

## Final full-pipeline acceptance

Job: `20260920_121333_064977_video_001`.

- Full 180-second production generation: 61.779 seconds, including audio, artwork sourcing, encoding, validation, QC and finalization.
- 1920x1080 at 15 FPS, NVENC CQ 23, 192k AAC; final file 19.76 MB.
- Render 19.321 seconds: normal clip 10.008, subscribe build 5.844, loop 0.864, mux 1.095.
- All 27 observed subprocess calls explicitly used `CREATE_NO_WINDOW`. This is a creation-flag audit, not observation of the user's Windows desktop. The shared helper covers FFmpeg/FFprobe, audio, legacy waveform, resource sampling, and QC. The imageio package's extra version/platform subprocesses were removed in favor of our existing real encoder probe.
- Actual beginning/middle/end frames were inspected; waveform and top-right icon remain visible, and the subscribe card disappears after its window.
- A separate 970-second, packet-copy-only cadence artifact verifies reminders at 1, 481 and 961 seconds and absence at 5, 479, 485, 959 and 965 seconds. Red card pixel counts are 20,979 when visible and zero when absent. No reminder at 61 or 121 seconds in the three-minute preset renders.
- All acceptance artifacts are local, excluded from publishing.

## Evidence

- `jobs/upgrade_baseline.json`, `jobs/upgrade_baseline_finish.json`, `jobs/upgrade_optimized.json`, `jobs/upgrade_final.json`.
- `jobs/upgrade_presets.json` and `jobs/upgrade_preset_{1080p,720p,480p}/metadata.json`.
- Commands saved under each output folder: `render_commands.json`, `subscribe_commands.json`.
- `jobs/upgrade_preset_1080p/cadence_contact_sheet.png` and `cadence_verification.json`.
- `jobs/20260920_121333_064977_video_001/verification_contact_sheet.jpg`.
- Focused tests: 47 passed. Broader production-hardening checks exposed an existing unrelated failure in `test_corrupt_music_skipped_and_empty_library_reported`: `media_history.rotate()` trusts caller-provided durations and the test feeds a corrupt file with a valid duration. That function was unchanged by this task. No unrelated music-selection behavior was changed to mask the failure.

No 45-minute rerender or Windows desktop observation was performed. Existing long-duration copy architecture, thumbnails, upload logic and job state handling are preserved. Quality settings changed only in Task 4 after the unchanged-quality performance comparison.

A separate 480p three-minute drift render also passed output validation with the original 60-second movement cycle. Short encode: 44.313s; six-second reminder plus keyframe-aligned 54-second tail/cycle build: 3.578s. This verifies the alternative path used by moving backgrounds without changing their existing motion period.

The requested jazz dashboard is served at `/legacy` (the root URL is the Studio dashboard). Its live page exposes the new selector. The existing Flask process was already running and is owned by another Windows security context; it was not restarted. Restart that process to load the new backend Python modules before generating through the live app.
