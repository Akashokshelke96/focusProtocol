# Three small content upgrades

## Scope

Only finished-audio normalization, defaults, and the short-clip dust composition changed. `copy_commands()` and its loop/mux stream-copy arguments are unchanged. No fingerprint, QC, thumbnail, or upload code was edited. The existing subscribe implementation is unchanged; acceptance explicitly disables subscribe so that both long-video stages remain packet copy.

## Loudness

`app/audio/local_timeline.py::assemble_tracks` now normalizes its already-encoded AAC output. The helper measures the input, uses FFmpeg loudnorm with measured dual-pass parameters, encodes to a sibling temporary MP4/AAC file, probes duration/codec, measures decoded AAC loudness, and replaces the original using `os.replace`. Failures retain the original audio and record a warning. The orchestrator passes its existing metadata dictionary to capture `loudness_normalized` and measured before/after values.

Requested programme target remains I=-14 LUFS, LRA=11, with final TP at or below -1.5 dBTP. Filter TP is -1.7: the initial AAC benchmark overshot a -1.5 filter ceiling to -1.38, so 0.2 dB additional encoder headroom is supported by measurement. There is no genre-specific target change; these are delivery targets, not a listening-volume guarantee.

Initial 180-second benchmark: single-pass encode 13.526 s; dual-pass analysis 7.854 s + encode 12.146 s. Single pass initially reached -14.00 LUFS, but a separate full-pipeline selection reached -13.13 LUFS. Dual pass was selected for reliable targeting despite the extra scan. A final decoded-output measurement adds verification time in both approaches. Metadata labels the method and stores true encoded-output measurements, not the filter's pre-encoder estimate.

R128's broadcast programme target is -23 LUFS; -14 here is the requested custom target using R128 measurement. Sources: [EBU R128](https://tech.ebu.ch/publications/r128/) and [FFmpeg loudnorm](https://ffmpeg.org/ffmpeg-filters.html#loudnorm).

## Drift, grain, and dust

Defaults are `STUDIO_MOTION_MODE=drift`, `VISUAL_EFFECT=old_film`, `VISUAL_EFFECT_OPACITY=0.06`. Settings, .env/.env.example, new Channel defaults, missing-value service fallbacks, and the new-channel form agree. Explicit saved channel preferences are preserved.

The existing drift and grain code passed inspection and visual tests, so neither implementation was changed. Drift traverses approximately 1.8% of frame width on its existing 60-second cycle. Grain uses `allf=t+u`; its existing forward/reverse six-second pattern joins across the 60-second loop.

`app/video/dust.py` mirrors the visualizer's cached-asset approach. `asset/dust_6s.mov` is a 6.000-second 640x360/30 FPS QTRLE/ARGB transparent asset, approximately 1 MB. Forty-five deterministic soft white dots follow periodic slow paths. Alpha is blurred independently to avoid dark fringes. Default `DUST_OPACITY=0.12`; `DUST_ENABLED=false` disables it. Dust is scaled full-frame and composited after background/branding but before soundwave. It is processed at output FPS and composited in YUV to reduce overhead. The asset is generated only when absent/empty, and no PNG sequences or full-video dust pass are created.

## Validation and artifacts

- Touched Python modules compile; Studio JS passes syntax checking.
- 70 relevant tests pass (58 focused tests plus 12 production-hardening checks; the unrelated failure below is excluded), including real AAC fade/crossfade behavior, static/motion graphs, grain, visualizer, dust periodicity/draw order, safe loudness failure, and packet-copy command assertions.
- Two older static-only test fixtures now explicitly request static mode and disable unrelated overlays rather than depending on changed defaults.
- A broader run exposed `test_corrupt_music_skipped_and_empty_library_reported` failing in untouched track rotation (it selected four entries instead of the expected single valid track). That unrelated implementation/test was not changed.
- Visual profiles: static, static+grain, drift+grain, drift+grain+dust at 1280x720/15 FPS, CRF 23. Each writes the same `short`, `loop`, `mux` command-file keys. Both loop and mux retain video copy; mux retains audio copy.
- Decoded screenshots are under `jobs/content_upgrade_acceptance/{static,grain,drift_grain,all}/frame_*.png`.
- `loudness_benchmark.json`, `dual_headroom_stats.json`, `visual_measurements.json`, and `pipeline.json` contain the measured results.

Changed implementation files: `app/audio/local_timeline.py`, `app/pipeline/long_form_jazz_orchestrator.py` (metadata argument only), `app/video/dust.py`, `app/video/short_loop.py` (dust in short command only), `app/config/settings.py`, `.env`, `.env.example`, `app/studio/profiles.py`, `app/studio/service.py` (default fallback only), `static/studio.js` (new-channel default only), and the generated dust asset. Added acceptance/test scripts are prefixed `content_` and `test_content_upgrades.py`.

## Final measured results

Full three-minute job `20260925_020313_404137_video_001` passed unchanged application QC. Audio/video are valid; audio is AAC stereo at 48 kHz. Audio duration before and after normalization is exactly 180.000 seconds. Final-mux decoded music hashes match the normalized AAC. Decoded full-output frames at 2 and 62 seconds match exactly, including dust, grain, drift phase, branding, and soundwave.

Loudness: **-17.25 → -14.02 LUFS**, true peak **-1.58 → -1.5 dBTP**, LRA **6.2 → 6.1 LU**. Dual-pass normalization plus decoded-output measurement took 34.837 seconds.

Pixel differences below are mean absolute RGB differences on a 0–255 scale, measured on decoded screenshots (not normalized percentages).

| Comparison | MAE |
|---|---:|
| static_temporal_mae | 1.4383 |
| grain_temporal_mae | 6.7093 |
| drift_half_cycle_mae | 14.8917 |
| drift_seam_mae | 4.7802 |
| dust_contribution_mae | 1.3764 |
| dust_phase_2_vs_62_mae | 0.0000 |
| all_seam_mae | 4.7825 |

Drift/grain short encode: **71.752 s**; adding dust: **112.303 s**, delta **+40.551 s** (+56.5%). This is a software-encode observation at 720p/15 FPS, not a hardware-independent cost guarantee. Both encode 60 seconds only, regardless of final long-video length. Full-pipeline wall times include render-slot contention with acceptance jobs, so use the isolated dust comparison for the overhead estimate.

Screenshots: [drift at 2 seconds](../jobs/content_upgrade_acceptance/drift_grain/frame_2.png), [drift at 32 seconds](../jobs/content_upgrade_acceptance/drift_grain/frame_32.png), [static](../jobs/content_upgrade_acceptance/static/frame_2.png), [final all-on output](../jobs/content_upgrade_acceptance/final-preview.png). No requested upgrade was skipped. No existing saved channel preference or protected pipeline component was rewritten.
