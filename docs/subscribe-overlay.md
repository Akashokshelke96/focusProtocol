# Subscribe WebM overlay

The active integration is `app/video/short_loop.py` immediately before the final mux. Background/motion/branding/visualizer short-clip construction and the existing packet-copy loop are preserved. `app/video/subscribe_overlay.py` discovers and probes the WebM, builds the schedule, and adds native FFmpeg overlay filters. The inactive legacy subscribe-card module is retained for compatibility.

## Behavior and controls

- Defaults: enabled for direct/new dashboard renders, every 180 seconds, first appearance after one interval. Existing Studio channels keep their saved subscribe toggle; newly created channels in the UI start enabled.
- Studio: Channels → edit channel → Subscribe animation, interval in seconds, size, and WebM selector. The legacy generation dashboard has the same controls.
- `.env`: `SUBSCRIBE_OVERLAY_ENABLED`, `SUBSCRIBE_OVERLAY_INTERVAL_SECONDS`, `SUBSCRIBE_OVERLAY_PATH` (folder or WebM file), `SUBSCRIBE_OVERLAY_FILE` (selected filename), `SUBSCRIBE_OVERLAY_WIDTH_RATIO`, `SUBSCRIBE_OVERLAY_RIGHT_PADDING_RATIO`, `SUBSCRIBE_OVERLAY_BOTTOM_PADDING_RATIO`.
- Optional `SUBSCRIBE_OVERLAY_START_AFTER_SECONDS` overrides the first trigger; omit it to follow the interval, or explicitly set 0 for an intro appearance.
- Automatic selection uses the first alphabetically sorted WebM. All discovered files are available in the UI selector.
- Triggers are strictly earlier than the job's final target duration. Each input plays once at natural speed. Playback is clipped at the final output boundary or the next trigger if the configured interval is shorter than the animation.
- Width is 17% of output width (about 326 pixels at 1080p); right margin is 5%, bottom margin 6.5%. Aspect ratio is preserved and the bounds fit inside the frame. FFmpeg detects the union of nontransparent alpha bounds to remove this asset's large empty canvas before scaling.
- Explicit libvpx/libvpx-vp9 decoding preserves WebM alpha. There is no color key or solid replacement background. Only music input `1:a:0` is mapped; its packets are copied unchanged. WebM sound is never mapped.
- Missing/unreadable/corrupt assets log a warning and use the existing mux. A failed overlay encode retries the original stream-copy mux. Cancellation, resource protection, and timeouts still stop the job.

## Performance

The disabled/no-trigger path remains stream copy. An enabled overlay requires one full-duration video encode during the existing final mux (FFmpeg cannot composite pixels using stream copy). The existing looped file is reused; no new intermediate videos, PNG frame sequences, or Python frame processing are introduced. Each trigger adds a WebM input and filter; shorter intervals increase decoder/filter overhead. Main audio remains stream copy. The 10-minute 720p/15 FPS software acceptance run's final mux took approximately 54 seconds on this machine; this is not a 1080p production benchmark.

## Files changed for this feature

- `app/video/subscribe_overlay.py` (new isolated overlay helper)
- `app/video/short_loop.py` (active insertion and fallback)
- `app/config/settings.py`, `.env`, `.env.example` (subscribe configuration only)
- `app/api/jazz_api.py`, `templates/jazz_dashboard.html` (legacy controls)
- `app/studio/api.py`, `app/studio/profiles.py`, `app/studio/service.py`, `static/studio.js` (Studio controls and saved per-channel values)
- `tests/test_subscribe_overlay.py`, `tests/subscribe_acceptance.py`, `tests/subscribe_edge_acceptance.py`, `tests/subscribe_pipeline_acceptance.py` (new checks)
- This document.

Pre-existing working-tree edits were retained. No changes were made to the audio provider, visualizer, image-motion implementation, or background selection.

## Validation

- Touched Python modules compile; Studio JavaScript passes `node --check`.
- 54 focused pytest tests pass, covering overlay schedules plus existing short-loop, motion, visualizer, and Studio behavior.
- Real 2/5/8/15-minute FFmpeg renders at 320×180 verify exact starts, natural disappearance, background pixels, video/audio streams, output duration, and identical decoded music hashes with an audio-bearing WebM.
- Real missing/corrupt asset and forced filter-failure renders complete without the overlay.
- A 1920×1080 render with a 3-second interval exercises animation clipping, restart, and responsive bounds.
- Full 10-minute orchestrator acceptance uses 1280×720, 15 FPS, ultrafast, CRF 28, and local assets; publishing is excluded. First successful job: `20260924_212044_373169_video_001`, duration 600.0 seconds, starts 180/360/540, lifecycle 100.086 seconds.
- UI HTML/API smoke checks return 200 and expose the discovered WebM; JavaScript syntax checked. No interactive browser test was performed.

Run tests with the repository's `.venv/Scripts/python`. Acceptance runners create local artifacts under `jobs/` and do not publish videos.

Final coexistence acceptance: `20260924_212327_276616_video_001` passed application QC with 600.0-second audio/video, 1280×720 at 15 FPS, visualizer enabled, image motion enabled with its existing 30-second cycle, and subscribe starts at 180/360/540. Alpha-cropped overlay bounds were [998, 636, 218, 37]. Final mux took 53.286 seconds; full lifecycle 125.133 seconds. The rendered frame at 03:03 was visually inspected: visualizer bottom-left, subscribe bottom-right, existing branding and background intact. As expected, the extra lossy video encode changes pixel values slightly; music remains copied.
