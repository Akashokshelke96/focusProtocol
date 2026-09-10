"""
Professional Web UI for YouTube Automation System
Flask backend with beautiful frontend dashboard
"""
import os
import json
from datetime import datetime, timedelta
from pathlib import Path
from flask import Flask, render_template, jsonify, request
from flask_cors import CORS
from app.config.logging_config import get_logger
from app.youtube.scheduler import YouTubeUploadScheduler
from app.youtube.metadata_generator import YouTubeMetadataGenerator
from app.youtube.thumbnail_generator import ThumbnailGenerator
from app.api.health_check import HealthChecker

logger = get_logger("web.app")

app = Flask(__name__)
CORS(app)

# Global instances - initialize to None
scheduler = None
health_checker = None

# Initialize instances on app startup
def init_app():
    """Initialize app instances."""
    global scheduler, health_checker
    scheduler = YouTubeUploadScheduler()
    health_checker = HealthChecker()
    logger.info("Web app initialized")


# Initialize before first request
@app.before_request
def before_first_request():
    """Initialize on first request."""
    global scheduler, health_checker
    if scheduler is None or health_checker is None:
        init_app()


# ============================================================================
# HEALTH CHECK ROUTES
# ============================================================================

@app.route('/api/health', methods=['GET'])
def get_health():
    """Get complete health status of all systems."""
    if health_checker is None:
        init_app()
    return jsonify(health_checker.check_all())


@app.route('/api/health/quick', methods=['GET'])
def get_quick_health():
    """Quick health check - just status."""
    if health_checker is None:
        init_app()
    results = health_checker.check_all()
    return jsonify({
        "status": results["status"],
        "timestamp": results["timestamp"],
        "systems_healthy": sum(1 for c in results["checks"].values() if c.get("status") == "healthy"),
        "total_systems": len(results["checks"])
    })


# ============================================================================
# SCHEDULING ROUTES
# ============================================================================

@app.route('/api/schedule/status', methods=['GET'])
def get_schedule_status():
    """Get current schedule status."""
    if scheduler is None:
        init_app()
    status = scheduler.get_schedule_status()
    return jsonify({
        "status": "success",
        "data": status,
        "timestamp": datetime.utcnow().isoformat()
    })


@app.route('/api/schedule/queue', methods=['GET'])
def get_queue():
    """Get videos ready for upload."""
    if scheduler is None:
        init_app()
    queue = scheduler.get_upload_queue()
    return jsonify({
        "status": "success",
        "count": len(queue),
        "videos": [
            {
                "episode": v.get("episode"),
                "scheduled_upload": v.get("scheduled_upload"),
                "priority": v.get("priority"),
                "status": v.get("status")
            }
            for v in queue
        ]
    })


@app.route('/api/schedule/queue-single', methods=['POST'])
def queue_single():
    """Queue a single compilation."""
    try:
        if scheduler is None:
            init_app()
        data = request.get_json()
        episode_num = data.get("episode_number", 1)
        hours_ahead = data.get("hours_ahead", 24)
        priority = data.get("priority", "normal")

        upload_time = datetime.utcnow() + timedelta(hours=hours_ahead)

        job = scheduler.queue_compilation(
            episode_number=episode_num,
            upload_datetime=upload_time,
            priority=priority
        )

        return jsonify({
            "status": "success",
            "message": f"Queued episode {episode_num}",
            "job": {
                "episode": job["episode"],
                "scheduled_upload": job["scheduled_upload"],
                "priority": job["priority"]
            }
        })
    except Exception as e:
        logger.error(f"Queue single failed: {e}")
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 400


@app.route('/api/schedule/batch-queue', methods=['POST'])
def batch_queue():
    """Queue multiple compilations."""
    try:
        if scheduler is None:
            init_app()
        data = request.get_json()
        num_videos = data.get("num_videos", 5)
        start_days_ahead = data.get("start_days_ahead", 1)
        frequency_days = data.get("frequency_days", 3)

        start_date = datetime.utcnow() + timedelta(days=start_days_ahead)

        jobs = scheduler.batch_queue_compilations(
            num_videos=num_videos,
            start_date=start_date,
            frequency_days=frequency_days
        )

        return jsonify({
            "status": "success",
            "message": f"Queued {len(jobs)} videos",
            "jobs": len(jobs),
            "episodes": [j["episode"] for j in jobs]
        })
    except Exception as e:
        logger.error(f"Batch queue failed: {e}")
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 400


# ============================================================================
# METADATA ROUTES
# ============================================================================

@app.route('/api/metadata/generate', methods=['POST'])
def generate_metadata():
    """Generate metadata for a compilation."""
    try:
        data = request.get_json()
        compilation_id = data.get("compilation_id", f"gen_{datetime.now().timestamp()}")
        song_titles = data.get("song_titles", ["Track 1", "Track 2", "Track 3"])
        duration = data.get("duration_minutes", 20)
        episode = data.get("episode_number", 1)

        gen = YouTubeMetadataGenerator()
        metadata = gen.generate_metadata(
            compilation_id=compilation_id,
            song_titles=song_titles,
            total_duration_minutes=duration,
            episode_number=episode
        )

        return jsonify({
            "status": "success",
            "data": metadata
        })
    except Exception as e:
        logger.error(f"Metadata generation failed: {e}")
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 400


# ============================================================================
# THUMBNAIL ROUTES
# ============================================================================

@app.route('/api/thumbnail/generate', methods=['POST'])
def generate_thumbnail():
    """Generate a single thumbnail."""
    try:
        data = request.get_json()
        episode = data.get("episode_number", 1)
        duration = data.get("duration_minutes", 20)
        title = data.get("title", "Silent Dark Blues")

        gen = ThumbnailGenerator()
        thumbnail = gen.generate_thumbnail(
            episode_number=episode,
            duration_minutes=duration,
            title_text=title
        )

        return jsonify({
            "status": "success",
            "path": str(thumbnail),
            "filename": thumbnail.name
        })
    except Exception as e:
        logger.error(f"Thumbnail generation failed: {e}")
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 400


@app.route('/api/thumbnail/batch', methods=['POST'])
def batch_thumbnails():
    """Generate multiple thumbnails."""
    try:
        data = request.get_json()
        count = data.get("count", 5)

        gen = ThumbnailGenerator()
        thumbnails = gen.batch_generate_thumbnails(episode_count=count)

        return jsonify({
            "status": "success",
            "generated": len(thumbnails),
            "files": [t.name for t in thumbnails]
        })
    except Exception as e:
        logger.error(f"Batch thumbnail generation failed: {e}")
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 400


# ============================================================================
# MUSIC GENERATION ROUTES
# ============================================================================

@app.route('/api/music/check-treblo', methods=['GET'])
def check_treblo_api():
    """Check Treblo API connection and key validity."""
    try:
        from app.providers.treblo import TrebloProvider

        treblo = TrebloProvider()

        if not treblo.api_key:
            return jsonify({
                "status": "error",
                "connected": False,
                "message": "TREBLO_API_KEY not found in environment",
                "help": "Add TREBLO_API_KEY to your .env file"
            })

        # Try a simple test call to verify API key
        import requests
        headers = {"Authorization": f"Bearer {treblo.api_key}"}

        try:
            response = requests.get(
                "https://api.treblo.com/v1/account",
                headers=headers,
                timeout=10
            )

            if response.status_code == 200:
                data = response.json()
                return jsonify({
                    "status": "success",
                    "connected": True,
                    "message": "Connected to Treblo API",
                    "account_info": data.get("account", {})
                })
            elif response.status_code == 401:
                return jsonify({
                    "status": "error",
                    "connected": False,
                    "message": "Invalid API key (401 Unauthorized)",
                    "help": "Check your TREBLO_API_KEY in .env"
                })
            else:
                return jsonify({
                    "status": "error",
                    "connected": False,
                    "message": f"Treblo API error: HTTP {response.status_code}",
                    "response": response.text
                })

        except requests.exceptions.Timeout:
            return jsonify({
                "status": "error",
                "connected": False,
                "message": "Connection timeout - Treblo API not responding",
                "help": "Check your internet connection"
            })
        except requests.exceptions.ConnectionError:
            return jsonify({
                "status": "error",
                "connected": False,
                "message": "Cannot connect to Treblo API",
                "help": "Check https://treblo.com/status"
            })

    except Exception as e:
        logger.error(f"Treblo API check failed: {e}")
        return jsonify({
            "status": "error",
            "connected": False,
            "message": f"Error checking API: {str(e)}"
        }), 500


@app.route('/api/music/start-generation', methods=['POST'])
def start_music_generation():
    """Start music generation with Treblo API."""
    try:
        from app.pipeline.dark_blues_generator import DarkBluesGenerationOrchestrator

        orchestrator = DarkBluesGenerationOrchestrator()
        result = orchestrator.start_generation()

        return jsonify({
            "status": "success",
            "data": result
        })
    except Exception as e:
        logger.error(f"Music generation start failed: {e}")
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 400


@app.route('/api/music/progress', methods=['GET'])
def get_music_progress():
    """Get progress of music generations."""
    try:
        from app.pipeline.dark_blues_generator import DarkBluesGenerationOrchestrator

        orchestrator = DarkBluesGenerationOrchestrator()
        progress = orchestrator.check_progress()

        return jsonify({
            "status": "success",
            "data": progress
        })
    except Exception as e:
        logger.error(f"Progress check failed: {e}")
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 400


@app.route('/api/music/full-status', methods=['GET'])
def get_full_music_status():
    """Get complete music generation and compilation status."""
    try:
        from app.pipeline.dark_blues_generator import DarkBluesGenerationOrchestrator

        orchestrator = DarkBluesGenerationOrchestrator()
        status = orchestrator.get_full_status()

        return jsonify({
            "status": "success",
            "data": status
        })
    except Exception as e:
        logger.error(f"Full status check failed: {e}")
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 400


@app.route('/api/music/create-compilations', methods=['POST'])
def create_music_compilations():
    """Create 2 compilations from 5 generated variations."""
    try:
        from app.pipeline.dark_blues_generator import DarkBluesGenerationOrchestrator

        orchestrator = DarkBluesGenerationOrchestrator()
        result = orchestrator.create_compilations()

        return jsonify({
            "status": "success",
            "data": result
        })
    except Exception as e:
        logger.error(f"Compilation creation failed: {e}")
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 400


# ============================================================================
# PAGE ROUTES
# ============================================================================

@app.route('/')
def index():
    """Main dashboard."""
    return render_template('dashboard.html')


@app.route('/music')
def music_page():
    """Music generation page."""
    return render_template('music.html')


@app.route('/schedule')
def schedule_page():
    """Schedule management page."""
    return render_template('schedule.html')


@app.route('/metadata')
def metadata_page():
    """Metadata generation page."""
    return render_template('metadata.html')


@app.route('/health')
def health_page():
    """Health check page."""
    return render_template('health.html')


# ============================================================================
# UTILITY ROUTES
# ============================================================================

@app.route('/api/info', methods=['GET'])
def get_info():
    """Get system information."""
    return jsonify({
        "name": "Silent Dark Blues YouTube Automation",
        "version": "1.0.0",
        "features": [
            "Batch Scheduling",
            "SEO Metadata Generation",
            "Thumbnail Creation"
        ],
        "api_endpoints": {
            "health": "/api/health",
            "schedule": "/api/schedule/status",
            "metadata": "/api/metadata/generate",
            "thumbnails": "/api/thumbnail/generate"
        }
    })


@app.errorhandler(404)
def not_found(error):
    """Handle 404 errors."""
    return jsonify({"status": "error", "message": "Endpoint not found"}), 404


@app.errorhandler(500)
def server_error(error):
    """Handle 500 errors."""
    logger.error(f"Server error: {error}")
    return jsonify({"status": "error", "message": "Internal server error"}), 500


if __name__ == '__main__':
    init_app()
    app.run(debug=False, host='0.0.0.0', port=5000)
