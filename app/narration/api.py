"""Flask blueprint exposing the narrated pipeline (/api/narration/*).

The API always auto-approves the script because a background web thread
cannot drive the interactive CLI gate. Use the CLI (``main.py narration``)
when you want the manual script review step, or stop after script generation
and resume with ``main.py narration-approve``.
"""
from __future__ import annotations
import threading
from datetime import datetime
from pathlib import Path

import requests
from flask import Blueprint, Response, jsonify, render_template, request

from app.config.logging_config import get_logger
from app.config.settings import get_settings
from app.jobs.manager import JobManager
from app.narration.config import remote_health_targets
from app.narration.pod_client import PodBatchClient, PodClientError

logger = get_logger("narration.api")

narration_api = Blueprint("narration_api", __name__)
job_manager = JobManager()

_state = {"thread": None, "job": None}
_state_lock = threading.Lock()


@narration_api.route("/api/narration/health", methods=["GET"])
def narration_health():
    """Report reachability of the configured remote services."""
    settings = get_settings()
    targets = remote_health_targets(settings)
    results = {}
    for name, url in targets.items():
        if not url:
            results[name] = {"configured": False, "reachable": False}
            continue
        try:
            response = requests.get(url, timeout=8)
            results[name] = {"configured": True, "reachable": response.status_code < 500,
                             "status_code": response.status_code}
        except requests.RequestException as error:
            results[name] = {"configured": True, "reachable": False, "error": str(error)[:200]}
    return jsonify({
        "remote_enabled": settings.narration_remote_enabled,
        "services": results,
        "timestamp": datetime.utcnow().isoformat(),
    })


@narration_api.route("/api/narration/generate", methods=["POST"])
def narration_generate():
    """Start a narrated generation job in the background (script auto-approved)."""
    with _state_lock:
        if _state["thread"] and _state["thread"].is_alive():
            return jsonify({"status": "error", "message": "A narration job is already running",
                            "job_id": (_state["job"] or {}).get("job_id")}), 409

    data = request.get_json() or {}
    topic = (data.get("topic") or "").strip()
    if not topic:
        return jsonify({"status": "error", "message": "A topic is required"}), 400
    duration = max(1.0, min(float(data.get("duration_minutes", 10)), 30.0))
    count = max(1, min(int(data.get("count", 1)), 5))
    settings = get_settings()

    def worker():
        from app.narration.orchestrator import NarrationOrchestrator
        try:
            orchestrator = NarrationOrchestrator(settings)
            success = orchestrator.run(topic, duration_minutes=duration,
                                       auto_approve=True, count=count)
            with _state_lock:
                _state["job"] = {
                    "job_id": orchestrator.last_job_ids[-1] if orchestrator.last_job_ids else None,
                    "status": "completed" if success else "failed",
                    "completed_at": datetime.utcnow().isoformat(),
                }
        except Exception as error:  # noqa: BLE001 - surfaced through job state
            logger.error("Narration worker failed: %s", error, exc_info=True)
            with _state_lock:
                _state["job"] = {"status": "failed", "error": str(error)}

    thread = threading.Thread(target=worker, name="narration-generate", daemon=True)
    with _state_lock:
        _state["thread"] = thread
        _state["job"] = {"status": "running", "topic": topic, "started_at": datetime.utcnow().isoformat()}
    thread.start()
    return jsonify({"status": "started", "message": "Narration generation started"}), 202


@narration_api.route("/api/narration/jobs", methods=["GET"])
def narration_jobs():
    limit = max(1, min(int(request.args.get("limit", 20)), 100))
    jobs = [job for job in job_manager.list_jobs(limit * 3) if (job.metadata or {}).get("narration_mode")]
    return jsonify({"jobs": [job.to_dict() for job in jobs[:limit]]})


@narration_api.route("/api/narration/status/<job_id>", methods=["GET"])
def narration_status(job_id: str):
    job = job_manager.get_job(job_id)
    if not job:
        return jsonify({"status": "error", "message": "Job not found"}), 404
    metadata_path = Path("jobs") / job_id / "metadata.json"
    metadata = job.metadata or {}
    if metadata_path.is_file():
        import json
        try:
            metadata = {**metadata, **json.loads(metadata_path.read_text(encoding="utf-8"))}
        except json.JSONDecodeError:
            pass
    return jsonify({
        "job_id": job.id,
        "stage": job.stage,
        "status": job.status,
        "error_message": job.error_message,
        "metadata": metadata,
    })


@narration_api.route("/api/narration/approve/<job_id>", methods=["POST"])
def narration_approve(job_id: str):
    """Mark a saved script approved so the job can be resumed from the CLI."""
    from app.narration.models import ScriptPlan
    script_path = Path("jobs") / job_id / "script" / "script.json"
    if not script_path.is_file():
        return jsonify({"status": "error", "message": "No script found for this job"}), 404
    plan = ScriptPlan.model_validate_json(script_path.read_text(encoding="utf-8"))
    plan.approved = True
    script_path.write_text(plan.model_dump_json(indent=2), encoding="utf-8")
    return jsonify({"status": "approved", "job_id": job_id, "title": plan.title})


# --------------------------------------------------------------------------
# Pod batch dashboard + proxy endpoints.
# The local dashboard polls these; they forward to the pod FastAPI server.
# --------------------------------------------------------------------------
def _pod_client() -> PodBatchClient:
    return PodBatchClient(get_settings())


def _pod_error(error: Exception):
    return jsonify({"configured": True, "status": "error", "message": str(error)}), 502


@narration_api.route("/narration", methods=["GET"])
def narration_dashboard():
    """Serve the per-video batch progress dashboard."""
    settings = get_settings()
    return render_template("narration_dashboard.html", settings=settings,
                           pod_configured=bool(settings.pod_batch_url))


@narration_api.route("/api/narration/batches", methods=["GET"])
def narration_batches():
    try:
        return jsonify({"configured": True, "batches": _pod_client().list_batches()})
    except PodClientError as error:
        return _pod_error(error)


@narration_api.route("/api/narration/batch/<batch_id>", methods=["GET"])
def narration_batch_status(batch_id: str):
    try:
        return jsonify(_pod_client().status(batch_id))
    except PodClientError as error:
        return _pod_error(error)


@narration_api.route("/api/narration/batch", methods=["POST"])
def narration_batch_submit():
    data = request.get_json() or {}
    topics = data.get("topics") or []
    if isinstance(topics, str):
        topics = [topic.strip() for topic in topics.split(",") if topic.strip()]
    items = [{"topic": topic, "duration_minutes": data.get("duration_minutes")} for topic in topics]
    items += data.get("items") or []
    if not items:
        return jsonify({"status": "error", "message": "Provide topics or items"}), 400
    try:
        return jsonify(_pod_client().submit(items, batch_id=data.get("batch_id", "") or "")), 202
    except PodClientError as error:
        return _pod_error(error)


@narration_api.route("/api/narration/batch/<batch_id>/resume", methods=["POST"])
def narration_batch_resume(batch_id: str):
    try:
        return jsonify(_pod_client().resume(batch_id))
    except PodClientError as error:
        return _pod_error(error)


@narration_api.route("/api/narration/exports/<batch_id>", methods=["GET"])
def narration_exports(batch_id: str):
    try:
        return jsonify({"files": _pod_client().exports(batch_id)})
    except PodClientError as error:
        return _pod_error(error)


@narration_api.route("/api/narration/download/<batch_id>/<name>", methods=["GET"])
def narration_download(batch_id: str, name: str):
    try:
        content = _pod_client().fetch_export(batch_id, name)
    except PodClientError as error:
        return _pod_error(error)
    mimetype = "video/mp4" if name.endswith(".mp4") else "image/png"
    return Response(content, mimetype=mimetype,
                    headers={"Content-Disposition": f'attachment; filename="{name}"'})
