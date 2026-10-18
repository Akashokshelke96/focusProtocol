"""
Jazz Video Generation API
RESTful backend for long-form jazz video generation and monitoring
"""
import json
import subprocess
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
from app.narration.api import narration_api

logger = get_logger("api.jazz")

app = Flask(__name__, template_folder="../../templates", static_folder="../../static")
CORS(app)
app.register_blueprint(narration_api)
app.config['MAX_CONTENT_LENGTH'] = 512 * 1024 * 1024
setup_logging(get_settings().log_level)

# Global state
current_job = None
job_manager = JobManager()
generation_thread = None
active_orchestrator = None
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
    from app.studio.store import read_json
    saved = read_json(run_dir / 'metadata.json', {}).get('video_path')
    if saved:
        path = Path(saved).resolve()
        if path.is_relative_to(run_dir) and path.is_file():
            return path
    run_output = run_dir / "output" / "final_90min_video.mp4"
    return run_output if run_output.exists() else run_dir / "video.mp4"


def _youtube_service():
    if request.args.get('channel'):
        from app.studio.api import service, channel_oauth
        return channel_oauth(service.store.channel(request.args['channel']))
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
    global current_job, generation_thread, active_orchestrator

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
        for key in ("visualizer_enabled", "watermark_enabled", "subscribe_overlay_enabled",
                      "dust_enabled", "branding_enabled",
                      "audio_crossfade_enabled", "audio_loudness_enabled",
                      "audio_fades_enabled", "audio_silence_removal_enabled"):
            if key in data:
                if type(data[key]) is not bool:
                    return jsonify({"status": "error", "message": f"{key} must be a boolean"}), 400
                setattr(settings, key, data[key])
        if 'waveform_enabled' in data and 'visualizer_enabled' not in data:
            if type(data['waveform_enabled']) is not bool:
                return jsonify(message='visualizer_enabled must be a boolean'), 400
            settings.visualizer_enabled = data['waveform_enabled']
        settings.waveform_enabled = False
        from app.config.settings import Settings
        overrides = {key.upper(): data[key] for key in ('quality_preset', 'visual_effect', 'visual_effect_opacity', 'subscribe_overlay_interval_seconds', 'subscribe_overlay_width_ratio', 'subscribe_overlay_file') if key in data}
        try:
            settings = Settings.model_validate({**settings.model_dump(by_alias=True), **overrides})
        except ValueError:
            return jsonify(message='Choose a valid quality preset, video filter/intensity, and subscribe interval/size'), 400
        context = {}
        if data.get('channel_id') or data.get('image_motion'):
            channel = studio_service.store.channel(data.get('channel_id', 'focus-protocol'))
            profile = next(p for p in studio_service.store.read()['profiles'] if p['id'] == channel['profile_id'])
            context = dict(channel=channel, profile=profile, content_id='', concept=data.get('concept', channel['name']),
                           background_mode=channel.get('background_mode', 'image'))
            settings.channel_brand_name = channel['name']
            # Channel overlay/motion defaults; explicit request fields above win.
            for skey, ckey in (("visualizer_enabled", "visualizer_enabled"),
                               ("watermark_enabled", "watermark_enabled"),
                               ("subscribe_overlay_enabled", "subscribe_enabled"),
                               ("dust_enabled", "dust_enabled"),
                               ("branding_enabled", "branding_enabled"),
                               ("studio_motion_mode", "motion_mode")):
                if skey not in data and ckey in channel:
                    try:
                        setattr(settings, skey, channel[ckey])
                    except ValueError:
                        pass
            if "visual_effect" not in data and channel.get("visual_effect"):
                try:
                    settings.visual_effect = channel["visual_effect"]
                except ValueError:
                    pass
        music_dir = data.get('music_dir')
        if music_dir and not context:
            context['channel'] = {'music_dir': music_dir}
        if data.get('image_motion') is not None:
            from app.video.image_motion import configuration
            context['image_motion'] = configuration(data['image_motion'])
        orchestrator = LongFormJazzOrchestrator(settings, context=context)
        active_orchestrator = orchestrator

        job_id = datetime.now().strftime("%Y%m%d_%H%M%S_jazz")
        started_at = datetime.now().astimezone()
        current_job = {
            "job_id": job_id,
            "channel_id": data.get('channel_id', 'focus-protocol'),
            "status": "running",
            "video_count": video_count,
            "test_mode": test_mode,
            "started_at": started_at.isoformat(),
            "duration_minutes": duration_minutes,
            "progress": 0,
            "message": "Initializing..."
        }

        def run_generation():
            global current_job

            try:
                # The studio coordinator briefly holds the shared generation
                # lock on its 5s reconcile ticks. Wait it out instead of
                # failing instantly; a genuinely busy pipeline still 409s up
                # front via the pre-check above.
                import time as _time
                from app.youtube.state import publishing_lock as _gen_lock
                _deadline = _time.time() + 300
                while True:
                    try:
                        with _gen_lock(Path("jobs") / "generation"):
                            pass
                        break
                    except RuntimeError:
                        if _time.time() >= _deadline:
                            raise
                        current_job["message"] = "Waiting for studio task to release the pipeline..."
                        _time.sleep(3)
                current_job["message"] = "Initializing..."
                from app.utils.power import keep_awake, require_scratch_space
                require_scratch_space(Path("jobs"), duration_minutes)
                with keep_awake(f"{video_count}x{duration_minutes}min generation"):
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

    try:
        if active_orchestrator is None:
            raise ValueError('No generation worker is available to cancel')
        active_orchestrator.cancel_requested = True
        if active_orchestrator.last_job_ids:
            directory = Path('jobs') / active_orchestrator.last_job_ids[-1]
            directory.mkdir(parents=True, exist_ok=True)
            (directory / 'cancel.request').touch()
        current_job['status'] = 'cancelling'
        current_job['message'] = 'Cancellation requested; the owned worker will stop at its next checkpoint'
        return jsonify({'status': 'success', 'message': current_job['message']}), 202
    except Exception as error:
        logger.error('Failed to cancel active generation: %s', error, exc_info=True)
        return jsonify({'status': 'error', 'message': str(error)}), 500


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
            if request.args.get('channel') and job_dict.get('metadata', {}).get('channel_id', 'focus-protocol') != request.args['channel']:
                continue
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
    channel = {}
    if request.args.get('channel'):
        from app.studio.api import service
        channel = service.store.channel(request.args['channel'])
    thumbnail_dir = Path(channel.get('thumbnail_dir', 'thumbnail'))
    local_thumbnail_count = sum(
        1 for path in thumbnail_dir.glob("*")
        if path.is_file() and path.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}
    ) if thumbnail_dir.exists() else 0
    from app.providers.media_history import validate_background
    backgrounds = []
    for folder in (Path(channel.get('background_dir', 'backgroundImages')),):
        for path in folder.glob('*'):
            if path.is_file() and path.suffix.lower() in {'.png', '.jpg', '.jpeg', '.webp'}:
                try:
                    validate_background(path)
                    backgrounds.append(path)
                except Exception:
                    continue
    image_ready = bool(backgrounds)
    return jsonify({"status": "success", "components": {
        "image_generator": {"status": "healthy" if image_ready else "error", "message": f"Local only: {len(backgrounds)} valid background images"},
        "background_prompt": {"status": "healthy" if background_prompts.exists() else "error"},
        "thumbnail": {"status": "healthy" if local_thumbnail_count else "error", "message": f"{local_thumbnail_count} immutable local thumbnail source(s); no background fallback"},
        "music": {"status": "healthy", "message": "Local music pipeline ready"},
        "video_renderer": {"status": "healthy", "message": "Static FFmpeg renderer ready"},
        "youtube": _youtube_service().connection_status(),
    }})


@app.route('/api/jazz/youtube/connect', methods=['GET'])
def youtube_connect():
    """Start the server-side Google OAuth flow."""
    try:
        if request.args.get('channel'):
            from app.studio.api import connect
            return connect(request.args['channel'])
        return redirect(_youtube_service().authorization_url())
    except Exception as error:
        logger.error("YouTube OAuth start failed (%s)", type(error).__name__)
        return jsonify({"status": "error", "message": "Could not start YouTube connection; check the selected channel’s OAuth configuration"}), 400


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
        from urllib.parse import urlencode
        return redirect('/?' + urlencode(dict(youtube='connected', channel=status.get('selected_channel', 'focus-protocol'))))
    except Exception as error:
        logger.error("YouTube OAuth callback failed (%s)", type(error).__name__)
        from urllib.parse import urlencode
        return redirect("/?" + urlencode({"youtube_error": "YouTube connection failed. Start Connect YouTube again and choose the correct account."}))


@app.route('/api/jazz/youtube/status', methods=['GET'])
def youtube_status():
    if request.args.get('channel'):
        from app.studio.api import connection
        return connection(request.args['channel'])
    return jsonify({"status": "success", **_youtube_service().connection_status()})


@app.route('/api/jazz/youtube/queue', methods=['GET'])
def youtube_queue():
    from app.youtube.publishing import PublishingQueue
    try:
        return jsonify({'jobs': PublishingQueue(get_settings(), channel_id=request.args.get('channel')).scan(), 'operation': publishing_task})
    except Exception as error:
        return jsonify({'status': 'error', 'message': str(error)}), 400


@app.route('/api/jazz/youtube/publish', methods=['POST'])
@app.route('/api/jazz/video/<job_id>/upload', methods=['POST'])
def upload_video(job_id=None):
    """Preserve legacy action URLs while using channel-aware durable batches."""
    from app.studio.api import service
    try:
        channel_id = request.args.get('channel') or (service.job(job_id)['channel_id'] if job_id else 'focus-protocol')
        if job_id and service.job(job_id)['channel_id'] != channel_id:
            raise ValueError('This video belongs to another channel')
        if not service.queue(channel_id).service.connection_status().get("connected"):
            return jsonify({
                'status': 'unauthorized', 
                'message': service.store.channel(channel_id)['name'] + ' is not connected — click Connect YouTube',
                'auth_url': '/api/jazz/youtube/connect?channel=' + channel_id
            }), 401
            
        ids = [job_id] if job_id else [r['job_id'] for r in service.jobs() if r['stage'] == 'ready_to_publish' and r['channel_id'] == channel_id]
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


@app.route('/api/jazz/jobs/<job_id>', methods=['DELETE'])
def delete_job(job_id):
    """Delete a job's folder and registry row, freeing disk."""
    global current_job
    try:
        if current_job and current_job.get('job_id') == job_id and current_job.get('status') == 'running':
            return jsonify({"status": "error", "message": "Job is generating; cancel it first"}), 409
        freed = job_manager.delete_job(job_id)
        if current_job and current_job.get('job_id') == job_id:
            current_job = None
        return jsonify({"status": "success", "job_id": job_id, "freed_bytes": freed})
    except RuntimeError as e:
        return jsonify({"status": "error", "message": str(e)}), 409
    except ValueError as e:
        return jsonify({"status": "error", "message": str(e)}), 404 if 'not found' in str(e).lower() else 400
    except Exception as e:
        logger.error(f"Failed to delete job: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


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
    from app.video.subscribe_overlay import files
    settings = get_settings()
    return render_template('jazz_dashboard.html', settings=settings, subscribe_files=[p.name for p in files(settings)])


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
