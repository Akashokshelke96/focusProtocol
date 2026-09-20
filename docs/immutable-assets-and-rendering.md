# Immutable artwork and bounded 1080p rendering

## Asset contract

The active long-form orchestrator assigns exactly one validated random background and one validated random thumbnail from the existing channel `background_dir` and `thumbnail_dir` settings (legacy defaults: `backgroundImages` and `thumbnail`). It never falls back between these folders and never calls image generation. Image prompt reservations are no longer consumed by local jobs.

`prompt_assets.json` persists both assignments before any copies or expensive work. `metadata.json` and the existing job state carry `assets.background` and `assets.thumbnail`, each containing the original filename, absolute source path, job copy path, and SHA-256. Copies preserve bytes and file extensions. Missing or altered assigned files produce an explicit error instead of random reassignment. An interrupted initial copy can resume from its saved assignments.

The renderer reads the assigned background directly. Scaling/cropping for the video happens in FFmpeg, before the still-frame loop. No `render_background.png` or branded replacement thumbnail is created. The source-image branding operation and thumbnail-edit endpoint are disabled in normal production. Historical image/thumbnail helpers remain for compatibility but are not called by the active workflow.

QC checks asset integrity. The preview route and publishing queue prefer the assigned thumbnail over stale historical thumbnail paths. Upload finalization verifies integrity before sending the same file. The detail page shows original filenames. Thumbnail editing controls are removed.

## Rendering

Production rejects dimensions other than 1920x1080. Legacy preview/balanced preset names remain valid but no longer force lower resolution, FPS, or quality. Configured FPS and quality remain authoritative.

The existing actual-encode probe selects a working NVENC backend. The local GTX 1650 has 4096 MiB VRAM, driver 592.82; nvidia-smi reports CUDA compatibility 13.1 (this does not imply the CUDA toolkit is installed). The packaged FFmpeg 7.1 backend successfully initializes h264_nvenc. No quality-reducing CPU fallback is attempted after a running GPU encode fails.

`RENDER_MAX_CONCURRENT=1` bounds native renders with cross-process file locks. Existing batch production remains serial. Waiting renders check cancellation, free slots, host RAM pressure, and GPU temperature. Existing CPU affinity/priority limits, progress watchdog, telemetry, and temperature/memory protection remain active.

`WAVEFORM_ANIMATED=false` defaults to one transparent PNG derived from RMS windows over the final audio, using bounded PCM chunks. Linear and circular styles remain available. Set `WAVEFORM_ANIMATED=true` to use the existing animated implementation; it costs more preparation time. For static compositions, FFmpeg caches the composed frame before timed effects and fades. No lower-resolution video or image-file alteration is used for optimization.

Completed jobs retain assigned artwork and final audio for retry. Existing cleanup removes only known redundant intermediates. No automatic recursive deletion was added.

## Recovery and segment decision

Assignments survive early failures. Retries with saved audio reuse it; retries after a successful encode can repeat validation/finalization without encoding again. A failure during encoding still restarts that encode. Segmented encoding was not introduced: dynamic effects, waveform timing, and fades would require a larger timestamp/concat change. The single-pass static cache has bounded memory and avoids adding a second rendering pipeline. Mid-encode checkpoint recovery remains a limitation.

## Acceptance and limitations

- Tests exercise byte identity, invalid-image rejection, assignment reuse, interrupted copies, tamper detection, canonical preview routing, queue cancellation, and render capacity, plus the existing regression suite.
- A real ten-minute full pipeline generated 600-second 1920x1080/30 FPS NVENC video with the animated visualizer and existing atmosphere effect. Both source/copy hashes match. All media QC checks pass; thumbnail upload eligibility fails because the original is 2,680,100 bytes.
- Screenshot `jobs/immutable_detail.png` verifies assigned filenames, original release artwork, video poster, and QC on the real detail page. An isolated headless Chrome instance was used after the bundled browser connector failed to initialize. No publication was performed.
- The local LLM endpoint on port 8787 was unavailable; the existing metadata fallback was used.
- Every current original in `thumbnail` exceeds the YouTube Data API's documented 2 MB upload cap (smallest: 2,462,962 bytes). The application preserves the originals and flags this explicitly. Upload-ready originals must be supplied to the configured folder for new jobs; automatic compression is intentionally absent.

API reference: https://developers.google.com/youtube/v3/docs/thumbnails/set

The 90-minute static-profile result and telemetry are written to `jobs/immutable_90min_acceptance/acceptance.json` when validation finishes. This profile uses 1080p/30 FPS, NVENC quality 18, static RMS waveform, no atmosphere filter, and no subscribe animation. Its timing is not an apples-to-apples comparison with the animated/atmosphere ten-minute profile.

## Completed 90-minute result

The full 5,400-second static-profile MP4 passed stream/dimension/FPS/duration validation and decode samples at the beginning, middle and end. NVENC rendering took 473.572 seconds. Source and job-copy SHA-256 hashes match for both assets. Only the original thumbnail upload-size check fails.

```json
{
  "samples": 88,
  "cpu_limited": true,
  "pressure_throttled": false,
  "cpu_percent": {
    "average": 41.77,
    "peak": 73.0
  },
  "ram_percent": {
    "average": 85.85,
    "peak": 87.3
  },
  "process_cpu_percent": {
    "average": 86.42,
    "peak": 101.9
  },
  "process_ram_mb": {
    "average": 391.02,
    "peak": 404
  },
  "gpu_utilization": {
    "average": 27.36,
    "peak": 30.0
  },
  "gpu_vram_mb": {
    "average": 493.0,
    "peak": 493.0
  },
  "gpu_temperature_c": {
    "average": 50.08,
    "peak": 51.0
  }
}
```

The ten-minute job was also retried: assigned assets and video modification time remained unchanged, proving finalization reused the saved render. All temporary browser profiles and local verification servers were stopped/removed after the screenshot check.

Final regression run: 102 passed, 1 skipped. Python compilation and JavaScript syntax/UI component checks passed.
