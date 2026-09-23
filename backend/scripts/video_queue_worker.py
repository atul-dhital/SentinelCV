import argparse
import os
import socket
import sys
import time

BACKEND_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_ROOT not in sys.path:
    sys.path.insert(0, BACKEND_ROOT)

from api.video import trigger_video_processing
from services import video_queue_service


def _process_one(timeout_seconds: int) -> bool:
    payload = video_queue_service.dequeue_video_job(timeout_seconds=timeout_seconds)
    if not payload:
        return False

    organization_id = str(payload.get("organization_id") or "").strip()
    video_path = str(payload.get("video_path") or "").strip()
    job_id = str(payload.get("job_id") or "").strip()
    if not organization_id or not video_path or not job_id:
        return False

    trigger_video_processing(organization_id, video_path, job_id)
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description="Process SentinelCV video jobs from Redis queue")
    parser.add_argument("--once", action="store_true", help="Process at most one queued job and exit")
    parser.add_argument("--poll-interval", type=float, default=1.0, help="Idle sleep seconds between polls")
    parser.add_argument("--pop-timeout", type=int, default=5, help="Blocking pop timeout in seconds")
    args = parser.parse_args()

    status = video_queue_service.get_video_job_queue_status()
    if status.get("mode") != "redis" or not status.get("active"):
        reason = status.get("reason") or "redis queue is not active"
        print(f"Cannot start worker: {reason}")
        return 1

    print(f"Listening on queue: {status.get('queue_key')}")

    worker_id = os.getenv("VIDEO_QUEUE_WORKER_ID") or f"video-{socket.gethostname()}-{os.getpid()}"
    worker_meta = {
        "hostname": socket.gethostname(),
        "pid": os.getpid(),
        "queue_key": status.get("queue_key"),
    }

    if args.once:
        video_queue_service.publish_worker_heartbeat("video", worker_id, metadata=worker_meta)
        processed = _process_one(args.pop_timeout)
        print("Processed one queued job" if processed else "No queued job available")
        return 0

    while True:
        video_queue_service.publish_worker_heartbeat("video", worker_id, metadata=worker_meta)
        processed = _process_one(args.pop_timeout)
        if not processed:
            time.sleep(max(args.poll_interval, 0.1))


if __name__ == "__main__":
    raise SystemExit(main())
