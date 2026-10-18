"""Local HTTP client for the pod batch server.

The local machine uses this to submit an approved batch, poll per-video
progress, and download finished MP4s/thumbnails. It talks only to the pod's
FastAPI server (``POD_BATCH_URL``); it never touches ComfyUI/TTS directly.
"""
from __future__ import annotations
import time
from pathlib import Path
from typing import Any, Callable, Optional

import requests

from app.config.logging_config import get_logger
from app.config.settings import Settings, get_settings

logger = get_logger("narration.pod_client")


class PodClientError(RuntimeError):
    """Raised when the pod batch server cannot be reached or returns an error."""


class PodBatchClient:
    def __init__(self, settings: Optional[Settings] = None, base_url: str = "",
                 token: str = "", timeout: int = 60):
        self.settings = settings or get_settings()
        self.base_url = (base_url or self.settings.pod_batch_url or "").rstrip("/")
        if not self.base_url:
            raise PodClientError("POD_BATCH_URL is not configured (e.g. "
                                 "https://<POD_ID>-8000.proxy.runpod.net)")
        self.token = token or self.settings.pod_batch_token
        self.timeout = timeout
        self.session = requests.Session()
        if self.token:
            self.session.headers["X-Batch-Token"] = self.token

    # ------------------------------------------------------------------ HTTP
    def _request(self, method: str, path: str, **kwargs) -> requests.Response:
        url = f"{self.base_url}{path}"
        kwargs.setdefault("timeout", self.timeout)
        try:
            response = self.session.request(method, url, **kwargs)
        except requests.RequestException as error:
            raise PodClientError(f"Pod request {method} {path} failed: {error}") from error
        if response.status_code >= 400:
            raise PodClientError(f"Pod returned {response.status_code} for {path}: {response.text[:300]}")
        return response

    def health(self) -> dict:
        return self._request("GET", "/health").json()

    def submit(self, items: list[dict], batch_id: str = "") -> dict:
        """Submit approved videos (topic/title/script/duration_minutes)."""
        payload: dict[str, Any] = {"items": items}
        if batch_id:
            payload["batch_id"] = batch_id
        return self._request("POST", "/batch", json=payload).json()

    def status(self, batch_id: str) -> dict:
        return self._request("GET", f"/batch/{batch_id}").json()

    def resume(self, batch_id: str) -> dict:
        return self._request("POST", f"/batch/{batch_id}/resume").json()

    def list_batches(self) -> list[dict]:
        return self._request("GET", "/batches").json().get("batches", [])

    def exports(self, batch_id: str) -> list[str]:
        return self._request("GET", f"/batch/{batch_id}/exports").json().get("files", [])

    def download(self, batch_id: str, name: str, dest_dir: Path) -> Path:
        dest_dir = Path(dest_dir)
        dest_dir.mkdir(parents=True, exist_ok=True)
        response = self._request("GET", f"/batch/{batch_id}/download/{name}", timeout=600)
        destination = dest_dir / name
        destination.write_bytes(response.content)
        logger.info("Downloaded %s -> %s", name, destination)
        return destination

    def download_all(self, batch_id: str, dest_dir: Path) -> list[Path]:
        return [self.download(batch_id, name, dest_dir) for name in self.exports(batch_id)]

    def fetch_export(self, batch_id: str, name: str) -> bytes:
        """Return raw export bytes (for streaming through the local dashboard)."""
        return self._request("GET", f"/batch/{batch_id}/download/{name}", timeout=600).content

    # ------------------------------------------------------------------ poll
    def is_terminal(self, state: dict) -> bool:
        return state.get("status") in ("completed", "completed_with_errors", "failed")

    def wait(self, batch_id: str, poll_seconds: Optional[float] = None,
             on_update: Optional[Callable[[dict], None]] = None,
             timeout: Optional[float] = None) -> dict:
        """Poll the batch until it finishes, reporting each state snapshot."""
        interval = poll_seconds or self.settings.pod_batch_poll_seconds
        deadline = time.time() + timeout if timeout else None
        last_phase = None
        while True:
            state = self.status(batch_id)
            if on_update:
                on_update(state)
            if self.is_terminal(state):
                return state
            if deadline and time.time() > deadline:
                raise PodClientError(f"Timed out waiting for batch {batch_id}")
            if state.get("phase") != last_phase:
                last_phase = state.get("phase")
                logger.info("Batch %s phase: %s", batch_id, last_phase)
            time.sleep(interval)
