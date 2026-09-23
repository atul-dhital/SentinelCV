from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from models import models
from schemas import schemas


@dataclass
class _VisitorAggregate:
    visitor_id: object
    visitor_name: Optional[str]
    camera_ids: set[str]
    sightings: int
    confidence_sum: float
    first_seen: datetime
    last_seen: datetime
    seen_on_query_camera: bool
    last_camera_id: Optional[str]
    last_timestamp: Optional[datetime]
    transitions: Dict[Tuple[str, str], Dict[str, object]]
    pose_quality_sum: float
    pose_samples: int
    angle_distribution: Dict[str, int]
    posture_distribution: Dict[str, int]


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def _normalize_timestamp(raw: Optional[datetime]) -> Optional[datetime]:
    if raw is None:
        return None
    if raw.tzinfo is None:
        return raw.replace(tzinfo=timezone.utc)
    return raw


def _normalize_face_angle(raw_angle: Optional[str]) -> Optional[str]:
    if raw_angle is None:
        return None
    normalized = str(raw_angle).strip().lower()
    aliases = {
        "front": "frontal",
        "frontal": "frontal",
        "45_left": "45_left",
        "left_45": "45_left",
        "left45": "45_left",
        "45_right": "45_right",
        "right_45": "45_right",
        "right45": "45_right",
        "left_profile": "profile",
        "right_profile": "profile",
        "profile": "profile",
    }
    return aliases.get(normalized, normalized if normalized in {"frontal", "45_left", "45_right", "profile"} else None)


def _pose_quality_from_event(event: models.VisionAnalyticsEvent) -> float:
    payload = event.payload if isinstance(event.payload, dict) else {}
    confidence = float(event.confidence or 0.0)
    average_visibility = float(payload.get("average_visibility", 0.0) or 0.0)
    keypoint_count = int(payload.get("keypoint_count", 0) or 0)
    keypoint_score = min(max(keypoint_count, 0) / 17.0, 1.0)
    return round(
        _clamp01((0.6 * confidence) + (0.25 * average_visibility) + (0.15 * keypoint_score)),
        4,
    )


def _build_pose_event_index(
    db: Session,
    organization_id: object,
    cutoff: datetime,
) -> Dict[str, Tuple[List[datetime], List[Tuple[float, Optional[str]]]]]:
    rows = (
        db.query(models.VisionAnalyticsEvent)
        .filter(models.VisionAnalyticsEvent.organization_id == organization_id)
        .filter(models.VisionAnalyticsEvent.event_type == "pose_estimate")
        .filter(models.VisionAnalyticsEvent.created_at >= cutoff)
        .filter(models.VisionAnalyticsEvent.camera_id.isnot(None))
        .order_by(models.VisionAnalyticsEvent.camera_id.asc(), models.VisionAnalyticsEvent.created_at.asc())
        .all()
    )

    grouped: Dict[str, Tuple[List[datetime], List[Tuple[float, Optional[str]]]]] = {}
    for row in rows:
        camera_key = str(row.camera_id)
        timestamp = _normalize_timestamp(row.created_at)
        if timestamp is None:
            continue

        quality = _pose_quality_from_event(row)
        posture = str(row.posture).strip().lower() if row.posture else None
        timestamps, values = grouped.setdefault(camera_key, ([], []))
        timestamps.append(timestamp)
        values.append((quality, posture))

    return grouped


def _lookup_pose_signal(
    pose_series: Optional[Tuple[List[datetime], List[Tuple[float, Optional[str]]]]],
    timestamp: Optional[datetime],
    *,
    max_gap_seconds: int = 45,
) -> Tuple[Optional[float], Optional[str]]:
    if pose_series is None:
        return None, None

    timestamps, values = pose_series
    if not timestamps:
        return None, None

    target = _normalize_timestamp(timestamp)
    if target is None:
        return None, None

    index = bisect_right(timestamps, target)
    candidates: List[int] = []
    if index < len(timestamps):
        candidates.append(index)
    if index > 0:
        candidates.append(index - 1)
    if not candidates:
        return None, None

    best_index = min(
        candidates,
        key=lambda candidate_index: abs((timestamps[candidate_index] - target).total_seconds()),
    )
    delta_seconds = abs((timestamps[best_index] - target).total_seconds())
    if delta_seconds > float(max_gap_seconds):
        return None, None

    return values[best_index]


def _avg(values: List[float]) -> Optional[float]:
    if not values:
        return None
    return round(sum(values) / max(len(values), 1), 2)


def _calculate_reid_score(
    unique_cameras: int,
    sightings: int,
    avg_confidence: float,
    transitions: int,
    pose_signal: float,
) -> float:
    camera_factor = min(unique_cameras / 4.0, 1.0)
    sightings_factor = min(sightings / 20.0, 1.0)
    confidence_factor = max(0.0, min(avg_confidence, 1.0))
    transition_factor = min(transitions / 8.0, 1.0)
    pose_factor = _clamp01(pose_signal)
    return round(
        (0.3 * camera_factor)
        + (0.22 * sightings_factor)
        + (0.22 * confidence_factor)
        + (0.14 * transition_factor)
        + (0.12 * pose_factor),
        4,
    )


def search_cross_camera_matches(
    db: Session,
    organization_id: object,
    request: schemas.CrossCameraReidRequest,
) -> schemas.CrossCameraReidResponse:
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(minutes=request.lookback_minutes)

    query = db.query(models.VisitorLog).filter(
        models.VisitorLog.organization_id == organization_id,
        models.VisitorLog.timestamp >= cutoff,
        models.VisitorLog.identified == True,
        models.VisitorLog.visitor_id.isnot(None),
    )

    if request.visitor_id:
        query = query.filter(models.VisitorLog.visitor_id == request.visitor_id)

    logs = query.order_by(models.VisitorLog.timestamp.asc()).all()

    face_data_ids = [log.face_data_id for log in logs if log.face_data_id is not None]
    face_angle_map: Dict[str, str] = {}
    if face_data_ids:
        for face_data_id, face_angle in db.query(
            models.FaceData.id,
            models.FaceData.face_angle,
        ).filter(models.FaceData.id.in_(face_data_ids)).all():
            normalized = _normalize_face_angle(face_angle)
            if normalized:
                face_angle_map[str(face_data_id)] = normalized

    pose_index = _build_pose_event_index(db, organization_id, cutoff)

    grouped: Dict[str, _VisitorAggregate] = {}
    target_camera = str(request.camera_id) if request.camera_id else None
    max_transition_gap_seconds = max(300, min(request.lookback_minutes * 60, 7200))

    for log in logs:
        visitor_key = str(log.visitor_id)
        if visitor_key not in grouped:
            grouped[visitor_key] = _VisitorAggregate(
                visitor_id=log.visitor_id,
                visitor_name=getattr(log, "visitor_name", None) or (log.visitor.name if log.visitor else None),
                camera_ids=set(),
                sightings=0,
                confidence_sum=0.0,
                first_seen=log.timestamp,
                last_seen=log.timestamp,
                seen_on_query_camera=False,
                last_camera_id=None,
                last_timestamp=None,
                transitions={},
                pose_quality_sum=0.0,
                pose_samples=0,
                angle_distribution={},
                posture_distribution={},
            )

        item = grouped[visitor_key]
        camera_id = str(log.camera_id) if log.camera_id else None

        if camera_id:
            item.camera_ids.add(camera_id)
            if target_camera and camera_id == target_camera:
                item.seen_on_query_camera = True

        item.sightings += 1
        item.confidence_sum += float(log.confidence or 0.0)

        if log.timestamp < item.first_seen:
            item.first_seen = log.timestamp
        if log.timestamp > item.last_seen:
            item.last_seen = log.timestamp

        if log.face_data_id is not None:
            angle = face_angle_map.get(str(log.face_data_id))
            if angle:
                item.angle_distribution[angle] = item.angle_distribution.get(angle, 0) + 1

        pose_quality, posture = _lookup_pose_signal(
            pose_index.get(camera_id) if camera_id else None,
            log.timestamp,
        )
        if pose_quality is not None:
            item.pose_quality_sum += float(pose_quality)
            item.pose_samples += 1
        if posture:
            item.posture_distribution[posture] = item.posture_distribution.get(posture, 0) + 1

        if item.last_camera_id and camera_id and item.last_camera_id != camera_id and item.last_timestamp:
            gap_seconds = (log.timestamp - item.last_timestamp).total_seconds()
            if 0 <= gap_seconds <= max_transition_gap_seconds:
                transition_key = (item.last_camera_id, camera_id)
                transition_entry = item.transitions.setdefault(
                    transition_key,
                    {
                        "count": 0,
                        "durations": [],
                    },
                )
                transition_entry["count"] = int(transition_entry["count"]) + 1
                durations = transition_entry["durations"]
                if isinstance(durations, list):
                    durations.append(float(gap_seconds))

        if camera_id:
            item.last_camera_id = camera_id
            item.last_timestamp = log.timestamp

    matches: List[schemas.CrossCameraReidMatch] = []
    for aggregate in grouped.values():
        camera_ids = sorted(aggregate.camera_ids)

        if len(camera_ids) < request.min_camera_count:
            continue
        if target_camera and not aggregate.seen_on_query_camera:
            continue

        transition_pairs = sorted(
            aggregate.transitions.items(),
            key=lambda pair: int(pair[1].get("count", 0)),
            reverse=True,
        )
        top_transitions: List[schemas.CrossCameraTransition] = []
        transition_count = sum(int(transition.get("count", 0)) for _, transition in transition_pairs)

        for (from_camera, to_camera), transition in transition_pairs[:5]:
            count = int(transition.get("count", 0))
            durations = transition.get("durations")
            avg_seconds = _avg(durations if isinstance(durations, list) else [])
            top_transitions.append(
                schemas.CrossCameraTransition(
                    from_camera_id=from_camera,
                    to_camera_id=to_camera,
                    count=count,
                    avg_transition_seconds=avg_seconds,
                )
            )

        average_confidence = round(aggregate.confidence_sum / max(aggregate.sightings, 1), 4)
        average_pose_quality = (
            round(aggregate.pose_quality_sum / aggregate.pose_samples, 4)
            if aggregate.pose_samples > 0
            else 0.0
        )
        angle_diversity = min(len(aggregate.angle_distribution) / 4.0, 1.0)
        pose_signal = (0.7 * average_pose_quality) + (0.3 * angle_diversity)
        reid_score = _calculate_reid_score(
            unique_cameras=len(camera_ids),
            sightings=aggregate.sightings,
            avg_confidence=average_confidence,
            transitions=transition_count,
            pose_signal=pose_signal,
        )

        if aggregate.sightings < request.min_sightings:
            continue
        if average_confidence < request.min_avg_confidence:
            continue
        if reid_score < request.min_reid_score:
            continue

        matches.append(
            schemas.CrossCameraReidMatch(
                visitor_id=aggregate.visitor_id,
                visitor_name=aggregate.visitor_name,
                camera_ids=camera_ids,
                sightings=aggregate.sightings,
                average_confidence=average_confidence,
                first_seen=aggregate.first_seen,
                last_seen=aggregate.last_seen,
                transition_count=transition_count,
                reid_score=reid_score,
                pose_quality_score=round(average_pose_quality, 4),
                pose_samples=int(aggregate.pose_samples),
                angle_distribution={
                    key: int(value)
                    for key, value in sorted(aggregate.angle_distribution.items())
                },
                posture_distribution={
                    key: int(value)
                    for key, value in sorted(aggregate.posture_distribution.items())
                },
                top_transitions=top_transitions,
            )
        )

    matches.sort(
        key=lambda m: (m.reid_score, m.sightings, m.average_confidence),
        reverse=True,
    )

    return schemas.CrossCameraReidResponse(
        query_camera_id=request.camera_id,
        lookback_minutes=request.lookback_minutes,
        evaluated_logs=len(logs),
        candidate_visitors=len(grouped),
        generated_at=now,
        matches=matches[: request.limit],
    )


def _serialize_movement_summary(
    summary: models.CrossCameraMovementSummary,
    *,
    visitor_names: Dict[str, Optional[str]],
    camera_names: Dict[str, Optional[str]],
) -> schemas.CrossCameraMovementSummaryItem:
    return schemas.CrossCameraMovementSummaryItem(
        id=summary.id,
        visitor_id=summary.visitor_id,
        visitor_name=visitor_names.get(str(summary.visitor_id)),
        from_camera_id=summary.from_camera_id,
        from_camera_name=camera_names.get(str(summary.from_camera_id)),
        to_camera_id=summary.to_camera_id,
        to_camera_name=camera_names.get(str(summary.to_camera_id)),
        first_seen=summary.first_seen,
        last_seen=summary.last_seen,
        transition_count=int(summary.transition_count or 0),
        sightings=int(summary.sightings or 0),
        average_confidence=float(summary.average_confidence or 0.0),
        avg_transition_seconds=float(summary.avg_transition_seconds) if summary.avg_transition_seconds is not None else None,
        reid_score=float(summary.reid_score or 0.0),
        source=summary.source or "reid_sync",
        details=dict(summary.details or {}),
        updated_at=summary.updated_at,
    )


def sync_cross_camera_movements(
    db: Session,
    organization_id: object,
    request: schemas.CrossCameraMovementSyncRequest,
) -> schemas.CrossCameraMovementSyncResponse:
    search_result = search_cross_camera_matches(
        db=db,
        organization_id=organization_id,
        request=request,
    )

    tracked_summaries: List[models.CrossCameraMovementSummary] = []
    visitor_names = {str(match.visitor_id): match.visitor_name for match in search_result.matches}
    camera_ids: set[str] = set()

    for match in search_result.matches:
        for transition in match.top_transitions:
            camera_ids.add(str(transition.from_camera_id))
            camera_ids.add(str(transition.to_camera_id))
            existing = db.query(models.CrossCameraMovementSummary).filter(
                models.CrossCameraMovementSummary.organization_id == organization_id,
                models.CrossCameraMovementSummary.visitor_id == match.visitor_id,
                models.CrossCameraMovementSummary.from_camera_id == transition.from_camera_id,
                models.CrossCameraMovementSummary.to_camera_id == transition.to_camera_id,
            ).first()

            details = {
                "camera_ids": [str(camera_id) for camera_id in match.camera_ids],
                "top_transitions": [transition_item.model_dump() for transition_item in match.top_transitions],
                "pose_quality_score": float(match.pose_quality_score or 0.0),
                "pose_samples": int(match.pose_samples or 0),
                "angle_distribution": dict(match.angle_distribution or {}),
                "posture_distribution": dict(match.posture_distribution or {}),
            }

            if existing is None:
                existing = models.CrossCameraMovementSummary(
                    organization_id=organization_id,
                    visitor_id=match.visitor_id,
                    from_camera_id=transition.from_camera_id,
                    to_camera_id=transition.to_camera_id,
                    first_seen=match.first_seen,
                    last_seen=match.last_seen,
                    transition_count=transition.count,
                    sightings=match.sightings,
                    average_confidence=match.average_confidence,
                    avg_transition_seconds=transition.avg_transition_seconds,
                    reid_score=match.reid_score,
                    source="reid_sync",
                    details=details,
                )
                db.add(existing)
            else:
                existing.first_seen = min(existing.first_seen, match.first_seen)
                existing.last_seen = max(existing.last_seen, match.last_seen)
                if request.overwrite_existing:
                    existing.transition_count = transition.count
                    existing.sightings = match.sightings
                else:
                    existing.transition_count = max(int(existing.transition_count or 0), transition.count)
                    existing.sightings = max(int(existing.sightings or 0), match.sightings)
                existing.average_confidence = max(float(existing.average_confidence or 0.0), match.average_confidence)
                existing.avg_transition_seconds = transition.avg_transition_seconds
                existing.reid_score = max(float(existing.reid_score or 0.0), match.reid_score)
                existing.source = "reid_sync"
                existing.details = details

            tracked_summaries.append(existing)

    db.commit()

    camera_name_map = {
        str(camera.id): camera.name
        for camera in db.query(models.Camera).filter(
            models.Camera.organization_id == organization_id,
            models.Camera.id.in_(list(camera_ids)) if camera_ids else False,
        ).all()
    } if camera_ids else {}

    unique_summaries = {str(summary.id): summary for summary in tracked_summaries}.values()
    items = [
        _serialize_movement_summary(summary, visitor_names=visitor_names, camera_names=camera_name_map)
        for summary in unique_summaries
    ]
    items.sort(key=lambda item: (item.reid_score, item.transition_count, item.sightings), reverse=True)

    return schemas.CrossCameraMovementSyncResponse(
        lookback_minutes=request.lookback_minutes,
        synced_matches=len(search_result.matches),
        upserted_movements=len(items),
        generated_at=search_result.generated_at,
        items=items,
    )


def list_cross_camera_movements(
    db: Session,
    organization_id: object,
    *,
    visitor_id: Optional[object] = None,
    camera_id: Optional[object] = None,
    limit: int = 25,
) -> schemas.CrossCameraMovementListResponse:
    query = db.query(models.CrossCameraMovementSummary).filter(
        models.CrossCameraMovementSummary.organization_id == organization_id
    )

    if visitor_id:
        query = query.filter(models.CrossCameraMovementSummary.visitor_id == visitor_id)
    if camera_id:
        query = query.filter(
            (models.CrossCameraMovementSummary.from_camera_id == camera_id)
            | (models.CrossCameraMovementSummary.to_camera_id == camera_id)
        )

    total = query.count()
    rows = query.order_by(models.CrossCameraMovementSummary.updated_at.desc()).limit(limit).all()

    camera_ids = {str(row.from_camera_id) for row in rows} | {str(row.to_camera_id) for row in rows}
    visitor_ids = {str(row.visitor_id) for row in rows}
    camera_name_map = {
        str(camera.id): camera.name
        for camera in db.query(models.Camera).filter(
            models.Camera.organization_id == organization_id,
            models.Camera.id.in_(list(camera_ids)) if camera_ids else False,
        ).all()
    } if camera_ids else {}
    visitor_name_map = {
        str(visitor.id): visitor.name
        for visitor in db.query(models.Visitor).filter(
            models.Visitor.organization_id == organization_id,
            models.Visitor.id.in_(list(visitor_ids)) if visitor_ids else False,
        ).all()
    } if visitor_ids else {}

    return schemas.CrossCameraMovementListResponse(
        total=total,
        items=[
            _serialize_movement_summary(row, visitor_names=visitor_name_map, camera_names=camera_name_map)
            for row in rows
        ],
    )
