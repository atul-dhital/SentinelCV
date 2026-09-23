"""
SentinelCV Distributed Worker Daemon

Long-running process that consumes jobs from the shared job queue
(Redis-backed when available, in-memory otherwise) and dispatches each
job to its registered handler. Multiple instances of this script can run
in parallel on the same or different hosts to scale horizontally.

Usage:
    python -m backend.scripts.distributed_worker
    python -m backend.scripts.distributed_worker --poll-interval 0.5
    python -m backend.scripts.distributed_worker --once
    python -m backend.scripts.distributed_worker --health-port 9090

The worker prints its identity (hostname:pid) on start so individual
instances are distinguishable in logs and Grafana dashboards.  When Redis
is available the worker publishes a heartbeat key
``sentinelcv:worker:<identity>`` with a 30-second TTL so all running
workers are visible to operators and load balancers via ``list_active_workers()``.

Job-type → handler bindings live in ``register_default_handlers`` below.
Add a handler whenever a new ``JobType`` value is introduced; the worker
will refuse the job (mark it failed) if no handler is registered, so this
file should always stay in sync with ``services/job_queue_service.JobType``.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import socket
import sys
import threading
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any, Dict, List, Optional

BACKEND_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_ROOT not in sys.path:
    sys.path.insert(0, BACKEND_ROOT)

from services.job_queue_service import Job, JobType, job_queue  # noqa: E402

logger = logging.getLogger("distributed_worker")

_WORKER_HEARTBEAT_KEY_PREFIX = "sentinelcv:worker:"
_WORKER_HEARTBEAT_TTL_SECONDS = 30
_HEARTBEAT_EVERY_N_ITERATIONS = 10  # publish heartbeat every N poll iterations


# ── Worker identity ───────────────────────────────────────────────────────


def _identity() -> str:
    return f"{socket.gethostname()}:{os.getpid()}"


# ── Heartbeat & multi-node coordination ──────────────────────────────────


def _get_redis_service():
    try:
        from services.redis_service import get_redis_service
        return get_redis_service()
    except Exception:
        return None


def _publish_heartbeat(stats: Dict[str, Any]) -> None:
    """Write worker presence + stats to Redis with a rolling TTL.

    Other workers and operators can call ``list_active_workers()`` to
    enumerate all running instances via the ``sentinelcv:worker:*`` pattern.
    If Redis is unavailable the call is a silent no-op.
    """
    redis = _get_redis_service()
    if redis is None:
        return
    key = f"{_WORKER_HEARTBEAT_KEY_PREFIX}{_identity()}"
    payload = {
        "identity": _identity(),
        "hostname": socket.gethostname(),
        "pid": os.getpid(),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "stats": stats,
    }
    try:
        redis.cache_set_json(key, payload, ttl=_WORKER_HEARTBEAT_TTL_SECONDS)
    except Exception as exc:
        logger.debug("Heartbeat publish failed: %s", exc)


def list_active_workers() -> List[Dict[str, Any]]:
    """Return heartbeat payloads for all currently running workers.

    Workers that missed their TTL window are automatically absent.
    """
    redis = _get_redis_service()
    if redis is None:
        return []
    pattern = f"{_WORKER_HEARTBEAT_KEY_PREFIX}*"
    try:
        keys = redis.scan_keys(pattern)
        workers = []
        for key in keys:
            data = redis.cache_get_json(key)
            if isinstance(data, dict):
                workers.append(data)
        return workers
    except Exception as exc:
        logger.debug("list_active_workers failed: %s", exc)
        return []


# ── Minimal HTTP health-check server ─────────────────────────────────────


class _HealthServer(threading.Thread):
    """Tiny HTTP server that exposes ``/health`` and ``/workers`` endpoints.

    Designed for Kubernetes liveness probes and Prometheus scraping.
    Runs as a daemon thread so it dies with the worker process.
    """

    def __init__(self, port: int) -> None:
        super().__init__(name="worker-health-server", daemon=True)
        self.port = port
        self._stats: Dict[str, Any] = {}

    def update_stats(self, stats: Dict[str, Any]) -> None:
        self._stats = dict(stats)

    def run(self) -> None:
        stats_ref = self  # captured by inner class

        class _Handler(BaseHTTPRequestHandler):
            def log_message(self, *_):  # silence default access log
                pass

            def do_GET(self):  # noqa: N802
                if self.path in ("/health", "/healthz"):
                    self._json(200, {
                        "status": "ok",
                        "identity": _identity(),
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "stats": stats_ref._stats,
                    })
                elif self.path == "/workers":
                    self._json(200, {"workers": list_active_workers()})
                else:
                    self._json(404, {"error": "not found"})

            def _json(self, code: int, body: dict) -> None:
                payload = json.dumps(body).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

        try:
            server = HTTPServer(("0.0.0.0", self.port), _Handler)
            logger.info("Health server listening on :%d", self.port)
            server.serve_forever()
        except Exception as exc:
            logger.warning("Health server failed to start on port %d: %s", self.port, exc)


# ── Handler implementations ──────────────────────────────────────────────


def _handle_video_processing(job: Job) -> dict:
    """Forward to the existing video pipeline."""
    from api.video import trigger_video_processing  # local import to avoid heavy startup

    payload = job.payload or {}
    organization_id = str(payload.get("organization_id") or "").strip()
    video_path = str(payload.get("video_path") or "").strip()
    target_job_id = str(payload.get("job_id") or job.id).strip()

    if not organization_id or not video_path:
        raise ValueError("video_processing job requires organization_id and video_path")

    trigger_video_processing(organization_id, video_path, target_job_id)
    return {"video_path": video_path, "organization_id": organization_id}


def _handle_synthetic_data(job: Job) -> dict:
    import asyncio

    from services.synthetic_data_service import SyntheticDataService

    payload = job.payload or {}
    target_job_id = str(payload.get("job_id") or job.id).strip()
    if not target_job_id:
        raise ValueError("synthetic_data_gen job requires a job_id payload")

    service = SyntheticDataService()
    asyncio.run(service.run_synthesis_job(target_job_id))
    return {"job_id": target_job_id}


def _handle_face_embedding(job: Job) -> dict:
    """Compute embeddings for a list of face image paths."""
    from ai_services.face_engine import FaceEngine  # type: ignore

    payload = job.payload or {}
    image_paths = payload.get("image_paths") or []
    if not isinstance(image_paths, list) or not image_paths:
        raise ValueError("face_embedding job requires non-empty image_paths list")

    engine = FaceEngine()
    embeddings = []
    for path in image_paths:
        try:
            embedding = engine.compute_embedding(str(path))
            embeddings.append({"path": str(path), "embedding": embedding})
        except Exception as exc:  # one bad image shouldn't kill the batch
            logger.warning("Embedding failed for %s: %s", path, exc)
            embeddings.append({"path": str(path), "error": str(exc)})

    return {"count": len(embeddings), "embeddings": embeddings}


def _handle_benchmark(job: Job) -> dict:
    """Run a benchmark sweep via the in-process benchmark service."""
    from services.benchmark_service import benchmark_service  # type: ignore

    payload = job.payload or {}
    suite = str(payload.get("suite") or "default")
    if hasattr(benchmark_service, "run_suite"):
        results = benchmark_service.run_suite(suite)
    else:
        results = {"error": "benchmark_service has no run_suite method"}
    return {"suite": suite, "results": results}


def _handle_report_generation(job: Job) -> dict:
    from services.report_service import generate_report  # type: ignore

    payload = job.payload or {}
    report_id = str(payload.get("report_id") or "").strip()
    if not report_id:
        raise ValueError("report_generation job requires report_id")

    generate_report(report_id)
    return {"report_id": report_id}


def _handle_email_notification(job: Job) -> dict:
    from services.email_service import send_email  # type: ignore

    payload = job.payload or {}
    recipient = payload.get("to")
    subject = payload.get("subject", "SentinelCV notification")
    body = payload.get("body", "")
    if not recipient:
        raise ValueError("email_notification job requires 'to'")
    send_email(recipient, subject, body)
    return {"to": recipient, "subject": subject}


# ── Registry ─────────────────────────────────────────────────────────────


def register_default_handlers() -> None:
    """Register the built-in handlers used by the SentinelCV deployment.

    Handlers that depend on optional services (e.g. email, benchmark) are
    registered defensively — a worker that lacks the dependency will mark
    the job as failed with a clear error rather than crashing.
    """
    job_queue.register_handler(JobType.VIDEO_PROCESSING.value, _handle_video_processing)
    job_queue.register_handler(JobType.SYNTHETIC_DATA_GEN.value, _handle_synthetic_data)
    job_queue.register_handler(JobType.FACE_EMBEDDING.value, _handle_face_embedding)
    job_queue.register_handler(JobType.BENCHMARK.value, _handle_benchmark)
    job_queue.register_handler(JobType.REPORT_GENERATION.value, _handle_report_generation)
    job_queue.register_handler(JobType.EMAIL_NOTIFICATION.value, _handle_email_notification)


# ── Worker loop ──────────────────────────────────────────────────────────


def run_worker(poll_interval: float, once: bool, health_port: Optional[int] = None) -> int:
    register_default_handlers()
    stats = job_queue.get_stats()
    logger.info(
        "Worker %s starting (backend=%s, registered_handlers=%d)",
        _identity(),
        stats.get("backend"),
        len(job_queue._handlers),  # noqa: SLF001
    )

    health_server: Optional[_HealthServer] = None
    if health_port is not None:
        health_server = _HealthServer(health_port)
        health_server.start()

    # Publish initial heartbeat so the worker appears immediately in listings.
    _publish_heartbeat(stats)

    if once:
        job = job_queue.process_one()
        if job is None:
            logger.info("Queue empty — nothing to process")
            return 0
        logger.info("Processed job %s (status=%s)", job.id, job.status)
        return 0 if job.status == "completed" else 1

    iteration = 0
    while True:
        try:
            job = job_queue.process_one()
            if job is None:
                time.sleep(max(poll_interval, 0.05))
            else:
                logger.info(
                    "Processed job %s type=%s status=%s",
                    job.id,
                    job.job_type,
                    job.status,
                )

            iteration += 1
            if iteration % _HEARTBEAT_EVERY_N_ITERATIONS == 0:
                current_stats = job_queue.get_stats()
                _publish_heartbeat(current_stats)
                if health_server is not None:
                    health_server.update_stats(current_stats)

        except KeyboardInterrupt:
            logger.info("Worker %s shutting down on Ctrl-C", _identity())
            return 0
        except Exception as exc:  # never let a bad job kill the worker
            logger.exception("Unexpected worker error: %s", exc)
            time.sleep(max(poll_interval, 0.05))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--poll-interval",
        type=float,
        default=1.0,
        help="Idle sleep between empty-queue polls (seconds)",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Process at most one queued job and exit (useful for tests)",
    )
    parser.add_argument(
        "--log-level",
        default=os.getenv("DISTRIBUTED_WORKER_LOG_LEVEL", "INFO"),
        help="Logging level (DEBUG/INFO/WARNING/ERROR)",
    )
    parser.add_argument(
        "--health-port",
        type=int,
        default=int(os.getenv("WORKER_HEALTH_PORT", "0")) or None,
        help="Port for the HTTP health-check server (0 = disabled). "
             "Exposes /health and /workers endpoints.",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=args.log_level.upper(),
        format="%(asctime)s %(levelname)-7s %(name)s %(message)s",
    )

    return run_worker(args.poll_interval, args.once, health_port=args.health_port)


if __name__ == "__main__":
    raise SystemExit(main())
