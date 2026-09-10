# Easy YouTube workflow

Double-click `Start-YouTube.cmd` to run the dashboard using the existing project environment. It uses the lightweight Waitress server with four threads. Do not run a second server if port 5000 is already occupied.

1. Click **Connect YouTube**, choose the Google account/channel, and grant consent once.
2. Generate jazz videos as usual. **Publishing status** lists the completed jobs.
3. Click **Publish pending videos**. All eligible pending jobs are validated and scheduled, with no file picker.

PowerShell equivalents, from the project directory:

```powershell
.\youtube.cmd youtube-connect
.\youtube.cmd youtube-status
.\youtube.cmd youtube-publish --dry-run
.\youtube.cmd youtube-publish
.\youtube.cmd youtube-upload --video "D:/videos/video.mp4" --title "My video" --description "Description" --tags "jazz,study"
```

The same commands work through `python main.py` when the project environment is activated. The manual command accepts `--thumbnail`, `--scheduled-time "2026-10-01T09:00:00+05:30"`, and `--privacy-status`. Automatic scheduling applies by default; turn off `YOUTUBE_AUTO_SCHEDULE_ENABLED` for unscheduled uploads. Unscheduled uploads default to private.

Scheduling defaults to 09:00 and 18:00 in Asia/Kolkata, skips times less than 15 minutes away, and limits each local day to two reserved publishing slots. Existing channel schedules and local reservations are checked before uploading. Configure more daily slots with `YOUTUBE_VIDEOS_PER_DAY` and comma-separated `YOUTUBE_SCHEDULE_TIMES`. A dry run checks local state only; the real run checks the channel too. YouTube handles publication after the scheduled upload, so this PC need not stay running until publication time.

Each existing job gains a `youtube.json` journal. The original generation registry is retained for compatibility; publishing adds no database. Atomic replacement, a process lock and SHA-256 identity prevent concurrent and repeated intentional uploads. A durable `uploading` entry is saved before upload and the YouTube ID is saved before thumbnail work. On interrupted uploads, the next publishing run searches the channel for the hash tag. If no match is found, the job remains `needs_review`; absence from a possibly delayed API listing is never treated as permission to upload again. Check YouTube Studio in that case. Do not delete the journal to force a retry. Exhausted transient retries may need human review.

Existing jazz jobs missing titles because of the old prompt-formatting bug receive factual local metadata from their background title and duration. Missing metadata on arbitrary videos is rejected. Byte-identical files are flagged as duplicates even if job names differ. Test outputs can be excluded by setting `youtube_exclude: true` in their metadata.

The supplied root `youtube_token.json` contains client configuration. The authorized token is stored separately in `jobs/youtube_token.json`. Do not share either file. Local HTTP callbacks are validated and exchanged at Google's HTTPS token endpoint, without globally disabling HTTPS checks. Tokens refresh automatically. Google may require renewed consent after token revocation, client changes or consent-screen testing expiry.

OmniRoute is enabled in this workspace with `LLM_PROVIDER=omniroute` and `OMNIROUTE_MODEL=auto/best-fast`. Change the model route in `.env`; no provider account is purchased or created by the app. Both JSON and SSE responses are supported. Provider selection applies to the existing LLM class and its content, scene and metadata calls.

For a small-machine preview use 1280x720, 15 FPS, ultrafast, CRF 28. The production default is 1920x1080, 24 FPS, faster, CRF 25; this replaces the old implicit medium/CRF 18 fallback that made the small machine encode much longer. The render prepares the static crop once, keeps the small audio-derived waveform, copies the final AAC audio, and adds faststart. The CTA uses a bounded, reusable frame loop and a configurable four-second display. The provided clip's white margins are cropped and keyed out in this workspace. Other clips should use the default full-frame crop and disabled white key, then adjust as needed.

The active jazz mode has no narration or captions and intentionally retains one static background. The older documentary pipeline remains available, but this change does not turn instrumental jazz into narrated documentaries or supply forced-aligned captions.

Validation and checks:

```powershell
.venv\Scripts\python.exe -m pytest tests/test_publishing.py tests/test_waveform.py -q
$env:PYTHONPATH='.'
.venv\Scripts\python.exe tests/publishing_acceptance_runner.py
```

New dependency: `tzdata` (small timezone data package needed on Windows). It is included in requirements.txt and installed in the existing .venv.

Google reference: https://developers.google.com/youtube/v3/guides/uploading_a_video
YouTube may restrict uploads from unverified API projects to private viewing; publication eligibility is controlled by Google, not this scheduler.


## Processing recovery

Upload acceptance is not publishing success. The saved video ID is followed through processing, thumbnail upload, metadata, visibility and schedule verification. Checks default to 30-second intervals with an 1800-second timeout (YOUTUBE_PROCESSING_POLL_INTERVAL / YOUTUBE_PROCESSING_TIMEOUT).

Resume verification without uploading another copy:

```powershell
.\youtube.cmd youtube-retry JOB_ID
```

The existing per-video Upload action also resumes verification. Timeout and thumbnail failures preserve the ID. The queue pauses on an incomplete lifecycle. youtube-status refreshes remote processing state.

The launcher uses JAZZ_PORT (default 5001), independently of OmniRoute's PORT. New OAuth connections require http://localhost:5001/callback in the Google client's authorized redirect URIs; existing tokens remain usable.

Multi-channel and visual upgrades remain gated on one live video passing processing and publishing verification, as requested in the upgrade brief.
