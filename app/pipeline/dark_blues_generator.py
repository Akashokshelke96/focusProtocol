"""
Dark Blues Music Generation Orchestrator
Creates 5 variations of 20-minute dark blues tracks using Treblo API
Tracks progress and manages compilation pipeline
"""
import json
import time
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Optional
from concurrent.futures import ThreadPoolExecutor, as_completed
from app.config.logging_config import get_logger
from app.providers.treblo import TrebloProvider, create_dark_blues_prompt

logger = get_logger("pipeline.dark_blues_generator")


class DarkBluesGenerationOrchestrator:
    """Orchestrate generation of 5 dark blues variations for 2 compilations."""

    def __init__(self):
        self.logger = logger
        self.treblo = TrebloProvider()
        self.root_dir = Path(__file__).parent.parent.parent
        self.output_dir = self.root_dir / "output" / "EPISODES"
        self.generations_file = self.root_dir / "music_generations.json"

        # Ensure directories exist
        self.output_dir.mkdir(parents=True, exist_ok=True)

        # Load or create generations tracking
        self.generations = self._load_generations()

    def _load_generations(self) -> Dict:
        """Load generation tracking data."""
        if self.generations_file.exists():
            with open(self.generations_file, "r") as f:
                return json.load(f)
        return {
            "started_at": None,
            "status": "idle",
            "variations": {},
            "compilations": {},
        }

    def _save_generations(self) -> None:
        """Save generation tracking data."""
        with open(self.generations_file, "w") as f:
            json.dump(self.generations, f, indent=2)
        self.logger.info("Generation state saved")

    def start_generation(self) -> Dict:
        """Start generating 5 dark blues variations.

        Returns:
            Dict with generation_ids and status
        """
        self.logger.info("")
        self.logger.info("=" * 80)
        self.logger.info("STARTING DARK BLUES MUSIC GENERATION")
        self.logger.info("=" * 80)
        self.logger.info("")

        # Initialize generation tracking
        self.generations["started_at"] = datetime.utcnow().isoformat()
        self.generations["status"] = "generating"
        self.generations["variations"] = {}

        generation_ids = []

        # Generate 5 variations
        for variation_num in range(1, 6):
            self.logger.info(f"Queueing variation {variation_num}/5...")

            prompt = create_dark_blues_prompt(variation_num)
            title = f"Dark Blues - Variation {variation_num}"

            result = self.treblo.generate_music(
                prompt=prompt,
                duration_seconds=1200,  # 20 minutes
                title=title,
                style="dark_blues",
            )

            if result.get("status") == "queued":
                gen_id = result["generation_id"]
                generation_ids.append(gen_id)

                # Track generation
                self.generations["variations"][gen_id] = {
                    "variation": variation_num,
                    "title": title,
                    "status": "queued",
                    "progress": 0,
                    "created_at": result["created_at"],
                    "generation_id": gen_id,
                }

                self.logger.info(f"  Queued: {gen_id}")
            else:
                self.logger.error(f"  Failed: {result.get('message')}")

        self._save_generations()

        self.logger.info("")
        self.logger.info(f"Queued {len(generation_ids)}/5 variations")
        self.logger.info("")

        return {
            "status": "queued",
            "generation_ids": generation_ids,
            "total": 5,
            "queued": len(generation_ids),
        }

    def check_progress(self) -> Dict:
        """Check progress of all generations.

        Returns:
            Dict with status of all 5 variations
        """
        if not self.generations["variations"]:
            return {"status": "idle", "message": "No generations in progress"}

        stats = {
            "queued": 0,
            "processing": 0,
            "completed": 0,
            "failed": 0,
            "variations": [],
        }

        for gen_id, gen_data in self.generations["variations"].items():
            status_result = self.treblo.get_generation_status(gen_id)

            # Update tracking
            gen_data["status"] = status_result.get("status")
            gen_data["progress"] = status_result.get("progress", 0)

            if gen_data["status"] == "completed":
                gen_data["file_url"] = status_result.get("file_url")
                gen_data["duration_seconds"] = status_result.get("duration_seconds")

            # Count stats
            if gen_data["status"] == "queued":
                stats["queued"] += 1
            elif gen_data["status"] == "processing":
                stats["processing"] += 1
            elif gen_data["status"] == "completed":
                stats["completed"] += 1
            elif gen_data["status"] == "failed":
                stats["failed"] += 1

            # Add to variations list
            stats["variations"].append({
                "variation": gen_data.get("variation"),
                "title": gen_data.get("title"),
                "status": gen_data["status"],
                "progress": gen_data["progress"],
                "generation_id": gen_id,
            })

        # Update overall status
        self.generations["status"] = (
            "completed"
            if stats["completed"] == 5
            else "generating"
            if stats["queued"] > 0 or stats["processing"] > 0
            else "failed"
            if stats["failed"] > 0
            else "idle"
        )

        self._save_generations()

        return {
            "status": self.generations["status"],
            "stats": stats,
            "variations": sorted(stats["variations"], key=lambda x: x["variation"]),
        }

    def download_completed(self) -> List[Path]:
        """Download all completed music files.

        Returns:
            List of downloaded file paths
        """
        self.logger.info("Checking for completed generations...")

        downloaded = []

        for gen_id, gen_data in self.generations["variations"].items():
            if gen_data.get("status") == "completed" and "file_path" not in gen_data:
                file_url = gen_data.get("file_url")
                if file_url:
                    # Download file
                    output_path = (
                        self.output_dir
                        / f"variation_{gen_data['variation']:02d}"
                        / "music.mp3"
                    )

                    if self.treblo.download_music(file_url, output_path):
                        gen_data["file_path"] = str(output_path)
                        downloaded.append(output_path)
                        self.logger.info(f"Downloaded variation {gen_data['variation']}")

        self._save_generations()
        return downloaded

    def wait_for_completion(self, timeout_seconds: int = 3600) -> bool:
        """Wait for all generations to complete.

        Args:
            timeout_seconds: Maximum time to wait

        Returns:
            True if all completed, False if timeout
        """
        self.logger.info(f"Waiting for generations to complete (timeout: {timeout_seconds}s)...")

        start_time = time.time()
        check_count = 0

        while time.time() - start_time < timeout_seconds:
            progress = self.check_progress()

            self.logger.info(
                f"[Check {check_count}] Completed: {progress['stats']['completed']}/5 | "
                f"Processing: {progress['stats']['processing']} | "
                f"Queued: {progress['stats']['queued']}"
            )

            if progress["stats"]["completed"] == 5:
                self.logger.info("All variations completed!")
                self.download_completed()
                return True

            if progress["stats"]["failed"] > 0:
                self.logger.warning(
                    f"Some variations failed: {progress['stats']['failed']}"
                )

            check_count += 1
            time.sleep(30)  # Check every 30 seconds

        self.logger.error("Generation timeout")
        return False

    def create_compilations(self) -> Dict:
        """Create 2x 20-minute compilations from 5 variations.

        Returns:
            Dict with compilation details
        """
        from app.youtube.scheduler import YouTubeUploadScheduler

        self.logger.info("")
        self.logger.info("=" * 80)
        self.logger.info("CREATING COMPILATIONS FROM GENERATED VARIATIONS")
        self.logger.info("=" * 80)
        self.logger.info("")

        # Check all variations completed
        progress = self.check_progress()
        if progress["stats"]["completed"] < 5:
            self.logger.error(
                f"Not all variations ready: {progress['stats']['completed']}/5"
            )
            return {"status": "error", "message": "Not all variations completed"}

        scheduler = YouTubeUploadScheduler()

        compilations = []

        # Create Compilation 1: Variations 1, 2, 3 (20 min each = 60 min)
        self.logger.info("Creating Compilation 1: Variations 1, 2, 3...")
        comp1 = {
            "compilation_id": "compilation_dark_blues_1",
            "title": "Deep Focus Music - Part 1 (60 Minutes)",
            "variations": [1, 2, 3],
            "total_duration_minutes": 60,
            "episode": 1,
        }
        compilations.append(comp1)
        self.logger.info(f"  Compilation 1: {comp1['title']}")

        # Create Compilation 2: Variations 3, 4, 5 (20 min each = 60 min)
        # (Note: Variation 3 appears in both for variety)
        self.logger.info("Creating Compilation 2: Variations 3, 4, 5...")
        comp2 = {
            "compilation_id": "compilation_dark_blues_2",
            "title": "Deep Focus Music - Part 2 (60 Minutes)",
            "variations": [3, 4, 5],
            "total_duration_minutes": 60,
            "episode": 2,
        }
        compilations.append(comp2)
        self.logger.info(f"  Compilation 2: {comp2['title']}")

        # Queue compilations for upload
        for comp in compilations:
            job = scheduler.queue_compilation(
                episode_number=comp["episode"],
                upload_datetime=datetime.utcnow(),
                priority="high",
            )
            self.logger.info(
                f"Queued episode {comp['episode']} for upload scheduling"
            )

        self.generations["compilations"] = {
            str(c["episode"]): c for c in compilations
        }
        self._save_generations()

        self.logger.info("")
        self.logger.info(f"Created {len(compilations)} compilations")
        self.logger.info("")

        return {
            "status": "success",
            "compilations": compilations,
            "total": len(compilations),
        }

    def get_full_status(self) -> Dict:
        """Get complete status of generation and compilations.

        Returns:
            Full status dict
        """
        progress = self.check_progress()

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "overall_status": self.generations["status"],
            "started_at": self.generations["started_at"],
            "generations": progress,
            "compilations": self.generations.get("compilations", {}),
            "tracking_file": str(self.generations_file),
        }
