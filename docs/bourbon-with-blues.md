# Camping With Blues

The default channel is now Camping With Blues with a slow-blues content profile. Its internal `focus-protocol` ID remains stable so existing jobs and OAuth credentials retain their association. Other channels keep their own identities.

In **Channels → Edit channel**, choose an atmosphere filter and opacity (0–0.30). Old movie is the default at 0.12; film grain, soft vignette and none are also available. These are native FFmpeg effects inspired by motion-graphics workflows, not an embedded Astrofox application. One source background remains in use for the whole video.

Enable **Show 12 session titles and left channel lettering** for the optional gold script/serif panel. The small YouTube play icon and channel name appear at the top right. Fonts remain consistent across jobs. `WAVEFORM_SCALE=2` doubles the previous height and width, with width limited to 94% of the frame for margins.

Blues videos request 12 new editorial session names from the configured LLM. Previously used names are rejected. If the provider is unavailable or returns invalid names, a nonrepeating local fallback is recorded as `session_title_source=local_fallback`. Descriptions label the timestamps as editorial chapters in the mix, not twelve distinct source tracks. The current audio timeline shuffles the permanent music library, crossfades tracks for four seconds, and uses each decoded audio source at most twice. See production-hardening.md for the current rules.

Background fallback selection prefers the configured background folder, validates files, and randomly exhausts the available pool before repeating. Rotation now persists in `jobs/media_usage.json`; previous background history is imported. The active pipeline now bypasses all image-generation APIs, including when legacy flags are enabled. Existing local imagery is not automatically changed into vintage blues imagery; curate the folder to maintain that aesthetic.

QC runs automatically before completion and again before publishing. Valid local image fallback is no longer a manual approval warning. Failures block completion/publishing and are recorded in `qc.json`. Checks cover streams, dimensions, FPS, durations, waveform metadata, thumbnails, and decoded beginning/middle/end samples. This is bounded technical QC, not a semantic aesthetic judgment or a full-frame corruption scan.

Validation: 41 focused tests passed. The 10-minute acceptance job `bourbon_branding_acceptance_20260911` passed all 12 QC checks at 1280×720, 15 FPS, ultrafast, CRF 28, old-film opacity 0.12 and the optional panel enabled. Audio was 600 seconds; MP4 duration was 599.933 seconds; total lifecycle was 187.936 seconds. The configured OmniRoute endpoint was offline, so this run exercised title fallback. The acceptance job is excluded from publishing.

Restart the running studio server to load Python changes, then refresh the page. Enable the optional panel in the channel settings when wanted. Browser automation could not connect because the installed browser plugin referenced a missing runtime file; JavaScript syntax and server-side tests passed.

Latest upgrade and acceptance results: [Production hardening](production-hardening.md).
