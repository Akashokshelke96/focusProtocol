from __future__ import annotations
"""
Job and state management
"""
import json
import os
import sqlite3
from dataclasses import dataclass, asdict
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Optional, Any
from app.config.settings import get_settings
from app.config.logging_config import get_logger

logger = get_logger("jobs.manager")


class JobStage(Enum):
    """Pipeline stages."""
    CREATED = "CREATED"
    CONTENT_GENERATED = "CONTENT_GENERATED"
    SCENES_PLANNED = "SCENES_PLANNED"
    MEDIA_SEARCHED = "MEDIA_SEARCHED"
    MEDIA_DOWNLOADED = "MEDIA_DOWNLOADED"
    MEDIA_VALIDATED = "MEDIA_VALIDATED"
    AUDIO_READY = "AUDIO_READY"
    TIMELINE_BUILT = "TIMELINE_BUILT"
    VIDEO_RENDERING = "VIDEO_RENDERING"
    VIDEO_COMPLETE = "VIDEO_COMPLETE"
    THUMBNAIL_COMPLETE = "THUMBNAIL_COMPLETE"
    METADATA_COMPLETE = "METADATA_COMPLETE"
    UPLOAD_COMPLETE = "UPLOAD_COMPLETE"


@dataclass
class JobState:
    """Represents job state."""
    id: str
    topic: str
    duration_minutes: int
    stage: str
    created_at: datetime
    updated_at: datetime
    status: str = "running"  # running, completed, failed
    error_message: Optional[str] = None
    metadata: dict[str, Any] = None

    def __post_init__(self):
        if self.metadata is None:
            self.metadata = {}

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "id": self.id,
            "topic": self.topic,
            "duration_minutes": self.duration_minutes,
            "stage": self.stage,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "status": self.status,
            "error_message": self.error_message,
            "metadata": self.metadata,
        }


class JobManager:
    """Manages job persistence and state."""

    def __init__(self):
        """Initialize job manager."""
        settings = get_settings()
        self.db_path = Path(settings.database_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()
        logger.info(f"Job manager initialized with database at {self.db_path}")

    def _init_db(self):
        """Initialize SQLite database."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS jobs (
                id TEXT PRIMARY KEY,
                topic TEXT NOT NULL,
                duration_minutes INTEGER NOT NULL,
                stage TEXT NOT NULL,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                error_message TEXT,
                metadata TEXT
            )
        """)

        conn.commit()
        conn.close()

    def create_job(self, job_id: str, topic: str, duration_minutes: int) -> JobState:
        """Create a new job."""
        previous = self.get_job(job_id)
        if previous:
            if previous.status not in ('failed', 'interrupted'):
                raise ValueError('Job already exists and cannot be generated twice')
            previous.status, previous.error_message = 'running', None
            previous.stage = JobStage.CREATED.value
            self.update_job(previous)
            return previous
        now = datetime.now()
        job = JobState(
            id=job_id,
            topic=topic,
            duration_minutes=duration_minutes,
            stage=JobStage.CREATED.value,
            created_at=now,
            updated_at=now,
            status="running",
        )

        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute("""
            INSERT INTO jobs (id, topic, duration_minutes, stage, status, created_at, updated_at, metadata)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            job.id,
            job.topic,
            job.duration_minutes,
            job.stage,
            job.status,
            job.created_at.isoformat(),
            job.updated_at.isoformat(),
            json.dumps(job.metadata),
        ))

        conn.commit()
        conn.close()

        from app.youtube.state import write_json
        write_json(Path('jobs') / job.id / 'job.json', job.to_dict())
        logger.info(f"Job created: {job_id}")
        return job

    def get_job(self, job_id: str) -> Optional[JobState]:
        """Retrieve job state."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute("SELECT * FROM jobs WHERE id = ?", (job_id,))
        row = cursor.fetchone()
        conn.close()

        if not row:
            return None

        return JobState(
            id=row[0],
            topic=row[1],
            duration_minutes=row[2],
            stage=row[3],
            status=row[4],
            created_at=datetime.fromisoformat(row[5]),
            updated_at=datetime.fromisoformat(row[6]),
            error_message=row[7],
            metadata=json.loads(row[8]) if row[8] else {},
        )

    def update_job(self, job: JobState):
        """Update job state."""
        job.updated_at = datetime.now()
        job.metadata['generation_status'] = job.status

        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute("""
            UPDATE jobs
            SET stage = ?, status = ?, updated_at = ?, error_message = ?, metadata = ?
            WHERE id = ?
        """, (
            job.stage,
            job.status,
            job.updated_at.isoformat(),
            job.error_message,
            json.dumps(job.metadata),
            job.id,
        ))

        conn.commit()
        conn.close()

        from app.youtube.state import write_json
        write_json(Path('jobs') / job.id / 'metadata.json', job.metadata)
        write_json(Path('jobs') / job.id / 'job.json', job.to_dict())
        logger.info(f"Job updated: {job.id} -> {job.stage}")

    def list_jobs(self, limit: int = 50) -> list[JobState]:
        """List recent jobs."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute("""
            SELECT * FROM jobs
            ORDER BY created_at DESC
            LIMIT ?
        """, (limit,))

        rows = cursor.fetchall()
        conn.close()

        jobs = []
        for row in rows:
            jobs.append(JobState(
                id=row[0],
                topic=row[1],
                duration_minutes=row[2],
                stage=row[3],
                status=row[4],
                created_at=datetime.fromisoformat(row[5]),
                updated_at=datetime.fromisoformat(row[6]),
                error_message=row[7],
                metadata=json.loads(row[8]) if row[8] else {},
            ))
        return jobs

    def delete_job(self, job_id: str) -> int:
        """Delete a job's folder and registry row. Returns freed bytes.

        Refuses when the job id is unsafe, unknown, or still rendering.
        """
        import re
        import shutil
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]*', job_id or ''):
            raise ValueError('Invalid job id')
        job_dir = (Path('jobs') / job_id).resolve()
        if not str(job_dir).startswith(str(Path('jobs').resolve()) + os.sep):
            raise ValueError('Invalid job id')
        if not job_dir.is_dir():
            raise ValueError('Job not found')
        if self.get_job(job_id) is None:
            raise ValueError('Job not found')
        try:
            from app.studio.recovery import process_alive
            from app.youtube.state import read_json
            progress = read_json(job_dir / 'render_progress.json', {})
            if progress.get('status') == 'running' and process_alive(progress.get('owner')):
                raise RuntimeError('Job is still rendering; cancel it first')
        except (RuntimeError, ValueError):
            raise
        except Exception:
            pass
        freed = sum(f.stat().st_size for f in job_dir.rglob('*') if f.is_file())
        shutil.rmtree(job_dir, ignore_errors=True)
        conn = sqlite3.connect(self.db_path)
        conn.execute("DELETE FROM jobs WHERE id = ?", (job_id,))
        conn.commit()
        conn.close()
        logger.info(f"Job deleted: {job_id} ({freed} bytes freed)")
        return freed
