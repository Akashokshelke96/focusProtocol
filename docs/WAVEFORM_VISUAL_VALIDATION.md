# Focus Protocol waveform and watermark

The automated renderer now uses a native, animated time-domain waveform. The
background remains one static image. The existing audio selection, crossfade,
loop/trim, output filename, job persistence, thumbnail, upload and image fallback
paths remain in place.

## Cause of the old output

`render-astrofox.js` was a Node wrapper around FFmpeg, not an invocation of the
Astrofox waveform renderer. It explicitly selected `showspectrum`, `color=rainbow`,
full frame width, 28% frame height, blur/glow and vignette. The orchestrator called
it before checking `waveform_enabled`. This explains both the screenshot's
spectrogram and why native waveform settings could not control it.

Automated jobs no longer invoke that bridge, including when an older environment
sets `ASTROFOX_VISUALIZER_ENABLED=true`. The legacy helper and script remain for
compatibility, and the Astrofox application source/build files are unmodified.

## Source inspection and what was reproduced

Inspected Astrofox files:

- `src/lib/displays/WaveformRingDisplay.ts`
- `src/lib/core/render/layers/WaveformRingDisplayLayer.tsx`
- `src/components/AudioWaveform.tsx`
- `src/components/ExportWaveform.tsx`
- `src/lib/audio/WaveParser.ts`
- `src/lib/canvas/CanvasAudio.ts`
- `src/lib/canvas/CanvasWaveRing.ts`
- `src/lib/canvas/CanvasBars.ts`
- `src/lib/core/render/layers/CanvasTextureLayer.tsx`
- `src/lib/utils/math.ts`

`WaveParser` reduces a time-domain buffer by selecting samples at evenly spaced
indices. It normalizes signed [-1, 1] values into [0, 1], with clamping. Its optional
temporal filter is `previous * smoothing + current * (1 - smoothing)`.
It does not perform percentile normalization, RMS analysis or dynamic-range
compression. `CanvasAudio`, used by the seek/export preview, instead estimates
absolute peaks: roughly ten samples per bar/window, taking the maximum across
channels. Those preview components draw a whole-track overview and recolor the
played/selected region; they are not an animated audio-reactive export algorithm.

`CanvasWaveRing` bounds incoming values, maps `(value - .5) * 2 * amplitude` into
radial displacement and sizes its canvas from radius, amplitude and stroke width.
It uses rounded joins/caps and optionally quadratic curves. `CanvasBars` maps
amplitude into a configured, clamped height and explicitly budgets width/spacing.
Opacity is a display/layer property passed through the texture layer. The examined
code has no special anti-saturation DSP: controlled geometry, sample count,
clamping, optional smoothing and appearance settings provide the restraint.

Reproduced principles: time-domain reduction, the temporal EMA, bounded geometry,
explicit count/spacing, a single color and controlled alpha. Not copied: React,
Web Audio/AudioBuffer, OffscreenCanvas, WebGL textures, radial geometry, quadratic
ring interpolation, gradients, shadows, FFT/spectral rendering, glow or vignette.
The backend uses RMS and percentile normalization as deliberate adaptations of
its pre-existing implementation, not as claims about Astrofox's algorithm.

Backend files inspected included settings, the full job/render flow in
`long_form_jazz_orchestrator.py`, timeline, renderer, local music/background
providers, the image generation/fallback call site, job manager, metadata and
FFprobe validation, Flask generation routes, dashboard polling, and existing tests.

## Native waveform

FFmpeg decodes the final assembled audio to mono 8 kHz PCM. A temporary disk-backed
PCM file is reduced in chunks to 1 ms RMS windows with NumPy. Short windows retain
note shape; the initial 10 ms windows looked too uniform on sustained jazz notes.
Each overlay frame shows the preceding 160 ms of actual audio using up to 160 bars.

A whole-track 98th-percentile reference, with a 0.05 floor, avoids amplifying
near-silence or independently normalizing each frame. Values are limited to [0, 1]
and gently compressed with a 0.8 exponent. Filter ON applies a [0.25, 0.5, 0.25]
spatial average and Astrofox-style temporal smoothing with coefficient 0.55.
Filter OFF bypasses both smoothing operations while retaining the height ceiling
and normalization. Silence produces only one-pixel baseline dots, not fake activity.

Pillow draws one-pixel-wide separated vertical bars, symmetric around the center.
The default canvas is 50% of frame width and 3% of frame height. Bar positions span
the actual canvas edges; no integer gap accumulation, cropping or later waveform
scaling can expand the visible width. At 1920x1080 the asset is 960x32, placed at
(480, 848), centered around y=864. Peak visible height is bounded by the asset.
Default color is white and opacity is 0.55; optional color alpha multiplies opacity.

Frames are streamed at 10 Hz into a lossless transparent FFV1 `waveform.mkv`, then
composited by the existing FFmpeg render. Only one `waveform.png` preview is saved
(at two seconds); there is no disk sequence of PNG frames. The background input
uses the configured video FPS so it does not throttle the animated overlay to
one update per second. Final output remains H.264/yuv420p plus AAC.

The metadata records dimensions, alpha bounding boxes (preview and union across
frames), overlay coordinates, bar count/width, color, opacity, engine, filter state,
animation rate and requested visualization configuration. The PNG bbox is in asset
coordinates; add `waveform_overlay_xy` for frame coordinates. There is no waveform
scale operation in the FFmpeg graph.

## Settings and UI

Defaults are in `app/config/settings.py`; matching examples are in `.env.example`.
The actual `.env` had no waveform/watermark overrides and did not need editing.

```dotenv
WAVEFORM_ENABLED=true
WAVEFORM_FILTER_ENABLED=true
WAVEFORM_WIDTH_RATIO=0.50
WAVEFORM_HEIGHT_RATIO=0.03
WAVEFORM_VERTICAL_POSITION_RATIO=0.80
WAVEFORM_BAR_WIDTH=1
WAVEFORM_OPACITY=0.55
WAVEFORM_COLOR=0xFFFFFF
WATERMARK_ENABLED=true
WATERMARK_WIDTH_RATIO=0.016667
WATERMARK_OPACITY=0.35
```

The old bottom-padding setting remains accepted for compatibility; the vertical
anchor controls placement in the active renderer. Width, height, position, bar
width and opacity have Pydantic bounds. Bar width is pixels; dimensions and position
use the configured resolution.

The dashboard starts with a three-minute duration field and provides waveform,
filter/smoothing and watermark checkboxes initialized from environment defaults.
The existing three-minute Test mode still works. JSON booleans
`waveform_enabled`, `waveform_filter_enabled` and `watermark_enabled` are optional.
The API rejects strings such as `"false"` with HTTP 400. It applies supplied booleans
to an isolated Settings copy, passes it into the job's orchestrator, and records
the resulting configuration in metadata. Omitted values preserve environment
defaults. A direct run without a duration now correctly uses the authoritative
`target_duration_minutes` rather than an unconditional 90-minute fallback.

The watermark width is now one-sixth of its former 0.10 setting: 32 pixels at
1920 width and 21 pixels at 1280 width. The previous 48-pixel minimum was removed
because it would defeat this reduction. Opacity is 0.35 instead of 0.75, with the
existing proportional bottom/right padding. The current PNG differs from the
negative screenshot and already has transparent corners; it was not edited.

## Modified source/document files

- `app/config/settings.py`
- `app/pipeline/long_form_jazz_orchestrator.py`
- `app/video/waveform.py` (new)
- `app/api/jazz_api.py`
- `templates/jazz_dashboard.html`
- `.env.example`
- `tests/__init__.py`
- `tests/test_waveform.py` (new)
- `tests/visual_acceptance.py` (new)
- `docs/WAVEFORM_VISUAL_VALIDATION.md` (new)

Generated test jobs, logs, SQLite records and prompt reservations also exist under
`jobs/`, as expected for production-path acceptance runs.

## Validation procedure and limitations

Compile touched Python modules, then run:

```powershell
python -m pytest tests/__init__.py tests/test_waveform.py test_routes.py test_colab_image_service.py -q
python -m pytest test_jazz_generation.py -q
python -m pytest tests/visual_acceptance.py -q -x
```

The local/focused suite passes 18 tests. Two stale existing fixtures were corrected:
the FPS assertion now matches the existing 24-FPS default, and the portrait fixture
meets minimum dimensions so it actually exercises the orientation check. Production
media validation was not changed to accommodate these tests.

The existing generation script's four tests pass, but they return booleans rather
than asserting them. Therefore its successful persisted job and FFprobe results
were also inspected; pytest's exit status alone is not the evidence of success.
The default-profile job is `20260908_040152_video_001`, 1920x1080 at 24 FPS, about
180 seconds, completed_with_fallback, with elapsed time 144.377 seconds.
Colab's configured hostname failed DNS resolution; the existing fallback produced
valid images. Successful remote image generation was not demonstrated.

The explicit acceptance tests assert outcomes, exact stream counts, video/audio
duration, dimensions, FPS, single image, 2-4 music tracks, waveform/watermark state,
elapsed metadata and changing waveform pixels. Profiles include four three-minute
toggle comparisons at 1280x720/15 FPS, a ten-minute run, and a three-minute
1920x1080 run. They use ultrafast/CRF 28 and the existing local image fallback path.
Results are saved in `jobs/visual_acceptance_results.json`; real extracted frames
are stored alongside each output. Final measured results are appended below.

The browser plugin failed to connect because its internal browser-service module
was missing. UI template rendering and request propagation were tested through
Flask; browser visual interaction could not be checked. Astrofox source is
unchanged, and its separate desktop build was not rerun. Legacy live-provider
diagnostic scripts outside the local suite were not treated as unit tests.
Existing dependency/deprecation warnings and an atexit logging warning remain.

## Final measured outputs

All six final acceptance tests passed (619.21 seconds for the full batch). All outputs have one video and one audio stream, one background, valid duration/resolution/FPS, persisted metadata and elapsed time.

Bounding-box coordinates below use exclusive right/bottom edges. PNG measurements are from the two-second alpha preview; maximum height is the union over the whole animation.

| Profile | Resolution / FPS | Duration (s) | PNG visible W x H | PNG visible frame X / Y | Max visible height | Elapsed (s) |
|---|---|---:|---|---|---:|---:|
| filter_on | 1280x720 / 15/1 | 179.933 | 640 x 15 | 320-960 / 568-583 | 19 | 116.008 |
| filter_off | 1280x720 / 15/1 | 179.933 | 640 x 20 | 320-960 / 566-586 | 20 | 83.095 |
| wave_off | 1280x720 / 15/1 | 180.000 | OFF | - | - | 78.009 |
| mark_off | 1280x720 / 15/1 | 179.933 | 640 x 15 | 320-960 / 568-583 | 19 | 86.625 |
| acceptance_10min | 1280x720 / 15/1 | 599.933 | 640 x 12 | 320-960 / 570-582 | 19 | 169.667 |
| full_hd | 1920x1080 / 15/1 | 179.933 | 960 x 23 | 480-1440 / 852-875 | 28 | 75.958 |

The waveform-enabled clips end up to 0.067 seconds before their target in these 15-FPS profiles because of FFmpeg shortest-input frame boundaries; they pass the configured duration tolerance. No-waveform output is exactly 180 seconds.

At 1920x1080, the waveform canvas is 960x32, its overlay origin is (480, 848), and its center is y=864. The watermark is 32 pixels wide at 35% opacity. At 1280x720, the watermark is 21 pixels wide.

The lossless waveform alpha changes at 100 ms intervals (254 and 275 changed pixels in consecutive samples of the final filter-on clip). The first 170 seconds of AAC packets have identical MD5 checksums for filter-on, filter-off and waveform-off: `e3fb0e9d63988359239bde11f8bd02b1`. End-of-file packet hashes differ with the small shortest-input duration difference.

Actual MP4 frames were opened and visually inspected for filter ON, filter OFF, waveform OFF, watermark OFF and final 1080p. The waveform is thin, monochrome, centered, compact and confined to its intended area; the background dominates. Disabled overlays are visibly absent.

Output links:

- filter_on: [video](<D:/Long Form Video Generator/jobs/20260908_040329_video_001/output/final_90min_video.mp4>) | [actual frame](<D:/Long Form Video Generator/jobs/20260908_040329_video_001/frame_3.png>)
- filter_off: [video](<D:/Long Form Video Generator/jobs/20260908_040527_video_001/output/final_90min_video.mp4>) | [actual frame](<D:/Long Form Video Generator/jobs/20260908_040527_video_001/frame_3.png>)
- wave_off: [video](<D:/Long Form Video Generator/jobs/20260908_040651_video_001/output/final_90min_video.mp4>) | [actual frame](<D:/Long Form Video Generator/jobs/20260908_040651_video_001/frame_3.png>)
- mark_off: [video](<D:/Long Form Video Generator/jobs/20260908_040810_video_001/output/final_90min_video.mp4>) | [actual frame](<D:/Long Form Video Generator/jobs/20260908_040810_video_001/frame_3.png>)
- acceptance_10min: [video](<D:/Long Form Video Generator/jobs/20260908_040938_video_001/output/final_90min_video.mp4>) | [actual frame](<D:/Long Form Video Generator/jobs/20260908_040938_video_001/frame_3.png>)
- full_hd: [video](<D:/Long Form Video Generator/jobs/20260908_041228_video_001/output/final_90min_video.mp4>) | [actual frame](<D:/Long Form Video Generator/jobs/20260908_041228_video_001/frame_3.png>)
