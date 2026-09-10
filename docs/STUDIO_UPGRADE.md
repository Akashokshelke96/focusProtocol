# Long-form Studio — implementation and verification

The upgraded application runs at **http://localhost:5001/**. Start it with
`Start-YouTube.cmd`. The classic dashboard remains at `/legacy`.

## Delivered

- A responsive, dark studio shell: overview, channels, content, production board,
  media library, publishing, calendar, operations, templates and settings.
- Four editable channel profiles: Focus Protocol, Girls Music, Bollywood and Study Music.
  Focus Protocol is connected. The other channels need their own YouTube connection
  and appropriate local music/background assets before regular production.
- Reusable niche-specific metadata strategies; channel-specific asset folders,
  thumbnails, themes, duration, render presets and daily schedules.
- Content batches from one concept per line. Explicit generation, daily automation,
  backlog limits, publishing priority and pause controls.
- Per-video previews and actions carry the job ID. The original upload URLs now
  feed the same channel-aware queue. Legacy video downloads support range requests.
- Atomic filesystem production/batch state and per-job snapshots. Generation uses
  a process lock and retries individual interrupted items. Successfully rendered
  or uploaded items are preserved across restart.
- Batch publishing with automatic slots, channel isolation, SHA-256 duplicate
  protection, durable remote IDs, remote processing checks and retryable steps.
  A local reservation is visibly distinguished from a YouTube-confirmed schedule.
- QC checks streams, target duration, dimensions, FPS, audio duration, thumbnails,
  metadata, configured waveform and three decode samples. Fallback images require
  review; approvals are tied to file fingerprints.
- Local artwork editing, music previews/assignment, hash inspection, asset usage,
  operational timings, and reviewed cleanup of narrowly allowlisted intermediates.
- Optional FFmpeg-native camera drift over the same single image. The existing
  animated amplitude waveform and cached subscribe overlay remain intact.

## Architecture and state

`app/studio/profiles.py` owns validated channel/content models and render presets.
`store.py` provides atomic, locked JSON transactions. `service.py` coordinates
production, QC, durable publishing batches and recovery. `api.py` exposes local
operations and constrained media routes. `assets.py` creates branded artwork and QC.

The existing `LongFormJazzOrchestrator` still owns music selection/crossfades,
looping/trimming, the single-image timeline, FFmpeg rendering and output validation.
It accepts a job context and snapshots the chosen profile. Its metadata writes are
atomic, it records stage timings, and it now rejects concurrent renders across entry points.

The existing `PublishingQueue`, `YouTubeService` and lifecycle module retain remote
upload ownership. New channels use separate token files. Existing upload IDs are
never blindly transferred again; uncertain outcomes require reconciliation.

State locations:

- `jobs/studio/operations.json`: channels, profiles, content, batches, asset annotations.
- `jobs/<job>/job.json`: generation stage/status snapshot.
- `jobs/<job>/metadata.json`: generated assets, profile snapshot and timing evidence.
- `jobs/<job>/qc.json`: checks and reviewed warnings.
- `jobs/<job>/youtube.json`: upload ID, lifecycle, schedule and verification evidence.

No database was introduced. The pre-existing SQLite registry remains for compatibility
with the original pipeline; the new operations state is stored in JSON. Secrets stay
server-side. The launcher binds only to loopback on port 5001. No unrelated services
were stopped or modified.

## Verification completed on 10 September 2026

**42 focused tests pass**, including existing publishing/lifecycle/waveform tests and
new channel isolation, durable recovery, duplicate concepts, safe path rejection,
cross-origin rejection, selected-job routing, backlog and scheduling tests.
Twenty automatic slots produced ten days with two distinct slots per day.

Run the regression suite with:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_studio.py tests/test_publishing.py tests/test_youtube_lifecycle.py tests/test_waveform.py -q
```

Real browser checks covered all ten navigation pages, channel creation/switching,
content creation/generation, video playback, metadata editing, thumbnail editing,
QC review, exact-job upload, selecting a publishing batch, and calendar-to-video
navigation. The final browser check recorded zero JavaScript errors and no mobile
horizontal overflow. Screenshots and JSON evidence are in this directory.

Real generation:

| Profile | Target | Result | Total time | Encoding time |
|---|---:|---|---:|---:|
| Focus Protocol, drift, 720p/15 FPS, ultrafast/CRF 28 | 600s | 599.933s MP4; QC checks passed, reviewed local-image fallback | 125.952s | 59.909s |
| Study Music, static, 720p/15 FPS, ultrafast/CRF 28 | 60s | Completed; stream/decode QC passed, local-image fallback warning | 36.171s | 4.906s |

The Study Music output uses its own metadata profile and contains no Jazz metadata.
Its preview remains available for review; it was not uploaded to an unconnected account.
The original fixed 5 MB validation floor was removed because a valid short video can
be smaller; stream/duration/decode checks provide the relevant validation.

Matched 60-second render benchmark at 1080p/24 FPS, faster/CRF 25:
static **22.190s**, drift **23.981s** (about 8.1% more time). Drift is optional.
This is not a claim that a full 90-minute render became faster. The real ten-minute
profile spent 49.262s on audio assembly, 6.986s on overlay preparation, and 59.909s
encoding. Astrofox's existing integration was inspected; it was not adopted or
claimed to have been benchmarked. A native CTA smoke render confirmed a visible,
foreground subscribe animation within the lower safe area.

Four real uploads completed processing and had their thumbnails, metadata and private
publish schedules verified against YouTube:

| Job | YouTube ID | Schedule in Asia/Kolkata |
|---|---|---|
| `studio_155baca366724f78b7daa0eb3f9a8ac2_1` | `KcQS11Xceek` | 10 Sep, 18:00 |
| `20260908_015040_video_001` | `hnwtPE7uYFs` | 11 Sep, 09:00 |
| `20260908_035801_video_001` | `d1137wuW3fk` | 11 Sep, 18:00 |
| `20260909_232202_video_001` | `fQVWA19thu4` | 12 Sep, 09:00 |

The first day had one remaining slot. The configured limit of two/day was respected.
One video was newly generated; three existing ten-minute renders were reviewed and
given updated metadata/artwork for the batch test. Restart preserved all four IDs
and upload timestamps. Requeuing the first video did not upload it again; each record
still has one transfer attempt. Failed/ambiguous upload behavior is covered by the
mocked failure tests, not described as an intentionally failed real upload.

Evidence: `studio-live-verification.json`, `studio-before-restart.json`,
`studio-after-restart.json`, `studio-final-state.json`, and the browser result files.
The final live state was checked again after the last server restart.

## Remaining external constraints

- The configured Colab tunnel did not resolve during acceptance. The explicit,
  validated local-image fallback worked and is recorded in job metadata/QC.
- The older upload `7Urh0bWGQgc` still reported remote processing when checked.
  It remains flagged for review and was not blindly uploaded again. The four new
  tests above completed processing successfully.
- The existing Focus Protocol token has upload/read scopes. Reconnect that channel
  once to grant the additional scope needed to edit metadata or schedules on an
  existing YouTube video. Initial metadata/scheduling on new uploads was verified.
  This distinction follows the official
  [videos.update authorization requirements](https://developers.google.com/youtube/v3/docs/videos/update#authorization).
- QC samples frames; it is not a full corruption scan, content-rights assessment,
  silence/loudness audit or a promise about YouTube copyright checks.
- Full 90-minute production and live publishing to the other three accounts were
  not tested. Production is left paused; confirmed YouTube schedules remain active.

The browser plugin failed at initialization because its runtime file was missing.
UI acceptance used an isolated headless Chromium process instead. Automatic approval
review rejected a redundant standalone thumbnail retry after the ordinary batch had
already completed that thumbnail; that rejected action was not executed or bypassed.
