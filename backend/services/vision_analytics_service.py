from __future__ import annotations

import base64
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from core.storage import storage
from models import models
from schemas import schemas


VALID_EVENT_TYPES = {"pose_estimate", "action_infer"}


def _split_data_uri(image_data: Optional[str]) -> tuple[Optional[str], Optional[str]]:
    if not image_data:
        return None, None

    if image_data.startswith("data:") and "," in image_data:
        header, raw = image_data.split(",", 1)
        mime = "image/jpeg"
        if ";" in header:
            mime_candidate = header[5:].split(";", 1)[0]
            if mime_candidate:
                mime = mime_candidate
        return raw, mime

    return image_data, "image/jpeg"


def normalize_thumbnail_data_uri(image_data: Optional[str]) -> Optional[str]:
    raw, mime = _split_data_uri(image_data)
    if not raw:
        return None
    return f"data:{mime or 'image/jpeg'};base64,{raw}"


def normalize_frame_payload(frame_data: str) -> tuple[str, str]:
    raw, mime = _split_data_uri(frame_data)
    if not raw:
        return frame_data, "data:image/jpeg;base64,"
    return raw, f"data:{mime or 'image/jpeg'};base64,{raw}"


def _snapshot_extension_from_mime(mime: Optional[str]) -> str:
    if not mime:
        return ".jpg"
    mapping = {
        "image/jpeg": ".jpg",
        "image/jpg": ".jpg",
        "image/png": ".png",
        "image/webp": ".webp",
    }
    return mapping.get(mime.lower(), ".jpg")


def persist_snapshot_thumbnail(
    image_data: Optional[str],
    *,
    event_type: str,
    camera_id: Optional[str] = None,
) -> Optional[str]:
    raw, mime = _split_data_uri(image_data)
    if not raw:
        return None

    try:
        image_bytes = base64.b64decode(raw)
    except Exception:
        return None

    if not image_bytes:
        return None

    ext = _snapshot_extension_from_mime(mime)
    camera_part = (camera_id or "nocamera").replace("-", "")[:12]
    file_name = f"{event_type}_{camera_part}_{uuid.uuid4().hex}{ext}"
    relative_path = f"vision_snapshots/{file_name}"

    try:
        storage.save_file(relative_path, image_bytes, content_type=mime or "image/jpeg")
    except RuntimeError:
        return None

    return relative_path


def snapshot_static_url(snapshot_path: Optional[str]) -> Optional[str]:
    if not snapshot_path:
        return None
    normalized = snapshot_path.replace("\\", "/").lstrip("/")
    return f"/static/{normalized}"


def _build_summary(event_type: str, payload: Dict[str, Any]) -> str:
    if event_type == "pose_estimate":
        posture = payload.get("posture", "unknown")
        keypoints = int(payload.get("keypoint_count", 0) or 0)
        visibility = float(payload.get("average_visibility", 0.0) or 0.0)
        return f"Pose {posture}, keypoints={keypoints}, visibility={visibility:.2f}"

    if event_type == "action_infer":
        action = payload.get("action", "unknown")
        gesture = payload.get("gesture", "none")
        confidence = float(payload.get("confidence", 0.0) or 0.0)
        return f"Action {action}, gesture={gesture}, confidence={confidence:.2f}"

    return event_type


def record_vision_event(
    db: Session,
    *,
    organization_id: object,
    event_type: str,
    source: str,
    model: Optional[str],
    status: str,
    payload: Dict[str, Any],
    camera_id: Optional[str] = None,
    snapshot_thumbnail: Optional[str] = None,
) -> models.VisionAnalyticsEvent:
    if event_type not in VALID_EVENT_TYPES:
        raise ValueError(f"Unsupported event_type: {event_type}")

    snapshot_path = persist_snapshot_thumbnail(
        snapshot_thumbnail,
        event_type=event_type,
        camera_id=camera_id,
    )
    summary = _build_summary(event_type, payload)

    confidence = payload.get("confidence")
    confidence_value = None
    if confidence is not None:
        try:
            confidence_value = float(confidence)
        except (TypeError, ValueError):
            confidence_value = None

    event = models.VisionAnalyticsEvent(
        organization_id=organization_id,
        camera_id=camera_id,
        event_type=event_type,
        source=source,
        model=model,
        status=status,
        summary=summary,
        confidence=confidence_value,
        posture=payload.get("posture"),
        action=payload.get("action"),
        gesture=payload.get("gesture"),
        snapshot_path=snapshot_path,
        payload=payload,
    )
    db.add(event)
    db.commit()
    db.refresh(event)
    return event


def list_vision_history(
    db: Session,
    *,
    organization_id: object,
    event_type: Optional[str] = None,
    camera_id: Optional[str] = None,
    limit: int = 20,
    lookback_hours: int = 72,
) -> schemas.VisionAnalyticsHistoryResponse:
    bounded_limit = max(1, min(limit, 200))
    bounded_hours = max(1, min(lookback_hours, 24 * 30))
    since = datetime.now(timezone.utc) - timedelta(hours=bounded_hours)

    query = db.query(models.VisionAnalyticsEvent).filter(
        models.VisionAnalyticsEvent.organization_id == organization_id,
        models.VisionAnalyticsEvent.created_at >= since,
    )

    if event_type:
        query = query.filter(models.VisionAnalyticsEvent.event_type == event_type)
    if camera_id:
        query = query.filter(models.VisionAnalyticsEvent.camera_id == camera_id)

    total = query.count()
    rows = query.order_by(models.VisionAnalyticsEvent.created_at.desc()).limit(bounded_limit).all()

    items: List[schemas.VisionAnalyticsHistoryItem] = []
    for row in rows:
        items.append(
            schemas.VisionAnalyticsHistoryItem(
                id=row.id,
                event_type=row.event_type,
                source=row.source,
                camera_id=row.camera_id,
                camera_name=row.camera.name if row.camera else None,
                model=row.model,
                status=row.status,
                summary=row.summary,
                posture=row.posture,
                action=row.action,
                gesture=row.gesture,
                confidence=row.confidence,
                snapshot_url=snapshot_static_url(row.snapshot_path),
                created_at=row.created_at,
            )
        )

    return schemas.VisionAnalyticsHistoryResponse(
        event_type=event_type,
        lookback_hours=bounded_hours,
        total=total,
        items=items,
    )


def summarize_recent_vision_activity(
    db: Session,
    *,
    organization_id: object,
    lookback_hours: int = 24,
) -> Dict[str, Any]:
    bounded_hours = max(1, min(lookback_hours, 24 * 30))
    since = datetime.now(timezone.utc) - timedelta(hours=bounded_hours)
    rows = db.query(models.VisionAnalyticsEvent).filter(
        models.VisionAnalyticsEvent.organization_id == organization_id,
        models.VisionAnalyticsEvent.created_at >= since,
    ).all()

    pose_events = [row for row in rows if row.event_type == "pose_estimate"]
    action_events = [row for row in rows if row.event_type == "action_infer"]

    posture_counts: Dict[str, int] = {}
    action_counts: Dict[str, int] = {}
    gesture_counts: Dict[str, int] = {}

    for row in pose_events:
        posture = (row.posture or "unknown").strip() or "unknown"
        posture_counts[posture] = posture_counts.get(posture, 0) + 1

    for row in action_events:
        action = (row.action or "unknown").strip() or "unknown"
        gesture = (row.gesture or "none").strip() or "none"
        action_counts[action] = action_counts.get(action, 0) + 1
        gesture_counts[gesture] = gesture_counts.get(gesture, 0) + 1

    top_posture = max(posture_counts.items(), key=lambda item: item[1])[0] if posture_counts else None
    top_action = max(action_counts.items(), key=lambda item: item[1])[0] if action_counts else None
    top_gesture = max(gesture_counts.items(), key=lambda item: item[1])[0] if gesture_counts else None

    return {
        "lookback_hours": bounded_hours,
        "total_events": len(rows),
        "pose_event_count": len(pose_events),
        "action_event_count": len(action_events),
        "top_posture": top_posture,
        "top_action": top_action,
        "top_gesture": top_gesture,
        "posture_counts": posture_counts,
        "action_counts": action_counts,
        "gesture_counts": gesture_counts,
    }
