from flask import Flask, render_template, request, jsonify, send_file
from pathlib import Path
import json
import os
import sys
from flask_cors import CORS

sys.path.insert(0, str(Path(__file__).parent))

from app.config.settings import get_settings, ensure_directories
from app.config.logging_config import setup_logging, get_logger
from app.providers.acemusic_v2 import AceStepProvider

app = Flask(__name__, template_folder='templates', static_folder='static')
CORS(app)  # Enable CORS for all routes
logger = get_logger("web.app")
ensure_directories()

DARK_BLUES_PROMPT = """Create an ORIGINAL dark, sophisticated, hypnotic blues instrumental designed for deep work and concentration.

CORE VIBE: Dark noir blues / cinematic blues / blues-rock. Masculine, mature, intelligent, mysterious and extremely controlled. The feeling is a highly focused person working alone at 2 AM.

RHYTHM: Slow, steady and deliberate. Around 75–82 BPM perceived tempo with subtle double-time pulse. Gentle blues swing.

DRUMS: Minimal live-feeling drums. Deep soft kick, dry controlled snare, subtle hi-hat and occasional ghost notes. Very few fills.

BASS: Deep, warm electric bass with slight analog saturation. Repeating blues-based pattern tightly locked to kick.

ELECTRIC GUITAR: Dark vintage electric guitar with warm tube-amp overdrive, smooth saturation, sustain and subtle compression. Use slow blues bends, slides, vibrato.

HARMONY: Dark minor-blues atmosphere with blues-scale vocabulary, dominant seventh tension and occasional chromatic movement.

ATMOSPHERE: Smoky, rainy, urban, nocturnal, sophisticated and slightly dangerous. Not sad - POWERFUL CALM. Should feel intelligent, disciplined and quietly intimidating.

PRODUCTION: Warm analog character, dark tonal balance, rich low-mids, controlled bass, smooth highs, subtle tape saturation, spacious stereo imaging.

DYNAMICS: Keep energy relatively consistent. NO dramatic climax. NO sudden drops. NO huge impacts. Maintain steady psychological momentum.

ABSOLUTELY AVOID: Vocals, lyrics, spoken words, EDM drops, trap beats, aggressive rock, flashy solos, shredding, catchy pop melodies, dramatic orchestration, excessive percussion, sudden transitions, cheerful moods.

PSYCHOLOGICAL TARGET: Listener should think "I'll just work for a while..." and suddenly realize two hours have passed. Make distractions feel distant and concentration feel effortless.

Think: DARK BLUES FOR PEOPLE WHO HAVE WORK TO DO.

Instrument. Completely original. Do not copy any existing song, melody, riff or distinctive musical phrase."""


@app.route('/')
def index():
    """Home page."""
    return render_template('index.html')


@app.route('/api/health', methods=['GET'])
def health():
    """Health check endpoint."""
    return jsonify({'status': 'ok', 'message': 'Server is running'})


@app.route('/api/test-acemusic', methods=['POST', 'GET'])
def test_acemusic():
    """Test ACE-Step API connection."""
    try:
        # Get prompt from request
        if request.method == 'POST':
            data = request.get_json() or {}
            prompt = data.get('prompt', DARK_BLUES_PROMPT)
        else:
            prompt = request.args.get('prompt', DARK_BLUES_PROMPT)

        logger.info(f"Testing ACE-Step API with prompt: {prompt[:60]}...")

        provider = AceStepProvider()

        # Test 1: Health check
        logger.info("Step 1: Health check...")
        if not provider.health_check():
            return jsonify({
                'status': 'error',
                'error': 'ACE-Step API is not responding',
                'details': 'Health check failed'
            }), 503

        logger.info("Step 2: API is healthy, attempting music generation...")

        # Test 2: Generate short sample
        results = provider.generate_music(
            prompt=prompt,
            duration_seconds=30,
            bpm=75,
            num_samples=1,
            thinking=True,
            inference_steps=32
        )

        if results:
            logger.info(f"SUCCESS: Generated {len(results)} sample(s)")
            return jsonify({
                'status': 'success',
                'message': f'ACE-Step API is working! Generated {len(results)} sample(s)',
                'samples': results,
                'details': {
                    'api_url': provider.base_url,
                    'api_key_set': bool(provider.api_key),
                    'sample_count': len(results)
                }
            })
        else:
            logger.error("Generation failed - no samples returned")
            return jsonify({
                'status': 'error',
                'error': 'Music generation failed',
                'details': 'No samples were generated',
                'api_url': provider.base_url
            }), 500

    except Exception as e:
        logger.error(f"Test error: {e}", exc_info=True)
        return jsonify({
            'status': 'error',
            'error': str(e),
            'details': 'See server logs for details'
        }), 500


@app.route('/api/generate-music', methods=['POST'])
def generate_music():
    """Generate music with ACE-Step."""
    try:
        data = request.get_json() or {}
        prompt = data.get('prompt', DARK_BLUES_PROMPT)
        duration = data.get('duration_minutes', 5)
        duration_seconds = duration * 60

        logger.info(f"Generating music: {duration} minutes")

        provider = AceStepProvider()
        results = provider.generate_music(
            prompt=prompt,
            duration_seconds=duration_seconds,
            bpm=75,
            num_samples=1,
            thinking=True
        )

        if results:
            return jsonify({
                'status': 'success',
                'message': 'Music generated successfully',
                'audio_url': results[0]['url'],
                'duration': results[0]['duration'],
                'bpm': results[0]['bpm']
            })
        else:
            return jsonify({'error': 'Music generation failed'}), 500

    except Exception as e:
        logger.error(f"Generation error: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/jobs', methods=['GET'])
def list_jobs():
    """List recent jobs."""
    try:
        from app.jobs.manager import JobManager
        manager = JobManager()
        jobs = manager.list_jobs(limit=10)

        return jsonify({
            'jobs': [
                {
                    'id': j.id,
                    'topic': j.topic,
                    'status': j.status,
                    'stage': j.stage,
                    'created_at': str(j.created_at) if hasattr(j, 'created_at') else 'N/A'
                }
                for j in jobs
            ]
        })
    except Exception as e:
        logger.error(f"Error listing jobs: {e}")
        return jsonify({'error': str(e)}), 500


@app.errorhandler(404)
def not_found(error):
    """Handle 404 errors."""
    return jsonify({'error': 'Endpoint not found'}), 404


@app.errorhandler(500)
def server_error(error):
    """Handle 500 errors."""
    return jsonify({'error': 'Internal server error'}), 500


if __name__ == '__main__':
    setup_logging()
    logger.info("")
    logger.info("="*70)
    logger.info("SILENT DARK BLUES - WEB UI")
    logger.info("="*70)
    logger.info("")
    logger.info("Starting server on http://localhost:5000")
    logger.info("")
    logger.info("Available Endpoints:")
    logger.info("  GET  /                    - Web UI")
    logger.info("  GET  /api/health          - Health check")
    logger.info("  POST /api/test-acemusic   - Test ACE-Step API")
    logger.info("  POST /api/generate-music  - Generate music")
    logger.info("  GET  /api/jobs            - List jobs")
    logger.info("")

    try:
        app.run(debug=True, host='0.0.0.0', port=5000, threaded=True, use_reloader=False)
    except Exception as e:
        logger.error(f"Server error: {e}")
