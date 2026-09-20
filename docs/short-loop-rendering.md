# Short-clip rendering for Camping With Blues

The production orchestrator compiles and verifies the complete audio first, then assigns background media through the existing selection method. It encodes a four-second video-only clip with two static text marks, copies that clip to the requested duration, and muxes the completed audio using stream copy. Duration comes from job metadata; FPS, resolution, encoder selection, and quality use existing settings.

The integration points are `LongFormJazzOrchestrator._render_video`, `app/video/short_loop.py`, and the existing branding module. `_render_video_segmented_legacy` remains available as compatibility code but is not called by production. No waveform generation, GIF loading, music-disc processing, subscribe overlay, or Astrofox call occurs in the new production path. Acceptance guards raise if legacy rendering is invoked.

Background images still come from the channel's configured directory, and video backgrounds still come from `inputVideos`. Static images loop seamlessly. Existing drift is represented by a periodic, subtle pan. Video backgrounds use a bounded forward/reverse cycle to avoid a hard cut; reversed movement can be noticeable for strongly directional action. Only half the short clip is buffered, never the full video.

The top-right text is warm white, up to 310 pixels wide, with 25-pixel top/right padding. The bottom-right text watermark is smaller and translucent, with 25-pixel bottom/right padding. Both say Camping With Blues. Existing typography code draws them once into a job-local overlay. There are exactly two deliberate branding locations.

Both existing named watermark PNGs contained Bourbon artwork. The identical old-name duplicate was removed after hash comparison; `watermark/camping-with-blues.png` retains the original bytes. That stale artwork is not used in production. Correct text branding is used instead, without modifying source images or thumbnails. Future channel/profile names were updated locally; existing job metadata, upload history, credentials, content records, and publishing batches were preserved.

Video fades and optional visual effects are omitted from this mode. Baking a fade into the loop would repeat it every four seconds. Separate opening/closing clips would be the compatible alternative if fades become required; they are not implemented here. Audio crossfades, fades, ordering, silence handling, target calculation and encoding remain unchanged. Existing optional subtitle handling is not rewritten.

Every FFmpeg stage uses the existing cancellation/resource/progress wrapper and validates its output. Failure stops subsequent stages and preserves completed audio and diagnostic intermediates. Commands are recorded in `output/render_commands.json`. Both long commands explicitly contain `-c:v copy`; AAC muxing uses `-c:a copy`. H.264 encoding uses no B-frames and explicit FPS/timestamps so repeated clips have a stable packet timeline. The existing output filename and finish/QC workflow remain in use.

The first moving-video acceptance caught a 3.933-second duration for a four-second clip. Explicit final FPS/timestamps corrected it. The same job was retried with its already-compiled audio and assigned assets. The latest older output's middle frame was not fully blank, so no exact universal blank-video root cause is claimed. Its old GIF coordinate expression could position the GIF above the frame; that entire path is now inactive.

The dashboard was not cleaned: the latest architecture brief superseded the preceding visualizer/reset task and explicitly scoped out dashboard/job-state changes.

## Measured acceptance results

All three jobs ran the normal local music selection, compilation, media assignment, finish, and QC path. They are excluded from publishing. Outputs contain H.264 video and AAC audio at 1920x1080, 15 FPS. The 3-minute and 90-minute cases used images; the 10-minute case used the existing input video.

| Minutes | Audio compilation | Short encode | Copy loop | Copy mux | Video stage total | Full lifecycle |
|---|---:|---:|---:|---:|---:|---:|
| 3 | 13.360s | 5.669s | 1.256s | 0.803s | 10.576s | 76.585s |
| 10 | 37.504s | 3.678s | 6.840s | 27.817s | 40.549s | 192.484s |
| 90 | 330.118s | 5.048s | 7.095s | 30.607s | 45.374s | 465.829s |

Video-stage totals include preparation and backend probing in addition to the three operations. Full lifecycle totals for 10 and 90 minutes include interruptions/retries and are not clean uninterrupted benchmarks. The 90-minute first attempt encountered an existing Windows metadata-file replacement access error after audio completion. Retrying the same job reused the completed audio; no job-state writer changes were made.

FFprobe measured exactly 180, 600, and 5400 seconds for both video and audio. The long output starts both streams at zero. Beginning/middle/end frames were inspected, and QC decoded representative samples. Repeated encoded video packet hashes match across loop boundaries in the shorter tests, AAC packet hashes match the source master, and packet timestamps advance monotonically, including near the 90-minute end. The moving-video seam's frame difference was smaller than its neighboring motion differences. There is no full-length video filter or encode.

Compilation passed. Regression suite: **118 passed, 1 skipped**. Eleven focused short-loop tests cover video-copy commands, arbitrary durations, image/video/drift graph construction, incomplete audio, encode failure, and production bypass of old overlays. Obsolete assertions for the abandoned two-GIF design were replaced by production-exclusion checks. The final diagnostic-command logging change also passed the focused suite.

Existing source thumbnail integrity passed. QC warns that the original thumbnail exceeds 2 MB; it was not modified. The supplied video background contains a small embedded source watermark, which was not edited out. No live YouTube upload/schedule operation was performed. The idle dashboard was restarted and its health endpoint returned HTTP 200, loading the new production code.

## Outputs

- 3 minutes: `D:\Long Form Video Generator\jobs\20260915_232322_761234_video_001\output\camping_with_blues_ep_01_3min.mp4`; job `20260915_232322_761234_video_001`.
- 10 minutes: `D:\Long Form Video Generator\jobs\20260915_232521_387107_video_001\output\camping_with_blues_ep_02_10min.mp4`; job `20260915_232521_387107_video_001`.
- 90 minutes: `D:\Long Form Video Generator\jobs\20260915_232914_760509_video_001\output\camping_with_blues_ep_03_90min.mp4`; job `20260915_232914_760509_video_001`.

Source originals, historical published metadata, OAuth state, and upload tracking were preserved. Dashboard cleanup from the earlier superseded brief was not performed.
