from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from typing import Any, Dict, List, Optional, Tuple


def _normalize_queue_mode(value: str) -> str:
    cleaned = (value or "").strip().lower()
    if cleaned in {"redis", "background"}:
        return cleaned
    return "background"


def _normalize_job_type(job_type: str) -> str:
    cleaned = (job_type or "").strip().lower()
    if cleaned in {"video", "synthetic", "temporal"}:
        return cleaned
    return "video"


def _queue_mode_env_name(job_type: str) -> str:
    normalized = _normalize_job_type(job_type)
    if normalized == "video":
        return "VIDEO_JOB_QUEUE_MODE"
    return f"{normalized.upper()}_JOB_QUEUE_MODE"


def _queue_key_env_name(job_type: str) -> str:
    normalized = _normalize_job_type(job_type)
    if normalized == "video":
        return "VIDEO_JOB_QUEUE_KEY"
    return f"{normalized.upper()}_JOB_QUEUE_KEY"


def _worker_heartbeat_prefix(job_type: str) -> str:
    normalized = _normalize_job_type(job_type)
    return f"sentinelcv:queue_worker:{normalized}:"


def _worker_heartbeat_ttl_seconds() -> int:
    raw = (os.getenv("QUEUE_WORKER_HEARTBEAT_TTL_SECONDS") or "").strip()
    try:
        parsed = int(raw) if raw else 30
    except ValueError:
        parsed = 30
    return max(5, min(600, parsed))


def get_video_job_queue_mode() -> str:
    return _normalize_queue_mode(os.getenv("VIDEO_JOB_QUEUE_MODE", "background"))


def get_video_job_queue_key() -> str:
    key = (os.getenv("VIDEO_JOB_QUEUE_KEY") or "").strip()
    return key or "sentinelcv:video_jobs"


def get_job_queue_mode(job_type: str) -> str:
    normalized = _normalize_job_type(job_type)
    env_name = _queue_mode_env_name(normalized)
    fallback = os.getenv("VIDEO_JOB_QUEUE_MODE", "background")
    return _normalize_queue_mode(os.getenv(env_name, fallback))


def get_job_queue_key(job_type: str) -> str:
    normalized = _normalize_job_type(job_type)
    env_name = _queue_key_env_name(normalized)
    default_keys = {
        "video": "sentinelcv:video_jobs",
        "synthetic": "sentinelcv:synthetic_jobs",
        "temporal": "sentinelcv:temporal_jobs",
    }
    key = (os.getenv(env_name) or "").strip()
    return key or default_keys.get(normalized, default_keys["video"])


def _get_redis_client() -> tuple[Optional[Any], Optional[str]]:
    try:
        import redis  # type: ignore
    except Exception:
        return None, "redis_python_package_missing"

    redis_url = (os.getenv("REDIS_URL") or "").strip()
    if not redis_url:
        return None, "redis_url_not_configured"

    try:
        client = redis.Redis.from_url(redis_url, decode_responses=True)
        client.ping()
        return client, None
    except Exception as exc:
        return None, f"redis_unreachable: {exc}"


def get_video_job_queue_status() -> Dict[str, Any]:
    return get_job_queue_status("video")


def _collect_worker_heartbeats(client: Any, job_type: str) -> List[Dict[str, Any]]:
    normalized = _normalize_job_type(job_type)
    pattern = f"{_worker_heartbeat_prefix(normalized)}*"
    workers: List[Dict[str, Any]] = []

    try:
        for key in client.scan_iter(match=pattern, count=100):
            payload = client.get(key)
            if not payload:
                continue
            try:
                parsed = json.loads(payload)
            except Exception:
                continue
            if not isinstance(parsed, dict):
                continue
            parsed.setdefault("worker_id", str(key).split(":")[-1])
            workers.append(parsed)
    except Exception:
        return []

    workers.sort(key=lambda item: str(item.get("heartbeat_at") or ""), reverse=True)
    return workers


def get_job_queue_status(job_type: str) -> Dict[str, Any]:
    normalized = _normalize_job_type(job_type)
    mode = get_job_queue_mode(normalized)
    key = get_job_queue_key(normalized)

    if mode != "redis":
        return {
            "mode": "background",
            "active": True,
            "provider": "fastapi_background_tasks",
            "queue_key": key,
            "job_type": normalized,
            "reason": None,
        }

    client, error = _get_redis_client()
    if client is None:
        return {
            "mode": "redis",
            "active": False,
            "provider": "redis_list",
            "queue_key": key,
            "job_type": normalized,
            "reason": error,
        }

    queue_depth: Optional[int] = None
    worker_heartbeats: List[Dict[str, Any]] = []
    try:
        queue_depth = int(client.llen(key))
    except Exception:
        queue_depth = None

    worker_heartbeats = _collect_worker_heartbeats(client, normalized)

    return {
        "mode": "redis",
        "active": True,
        "provider": "redis_list",
        "queue_key": key,
        "job_type": normalized,
        "reason": None,
        "queue_depth": queue_depth,
        "worker_count": len(worker_heartbeats),
        "workers": worker_heartbeats[:10],
    }


def enqueue_video_job(organization_id: str, video_path: str, job_id: str) -> Tuple[bool, str]:
    payload = {
        "organization_id": organization_id,
        "video_path": video_path,
        "job_id": job_id,
    }
    return enqueue_job("video", payload)


def enqueue_synthetic_job(organization_id: str, job_id: str, config_id: str, total_samples: int) -> Tuple[bool, str]:
    payload = {
        "organization_id": organization_id,
        "job_id": job_id,
        "config_id": config_id,
        "total_samples": int(total_samples),
    }
    return enqueue_job("synthetic", payload)


def enqueue_temporal_job(
    organization_id: str,
    job_id: str,
    config_id: str,
    input_video_path: str,
) -> Tuple[bool, str]:
    payload = {
        "organization_id": organization_id,
        "job_id": job_id,
        "config_id": config_id,
        "input_video_path": input_video_path,
    }
    return enqueue_job("temporal", payload)


def enqueue_job(job_type: str, payload: Dict[str, Any]) -> Tuple[bool, str]:
    normalized = _normalize_job_type(job_type)
    status = get_job_queue_status(normalized)
    if status.get("mode") != "redis":
        return False, "redis_queue_disabled"
    if not status.get("active"):
        return False, str(status.get("reason") or "redis_queue_unavailable")

    client, error = _get_redis_client()
    if client is None:
        return False, error or "redis_queue_unavailable"

    try:
        queue_payload = dict(payload)
        queue_payload["job_type"] = normalized
        queue_payload["enqueued_at"] = datetime.now(timezone.utc).isoformat()
        client.rpush(get_job_queue_key(normalized), json.dumps(queue_payload))
        return True, "enqueued"
    except Exception as exc:
        return False, f"redis_enqueue_failed: {exc}"


def publish_worker_heartbeat(
    job_type: str,
    worker_id: str,
    metadata: Optional[Dict[str, Any]] = None,
) -> Tuple[bool, str]:
    normalized = _normalize_job_type(job_type)
    worker_name = (worker_id or "").strip()
    if not worker_name:
        return False, "missing_worker_id"

    status = get_job_queue_status(normalized)
    if status.get("mode") != "redis":
        return False, "redis_queue_disabled"
    if not status.get("active"):
        return False, str(status.get("reason") or "redis_queue_unavailable")

    client, error = _get_redis_client()
    if client is None:
        return False, error or "redis_queue_unavailable"

    heartbeat = {
        "worker_id": worker_name,
        "job_type": normalized,
        "heartbeat_at": datetime.now(timezone.utc).isoformat(),
        "metadata": metadata or {},
    }

    try:
        key = f"{_worker_heartbeat_prefix(normalized)}{worker_name}"
        client.set(key, json.dumps(heartbeat), ex=_worker_heartbeat_ttl_seconds())
        return True, "heartbeat_updated"
    except Exception as exc:
        return False, f"heartbeat_update_failed: {exc}"


def dequeue_video_job(timeout_seconds: int = 5) -> Optional[Dict[str, Any]]:
    return dequeue_job("video", timeout_seconds=timeout_seconds)


def dequeue_job(job_type: str, timeout_seconds: int = 5) -> Optional[Dict[str, Any]]:
    normalized = _normalize_job_type(job_type)
    status = get_job_queue_status(normalized)
    if status.get("mode") != "redis" or not status.get("active"):
        return None

    client, _error = _get_redis_client()
    if client is None:
        return None

    item = client.blpop(get_job_queue_key(normalized), timeout=timeout_seconds)
    if not item:
        return None

    _queue_name, payload = item
    try:
        parsed = json.loads(payload)
    except Exception:
        return None

    if not isinstance(parsed, dict):
        return None

    parsed.setdefault("job_type", normalized)
    return parsed
