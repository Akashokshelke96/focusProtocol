"""
Main CLI entry point
"""
import argparse
import sys
from pathlib import Path
from app.config.settings import get_settings, ensure_directories
from app.config.logging_config import setup_logging, get_logger
from app.pipeline.orchestrator import PipelineOrchestrator
from app.pipeline.long_form_jazz_orchestrator import LongFormJazzOrchestrator
from app.jobs.manager import JobManager

logger = None


def setup():
    """Initialize application."""
    global logger
    ensure_directories()
    logger = setup_logging()


def main():
    """Main entry point."""
    setup()

    parser = argparse.ArgumentParser(
        description="YouTube Automation Engine - Generate videos from topics"
    )

    subparsers = parser.add_subparsers(dest="command", help="Command")

    # Generate command
    generate_parser = subparsers.add_parser("generate", help="Generate a new video")
    generate_parser.add_argument("--topic", required=True, help="Video topic")
    generate_parser.add_argument("--duration", type=int, default=None, help="Duration in minutes")
    generate_parser.add_argument("--style", default="Cinematic educational documentary", help="Video style")
    generate_parser.add_argument("--tone", default="Informative and engaging", help="Video tone")
    generate_parser.add_argument("--test", action="store_true", help="Use test duration (3 min)")

    # Jazz command
    jazz_parser = subparsers.add_parser("jazz", help="Generate long-form jazz videos")
    jazz_parser.add_argument("--count", type=int, default=1, help="Number of videos to generate (default 1)")
    jazz_parser.add_argument("--test", action="store_true", help="Use test duration (3 min)")

    # Resume command
    resume_parser = subparsers.add_parser("resume", help="Resume a job")
    resume_parser.add_argument("job_id", help="Job ID to resume")

    # List jobs command
    list_parser = subparsers.add_parser("list-jobs", help="List all jobs")
    list_parser.add_argument("--limit", type=int, default=10, help="Number of jobs to show")

    # Validate command
    validate_parser = subparsers.add_parser("validate", help="Validate a job output")
    validate_parser.add_argument("job_id", help="Job ID to validate")

    subparsers.add_parser('youtube-connect', help='Connect your YouTube channel once')
    subparsers.add_parser('youtube-status', help='Show publishing queue and connection')
    publish_parser = subparsers.add_parser('youtube-publish', help='Publish all completed pending jobs')
    publish_parser.add_argument('--dry-run', action='store_true', help='Validate and preview local slots without uploading')
    retry_parser = subparsers.add_parser('youtube-retry', help='Resume processing and verification by saved job ID')
    retry_parser.add_argument('job_id')
    upload_parser = subparsers.add_parser('youtube-upload', help='Upload a video without a file picker')
    upload_parser.add_argument('--video', required=True)
    upload_parser.add_argument('--title', required=True)
    upload_parser.add_argument('--description', default='')
    upload_parser.add_argument('--tags', default='')
    upload_parser.add_argument('--thumbnail')
    upload_parser.add_argument('--scheduled-time')
    upload_parser.add_argument('--privacy-status', choices=['private', 'unlisted', 'public'], default='private')
    args = parser.parse_args()

    if args.command and args.command.startswith('youtube-'):
        return cmd_youtube(args)

    if args.command == "generate":
        return cmd_generate(args)
    elif args.command == "jazz":
        return cmd_jazz(args)
    elif args.command == "resume":
        return cmd_resume(args)
    elif args.command == "list-jobs":
        return cmd_list_jobs(args)
    elif args.command == "validate":
        return cmd_validate(args)
    else:
        parser.print_help()
        return 1


def cmd_generate(args):
    """Handle generate command."""
    settings = get_settings()

    # Check required API keys
    missing = settings.validate_required_keys()
    if missing:
        logger.error(f"Missing required API keys: {', '.join(missing)}")
        logger.error("Please set these in .env file")
        return 1

    # Determine duration
    duration = args.duration
    if args.test:
        duration = settings.test_video_duration_minutes
    elif duration is None:
        duration = settings.default_video_duration_minutes

    logger.info(f"Starting video generation...")
    logger.info(f"Topic: {args.topic}")
    logger.info(f"Duration: {duration} minutes")
    logger.info(f"Style: {args.style}")
    logger.info(f"Tone: {args.tone}")

    try:
        orchestrator = PipelineOrchestrator(settings)
        success = orchestrator.run(
            topic=args.topic,
            duration_minutes=duration,
            style=args.style,
            tone=args.tone,
        )

        return 0 if success else 1

    except Exception as e:
        logger.error(f"Generation failed: {e}", exc_info=True)
        return 1


def cmd_youtube(args):
    import json
    from app.youtube.publishing import PublishingQueue
    settings = get_settings()
    queue = PublishingQueue(settings)
    try:
        if args.command == 'youtube-connect':
            import webbrowser
            from urllib.parse import urlsplit
            base = urlsplit(settings.youtube_redirect_uri)
            url = f'{base.scheme}://{base.netloc}/api/jazz/youtube/connect'
            print('Start python run_jazz_ui.py, then authorize at: ' + url)
            webbrowser.open(url)
            return 0
        if args.command == 'youtube-status':
            connection = queue.service.connection_status()
            print(json.dumps(connection, indent=2))
            rows = queue.reconcile() if connection.get('connected') else queue.scan()
            for state in ('pending', 'scheduled', 'uploaded', 'published', 'failed', 'needs_review', 'duplicate'):
                print(f'{state}: {sum(r["youtube_status"] == state for r in rows)}')
            for row in rows:
                print(f'{row["job_id"]} | {row["youtube_status"]} | {row.get("scheduled_publish_time") or row.get("upload_timestamp") or "-"} | {row.get("youtube_video_id") or "-"}')
            return 0
        job_id = args.job_id if args.command == 'youtube-retry' else None
        if args.command == 'youtube-upload':
            job_id = queue.add_manual(args.video, title=args.title, description=args.description,
                tags=[t.strip() for t in args.tags.split(',') if t.strip()], thumbnail_path=args.thumbnail,
                scheduled_publish_time=args.scheduled_time, privacy_status=args.privacy_status)
        results = queue.publish(dry_run=getattr(args, 'dry_run', False), job_id=job_id)
        print('YouTube Publishing Queue')
        if getattr(args, 'dry_run', False):
            print('Preview only; remote schedule conflicts are checked during real publishing.')
        for row in results:
            print(f'{row["job_id"]}: {row["youtube_status"]} | {row.get("scheduled_publish_time") or "private"} | {row.get("last_error") or "OK"}')
        print(f'{len(results)} pending jobs checked.')
        return int(any(r['youtube_status'] in ('failed', 'needs_review', 'processing_timeout', 'verification_failed', 'thumbnail_retry') for r in results))
    except Exception as error:
        print(f'YouTube: {error}')
        return 1


def cmd_jazz(args):
    """Handle jazz video generation command."""
    settings = get_settings()

    # Check required API keys (only Gemini needed for jazz)
    if not settings.gemini_api_key and settings.llm_provider != 'omniroute':
        logger.error("Missing GEMINI_API_KEY")
        logger.error("Please set this in .env file")
        return 1

    video_count = args.count
    test_mode = args.test

    logger.info(f"Starting jazz video generation...")
    logger.info(f"Videos to generate: {video_count}")
    logger.info(f"Test mode: {test_mode}")

    try:
        orchestrator = LongFormJazzOrchestrator(settings)
        test_duration = settings.jazz_test_duration_minutes if test_mode else None
        success = orchestrator.run(
            video_count=video_count,
            test_mode=test_mode,
            test_duration_minutes=test_duration,
        )

        return 0 if success else 1

    except Exception as e:
        logger.error(f"Jazz generation failed: {e}", exc_info=True)
        return 1


def cmd_resume(args):
    """Handle resume command."""
    logger.info(f"Resuming job: {args.job_id}")
    logger.warning("Resume functionality not yet implemented")
    return 1


def cmd_list_jobs(args):
    """Handle list-jobs command."""
    try:
        manager = JobManager()
        jobs = manager.list_jobs(limit=args.limit)

        if not jobs:
            logger.info("No jobs found")
            return 0

        logger.info(f"\nRecent Jobs ({len(jobs)}):\n")
        for job in jobs:
            status_indicator = "✓" if job.status == "completed" else "✗" if job.status == "failed" else "⟳"
            logger.info(
                f"  {status_indicator} {job.id} | {job.topic[:40]:<40} | {job.stage:<20}"
            )
        logger.info()

        return 0

    except Exception as e:
        logger.error(f"Failed to list jobs: {e}")
        return 1


def cmd_validate(args):
    """Handle validate command."""
    logger.info(f"Validating job: {args.job_id}")
    logger.warning("Validation functionality not yet implemented")
    return 1


if __name__ == "__main__":
    sys.exit(main())
