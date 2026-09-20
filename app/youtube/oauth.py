"""Server-side YouTube OAuth and resumable upload support."""
from __future__ import annotations

import json
import secrets
import time
from urllib.parse import urlsplit, parse_qs
from pathlib import Path
from typing import Any, Callable, Optional

from app.config.logging_config import get_logger
from app.config.settings import Settings
from app.youtube.state import write_json

logger = get_logger("youtube.oauth")
SCOPES = ["https://www.googleapis.com/auth/youtube.upload", "https://www.googleapis.com/auth/youtube.readonly", "https://www.googleapis.com/auth/youtube.force-ssl"]


class YouTubeService:
    """Own OAuth tokens and YouTube API calls; never expose credentials to the UI."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.token_path = Path(settings.youtube_token_file)
        self.state_path = self.token_path.with_name('youtube_oauth_state.json')

    def _client_config(self) -> dict[str, Any]:
        config_path = Path(self.settings.youtube_client_secrets_file)
        if config_path.is_file():
            config = json.loads(config_path.read_text(encoding='utf-8'))
            if 'web' in config or 'installed' in config:
                return config
        missing = [
            name for name, value in {
                "YOUTUBE_CLIENT_ID": self.settings.youtube_client_id,
                "YOUTUBE_CLIENT_SECRET": self.settings.youtube_client_secret,
                "YOUTUBE_REDIRECT_URI": self.settings.youtube_redirect_uri,
            }.items() if not value
        ]
        if missing:
            raise RuntimeError(f"Missing configuration: {', '.join(missing)}")
        return {"web": {
            "client_id": self.settings.youtube_client_id,
            "client_secret": self.settings.youtube_client_secret,
            "redirect_uris": [self.settings.youtube_redirect_uri],
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
        }}

    def authorization_url(self) -> str:
        from google_auth_oauthlib.flow import Flow

        flow = Flow.from_client_config(self._client_config(), scopes=SCOPES)
        flow.redirect_uri = self.settings.youtube_redirect_uri
        url, state = flow.authorization_url(access_type="offline", prompt="consent select_account", include_granted_scopes="true")
        state_file = json.loads(self.state_path.read_text()) if self.state_path.exists() else {}
        attempts = state_file.get('attempts') or ([state_file] if state_file.get('state') else [])
        attempts = [item for item in attempts if time.time() - item.get('created', 0) <= 600]
        attempts.append({'state': state, 'created': time.time(), 'verifier': flow.code_verifier})
        write_json(self.state_path, {'attempts': attempts[-5:]})
        return url

    def complete_authorization(self, authorization_response: str) -> dict[str, Any]:
        from google_auth_oauthlib.flow import Flow

        parsed = urlsplit(authorization_response)
        configured = urlsplit(self.settings.youtube_redirect_uri)
        if (parsed.scheme, parsed.netloc, parsed.path) != (configured.scheme, configured.netloc, configured.path):
            raise ValueError('OAuth callback does not match YOUTUBE_REDIRECT_URI')
        if parsed.scheme != 'https' and not (parsed.scheme == 'http' and parsed.hostname in ('localhost', '127.0.0.1', '::1')):
            raise ValueError('HTTP OAuth redirects are allowed only on localhost')
        query = parse_qs(parsed.query)
        state_file = json.loads(self.state_path.read_text()) if self.state_path.exists() else {}
        attempts = state_file.get('attempts') or ([state_file] if state_file.get('state') else [])
        returned_state = query.get('state', [''])[0]
        saved = next((item for item in attempts if time.time() - item.get('created', 0) <= 600 and secrets.compare_digest(returned_state, item.get('state', 'missing'))), None)
        if not saved:
            raise ValueError('OAuth state is invalid or expired. Start Connect YouTube again.')
        if not query.get('code'):
            raise ValueError('Google did not return an authorization code')
        flow = Flow.from_client_config(self._client_config(), scopes=SCOPES, state=saved['state'], code_verifier=saved.get('verifier'))
        flow.redirect_uri = self.settings.youtube_redirect_uri
        # Validate the loopback callback ourselves, then exchange over Google's HTTPS endpoint.
        flow.fetch_token(code=query['code'][0])
        self.token_path.parent.mkdir(parents=True, exist_ok=True)
        write_json(self.token_path, json.loads(flow.credentials.to_json()))
        remaining = [item for item in attempts if item != saved and time.time() - item.get('created', 0) <= 600]
        if remaining:
            write_json(self.state_path, {'attempts': remaining})
        else:
            self.state_path.unlink(missing_ok=True)
        logger.info("YouTube OAuth completed; token stored server-side")
        return self.connection_status()

    def _credentials(self):
        from google.oauth2.credentials import Credentials

        if not self.token_path.exists():
            return None
        credentials = Credentials.from_authorized_user_file(str(self.token_path))
        if credentials.expired and credentials.refresh_token:
            from google.auth.transport.requests import Request
            from functools import partial
            credentials.refresh(partial(Request(), timeout=20))
            write_json(self.token_path, json.loads(credentials.to_json()))
        return credentials if credentials.valid else None

    def connection_status(self) -> dict[str, Any]:
        try:
            credentials = self._credentials()
            if not credentials:
                return {"connected": False, "channel_name": None, "error": "Connect YouTube once to authorize your channel."}
            response = self.client(timeout=20).channels().list(part="snippet", mine=True).execute()
            items = response.get("items", [])
            name = items[0].get("snippet", {}).get("title") if items else None
            return {"connected": bool(items), "channel_name": name, "channel_id": items[0]['id'] if items else None,
                    'can_edit_published': any(credentials.has_scopes([scope]) for scope in ('https://www.googleapis.com/auth/youtube', 'https://www.googleapis.com/auth/youtube.force-ssl'))}
        except Exception as error:
            logger.error("YouTube connection check failed: %s", error, exc_info=True)
            return {"connected": False, "channel_name": None, "error": str(error)}

    def upload(
        self,
        video_path: Path,
        metadata: dict[str, Any],
        progress_callback: Optional[Callable[[float], None]] = None,
        uploaded_callback: Optional[Callable[[dict], None]] = None,
    ) -> dict[str, Any]:
        if not video_path.exists() or not video_path.is_file():
            raise FileNotFoundError(f"Video file is not readable: {video_path}")
        credentials = self._credentials()
        if not credentials:
            raise RuntimeError("YouTube account is not connected. Click Connect YouTube to authorize the account.")

        from googleapiclient.discovery import build
        from googleapiclient.http import MediaFileUpload

        body = {
            "snippet": {
                "title": metadata['title'],
                "description": metadata.get('description', ''),
                "tags": metadata.get('tags', []),
                "categoryId": str(metadata.get('category', self.settings.youtube_category)),
            },
            "status": {"privacyStatus": metadata.get('privacy_status', 'private'), "selfDeclaredMadeForKids": False},
        }
        if metadata.get('scheduled_publish_time'):
            from datetime import datetime, timezone
            scheduled = datetime.fromisoformat(metadata['scheduled_publish_time'].replace('Z', '+00:00'))
            if scheduled.tzinfo is None or scheduled <= datetime.now(timezone.utc):
                raise ValueError('Scheduled publish time must be timezone-aware and in the future')
            body['status'].update(privacyStatus='private', publishAt=scheduled.isoformat())
        if self.settings.youtube_language:
            body['snippet']['defaultLanguage'] = self.settings.youtube_language
        media = MediaFileUpload(str(video_path), mimetype="video/mp4", chunksize=8 * 1024 * 1024, resumable=True)
        client = self.client()
        request = client.videos().insert(part="snippet,status", body=body, media_body=media)
        response = None
        while response is None:
            _, response = request.next_chunk(num_retries=self.settings.max_retries)
            if progress_callback and media.size() and request.resumable_progress is not None:
                progress_callback(min(100.0, request.resumable_progress * 100.0 / media.size()))
        video_id = response.get("id")
        if not video_id:
            raise RuntimeError(f"YouTube upload returned no video ID: {json.dumps(response)}")
        logger.info("YouTube upload completed: %s", video_id)
        result = {"video_id": video_id, "watch_url": f"https://www.youtube.com/watch?v={video_id}", "remote_status": response.get('status', {})}
        if uploaded_callback:
            uploaded_callback(result)
        return result

    def video_details(self, video_id):
        items = self.client().videos().list(part='snippet,status,processingDetails,contentDetails', id=video_id).execute(num_retries=self.settings.max_retries).get('items', [])
        if not items:
            raise RuntimeError('Saved video is unavailable to this account; automatic re-upload is blocked.')
        return items[0]

    def upload_thumbnail(self, video_id, path):
        from googleapiclient.http import MediaFileUpload
        result = self.client().thumbnails().set(videoId=video_id, media_body=MediaFileUpload(str(path))).execute(num_retries=self.settings.max_retries)
        if not result.get('items'):
            raise RuntimeError('YouTube did not confirm the thumbnail upload')
        return result

    def update_metadata(self, video_id, metadata):
        """Apply only the snippet fields the operator edited."""
        self._require_edit_scope()
        existing = self.video_details(video_id).get('snippet', {})
        snippet = {key: existing[key] for key in ('defaultLanguage', 'defaultAudioLanguage') if key in existing}
        snippet.update({'title': metadata['title'], 'description': metadata.get('description', ''),
                   'tags': list(metadata.get('tags', [])), 'categoryId': str(metadata.get('category', self.settings.youtube_category))}
        )
        if metadata.get('sha256'):
            snippet['tags'].append('engine-sha256-' + metadata['sha256'])
        return self.client().videos().update(part='snippet', body={'id': video_id, 'snippet': snippet}).execute(num_retries=self.settings.max_retries)

    def update_schedule(self, video_id, scheduled):
        from app.youtube.publishing import instant
        from datetime import datetime, timezone
        if instant(scheduled) <= datetime.now(timezone.utc):
            raise ValueError('Schedule must be in the future')
        self._require_edit_scope()
        existing = self.video_details(video_id).get('status', {})
        if existing.get('privacyStatus') != 'private':
            raise ValueError('Only a private, never-published video can be scheduled')
        status = {key: existing[key] for key in ('license', 'embeddable', 'publicStatsViewable', 'selfDeclaredMadeForKids', 'containsSyntheticMedia') if key in existing}
        status.update(privacyStatus='private', publishAt=scheduled)
        return self.client().videos().update(part='status', body={'id': video_id, 'status': status}).execute(num_retries=self.settings.max_retries)

    def _require_edit_scope(self):
        credentials = self._credentials()
        if not credentials or not any(credentials.has_scopes([scope]) for scope in ('https://www.googleapis.com/auth/youtube', 'https://www.googleapis.com/auth/youtube.force-ssl')):
            raise ValueError('Reconnect this channel in Channels to authorize editing existing YouTube metadata and schedules. New uploads remain available.')

    def client(self, timeout=60):
        import httplib2
        import google_auth_httplib2
        from googleapiclient.discovery import build
        credentials = self._credentials()
        if not credentials:
            raise RuntimeError('Connect YouTube once before publishing.')
        http = httplib2.Http(timeout=timeout)
        http.follow_redirects = False
        transport = google_auth_httplib2.AuthorizedHttp(credentials, http=http)
        return build('youtube', 'v3', http=transport, cache_discovery=False)

    def channel_videos(self):
        """Read every upload to reconcile crash markers and reserve remote slots."""
        client = self.client()
        channels = client.channels().list(part='contentDetails', mine=True).execute(num_retries=3).get('items', [])
        if not channels:
            raise RuntimeError('The authorized Google account has no YouTube channel.')
        playlist = channels[0]['contentDetails']['relatedPlaylists']['uploads']
        videos, token = [], None
        while True:
            page = client.playlistItems().list(part='contentDetails', playlistId=playlist, maxResults=50, pageToken=token).execute(num_retries=3)
            ids = [item['contentDetails']['videoId'] for item in page.get('items', [])]
            if ids:
                videos.extend(client.videos().list(part='snippet,status', id=','.join(ids)).execute(num_retries=3).get('items', []))
            token = page.get('nextPageToken')
            if not token:
                return videos
