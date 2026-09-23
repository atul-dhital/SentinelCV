"""
Background Job Queue Service

Provides job queuing, scheduling, and status tracking for async tasks.
Uses Redis as broker when available, falls back to in-memory queue.

Supports a per-job-type handler registry so that multiple worker processes
(possibly on different hosts) can share the same Redis-backed queue and
process jobs in parallel — the foundation for distributed processing.
"""

import uuid
import time
import json
import logging
import threading
import traceback
from typing import Any, Callable, Dict, List, Optional
from dataclasses import dataclass, field, asdict
from enum import Enum
from collections import deque
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

JOB_CACHE_TTL_SECONDS = 86400
REDIS_PENDING_QUEUE_KEY = "sentinelcv:jobqueue:pending"
REDIS_JOB_INDEX_KEY = "sentinelcv:jobqueue:index"


class JobStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class JobType(str, Enum):
    VIDEO_PROCESSING = "video_processing"
    MODEL_TRAINING = "model_training"
    DATA_QUALITY_AUDIT = "data_quality_audit"
    SYNTHETIC_DATA_GEN = "synthetic_data_gen"
    REPORT_GENERATION = "report_generation"
    FACE_EMBEDDING = "face_embedding"
    BENCHMARK = "benchmark"
    EXPORT_MODEL = "export_model"
    EMAIL_NOTIFICATION = "email_notification"


MAX_JOB_RETRIES = 3
RETRY_BASE_DELAY_SECONDS = 5.0  # delay = base * 2^attempt


@dataclass
class Job:
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    job_type: str = ""
    payload: dict = field(default_factory=dict)
    status: str = JobStatus.QUEUED
    result: Optional[dict] = None
    error: Optional[str] = None
    progress: float = 0.0
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    organization_id: Optional[str] = None
    user_id: Optional[str] = None
    retry_count: int = 0
    max_retries: int = MAX_JOB_RETRIES
    retry_after: Optional[str] = None   # ISO timestamp; worker skips until this time

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "Job":
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


class JobQueue:
    """
    In-memory job queue with optional Redis backing.
    Thread-safe for concurrent access.
    """

    def __init__(self):
        self._queue: deque = deque()
        self._jobs: Dict[str, Job] = {}
        self._lock = threading.Lock()
        self._redis = None
        self._handlers: Dict[str, Callable[[Job], Optional[dict]]] = {}
        self._try_redis()

    # ── Handler registry ────────────────────────────────────────────────
    def register_handler(
        self,
        job_type: str,
        handler: Callable[["Job"], Optional[dict]],
    ) -> None:
        """Register a callable that processes jobs of ``job_type``.

        The handler receives the dequeued ``Job`` and may return a result
        dict that gets stored on the job. Raising an exception marks the
        job as failed with the exception's string representation.

        Multiple worker processes can register the same handler against
        the same Redis-backed queue to scale processing horizontally.
        """
        self._handlers[job_type] = handler
        logger.info("Registered handler for job_type=%s", job_type)

    def get_handler(self, job_type: str) -> Optional[Callable[["Job"], Optional[dict]]]:
        return self._handlers.get(job_type)

    def process_one(self) -> Optional[Job]:
        """Pop a single job and dispatch it to the matching handler.

        Returns the processed Job (in completed/failed/queued state), or None
        when the queue is empty. Designed to be called in a tight loop by a
        worker daemon (see ``backend/scripts/distributed_worker.py``).

        Retry policy: on failure the job is re-queued up to ``max_retries``
        times with exponential back-off (base * 2^attempt seconds).  After
        exhausting retries the job is permanently marked FAILED.
        """
        job = self.dequeue()
        if not job:
            return None

        # Respect retry_after delay — put back and skip this cycle
        if job.retry_after:
            try:
                retry_at = datetime.fromisoformat(job.retry_after)
                if retry_at.tzinfo is None:
                    retry_at = retry_at.replace(tzinfo=timezone.utc)
                if datetime.now(timezone.utc) < retry_at:
                    job.status = JobStatus.QUEUED
                    with self._lock:
                        self._jobs[job.id] = job
                        self._queue.append(job.id)
                    if self._redis:
                        self._persist_job(job)
                        self._redis.list_right_push(REDIS_PENDING_QUEUE_KEY, job.id)
                    return None
            except (ValueError, TypeError):
                pass

        handler = self.get_handler(job.job_type)
        if handler is None:
            self.fail_job(job.id, f"No handler registered for job_type={job.job_type}")
            return self.get_job(job.id)

        try:
            result = handler(job)
            self.complete_job(job.id, result if isinstance(result, dict) else None)
        except Exception as exc:
            tb = traceback.format_exc()
            logger.error("Job %s failed (attempt %d/%d): %s\n%s",
                         job.id, job.retry_count + 1, job.max_retries + 1, exc, tb)
            job.retry_count += 1
            if job.retry_count <= job.max_retries:
                delay = RETRY_BASE_DELAY_SECONDS * (2 ** (job.retry_count - 1))
                retry_at = datetime.now(timezone.utc).replace(
                    microsecond=0
                ).isoformat()
                from datetime import timedelta
                retry_dt = datetime.now(timezone.utc) + timedelta(seconds=delay)
                job.retry_after = retry_dt.isoformat()
                job.status = JobStatus.QUEUED
                job.error = str(exc)
                job.started_at = None
                with self._lock:
                    self._jobs[job.id] = job
                    self._queue.append(job.id)
                if self._redis:
                    self._persist_job(job)
                    self._redis.list_right_push(REDIS_PENDING_QUEUE_KEY, job.id)
                logger.info("Job %s scheduled for retry %d in %.0fs",
                            job.id, job.retry_count, delay)
            else:
                self.fail_job(job.id, str(exc))
                logger.error("Job %s permanently failed after %d retries",
                             job.id, job.max_retries)
        return self.get_job(job.id)

    def _try_redis(self):
        """Try to use Redis for persistent queue."""
        try:
            from services.redis_service import get_redis_service

            redis_service = get_redis_service()
            if redis_service.is_redis:
                self._redis = redis_service
                logger.info("Job queue using Redis backend")
            else:
                logger.info("Job queue using in-memory backend")
        except Exception:
            logger.info("Job queue using in-memory backend")

    def _job_cache_key(self, job_id: str) -> str:
        return f"sentinelcv:job:{job_id}"

    def _persist_job(self, job: Job):
        if self._redis:
            self._redis.cache_set_json(
                self._job_cache_key(job.id),
                job.to_dict(),
                ttl=JOB_CACHE_TTL_SECONDS,
            )
            self._add_job_to_index(job.id)

    def _load_job_from_redis(self, job_id: str) -> Optional[Job]:
        if not self._redis:
            return None
        data = self._redis.cache_get_json(self._job_cache_key(job_id))
        if isinstance(data, dict):
            return Job.from_dict(data)
        return None

    def _add_job_to_index(self, job_id: str):
        if not self._redis:
            return
        current = self._redis.cache_get_json(REDIS_JOB_INDEX_KEY) or []
        if not isinstance(current, list):
            current = []
        current = [str(existing) for existing in current if str(existing) != job_id]
        current.insert(0, job_id)
        self._redis.cache_set_json(
            REDIS_JOB_INDEX_KEY,
            current[:1000],
            ttl=JOB_CACHE_TTL_SECONDS,
        )

    def _all_jobs(self) -> List[Job]:
        with self._lock:
            jobs_by_id: Dict[str, Job] = dict(self._jobs)

        if self._redis:
            indexed_job_ids = self._redis.cache_get_json(REDIS_JOB_INDEX_KEY) or []
            if isinstance(indexed_job_ids, list):
                for job_id in indexed_job_ids:
                    normalized_id = str(job_id)
                    if normalized_id in jobs_by_id:
                        continue
                    job = self._load_job_from_redis(normalized_id)
                    if job:
                        jobs_by_id[job.id] = job

        return list(jobs_by_id.values())

    def enqueue(
        self,
        job_type: str,
        payload: dict,
        organization_id: Optional[str] = None,
        user_id: Optional[str] = None,
    ) -> Job:
        """Add a job to the queue."""
        job = Job(
            job_type=job_type,
            payload=payload,
            organization_id=organization_id,
            user_id=user_id,
        )

        with self._lock:
            self._jobs[job.id] = job
            if not self._redis:
                self._queue.append(job.id)

        if self._redis:
            self._persist_job(job)
            queued = self._redis.list_right_push(REDIS_PENDING_QUEUE_KEY, job.id)
            if not queued:
                with self._lock:
                    self._queue.append(job.id)

        logger.info(f"Enqueued job {job.id} (type={job_type})")
        return job

    def dequeue(self) -> Optional[Job]:
        """Get the next job from the queue."""
        if self._redis:
            while True:
                job_id = self._redis.list_left_pop(REDIS_PENDING_QUEUE_KEY)
                if not job_id:
                    break
                job = self.get_job(str(job_id))
                if not job or job.status != JobStatus.QUEUED:
                    continue
                job.status = JobStatus.RUNNING
                job.started_at = datetime.now(timezone.utc).isoformat()
                self._persist_job(job)
                with self._lock:
                    self._jobs[job.id] = job
                return job

        with self._lock:
            if not self._queue:
                return None
            job_id = self._queue.popleft()
            job = self._jobs.get(job_id)
            if job:
                job.status = JobStatus.RUNNING
                job.started_at = datetime.now(timezone.utc).isoformat()
                self._persist_job(job)
            return job

    def complete_job(self, job_id: str, result: Optional[dict] = None):
        """Mark a job as completed."""
        job = self.get_job(job_id)
        if not job:
            return
        job.status = JobStatus.COMPLETED
        job.result = result
        job.progress = 100.0
        job.completed_at = datetime.now(timezone.utc).isoformat()
        with self._lock:
            self._jobs[job_id] = job
        self._persist_job(job)

    def fail_job(self, job_id: str, error: str):
        """Mark a job as failed."""
        job = self.get_job(job_id)
        if not job:
            return
        job.status = JobStatus.FAILED
        job.error = error
        job.completed_at = datetime.now(timezone.utc).isoformat()
        with self._lock:
            self._jobs[job_id] = job
        self._persist_job(job)

    def update_progress(self, job_id: str, progress: float):
        """Update job progress (0-100)."""
        job = self.get_job(job_id)
        if not job:
            return
        job.progress = min(100.0, max(0.0, progress))
        with self._lock:
            self._jobs[job_id] = job
        self._persist_job(job)

    def get_job(self, job_id: str) -> Optional[Job]:
        """Get job by ID."""
        if self._redis:
            job = self._load_job_from_redis(job_id)
            if job:
                with self._lock:
                    self._jobs[job_id] = job
                return job
        with self._lock:
            return self._jobs.get(job_id)

    def get_job_status(self, job_id: str) -> Optional[dict]:
        """Get job status as dict."""
        job = self.get_job(job_id)
        if job:
            return job.to_dict()
        return None

    def list_jobs(
        self,
        organization_id: Optional[str] = None,
        status_filter: Optional[str] = None,
        job_type: Optional[str] = None,
        limit: int = 50,
    ) -> List[dict]:
        """List jobs with optional filters."""
        jobs = self._all_jobs()

        if organization_id:
            jobs = [j for j in jobs if j.organization_id == organization_id]
        if status_filter:
            jobs = [j for j in jobs if j.status == status_filter]
        if job_type:
            jobs = [j for j in jobs if j.job_type == job_type]

        jobs.sort(key=lambda j: j.created_at, reverse=True)
        return [j.to_dict() for j in jobs[:limit]]

    def cancel_job(self, job_id: str) -> bool:
        """Cancel a queued job."""
        job = self.get_job(job_id)
        if job and job.status == JobStatus.QUEUED:
            job.status = JobStatus.CANCELLED
            with self._lock:
                self._jobs[job_id] = job
                if job_id in self._queue:
                    self._queue.remove(job_id)
            if self._redis:
                self._redis.list_remove(REDIS_PENDING_QUEUE_KEY, job_id, count=0)
            self._persist_job(job)
            return True
        return False

    def queue_size(self) -> int:
        if self._redis:
            with self._lock:
                local_size = len(self._queue)
            return self._redis.list_length(REDIS_PENDING_QUEUE_KEY) + local_size
        with self._lock:
            return len(self._queue)

    def get_stats(self) -> dict:
        """Get queue statistics."""
        jobs = self._all_jobs()

        return {
            "total_jobs": len(jobs),
            "queued": sum(1 for j in jobs if j.status == JobStatus.QUEUED),
            "running": sum(1 for j in jobs if j.status == JobStatus.RUNNING),
            "completed": sum(1 for j in jobs if j.status == JobStatus.COMPLETED),
            "failed": sum(1 for j in jobs if j.status == JobStatus.FAILED),
            "cancelled": sum(1 for j in jobs if j.status == JobStatus.CANCELLED),
            "queue_size": self.queue_size(),
            "backend": "redis" if self._redis and self._redis.is_redis else "in-memory",
        }


# Singleton
job_queue = JobQueue()
