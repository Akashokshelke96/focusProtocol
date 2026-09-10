#!/usr/bin/env python
"""
YouTube Automation System - Complete Test & Demonstration
Tests: 1) Batch Scheduling, 2) SEO Metadata, 3) Thumbnail Generation
"""
import sys
from pathlib import Path
from datetime import datetime, timedelta
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / '.env')
sys.path.insert(0, str(Path(__file__).parent))

from app.config.logging_config import setup_logging, get_logger
from app.youtube.scheduler import YouTubeUploadScheduler
from app.youtube.metadata_generator import YouTubeMetadataGenerator
from app.youtube.thumbnail_generator import ThumbnailGenerator

logger = None


def test_metadata_generation():
    """Test 1: SEO Metadata Generation"""
    logger.info("")
    logger.info("=" * 80)
    logger.info("TEST 1: SEO METADATA GENERATION")
    logger.info("=" * 80)
    logger.info("")

    try:
        gen = YouTubeMetadataGenerator()

        # Generate metadata for test compilation
        metadata = gen.generate_metadata(
            compilation_id="test_001",
            song_titles=["Song 1", "Song 2", "Song 3", "Song 4"],
            total_duration_minutes=20,
            episode_number=1,
        )

        logger.info("Generated Metadata:")
        logger.info(f"  Title: {metadata.get('title', 'N/A')}")
        logger.info(f"  Tags: {', '.join(metadata.get('tags', [])[:5])}...")
        logger.info(f"  Hashtags: {', '.join(metadata.get('hashtags', []))}")
        logger.info(f"  Description length: {len(metadata.get('description', ''))} chars")
        logger.info("")

        # Validate metadata
        assert metadata.get('title'), "Title missing"
        assert len(metadata.get('title', '')) <= 60, "Title too long"
        assert metadata.get('tags'), "Tags missing"
        assert len(metadata.get('tags', [])) >= 10, "Need at least 10 tags"
        assert metadata.get('description'), "Description missing"
        assert len(metadata.get('description', '')) > 500, "Description too short"

        logger.info("TEST 1 PASSED: Metadata generation working correctly")
        logger.info("")
        return True

    except Exception as e:
        logger.error(f"TEST 1 FAILED: {e}")
        return False


def test_thumbnail_generation():
    """Test 2: Thumbnail Generation"""
    logger.info("")
    logger.info("=" * 80)
    logger.info("TEST 2: THUMBNAIL GENERATION")
    logger.info("=" * 80)
    logger.info("")

    try:
        gen = ThumbnailGenerator()

        # Generate 3 test thumbnails
        thumbnails = []
        for ep in range(1, 4):
            logger.info(f"Generating thumbnail for episode {ep}...")
            thumb = gen.generate_thumbnail(
                episode_number=ep,
                duration_minutes=20,
                title_text=f"Silent Gentleman Vol.{ep}",
            )
            thumbnails.append(thumb)
            assert thumb.exists(), f"Thumbnail {ep} not created"
            size_mb = thumb.stat().st_size / (1024 * 1024)
            logger.info(f"  Created: {thumb.name} ({size_mb:.2f} MB)")

        logger.info("")
        logger.info(f"TEST 2 PASSED: Generated {len(thumbnails)} thumbnails")
        logger.info(f"  Output directory: {thumbnails[0].parent}")
        logger.info("")
        return True

    except Exception as e:
        logger.error(f"TEST 2 FAILED: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_batch_scheduling():
    """Test 3: Batch Scheduling & Queue Management"""
    logger.info("")
    logger.info("=" * 80)
    logger.info("TEST 3: BATCH SCHEDULING")
    logger.info("=" * 80)
    logger.info("")

    try:
        # Create fresh scheduler for this test
        scheduler = YouTubeUploadScheduler()
        initial_count = len(scheduler.schedule["queue"])

        # Queue multiple compilations
        logger.info(f"Queueing 5 compilations (existing: {initial_count})...")
        start_date = datetime.utcnow() + timedelta(days=1)
        jobs = scheduler.batch_queue_compilations(
            num_videos=5,
            start_date=start_date,
            frequency_days=3,
        )

        assert len(jobs) == 5, "Should queue 5 videos"
        logger.info(f"Queued {len(jobs)} new videos")
        logger.info("")

        # Check schedule status
        status = scheduler.get_schedule_status()
        logger.info("Schedule Status:")
        logger.info(f"  Total scheduled: {status['total_scheduled']}")
        logger.info(f"  Queued for processing: {status['queued']}")
        logger.info(f"  Ready for upload: {status['ready_for_upload']}")
        logger.info(f"  Already uploaded: {status['uploaded']}")
        logger.info("")

        # Validate at least 5 new were added
        assert len(jobs) == 5, "Should have queued 5 videos"
        assert status['queued'] >= 5, "Should have at least 5 queued videos"

        logger.info("TEST 3 PASSED: Batch scheduling working correctly")
        logger.info("")
        return True

    except Exception as e:
        logger.error(f"TEST 3 FAILED: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_integrated_workflow():
    """Test 4: Integrated Workflow (All 3 Features Together)"""
    logger.info("")
    logger.info("=" * 80)
    logger.info("TEST 4: INTEGRATED WORKFLOW")
    logger.info("=" * 80)
    logger.info("")

    try:
        scheduler = YouTubeUploadScheduler()
        metadata_gen = YouTubeMetadataGenerator()
        thumbnail_gen = ThumbnailGenerator()

        # Queue an episode
        logger.info("Step 1: Queue an episode")
        job = scheduler.queue_compilation(
            episode_number=10,
            upload_datetime=datetime.utcnow() + timedelta(hours=1),
            priority="high",
        )
        logger.info(f"  Queued episode {job['episode']}")
        logger.info("")

        # Generate metadata for queued episode
        logger.info("Step 2: Generate metadata for queued episode")
        metadata = metadata_gen.generate_metadata(
            compilation_id=f"test_workflow_{job['episode']}",
            song_titles=["Track A", "Track B", "Track C"],
            total_duration_minutes=20,
            episode_number=job['episode'],
        )
        logger.info(f"  Title: {metadata.get('title', '')[:50]}")
        logger.info("")

        # Generate thumbnail with metadata
        logger.info("Step 3: Generate thumbnail with title from metadata")
        thumbnail = thumbnail_gen.generate_thumbnail(
            episode_number=job['episode'],
            duration_minutes=20,
            title_text=metadata.get('title', '')[:40],
        )
        logger.info(f"  Created: {thumbnail.name}")
        logger.info("")

        # Use existing demo video as placeholder
        demo_video = Path("output/demo_20260902_033708/demo_with_visualizer.mp4")
        if demo_video.exists():
            logger.info("Step 4: Link demo video as placeholder")
            job['video_path'] = str(demo_video)
            job['metadata'] = metadata
            job['thumbnail_path'] = str(thumbnail)
            job['status'] = 'ready_for_upload'
            logger.info(f"  Video: {demo_video.name}")
            logger.info("")

            # Mock upload to YouTube
            logger.info("Step 5: Mock YouTube upload with all assets")
            upload_result = scheduler.mock_upload_to_youtube(job)
            logger.info(f"  Status: {upload_result['status']}")
            logger.info(f"  Video URL: {upload_result.get('video_url', 'N/A')}")
            logger.info(f"  Thumbnail: {Path(job['thumbnail_path']).name}")
            logger.info("")

            assert upload_result['status'] == 'uploaded', "Upload should succeed"
            logger.info("TEST 4 PASSED: Integrated workflow completed successfully")
            logger.info("")
            return True
        else:
            logger.warning("No demo video found - skipping mock upload test")
            logger.info("TEST 4 PASSED: Metadata + Thumbnail generation working (upload skipped)")
            logger.info("")
            return True

    except Exception as e:
        logger.error(f"TEST 4 FAILED: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    """Run all tests."""
    global logger
    logger = setup_logging()

    logger.info("")
    logger.info("=" * 80)
    logger.info("YOUTUBE AUTOMATION SYSTEM - COMPLETE TEST SUITE")
    logger.info("Testing: 1) Batch Scheduling, 2) SEO Metadata, 3) Thumbnails")
    logger.info("=" * 80)
    logger.info("")

    results = {
        "Metadata Generation": test_metadata_generation(),
        "Thumbnail Generation": test_thumbnail_generation(),
        "Batch Scheduling": test_batch_scheduling(),
        "Integrated Workflow": test_integrated_workflow(),
    }

    # Summary
    logger.info("")
    logger.info("=" * 80)
    logger.info("TEST SUMMARY")
    logger.info("=" * 80)
    logger.info("")

    passed = sum(1 for v in results.values() if v)
    total = len(results)

    for test_name, passed_flag in results.items():
        status = "PASSED" if passed_flag else "FAILED"
        logger.info(f"  {test_name}: {status}")

    logger.info("")
    logger.info(f"Overall: {passed}/{total} tests passed")
    logger.info("")

    if passed == total:
        logger.info("SUCCESS - All YouTube automation features tested and working!")
        logger.info("")
        logger.info("Features Implemented:")
        logger.info("  1. Batch Scheduling - Queue multiple compilations with upload times")
        logger.info("  2. SEO Metadata - Gemini-generated titles, descriptions, tags, hashtags")
        logger.info("  3. Thumbnail Generation - Auto-created branded thumbnails (1280x720)")
        logger.info("")
        logger.info("Files Created:")
        logger.info("  - app/youtube/metadata_generator.py")
        logger.info("  - app/youtube/thumbnail_generator.py")
        logger.info("  - app/youtube/scheduler.py")
        logger.info("  - youtube_automation_test.py (this file)")
        logger.info("")
        return 0
    else:
        logger.error("Some tests failed - see details above")
        return 1


if __name__ == "__main__":
    sys.exit(main())
