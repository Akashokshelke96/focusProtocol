#!/usr/bin/env python
"""
Test script for Long-Form Jazz video generation.
Run with: python test_jazz_generation.py
"""
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

from app.config.settings import get_settings, ensure_directories
from app.config.logging_config import setup_logging
from app.providers.local_music import LocalMusicProvider
from app.providers.local_background import LocalBackgroundProvider
from app.pipeline.long_form_jazz_orchestrator import LongFormJazzOrchestrator


def test_music_provider():
    """Test LocalMusicProvider functionality."""
    print("\n" + "="*60)
    print("TEST 1: Music Provider")
    print("="*60)

    provider = LocalMusicProvider()
    files = provider.get_available_music_files()

    if not files:
        print("ERROR: No music files found")
        return False

    print(f"Found {len(files)} music files:")
    for i, f in enumerate(files[:5], 1):
        print(f"  {i}. {f['filename']} - {f['duration']/60:.1f} minutes")

    # Test random selection
    selected = provider.select_random_tracks(count=3)
    print(f"\nSelected {len(selected)} random tracks:")
    for i, f in enumerate(selected, 1):
        print(f"  {i}. {f['filename']} - {f['duration']/60:.1f} minutes")

    return True


def test_background_provider():
    """Test LocalBackgroundProvider functionality."""
    print("\n" + "="*60)
    print("TEST 2: Background Image Provider")
    print("="*60)

    provider = LocalBackgroundProvider()
    files = provider.get_available_images()

    if not files:
        print("ERROR: No background images found")
        return False

    print(f"Found {len(files)} background images:")
    for i, f in enumerate(files, 1):
        print(f"  {i}. {f['filename']} - {f['width']}x{f['height']}")

    # Test random selection
    selected = provider.select_random_images(count=3)
    print(f"\nSelected {len(selected)} random images:")
    for i, f in enumerate(selected, 1):
        print(f"  {i}. {f['filename']}")

    return True


def test_orchestrator_setup():
    """Test LongFormJazzOrchestrator initialization."""
    print("\n" + "="*60)
    print("TEST 3: Orchestrator Setup")
    print("="*60)

    try:
        settings = get_settings()
        orchestrator = LongFormJazzOrchestrator(settings)
        print("Orchestrator initialized successfully")
        print(f"  Video dimensions: {settings.video_width}x{settings.video_height}")
        print(f"  Video FPS: {settings.video_fps}")
        print(f"  Jazz target duration: {settings.jazz_target_duration_minutes} minutes")
        print(f"  Jazz tracks: {settings.jazz_music_tracks}")
        print(f"  Jazz images: {settings.jazz_background_images}")
        return True
    except Exception as e:
        print(f"ERROR: {e}")
        return False


def test_full_generation_test_mode():
    """Test full generation with test duration (3 minutes)."""
    print("\n" + "="*60)
    print("TEST 4: Full Generation (TEST MODE - 3 minutes)")
    print("="*60)

    try:
        settings = get_settings()

        if not settings.gemini_api_key:
            print("WARNING: GEMINI_API_KEY not set. Thumbnail generation will be skipped.")

        orchestrator = LongFormJazzOrchestrator(settings)

        print("\nStarting test generation...")
        print("This will generate a 3-minute jazz video for testing purposes.\n")

        success = orchestrator.run(
            video_count=1,
            test_mode=True,
            test_duration_minutes=3,
        )

        if success:
            print("\nTest generation SUCCESSFUL")
            return True
        else:
            print("\nTest generation FAILED")
            return False

    except Exception as e:
        print(f"ERROR during generation: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    """Run all tests."""
    print("\n" + "="*70)
    print("LONG-FORM JAZZ VIDEO GENERATION - TEST SUITE")
    print("="*70)

    # Setup
    ensure_directories()
    setup_logging()

    # Run tests
    results = {
        "Music Provider": test_music_provider(),
        "Background Provider": test_background_provider(),
        "Orchestrator Setup": test_orchestrator_setup(),
        "Full Generation (Test)": test_full_generation_test_mode(),
    }

    # Summary
    print("\n" + "="*70)
    print("TEST SUMMARY")
    print("="*70)

    for test_name, result in results.items():
        status = "PASS" if result else "FAIL"
        print(f"{test_name:<40} {status}")

    passed = sum(1 for r in results.values() if r)
    total = len(results)

    print(f"\nTotal: {passed}/{total} tests passed")

    if passed == total:
        print("\nAll tests passed! Ready for production generation.")
        print("\nTo generate a 90-minute jazz video, run:")
        print("  python main.py jazz --count 1")
        print("\nTo generate 10 videos, run:")
        print("  python main.py jazz --count 10")
        return 0
    else:
        print("\nSome tests failed. Please fix the errors above.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
