"""FastAPI batch server that runs on the RunPod pod.

The local machine submits an approved batch, then polls ``GET /batch/{id}``
for per-video, per-stage progress and downloads the finished MP4s. All heavy
work (ComfyUI images, Kokoro TTS, WhisperX, FFmpeg) happens here.

Run on the pod::

    python -m app.narration.pod.server

Endpoints
    GET  /health
    GET  /batches
    POST /batch
    GET  /batch/{batch_id}
    POST /batch/{batch_id}/resume
    GET  /batch/{batch_id}/exports
    GET  /batch/{batch_id}/download/{name}

Install the pod extras first: ``pip install -r deploy/requirements-pod.txt``.
"""
from __future__ import annotations
import json
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from app.config.logging_config import get_logger
from app.config.settings import get_settings

logger = get_logger("narration.server")

try:
    from fastapi import Depends, FastAPI, Header, HTTPException
    from fastapi.responses import FileResponse
    from pydantic import BaseModel
except ImportError as error:  # pragma: no cover - pod-only dependency
    raise ImportError(
        "The pod batch server needs FastAPI + uvicorn. "
        "Install them with: pip install -r deploy/requirements-pod.txt") from error


class BatchItem(BaseModel):
    topic: str = ""
    title: str = ""
    script: str = ""
    duration_minutes: Optional[float] = None


class BatchRequest(BaseModel):
    items: list[BatchItem]
    batch_id: Optional[str] = None


app = FastAPI(title="Narration Batch Server", version="1.0")
_threads: dict[str, threading.Thread] = {}
_lock = threading.Lock()


# --------------------------------------------------------------- auth/helpers
def verify_token(token: Optional[str] = Header(default=None, alias="X-Batch-Token")) -> None:
    expected = get_settings().pod_batch_token
    if expected and token != expected:
        raise HTTPException(status_code=401, detail="invalid or missing X-Batch-Token")


def _workspace() -> Path:
    return Path(get_settings().narration_batch_workspace)


def _batch_dir(batch_id: str) -> Path:
    if not batch_id or any(ch in batch_id for ch in "/\\.."):
        raise HTTPException(status_code=400, detail="invalid batch id")
    return _workspace() / batch_id


def _read_state(batch_id: str) -> Optional[dict]:
    path = _batch_dir(batch_id) / "state.json"
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def _run_batch(batch_id: str, items: list[dict]) -> None:
    from app.narration.pod.batch_engine import BatchEngine
    try:
        engine = BatchEngine(get_settings(), _batch_dir(batch_id))
        engine.run(items, batch_id=batch_id)
    except Exception as error:  # noqa: BLE001 - surfaced through state.json
        logger.error("Batch %s crashed: %s", batch_id, error, exc_info=True)


def _items_payload(items: list[BatchItem]) -> list[dict]:
    return [
        {key: value for key, value in item.model_dump().items() if value not in (None, "")}
        for item in items
    ]


# ------------------------------------------------------------------- routes
@app.get("/health")
def health() -> dict:
    settings = get_settings()
    comfy: dict[str, Any] = {"configured": bool(settings.comfy_base_url), "reachable": False}
    if settings.comfy_base_url:
        try:
            import requests
            response = requests.get(f"{settings.comfy_base_url.rstrip('/')}/system_stats", timeout=8)
            comfy["reachable"] = response.status_code < 500
        except Exception as error:  # noqa: BLE001
            comfy["error"] = str(error)[:200]
    return {
        "status": "ok",
        "tts_backend": settings.narration_tts_backend,
        "align_backend": settings.narration_align_backend,
        "comfyui": comfy,
        "timestamp": datetime.utcnow().isoformat(),
    }


@app.get("/batches")
def list_batches(_: None = Depends(verify_token)) -> dict:
    root = _workspace()
    batches = []
    if root.is_dir():
        for directory in sorted(root.iterdir(), reverse=True):
            state = _read_state(directory.name)
            if state:
                batches.append({"batch_id": directory.name, "status": state.get("status"),
                                "phase": state.get("phase"),
                                "videos": len(state.get("videos", []))})
    return {"batches": batches}


@app.post("/batch")
def create_batch(payload: BatchRequest, _: None = Depends(verify_token)) -> dict:
    if not payload.items:
        raise HTTPException(status_code=400, detail="at least one item is required")
    batch_id = payload.batch_id or datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    directory = _batch_dir(batch_id)
    directory.mkdir(parents=True, exist_ok=True)
    with _lock:
        if batch_id in _threads and _threads[batch_id].is_alive():
            raise HTTPException(status_code=409, detail="this batch is already running")
        thread = threading.Thread(target=_run_batch, args=(batch_id, _items_payload(payload.items)),
                                  name=f"batch-{batch_id}", daemon=True)
        _threads[batch_id] = thread
    thread.start()
    logger.info("Batch %s started with %s videos", batch_id, len(payload.items))
    return {"batch_id": batch_id, "status": "started", "videos": len(payload.items)}


@app.post("/batch/{batch_id}/resume")
def resume_batch(batch_id: str, _: None = Depends(verify_token)) -> dict:
    state = _read_state(batch_id)
    if not state:
        raise HTTPException(status_code=404, detail="batch not found")
    items = [{"topic": v.get("topic", ""), "title": v.get("title", ""),
              "script": v.get("script", ""), "duration_minutes": v.get("duration_minutes")}
             for v in state.get("videos", [])]
    with _lock:
        thread = threading.Thread(target=_run_batch, args=(batch_id, items),
                                  name=f"batch-{batch_id}", daemon=True)
        _threads[batch_id] = thread
    thread.start()
    return {"batch_id": batch_id, "status": "resuming"}


@app.get("/batch/{batch_id}")
def batch_status(batch_id: str, _: None = Depends(verify_token)) -> dict:
    state = _read_state(batch_id)
    if not state:
        raise HTTPException(status_code=404, detail="batch not found")
    return state


@app.get("/batch/{batch_id}/exports")
def batch_exports(batch_id: str, _: None = Depends(verify_token)) -> dict:
    exports = _batch_dir(batch_id) / "exports"
    files = sorted(p.name for p in exports.iterdir()) if exports.is_dir() else []
    return {"batch_id": batch_id, "files": files}


@app.get("/batch/{batch_id}/download/{name}")
def download_export(batch_id: str, name: str, _: None = Depends(verify_token)):
    exports = _batch_dir(batch_id) / "exports"
    target = exports / name
    if not target.is_file() or target.parent.resolve() != exports.resolve():
        raise HTTPException(status_code=404, detail="export not found")
    return FileResponse(str(target), filename=name)


def run() -> None:
    """Launch the batch server with uvicorn on the configured host/port."""
    import uvicorn
    settings = get_settings()
    logger.info("Starting narration batch server on %s:%s", settings.pod_batch_host, settings.pod_batch_port)
    uvicorn.run(app, host=settings.pod_batch_host, port=settings.pod_batch_port)


if __name__ == "__main__":  # pragma: no cover - process entrypoint
    run()
