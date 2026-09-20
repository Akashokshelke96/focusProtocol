# Visualizer and YouTube status upgrade

## Generation controls

Choose **Linear** or **Circular** in **Create content**, **Channels → Edit profile**, or the classic generator. The content item stores its selection, and the render records it in `visualization_config.waveform_style` and `waveform_style` in `metadata.json`.

`WAVEFORM_VISUAL_HEIGHT_RATIO=0.10` sets a 108px region at 1080p, or 72px at 720p. Linear width retains the previous scaling and safe margins. Circular uses a square region so it does not become an ellipse. Both remain horizontally centered at the existing vertical anchor. Actual line lengths vary with audio energy, including becoming small in quiet sections.

Lines default to black at 90% opacity, with a faint one-pixel light keyline for visibility over dark backgrounds. The radial shape is hollow, with 64 mirrored outward strokes and no filled disk. Both modes use the existing smoothed audio amplitude analysis and 10 FPS overlay encoder. No second rendering engine, browser capture, or PNG frame sequence was added.

The installed Astrofox `CanvasRadial.ts` already implements the requested geometry. Its outward-bar calculation is adapted into the existing Pillow renderer, with the MIT notice in `docs/licenses/astrofox-MIT.txt`. The old `render-astrofox.js` bridge uses a rainbow FFmpeg spectrum and does not invoke that canvas implementation; starting the full Electron/WebGL application would add a separate engine. The adaptation preserves radius, inner radius, bar count, width, and mirrored placement while feeding the existing audio-amplitude data.

## Publishing display

Each job has a separate publishing projection derived from saved YouTube state. A green **Uploaded to YouTube** badge records successful receipt independently of the current stage: Not uploaded, Uploading, Uploaded—processing, Uploaded—ready, Scheduled, Published, or Failed. Scheduled is purple; processing amber; errors red. A local schedule reservation cannot become a confirmed YouTube schedule merely because time passes.

Overview and Publishing show totals, uploaded receipts, not uploaded, uploading, processing, scheduled, published and failures. Publishing and Production include status filters. Publishing batch counts use member jobs' persisted state. Exclusive stage counts sum to the batch size; the overall uploaded receipt total includes processing, scheduled and published jobs.

`youtube.json` remains authoritative. Existing IDs, processing state, schedule, timestamps and errors are retained; saves also normalize `upload_status`, `thumbnail_status`, `metadata_status`, `last_checked`, `upload_error` and first observed `published_time`. No new database was introduced. Local MP4 existence is never upload evidence. Uploaded videos with later verification failures retain the receipt badge alongside the failure badge.

## Validation and performance

- 60 Python tests passed, including restart persistence for 20 jobs (8 ready uploads, 6 scheduled, 6 not uploaded), batch counts, local reservation distinction, hollow radial geometry and saved style selection.
- Node UI rendering tests passed for badges, filters, missing-local-file visibility and style defaults; JavaScript syntax and Python compilation passed.
- Matched 30-second 720p/15 FPS/ultrafast/CRF 28 samples, two runs: previous geometry averaged **3.99s**, new linear **5.32s**, circular **3.15s** for overlay preparation plus encoding. The linear keyline increases preparation cost. These short samples are approximate, not a 90-minute extrapolation. The initial standalone timing was interrupted and discarded.
- Full pipeline job `bourbon_radial_acceptance_20260911`: **185.323s** lifecycle for a 10-minute render, **15.119s** overlay preparation and **97.646s** encoding. Audio was 600 seconds; MP4 was 599.933 seconds, 1280×720 at 15 FPS. All **14** final QC checks passed, including selected visualizer style and bounds. This test job is excluded from publishing.

A matched 30-second filter comparison took 1.77s without an atmosphere effect and 2.80s with old film: grain/vignette/flicker added about 1.03s. FFmpeg encoding is the largest measured full-render stage; the radial overlay stays small. The test used local image and title fallbacks because the configured LLM gateway was offline. Automated live browser inspection remains unavailable due to the installed browser runtime problem documented in the branding upgrade; UI checks here are rendering tests, not a browser session.

Restart the studio server and refresh the page to load the changes. Existing videos retain their original visualizer; new generation uses the selected style.
