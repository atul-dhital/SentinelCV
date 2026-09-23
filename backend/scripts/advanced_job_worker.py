import argparse
import asyncio
import os
import socket
import sys
import time

BACKEND_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_ROOT not in sys.path:
    sys.path.insert(0, BACKEND_ROOT)

from api.video import trigger_video_processing
from services import temporal_augmentation_service, video_queue_service
from services.synthetic_data_service import SyntheticDataService


def _process_video_job(payload: dict) -> bool:
    organization_id = str(payload.get("organization_id") or "").strip()
    video_path = str(payload.get("video_path") or "").strip()
    job_id = str(payload.get("job_id") or "").strip()
    if not organization_id or not video_path or not job_id:
        return False

    trigger_video_processing(organization_id, video_path, job_id)
    return True


def _process_synthetic_job(payload: dict) -> bool:
    job_id = str(payload.get("job_id") or "").strip()
    if not job_id:
        return False

    service = SyntheticDataService()
    asyncio.run(service.run_synthesis_job(job_id))
    return True


def _process_temporal_job(payload: dict) -> bool:
    job_id = str(payload.get("job_id") or "").strip()
    if not job_id:
        return False

    service = temporal_augmentation_service.TemporalAugmentationService()
    asyncio.run(service.run_augmentation_job(job_id))
    return True


def _process_one(job_type: str, timeout_seconds: int) -> bool:
    payload = video_queue_service.dequeue_job(job_type, timeout_seconds=timeout_seconds)
    if not payload:
        return False

    if job_type == "video":
        return _process_video_job(payload)
    if job_type == "synthetic":
        return _process_synthetic_job(payload)
    if job_type == "temporal":
        return _process_temporal_job(payload)
    return False


def main() -> int:
    parser = argparse.ArgumentParser(description="Process SentinelCV queued jobs from Redis")
    parser.add_argument(
        "--job-type",
        choices=["video", "synthetic", "temporal", "all"],
        default="all",
        help="Job queue to process",
    )
    parser.add_argument("--once", action="store_true", help="Process at most one queued job and exit")
    parser.add_argument("--poll-interval", type=float, default=1.0, help="Idle sleep seconds between polls")
    parser.add_argument("--pop-timeout", type=int, default=5, help="Blocking pop timeout in seconds")
    args = parser.parse_args()

    job_types = ["video", "synthetic", "temporal"] if args.job_type == "all" else [args.job_type]

    inactive = []
    for job_type in job_types:
        status = video_queue_service.get_job_queue_status(job_type)
        if status.get("mode") != "redis" or not status.get("active"):
            inactive.append(f"{job_type}: {status.get('reason') or 'redis queue is not active'}")

    if inactive and len(inactive) == len(job_types):
        print("Cannot start worker: " + "; ".join(inactive))
        return 1

    print("Listening on queues:")
    for job_type in job_types:
        status = video_queue_service.get_job_queue_status(job_type)
        print(f"- {job_type}: {status.get('queue_key')}")

    worker_id = os.getenv("ADV_JOB_WORKER_ID") or f"adv-{socket.gethostname()}-{os.getpid()}"
    base_meta = {
        "hostname": socket.gethostname(),
        "pid": os.getpid(),
        "worker_mode": args.job_type,
    }

    if args.once:
        for job_type in job_types:
            status = video_queue_service.get_job_queue_status(job_type)
            metadata = dict(base_meta)
            metadata["queue_key"] = status.get("queue_key")
            video_queue_service.publish_worker_heartbeat(job_type, worker_id, metadata=metadata)
            if _process_one(job_type, args.pop_timeout):
                print(f"Processed one queued {job_type} job")
                return 0
        print("No queued job available")
        return 0

    while True:
        processed_any = False
        for job_type in job_types:
            status = video_queue_service.get_job_queue_status(job_type)
            metadata = dict(base_meta)
            metadata["queue_key"] = status.get("queue_key")
            video_queue_service.publish_worker_heartbeat(job_type, worker_id, metadata=metadata)
            if _process_one(job_type, args.pop_timeout):
                processed_any = True
        if not processed_any:
            time.sleep(max(args.poll_interval, 0.1))


if __name__ == "__main__":
    raise SystemExit(main())
