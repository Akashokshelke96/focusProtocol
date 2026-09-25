# Channel onboarding and UI colors

Implemented channel onboarding, folder creation, private OAuth client storage, shared callback routing, scoped connection status and publishing, channel selection in both dashboards, and persistent workspace colors.

**One requested item remains pending:** the active `app/video/branding.py::loop_branding` hard-codes Camping With Blues text. The supplied prompt explicitly forbids changes to branding overlays. The narrow exception requested in the task conversation has not yet been approved. The new watermark file/folder field is validated, created, and saved, but is not yet consumed by the active short-loop renderer. Do not consider Wolfie-specific video branding complete or publish a Wolfie render until this is resolved. No overlay, audio assembly, encoder, fingerprint/rotation, QC, or thumbnail compression code was changed by this task.

## Using the UI

Restart the Flask app to load the backend changes, then open Channels → Add channel (or Add channel in the classic dashboard). Enter Wolfie Blues and its Google OAuth client ID/secret. The slug and editable folders default to `wolfie-blues`, `music-wolfie`, `backgroundImages-wolfie`, `thumbnail-wolfie`, `watermark-wolfie`, and `jobs/output-wolfie`.

Select a channel before generating or connecting YouTube. The UI shows its connected YouTube channel title (not a Google email address) and video count. Camping With Blues defaults to forest green; new channels default to midnight blue. Forest, midnight, plum, and amber are editable in Edit profile. Selection survives page reloads and applies in both dashboards.

The canonical video and job records remain in `jobs/<job_id>/`. A channel with a separate output folder also receives a final MP4 copy under `<output_dir>/<job_id>/`, recorded as `channel_output_path`. This preserves existing job discovery, playback, publishing, and cleanup architecture.

## Credentials and routes

- `jobs/studio/credentials/<id>/client_secrets.json`: OAuth client configuration, outside profiles and `.env`.
- `jobs/studio/credentials/<id>/token.json`: non-default channel token.
- Existing configured `youtube_token.json`: unchanged default-channel token path.
- `youtube_oauth_state.json` beside the global token: expiring state/channel/PKCE attempts, protected by an exclusive lock; shared `/callback` dispatches to the matching channel.
- Windows credentials directories grant access to the account running the app, with inherited permissions removed. POSIX uses directory mode 0700 and client file mode 0600. This is account-level filesystem protection, not application-specific encryption.

No new public routes were needed. Existing routes were extended:

- `POST /api/studio/channels`: accepts OAuth fields, `watermark_path`, `output_dir`, `ui_palette`, and `create_only`; creates directories and never returns credentials.
- `GET /api/jazz/youtube/connect?channel=<id>` and shared `/callback`: selected client/token, state verification, existing account binding checked before replacing its token.
- `GET /api/jazz/youtube/status?channel=<id>`: selected connection, title/account, video count.
- Jazz jobs/components/queue/publish routes accept `channel`; generation accepts JSON `channel_id`.
- Existing Studio channel connect/connection and job publishing routes use the same isolation.

Missing channel parameters preserve legacy credential paths; old job state without a channel resolves to `focus-protocol`. Aggregate publishing resolves a service per channel, including thumbnail upload and post-upload verification through the existing lifecycle function. Wrong-channel upload requests are rejected.

## Verification

- All touched Python files compile; JavaScript syntax and Git whitespace checks pass.
- Focused regression suite: **59 passed, 1 skipped**. Mock Google flows cover token isolation, concurrent pending states, independent status, expired/replayed callbacks, wrong-account token preservation, publishing credential resolution, and selected generation folders. Pytest emitted cleanup warnings for old temporary directories protected by the credential ACL test; assertions passed.
- Real UI onboarding passed in an isolated workspace at `jobs/channel-ui-acceptance/`, using dummy OAuth values. Created profile and credentials: `jobs/channel-ui-acceptance/jobs/studio/operations.json` and `jobs/channel-ui-acceptance/jobs/studio/credentials/wolfie-blues-acceptance/client_secrets.json`. Music/background/thumbnail/watermark/output folders exist beneath that isolated workspace. No fake channel was added to the production store.
- Browser checks verified distinct green/blue backgrounds, saved palette edits across reloads, correct classic music folder, connection text/counts, and zero JavaScript errors. Screenshots: `docs/channel-onboarding-acceptance.png`, `docs/channel-classic-acceptance.png`.
- Real 1-minute focus-protocol job: `20260921_235721_320461_video_001`. QC passed. FFprobe: one H.264 video stream at 854×480, 15 FPS, 60.000 seconds; one AAC stream at 60.000 seconds; exactly one background. Existing token hash unchanged. Saved `output/render_commands.json` retains video copy for loop and mux, and audio copy for mux. The acceptance job is excluded from publishing. Evidence: `docs/channel-render-acceptance.json`.
- No real Google sign-in or upload was performed; the operator must supply Wolfie's real credentials and media.

## Files changed by this task

`app/studio/profiles.py`, `app/studio/channel_credentials.py` (new), `app/studio/service.py`, `app/studio/api.py`, `app/api/jazz_api.py`, `app/youtube/oauth.py`, `app/youtube/publishing.py`, `app/pipeline/long_form_jazz_orchestrator.py` (final export only), `static/channel-ui.js` and `.css` (new), `static/studio.js`, both dashboard templates, `tests/test_channel_onboarding.py` (new), and `tests/test_studio.py`.

Pre-existing changes in `app/studio/assets.py`, `app/youtube/lifecycle.py`, and the thumbnail portions of `app/youtube/publishing.py` were preserved. No commits were made.

## Removing a channel / rollback

Pause production and finish or cancel its queued work first. Back up `jobs/studio/operations.json`; remove only the chosen channel and its pending content/batch entries while the server is stopped. Keep the channel profile if you still need to operate on its historical jobs. After archiving its jobs, remove its credential directory to disconnect it and optionally remove its exclusively owned media/output folders. Never remove shared folders or `focus-protocol`'s existing token. Removing local credentials does not delete uploaded YouTube videos.

To undo code changes, revert only this task's hunks and new files, preserving the pre-existing thumbnail fixes. Existing default-channel folders/tokens and legacy job JSON do not need migration.

Task 4 was limited to palette/selector polish, scoped connection errors and publish logging. Broader render, audio, branding, motion, QC, thumbnail, and compression changes were deliberately skipped.
