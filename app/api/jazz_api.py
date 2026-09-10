"""
Jazz Video Generation API
RESTful backend for long-form jazz video generation and monitoring
"""
import json
import threading
from datetime import datetime
from pathlib import Path
from flask import Flask, render_template, jsonify, request, redirect
from flask_cors import CORS
from app.config.settings import get_settings, ensure_directories
from app.config.logging_config import get_logger, get_recent_logs, setup_logging
from app.pipeline.long_form_jazz_orchestrator import LongFormJazzOrchestrator
from app.jobs.manager import JobManager
from app.youtube.oauth import YouTubeService

logger = get_logger("api.jazz")

app = Flask(__name__, template_folder="../../templates", static_folder="../../static")
CORS(app)
setup_logging(get_settings().log_level)

# Global state
current_job = None
job_manager = JobManager()
generation_thread = None
publishing_task = {}
publishing_guard = threading.Lock()


@app.before_request
def protect_local_actions():
    from urllib.parse import urlsplit
    if request.method in ('POST', 'PUT', 'PATCH', 'DELETE'):
        origin = request.headers.get('Origin')
        if origin and urlsplit(origin).netloc != request.host:
            return jsonify(message='Use the local studio to change state'), 403


def _video_path(job_id):
    """Return the current run-local output path with legacy fallback."""
    run_dir = Path("jobs").resolve() / job_id
    run_output = run_dir / "output" / "final_90min_video.mp4"
    return run_output if run_output.exists() else run_dir / "video.mp4"


def _youtube_service():
    return YouTubeService(get_settings())


# ============================================================================
# HEALTH & STATUS
# ============================================================================

@app.route('/api/jazz/health', methods=['GET'])
def health():
    """Health check for jazz generation system."""
    return jsonify({
        "status": "healthy",
        "service": "jazz-video-generator",
        "timestamp": datetime.utcnow().isoformat()
    })


# ============================================================================
# GENERATION CONTROL
# ============================================================================

@app.route('/api/jazz/generate', methods=['POST'])
def start_generation():
    """Start a new jazz video generation."""
    global current_job, generation_thread

    try:
        data = request.get_json() or {}
        video_count = int(data.get('video_count', 1))
        if not 1 <= video_count <= 50:
            return jsonify({'message': 'Choose 1–50 videos'}), 400
        test_mode = data.get('test_mode', False)
        duration_minutes = max(1, min(int(data.get('duration_minutes', get_settings().target_duration_minutes)), 180))

        from app.studio.api import service as studio_service
        if (generation_thread and generation_thread.is_alive()) or any(c['stage'] == 'generating' for c in studio_service.store.read()['content']):
            return jsonify({
                "status": "error",
                "message": "Generation already in progress",
                "current_job": current_job
            }), 409

        # Start generation in background
        settings = get_settings().model_copy(deep=True)
        for key in ("waveform_enabled", "waveform_filter_enabled", "watermark_enabled", "subscribe_overlay_enabled"):
            if key in data:
                if type(data[key]) is not bool:
                    return jsonify({"status": "error", "message": f"{key} must be a boolean"}), 400
                setattr(settings, key, data[key])
        orchestrator = LongFormJazzOrchestrator(settings)

        def run_generation():
            global current_job
            job_id = datetime.now().strftime("%Y%m%d_%H%M%S_jazz")
            started_at = datetime.now().astimezone()
            current_job = {
                "job_id": job_id,
                "status": "running",
                "video_count": video_count,
                "test_mode": test_mode,
                "started_at": started_at.isoformat(),
                "duration_minutes": duration_minutes,
                "progress": 0,
                "message": "Initializing..."
            }

            try:
                success = orchestrator.run(
                    video_count=video_count,
                    test_mode=test_mode,
                    test_duration_minutes=3 if test_mode else None,
                    duration_minutes=duration_minutes,
                )

                if success:
                    current_job["status"] = "completed"
                    current_job["progress"] = 100
                    current_job["message"] = "Generation complete"
                    current_job["completed_at"] = datetime.utcnow().isoformat()

                    real_job_ids = orchestrator.last_job_ids
                    if real_job_ids:
                        job_id = real_job_ids[-1]
                        current_job["job_id"] = job_id

                    # Load metadata
                    job_dir = Path("jobs") / job_id
                    metadata_path = job_dir / "metadata.json"
                    if metadata_path.exists():
                        with open(metadata_path) as f:
                            current_job["metadata"] = json.load(f)
                        current_job["started_at"] = current_job["metadata"].get("started_at", current_job["started_at"])
                        current_job["completed_at"] = current_job["metadata"].get("completed_at")
                        current_job["total_elapsed_seconds"] = current_job["metadata"].get("total_elapsed_seconds")
                        if current_job["metadata"].get("fallback_used"):
                            current_job["status"] = "completed_with_fallback"

                    video_path = _video_path(job_id)
                    if video_path.exists():
                        current_job["video_path"] = str(video_path)
                else:
                    current_job["status"] = "failed"
                    current_job["message"] = "Generation failed"
                    if orchestrator.last_job_ids:
                        failed_job_id = orchestrator.last_job_ids[-1]
                        failed_metadata_path = Path("jobs") / failed_job_id / "metadata.json"
                        if failed_metadata_path.exists():
                            current_job["job_id"] = failed_job_id
                            with open(failed_metadata_path, encoding="utf-8") as metadata_file:
                                current_job["metadata"] = json.load(metadata_file)
                            current_job["completed_at"] = current_job["metadata"].get("completed_at")
                            current_job["total_elapsed_seconds"] = current_job["metadata"].get("total_elapsed_seconds")

            except Exception as e:
                current_job["status"] = "failed"
                current_job["message"] = str(e)
                current_job["completed_at"] = datetime.now().astimezone().isoformat()
                current_job["total_elapsed_seconds"] = round(
                    (datetime.fromisoformat(current_job["completed_at"]) - started_at).total_seconds(), 3
                )
                logger.error(f"Generation failed: {e}", exc_info=True)

        generation_thread = threading.Thread(target=run_generation, daemon=True)
        generation_thread.start()

        return jsonify({
            "status": "success",
            "message": "Generation started",
            "job": current_job
        }), 202

    except Exception as e:
        logger.error(f"Failed to start generation: {e}")
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500


@app.route('/api/jazz/status', methods=['GET'])
def get_status():
    """Get current generation status."""
    if current_job:
        return jsonify({
            "status": "success",
            "job": current_job
        })
    else:
        return jsonify({
            "status": "success",
            "job": None,
            "message": "No active generation"
        })


@app.route('/api/jazz/cancel', methods=['POST'])
def cancel_generation():
    """Cancel current generation."""
    global current_job, generation_thread

    if not current_job or current_job.get('status') != 'running':
        return jsonify({
            "status": "error",
            "message": "No generation in progress"
        }), 400

    return jsonify({'status': 'error', 'message': 'The active render must finish. Pause production in Studio to stop additional queued videos.'}), 409


# ============================================================================
# JOB HISTORY
# ============================================================================

@app.route('/api/jazz/jobs', methods=['GET'])
def list_jobs():
    """List recent jazz video jobs."""
    try:
        limit = request.args.get('limit', 10, type=int)
        jobs = job_manager.list_jobs(limit=limit)

        # Filter only jazz jobs
        jazz_jobs = [j for j in jobs if 'jazz' in j.id.lower() or 'Long-form Jazz Video' in j.topic]

        job_list = []
        for job in jazz_jobs:
            job_dict = job.to_dict()

            # Load metadata if exists
            job_dir = Path("jobs") / job.id
            metadata_path = job_dir / "metadata.json"
            if metadata_path.exists():
                try:
                    with open(metadata_path) as f:
                        job_dict["metadata"] = json.load(f)
                except:
                    pass

            # Add video path
            video_path = _video_path(job.id)
            if video_path.exists():
                job_dict["video_path"] = str(video_path)

            job_list.append(job_dict)

        return jsonify({
            "status": "success",
            "count": len(job_list),
            "jobs": job_list
        })

    except Exception as e:
        logger.error(f"Failed to list jobs: {e}")
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500


@app.route('/api/jazz/logs', methods=['GET'])
def get_logs():
    """Return recent server logs for the live dashboard panel."""
    return jsonify({"status": "success", "logs": get_recent_logs(request.args.get('limit', 200, type=int))})


@app.route('/api/jazz/components', methods=['GET'])
def component_status():
    """Return lightweight component readiness without exposing credentials."""
    settings = get_settings()
    background_prompts = Path("app/pipeline/backgroundImagesPrompts.json")
    thumbnail_dir = Path("thumbnail")
    local_thumbnail_count = sum(
        1 for path in thumbnail_dir.glob("*")
        if path.is_file() and path.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}
    ) if thumbnail_dir.exists() else 0
    image_ready = bool(settings.colab_image_api_url)
    return jsonify({"status": "success", "components": {
        "image_generator": {"status": "healthy" if image_ready else "warning", "message": "Configured" if image_ready else "COLAB_IMAGE_API_URL missing"},
        "background_prompt": {"status": "healthy" if background_prompts.exists() else "error"},
        "thumbnail": {"status": "healthy" if local_thumbnail_count else "error", "message": f"{local_thumbnail_count} local thumbnail(s) available"},
        "music": {"status": "healthy", "message": "Local music pipeline ready"},
        "video_renderer": {"status": "healthy", "message": "Static FFmpeg renderer ready"},
        "youtube": _youtube_service().connection_status(),
    }})


@app.route('/api/jazz/youtube/connect', methods=['GET'])
def youtube_connect():
    """Start the server-side Google OAuth flow."""
    try:
        return redirect(_youtube_service().authorization_url())
    except Exception as error:
        logger.error("YouTube OAuth start failed: %s", error, exc_info=True)
        return jsonify({"status": "error", "message": str(error)}), 400


@app.route('/api/jazz/youtube/callback', methods=['GET'])
@app.route('/callback', methods=['GET'])
def youtube_callback():
    """Receive Google's OAuth callback without exposing tokens to the browser."""
    try:
        if request.args.get("error"):
            raise RuntimeError(f"YouTube OAuth authorization failed: {request.args['error']}")
        from app.studio.api import complete_channel_callback
        status = complete_channel_callback(request.url) or _youtube_service().complete_authorization(request.url)
        if not status.get("connected"):
            raise RuntimeError(status.get("error", "No YouTube channel found"))
        return redirect("/?youtube=connected")
    except Exception as error:
        logger.error("YouTube OAuth callback failed: %s", error, exc_info=True)
        from urllib.parse import urlencode
        return redirect("/?" + urlencode({"youtube_error": str(error)}))


@app.route('/api/jazz/youtube/status', methods=['GET'])
def youtube_status():
    return jsonify({"status": "success", **_youtube_service().connection_status()})


@app.route('/api/jazz/youtube/queue', methods=['GET'])
def youtube_queue():
    from app.youtube.publishing import PublishingQueue
    try:
        return jsonify({'jobs': PublishingQueue(get_settings()).scan(), 'operation': publishing_task})
    except Exception as error:
        return jsonify({'status': 'error', 'message': str(error)}), 400


@app.route('/api/jazz/youtube/publish', methods=['POST'])
@app.route('/api/jazz/video/<job_id>/upload', methods=['POST'])
def upload_video(job_id=None):
    """Preserve legacy action URLs while using channel-aware durable batches."""
    from app.studio.api import service
    try:
        ids = [job_id] if job_id else [r['job_id'] for r in service.jobs() if r['stage'] == 'ready_to_publish']
        batch = service.enqueue_publish(ids)
        return jsonify({'status': 'accepted', 'message': 'Publishing batch queued', 'batch': batch}), 202
    except (ValueError, RuntimeError) as error:
        return jsonify({'status': 'error', 'message': str(error)}), 400


@app.route('/api/jazz/jobs/<job_id>', methods=['GET'])
def get_job(job_id):
    """Get specific job details."""
    try:
        job = job_manager.get_job(job_id)
        if not job:
            return jsonify({
                "status": "error",
                "message": "Job not found"
            }), 404

        job_dict = job.to_dict()

        # Load metadata
        job_dir = Path("jobs") / job_id
        metadata_path = job_dir / "metadata.json"
        if metadata_path.exists():
            with open(metadata_path) as f:
                job_dict["metadata"] = json.load(f)

        # Add video path
        video_path = _video_path(job_id)
        if video_path.exists():
            job_dict["video_path"] = str(video_path)

        return jsonify({
            "status": "success",
            "job": job_dict
        })

    except Exception as e:
        logger.error(f"Failed to get job: {e}")
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500


# ============================================================================
# VIDEO PREVIEW & DOWNLOAD
# ============================================================================

@app.route('/api/jazz/video/<job_id>/preview', methods=['GET'])
def get_video_preview(job_id):
    """Get video preview info."""
    try:
        job_dir = Path("jobs") / job_id
        video_path = _video_path(job_id)

        if not video_path.exists():
            return jsonify({
                "status": "error",
                "message": "Video not found"
            }), 404

        # Get file info
        file_size = video_path.stat().st_size
        size_mb = file_size / (1024 * 1024)

        # Load metadata
        metadata_path = job_dir / "metadata.json"
        metadata = {}
        if metadata_path.exists():
            with open(metadata_path) as f:
                metadata = json.load(f)

        return jsonify({
            "status": "success",
            "preview": {
                "video_path": str(video_path),
                "file_size_mb": round(size_mb, 2),
                "metadata": metadata,
                "ready_for_upload": True
            }
        })

    except Exception as e:
        logger.error(f"Failed to get video preview: {e}")
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500


@app.route('/api/jazz/video/<job_id>/download', methods=['GET'])
def download_video(job_id):
    """Download video file."""
    from flask import send_file

    try:
        job_dir = Path("jobs") / job_id
        video_path = _video_path(job_id)

        if not video_path.exists():
            return jsonify({
                "status": "error",
                "message": "Video not found"
            }), 404

        return send_file(
            video_path,
            mimetype='video/mp4',
            as_attachment=True,
            download_name=f"jazz_{job_id}.mp4"
        )

    except Exception as e:
        logger.error(f"Failed to download video: {e}")
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500


# ============================================================================
# UI ROUTES
# ============================================================================

@app.route('/', methods=['GET'])
def index():
    """Main dashboard."""
    return render_template('studio.html')


@app.route('/legacy')
def legacy_dashboard():
    return render_template('jazz_dashboard.html', settings=get_settings())


@app.route('/jobs', methods=['GET'])
def jobs_page():
    """Jobs history page."""
    return redirect('/#production')


@app.route('/job/<job_id>', methods=['GET'])
def job_detail_page(job_id):
    """Job detail page."""
    return redirect('/#job/' + job_id)


# ============================================================================
# ERROR HANDLERS
# ============================================================================

@app.errorhandler(404)
def not_found(e):
    """Handle 404 errors."""
    return jsonify({
        "status": "error",
        "message": "Not found"
    }), 404


@app.errorhandler(500)
def server_error(e):
    """Handle 500 errors."""
    logger.error(f"Server error: {e}")
    return jsonify({
        "status": "error",
        "message": "Internal server error"
    }), 500


from app.studio.api import studio
app.register_blueprint(studio)

if __name__ == '__main__':
    ensure_directories()
    app.run(debug=False, port=5001, host='127.0.0.1')
