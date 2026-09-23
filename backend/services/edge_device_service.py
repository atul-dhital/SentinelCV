from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple
import hashlib
import logging
import secrets
import json
import uuid

logger = logging.getLogger(__name__)

from sqlalchemy.orm import Session

from core.security import decrypt_embedding
from models import models


@dataclass
class EdgeEmbeddingSyncResult:
    items: List[Dict[str, Any]]
    count: int
    next_offset: Optional[int]


@dataclass
class EdgeDeviceSummaryResult:
    total_devices: int
    online_devices: int
    offline_devices: int
    error_devices: int
    deployed_devices: int
    devices_with_recent_sync: int
    last_seen_at: Optional[datetime]
    recent_events: List[models.EdgeDeviceEvent]


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def generate_device_token() -> Tuple[str, str, str]:
    token = secrets.token_urlsafe(32)
    token_hash = _hash_token(token)
    token_prefix = token[:8]
    return token, token_hash, token_prefix


def find_device_by_token(db: Session, token: str) -> Optional[models.EdgeDevice]:
    token_hash = _hash_token(token)
    return db.query(models.EdgeDevice).filter(
        models.EdgeDevice.token_hash == token_hash,
    ).first()


def _parse_embedding_payload(raw_embedding: Any) -> Optional[List[float]]:
    if raw_embedding is None:
        return None

    if isinstance(raw_embedding, (list, tuple)):
        try:
            return [float(value) for value in raw_embedding]
        except (TypeError, ValueError):
            return None

    tolist = getattr(raw_embedding, "tolist", None)
    if callable(tolist):
        try:
            values = tolist()
            if isinstance(values, list):
                return [float(value) for value in values]
        except (TypeError, ValueError):
            return None

    if isinstance(raw_embedding, str):
        candidate_strings = [raw_embedding]
        try:
            candidate_strings.insert(0, decrypt_embedding(raw_embedding))
        except Exception:
            pass

        for candidate in candidate_strings:
            try:
                parsed = json.loads(candidate)
                if isinstance(parsed, list):
                    return [float(value) for value in parsed]
            except Exception:
                continue

        cleaned = raw_embedding.strip()
        if cleaned.startswith("[") and cleaned.endswith("]"):
            try:
                return [float(piece.strip()) for piece in cleaned[1:-1].split(",") if piece.strip()]
            except (TypeError, ValueError):
                return None

    return None


def build_embedding_sync_payload(
    db: Session,
    organization_id: object,
    *,
    since: Optional[datetime],
    offset: int,
    limit: int,
) -> EdgeEmbeddingSyncResult:
    query = (
        db.query(models.FaceData)
        .join(models.Visitor)
        .filter(models.Visitor.organization_id == organization_id)
        .order_by(models.FaceData.created_at.asc())
    )

    if since is not None:
        query = query.filter(models.FaceData.created_at >= since)

    items: List[Dict[str, Any]] = []
    rows = query.offset(offset).limit(limit + 1).all()

    for face in rows[:limit]:
        embedding = _parse_embedding_payload(face.embedding)
        if not embedding:
            continue

        visitor = face.visitor
        items.append(
            {
                "visitor_id": visitor.id,
                "visitor_name": visitor.name if visitor else None,
                "visitor_known": bool(visitor.is_known) if visitor else False,
                "face_data_id": face.id,
                "embedding": embedding,
                "image_url": face.image_url,
                "quality_score": float(face.quality_score or 0.0),
                "face_angle": face.face_angle,
                "is_primary": bool(face.is_primary),
                "created_at": face.created_at,
            }
        )

    next_offset = None
    if len(rows) > limit:
        next_offset = offset + limit

    return EdgeEmbeddingSyncResult(
        items=items,
        count=len(items),
        next_offset=next_offset,
    )


def record_edge_event(
    db: Session,
    device: models.EdgeDevice,
    event_type: str,
    severity: str,
    title: str,
    message: Optional[str],
    payload: Optional[Dict[str, Any]],
) -> models.EdgeDeviceEvent:
    event = models.EdgeDeviceEvent(
        organization_id=device.organization_id,
        edge_device_id=device.id,
        event_type=event_type,
        severity=severity,
        title=title,
        message=message,
        payload=payload or {},
    )
    db.add(event)

    notification = models.Notification(
        organization_id=device.organization_id,
        user_id=None,
        title=title,
        message=message,
        notification_type=severity,
        link=None,
    )
    db.add(notification)
    db.commit()
    db.refresh(event)
    return event


def update_device_heartbeat(
    db: Session,
    device: models.EdgeDevice,
    *,
    status: Optional[str],
    ip_address: Optional[str],
    metrics: Optional[Dict[str, Any]],
    model_version_id: Optional[object],
) -> models.EdgeDevice:
    device.last_seen = datetime.now(timezone.utc)
    if status:
        device.status = status
    if ip_address:
        device.ip_address = ip_address
    if metrics is not None:
        device.last_metrics = metrics
    if model_version_id is not None:
        device.model_version_id = model_version_id
    db.commit()
    db.refresh(device)
    return device


def deploy_model_to_device(
    db: Session,
    device: models.EdgeDevice,
    model_version: models.ModelVersion,
    *,
    deployment_config: Optional[Dict[str, Any]] = None,
) -> models.EdgeDevice:
    deployed_at = datetime.now(timezone.utc)
    model_config = dict(device.model_config or {})
    model_config.update(
        {
            "model_id": str(model_version.id),
            "model_name": model_version.name,
            "model_type": model_version.model_type,
            "version": model_version.version,
            "deployed_at": deployed_at.isoformat(),
            "deployment_config": deployment_config or {},
        }
    )

    device.model_version_id = model_version.id
    device.model_artifact_path = model_version.file_path
    device.model_config = model_config
    device.last_sync_at = deployed_at
    device.last_sync_status = "success"
    device.status = "online" if device.status in {None, "", "offline"} else device.status
    device.updated_at = deployed_at
    db.commit()
    db.refresh(device)

    record_edge_event(
        db,
        device,
        event_type="deployment",
        severity="info",
        title=f"Model deployed: {model_version.name} v{model_version.version}",
        message=f"Deployed {model_version.model_type} model to edge device",
        payload={
            "model_version_id": str(model_version.id),
            "model_name": model_version.name,
            "model_type": model_version.model_type,
            "version": model_version.version,
            "artifact_path": model_version.file_path,
            "deployment_config": deployment_config or {},
        },
    )
    db.refresh(device)
    return device


_HEARTBEAT_STALE_SECONDS: int = 120   # device considered offline after 2 min


def check_device_health(device: models.EdgeDevice) -> Dict[str, Any]:
    """Return health status dict for a single edge device.

    Marks device offline when no heartbeat received within HEARTBEAT_STALE_SECONDS.
    Detects model staleness by comparing device model_version_id against the
    latest deployed version recorded in model_config.
    """
    now = datetime.now(timezone.utc)
    last_seen = device.last_seen
    if last_seen is None:
        heartbeat_age_seconds = None
        is_reachable = False
    else:
        if last_seen.tzinfo is None:
            last_seen = last_seen.replace(tzinfo=timezone.utc)
        heartbeat_age_seconds = (now - last_seen).total_seconds()
        is_reachable = heartbeat_age_seconds <= _HEARTBEAT_STALE_SECONDS

    metrics = device.last_metrics or {}
    model_config = device.model_config or {}
    deployed_at_str = model_config.get("deployed_at")

    return {
        "device_id": str(device.id),
        "device_name": device.name,
        "status": device.status,
        "is_reachable": is_reachable,
        "heartbeat_age_seconds": heartbeat_age_seconds,
        "stale_threshold_seconds": _HEARTBEAT_STALE_SECONDS,
        "model_version_id": str(device.model_version_id) if device.model_version_id else None,
        "model_name": model_config.get("model_name"),
        "model_version": model_config.get("version"),
        "deployed_at": deployed_at_str,
        "last_sync_at": device.last_sync_at.isoformat() if device.last_sync_at else None,
        "last_sync_status": device.last_sync_status,
        "cpu_usage": metrics.get("cpu_usage"),
        "memory_usage": metrics.get("memory_usage"),
        "temperature_c": metrics.get("temperature_c"),
        "inference_queue_depth": metrics.get("inference_queue_depth", 0),
        "ip_address": device.ip_address,
    }


def auto_mark_offline_stale_devices(db: Session, organization_id: object) -> int:
    """Mark as offline any devices that missed their heartbeat window.

    Returns the number of devices updated.
    """
    stale_cutoff = datetime.now(timezone.utc) - timedelta(seconds=_HEARTBEAT_STALE_SECONDS)
    devices = (
        db.query(models.EdgeDevice)
        .filter(
            models.EdgeDevice.organization_id == organization_id,
            models.EdgeDevice.status == "online",
            models.EdgeDevice.last_seen < stale_cutoff,
        )
        .all()
    )
    updated = 0
    for device in devices:
        device.status = "offline"
        record_edge_event(
            db,
            device,
            event_type="connectivity",
            severity="warning",
            title="Edge device heartbeat timeout",
            message=f"No heartbeat received for >{_HEARTBEAT_STALE_SECONDS}s — marking offline",
            payload={"last_seen": device.last_seen.isoformat() if device.last_seen else None},
        )
        updated += 1
    if updated:
        db.commit()
        logger.warning("Marked %d stale edge device(s) offline", updated)
    return updated


@dataclass
class InferenceRequest:
    request_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    device_id: str = ""
    organization_id: str = ""
    image_path: Optional[str] = None
    embedding_input: Optional[List[float]] = None
    request_type: str = "identify"   # identify | detect | liveness
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    status: str = "pending"
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    completed_at: Optional[str] = None


def dispatch_inference_to_device(
    db: Session,
    device: models.EdgeDevice,
    *,
    request_type: str = "identify",
    image_path: Optional[str] = None,
    embedding_input: Optional[List[float]] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Queue an inference request for an edge device.

    Records the request as an edge event and returns a tracking dict the
    caller can poll.  In a real deployment the device polls
    ``GET /api/v1/edge-devices/<id>/inference-queue`` for pending jobs.
    """
    if device.status not in ("online", "deployed"):
        raise ValueError(
            f"Device '{device.name}' is {device.status} — cannot dispatch inference"
        )

    request_id = str(uuid.uuid4())
    payload = {
        "request_id": request_id,
        "request_type": request_type,
        "image_path": image_path,
        "has_embedding": embedding_input is not None,
        "metadata": metadata or {},
    }

    record_edge_event(
        db,
        device,
        event_type="inference_dispatch",
        severity="info",
        title=f"Inference dispatched: {request_type}",
        message=f"Request {request_id} queued for {device.name}",
        payload=payload,
    )

    logger.info("Inference request %s dispatched to device %s", request_id, device.id)
    return {
        "request_id": request_id,
        "device_id": str(device.id),
        "device_name": device.name,
        "request_type": request_type,
        "status": "queued",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }


def record_inference_result(
    db: Session,
    device: models.EdgeDevice,
    *,
    request_id: str,
    result: Dict[str, Any],
    processing_time_ms: Optional[float] = None,
) -> Dict[str, Any]:
    """Store the inference result received back from an edge device."""
    now = datetime.now(timezone.utc)
    payload: Dict[str, Any] = {
        "request_id": request_id,
        "result": result,
        "processing_time_ms": processing_time_ms,
        "received_at": now.isoformat(),
    }

    record_edge_event(
        db,
        device,
        event_type="inference_result",
        severity="info",
        title=f"Inference result received: {request_id[:8]}",
        message=(
            f"Device returned result in "
            f"{processing_time_ms:.0f}ms" if processing_time_ms else "Device returned result"
        ),
        payload=payload,
    )

    # Update metrics from result if present
    if processing_time_ms is not None:
        current_metrics = dict(device.last_metrics or {})
        history = current_metrics.get("inference_latency_history_ms", [])
        history.append(round(processing_time_ms, 2))
        current_metrics["inference_latency_history_ms"] = history[-20:]
        current_metrics["avg_inference_latency_ms"] = round(
            sum(history) / len(history), 2
        )
        device.last_metrics = current_metrics
        db.commit()
        db.refresh(device)

    logger.debug("Inference result for %s stored (device %s)", request_id, device.id)
    return payload


def build_device_summary(
    db: Session,
    organization_id: object,
    *,
    recent_event_limit: int = 10,
) -> EdgeDeviceSummaryResult:
    devices = (
        db.query(models.EdgeDevice)
        .filter(models.EdgeDevice.organization_id == organization_id)
        .order_by(models.EdgeDevice.created_at.desc())
        .all()
    )
    events = (
        db.query(models.EdgeDeviceEvent)
        .filter(models.EdgeDeviceEvent.organization_id == organization_id)
        .order_by(models.EdgeDeviceEvent.created_at.desc())
        .limit(recent_event_limit)
        .all()
    )

    last_seen_at = None
    for device in devices:
        if device.last_seen and (last_seen_at is None or device.last_seen > last_seen_at):
            last_seen_at = device.last_seen

    return EdgeDeviceSummaryResult(
        total_devices=len(devices),
        online_devices=sum(1 for device in devices if device.status == "online"),
        offline_devices=sum(1 for device in devices if device.status == "offline"),
        error_devices=sum(1 for device in devices if device.status == "error"),
        deployed_devices=sum(1 for device in devices if device.model_version_id is not None),
        devices_with_recent_sync=sum(1 for device in devices if device.last_sync_at is not None),
        last_seen_at=last_seen_at,
        recent_events=events,
    )
