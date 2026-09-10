# Astrofox Visualizer Pipeline

The long-form renderer now invokes `render-astrofox.js` by default. The bridge uses FFmpeg's streaming `showspectrum` filter with Astrofox-aligned defaults: logarithmic frequency scaling, Hann windows, centered lower-third placement, and low-opacity glow/vignette treatment.

## Astrofox audit

- Display definitions live in `astrofox/src/lib/displays/BarSpectrumDisplay.ts`, `RadialSpectrumDisplay.ts`, and `WaveSpectrumDisplay.ts`.
- Display layers render through `astrofox/src/lib/core/render/layers/*DisplayLayer.tsx`; effects are shader passes using `inputTexture`, `resolution`, `time`, and `fft` uniforms.
- Audio parsing is owned by `astrofox/src/lib/audio/FFTParser.ts`, with FFT calculation and per-frame export orchestration in the renderer/export path described by `astrofox/docs/external-plugins-analysis.md`.
- Astrofox's desktop exporter streams raw RGBA frames to FFmpeg in `astrofox/src/lib/video/VideoExporter.ts`, flips/scales to BT.709, and encodes `yuv420p`. The parent application's bridge preserves that streaming and color-management contract without requiring an Electron window for a 90-minute batch job.

It keeps the background as a separate looped input, scales it with Lanczos, and composites the transparent spectrum over it. No per-frame PNGs or full-length FFT arrays are created. The output defaults to 1920x1080, CRF 18, `medium`, AAC 320k, and BT.709 tags. Set `VIDEO_WIDTH`/`VIDEO_HEIGHT` to 2560x1440 or 3840x2160 for higher-resolution output.

## CLI benchmark

```powershell
node .\render-astrofox.js --audio .\music\sample.mp3 --image .\backgroundImages\sample.png --output .\output\astrofox-15s.mp4 --resolution 1920x1080 --fps 30 --duration 15
ffprobe -v error -show_streams -show_format .\output\astrofox-15s.mp4
```

The parent pipeline falls back to its existing static waveform only when Node, the bridge, or the FFmpeg spectrum graph is unavailable. Set `ASTROFOX_VISUALIZER_ENABLED=false` to force that compatibility path.