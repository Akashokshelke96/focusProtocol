"""
Batch Scheduler & YouTube Uploader
Schedules multiple compilations and uploads to YouTube
"""
import json
import time
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional, List
from app.config.logging_config import get_logger
from app.youtube.metadata_generator import YouTubeMetadataGenerator
from app.youtube.thumbnail_generator import ThumbnailGenerator
from app.pipeline.silent_dark_blues_compiler import SilentDarkBluesCompiler

logger = get_logger("youtube.scheduler")


class YouTubeUploadScheduler:
    """Schedule and batch process YouTube video uploads."""

    def __init__(self):
        self.logger = logger
        self.metadata_gen = YouTubeMetadataGenerator()
        self.thumbnail_gen = ThumbnailGenerator()
        self.root_dir = Path(__file__).parent.parent.parent
        self.schedule_file = self.root_dir / "youtube_upload_schedule.json"
        self.load_schedule()

    def load_schedule(self) -> dict:
        """Load existing schedule or create new one."""
        if self.schedule_file.exists():
            with open(self.schedule_file, "r") as f:
                self.schedule = json.load(f)
            self.logger.info(f"Loaded schedule with {len(self.schedule.get('queue', []))} videos")
        else:
            self.schedule = {
                "created_at": datetime.utcnow().isoformat(),
                "queue": [],
                "completed": [],
                "failed": [],
            }
        return self.schedule

    def save_schedule(self) -> None:
        """Save schedule to disk."""
        with open(self.schedule_file, "w") as f:
            json.dump(self.schedule, f, indent=2)
        self.logger.info(f"Schedule saved ({len(self.schedule['queue'])} queued)")

    def queue_compilation(
        self,
        episode_number: int,
        upload_datetime: datetime,
        priority: str = "normal",
    ) -> dict:
        """Queue a compilation for generation and upload."""
        job = {
            "episode": episode_number,
            "scheduled_upload": upload_datetime.isoformat(),
            "priority": priority,
            "status": "queued",
            "created_at": datetime.utcnow().isoformat(),
            "compilation_id": None,
            "video_path": None,
            "thumbnail_path": None,
            "metadata": None,
            "youtube_video_id": None,
        }

        self.schedule["queue"].append(job)
        self.save_schedule()
        self.logger.info(f"Queued episode {episode_number} for {upload_datetime}")
        return job

    def batch_queue_compilations(self, num_videos: int, start_date: datetime, frequency_days: int = 3) -> List[dict]:
        """Queue multiple compilations on a schedule."""
        self.logger.info(f"Queueing {num_videos} videos starting {start_date} (every {frequency_days} days)...")

        jobs = []
        for i in range(num_videos):
            episode_num = len(self.schedule["completed"]) + len(self.schedule["queue"]) + 1
            upload_time = start_date + timedelta(days=i * frequency_days)
            job = self.queue_compilation(
                episode_number=episode_num,
                upload_datetime=upload_time,
                priority="normal" if i > 0 else "high",
            )
            jobs.append(job)

        self.logger.info(f"Queued {len(jobs)} videos")
        return jobs

    def process_queue(self, max_parallel: int = 1, auto_upload: bool = False) -> dict:
        """Process queued compilations."""
        self.logger.info("")
        self.logger.info("=" * 80)
        self.logger.info("PROCESSING YOUTUBE UPLOAD QUEUE")
        self.logger.info("=" * 80)
        self.logger.info("")

        queued = self.schedule["queue"]
        if not queued:
            self.logger.info("No videos in queue")
            return {"status": "empty", "processed": 0}

        # Sort by priority and scheduled time
        queued.sort(key=lambda x: (x["priority"] != "high", x["scheduled_upload"]))

        processed = 0
        for i, job in enumerate(queued[:max_parallel], 1):
            self.logger.info(f"[{i}/{min(len(queued), max_parallel)}] Processing episode {job['episode']}...")

            try:
                # Generate compilation
                compiler = SilentDarkBluesCompiler()
                result = compiler.run()

                if result["status"] != "success":
                    job["status"] = "failed"
                    job["error"] = result.get("reason", "Unknown error")
                    self.logger.error(f"Compilation failed: {job['error']}")
                    self.schedule["failed"].append(job)
                    self.schedule["queue"].remove(job)
                    continue

                job["compilation_id"] = result["run_id"]
                job["video_path"] = result["final_video"]

                # Generate metadata
                self.logger.info("Generating YouTube metadata...")
                metadata = self.metadata_gen.generate_metadata(
                    compilation_id=result["run_id"],
                    song_titles=[f"Song {i+1}" for i in range(len(result.get("videos_generated", 0)))],
                    total_duration_minutes=int(result["total_duration_minutes"]),
                    episode_number=job["episode"],
                )
                job["metadata"] = metadata

                # Generate thumbnail
                self.logger.info("Generating thumbnail...")
                thumbnail = self.thumbnail_gen.generate_thumbnail(
                    episode_number=job["episode"],
                    duration_minutes=int(result["total_duration_minutes"]),
                    title_text=metadata.get("title", "")[:40],
                )
                job["thumbnail_path"] = str(thumbnail)

                job["status"] = "ready_for_upload"
                processed += 1

                self.logger.info(f"Episode {job['episode']} ready for upload")
                self.logger.info(f"  Video: {Path(job['video_path']).name}")
                self.logger.info(f"  Thumbnail: {Path(job['thumbnail_path']).name}")
                self.logger.info(f"  Title: {metadata.get('title', '')[:50]}")
                self.logger.info("")

            except Exception as e:
                self.logger.error(f"Processing failed for episode {job['episode']}: {e}")
                job["status"] = "failed"
                job["error"] = str(e)
                self.schedule["failed"].append(job)
                self.schedule["queue"].remove(job)
                continue

        # Remove processed items from queue
        self.schedule["queue"] = [j for j in self.schedule["queue"] if j["status"] == "queued"]

        self.save_schedule()

        self.logger.info("")
        self.logger.info("=" * 80)
        self.logger.info(f"QUEUE PROCESSING COMPLETE ({processed} processed)")
        self.logger.info("=" * 80)
        self.logger.info("")

        return {
            "status": "success",
            "processed": processed,
            "ready_for_upload": sum(1 for j in self.schedule.get("queue", []) if j.get("status") == "ready_for_upload"),
        }

    def get_upload_queue(self) -> List[dict]:
        """Get list of videos ready for upload."""
        ready = [j for j in self.schedule["queue"] if j.get("status") == "ready_for_upload"]
        return sorted(ready, key=lambda x: x["scheduled_upload"])

    def mock_upload_to_youtube(self, job: dict) -> dict:
        """Simulate YouTube upload (for testing without credentials)."""
        self.logger.info(f"MOCK: Uploading episode {job['episode']} to YouTube...")

        video_path = Path(job["video_path"])
        thumbnail_path = Path(job["thumbnail_path"])

        if not video_path.exists():
            self.logger.error(f"Video not found: {video_path}")
            return {"status": "failed", "error": "Video not found"}

        if not thumbnail_path.exists():
            self.logger.error(f"Thumbnail not found: {thumbnail_path}")
            return {"status": "failed", "error": "Thumbnail not found"}

        # Generate mock video ID
        video_id = f"sdb_{job['episode']:03d}_{int(time.time() % 1000000)}"

        result = {
            "video_id": video_id,
            "title": job["metadata"].get("title", ""),
            "episode": job["episode"],
            "uploaded_at": datetime.utcnow().isoformat(),
            "video_url": f"https://youtube.com/watch?v={video_id}",
            "status": "uploaded",
        }

        job["youtube_video_id"] = video_id
        job["status"] = "uploaded"
        job["uploaded_at"] = result["uploaded_at"]

        # Save all episode data to EPISODES folder structure
        self.save_episode_data(job)

        self.logger.info(f"MOCK uploaded: {result['video_url']}")
        return result

    def save_episode_data(self, job: dict) -> None:
        """Save all episode data to EPISODES folder structure."""
        from pathlib import Path
        import json

        episode_num = job["episode"]
        episode_dir = Path("output") / "EPISODES" / f"episode_{episode_num:03d}"
        episode_dir.mkdir(parents=True, exist_ok=True)

        # Save episode metadata
        metadata_file = episode_dir / "metadata.json"
        metadata_content = {
            "episode": episode_num,
            "created_at": job.get("created_at"),
            "scheduled_upload": job.get("scheduled_upload"),
            "priority": job.get("priority"),
            "status": job.get("status"),
            "compilation_id": job.get("compilation_id"),
            "metadata": job.get("metadata"),
            "youtube_video_id": job.get("youtube_video_id"),
            "uploaded_at": job.get("uploaded_at"),
        }

        with open(metadata_file, "w") as f:
            json.dump(metadata_content, f, indent=2)

        self.logger.info(f"Episode data saved to {episode_dir}")

    def get_schedule_status(self) -> dict:
        """Get current schedule status."""
        return {
            "total_scheduled": len(self.schedule["queue"]) + len(self.schedule["completed"]),
            "queued": len([j for j in self.schedule["queue"] if j["status"] == "queued"]),
            "ready_for_upload": len([j for j in self.schedule["queue"] if j["status"] == "ready_for_upload"]),
            "uploaded": len(self.schedule["completed"]),
            "failed": len(self.schedule["failed"]),
        }

    def print_status(self) -> None:
        """Print schedule status."""
        status = self.get_schedule_status()
        self.logger.info("")
        self.logger.info("YOUTUBE SCHEDULE STATUS")
        self.logger.info("-" * 40)
        self.logger.info(f"Queued for processing: {status['queued']}")
        self.logger.info(f"Ready for upload: {status['ready_for_upload']}")
        self.logger.info(f"Uploaded: {status['uploaded']}")
        self.logger.info(f"Failed: {status['failed']}")
        self.logger.info(f"Total scheduled: {status['total_scheduled']}")
        self.logger.info("")
