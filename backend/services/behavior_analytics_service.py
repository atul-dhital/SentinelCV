from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Optional, Tuple

from sqlalchemy.orm import Session

from models import models
from schemas import schemas
from services import visitor_service


_PRIORITY_ORDER = {
    "low": 1,
    "medium": 2,
    "high": 3,
    "critical": 4,
}


def _priority_value(priority: str) -> int:
    return _PRIORITY_ORDER.get((priority or "low").lower(), 1)


def _detect_anomaly(
    pose_estimate: schemas.PoseEstimateResponse,
    action_inference: schemas.ActionInferResponse,
) -> tuple[float, str, str, List[str]]:
    score = 0.0
    reasons: List[str] = []
    label = "normal_behavior"

    posture = (pose_estimate.posture or "unknown").lower()
    action = (action_inference.action or "unknown").lower()
    gesture = (action_inference.gesture or "none").lower()
    confidence = float(action_inference.confidence or 0.0)
    keypoint_count = int(pose_estimate.keypoint_count or 0)

    if posture == "unknown":
        score += 0.2
        reasons.append("posture_unknown")

    if keypoint_count < 8 and pose_estimate.available:
        score += 0.15
        reasons.append("low_pose_keypoints")

    if confidence < 0.35:
        score += 0.25
        reasons.append("low_action_confidence")

    if action in {"fall", "falling", "fight", "fighting", "violent_motion", "running"}:
        score += 0.4
        reasons.append(f"action:{action}")
        if action in {"fall", "falling"}:
            label = "fall_detected"
        elif action in {"fight", "fighting", "violent_motion"}:
            label = "aggressive_behavior"
        elif action == "running":
            label = "rapid_movement"

    if gesture in {"panic", "distress", "help"}:
        score += 0.35
        reasons.append(f"gesture:{gesture}")
        if label == "normal_behavior":
            label = "distress_gesture"

    if posture in {"collapsed", "fallen", "lying_down"}:
        score += 0.4
        reasons.append(f"posture:{posture}")
        if label in {"normal_behavior", "rapid_movement"}:
            label = "person_down"

    if posture in {"sitting_or_crouching", "transitioning"} and action in {"unknown", "hand_raised"}:
        score += 0.1
        reasons.append("posture_action_mismatch")

    score = max(0.0, min(score, 1.0))

    if score >= 0.8:
        return score, label if label != "normal_behavior" else "critical_behavior", "critical", reasons
    if score >= 0.6:
        return score, label if label != "normal_behavior" else "high_risk_behavior", "high", reasons
    if score >= 0.4:
        return score, label if label != "normal_behavior" else "suspicious_behavior", "medium", reasons
    if score >= 0.25:
        return score, label if label != "normal_behavior" else "watchlist_behavior", "low", reasons
    return score, "normal_behavior", "info", reasons


def _behavior_item(row: models.BehaviorEvent) -> schemas.BehaviorEventItem:
    return schemas.BehaviorEventItem(
        id=row.id,
        event_type=row.event_type,
        source=row.source,
        visitor_id=row.visitor_id,
        visitor_name=row.visitor.name if row.visitor else None,
        visitor_log_id=row.visitor_log_id,
        camera_id=row.camera_id,
        camera_name=row.camera.name if row.camera else None,
        posture=row.posture,
        action=row.action,
        gesture=row.gesture,
        confidence=float(row.confidence or 0.0),
        anomaly_score=float(row.anomaly_score or 0.0),
        anomaly_label=row.anomaly_label or "normal_behavior",
        severity=row.severity or "info",
        reviewed=bool(row.reviewed),
        details=row.details or {},
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _signal_item(row: models.ContinuousLearningSignal) -> schemas.ContinuousLearningSignalItem:
    return schemas.ContinuousLearningSignalItem(
        id=row.id,
        signal_type=row.signal_type,
        priority=row.priority,
        status=row.status,
        confidence=row.confidence,
        source=row.source,
        visitor_id=row.visitor_id,
        visitor_name=row.visitor.name if row.visitor else None,
        visitor_log_id=row.visitor_log_id,
        behavior_event_id=row.behavior_event_id,
        details=row.details or {},
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def persist_behavior_analysis(
    *,
    db: Session,
    organization_id: object,
    camera: Optional[models.Camera],
    visitor: Optional[models.Visitor],
    visitor_log: Optional[models.VisitorLog],
    pose_estimate: schemas.PoseEstimateResponse,
    action_inference: schemas.ActionInferResponse,
    source: str,
    initiated_by_user_id: object,
) -> Tuple[schemas.BehaviorEventItem, Optional[schemas.ContinuousLearningSignalItem], List[str]]:
    anomaly_score, anomaly_label, severity, anomaly_reasons = _detect_anomaly(
        pose_estimate,
        action_inference,
    )

    event_type = "anomaly" if anomaly_score >= 0.4 else "behavior"
    behavior_event = models.BehaviorEvent(
        organization_id=organization_id,
        visitor_id=visitor.id if visitor else None,
        visitor_log_id=visitor_log.id if visitor_log else None,
        camera_id=camera.id if camera else None,
        event_type=event_type,
        source=source,
        posture=pose_estimate.posture,
        action=action_inference.action,
        gesture=action_inference.gesture,
        confidence=float(action_inference.confidence or 0.0),
        anomaly_score=anomaly_score,
        anomaly_label=anomaly_label,
        severity=severity,
        details={
            "pose": pose_estimate.model_dump(),
            "action": action_inference.model_dump(),
            "anomaly_reasons": anomaly_reasons,
        },
    )
    db.add(behavior_event)
    db.flush()

    learning_signal = None
    should_create_signal = anomaly_score >= 0.4 or float(action_inference.confidence or 0.0) < 0.45
    if should_create_signal:
        signal_type = "anomaly" if anomaly_score >= 0.4 else "low_confidence"
        priority = "critical" if severity == "critical" else "high" if severity == "high" else "medium"
        learning_signal = models.ContinuousLearningSignal(
            organization_id=organization_id,
            visitor_id=visitor.id if visitor else None,
            visitor_log_id=visitor_log.id if visitor_log else None,
            behavior_event_id=behavior_event.id,
            signal_type=signal_type,
            priority=priority,
            status="open",
            confidence=float(action_inference.confidence or 0.0),
            source="behavior_pipeline",
            details={
                "anomaly_label": anomaly_label,
                "anomaly_score": anomaly_score,
                "initiated_by": str(initiated_by_user_id),
            },
        )
        db.add(learning_signal)

    db.commit()
    db.refresh(behavior_event)
    if learning_signal is not None:
        db.refresh(learning_signal)

    return (
        _behavior_item(behavior_event),
        _signal_item(learning_signal) if learning_signal else None,
        anomaly_reasons,
    )


def list_behavior_events(
    *,
    db: Session,
    organization_id: object,
    limit: int = 25,
    event_type: Optional[str] = None,
    severity: Optional[str] = None,
    reviewed: Optional[bool] = None,
    min_anomaly_score: float = 0.0,
) -> schemas.BehaviorEventListResponse:
    bounded_limit = max(1, min(limit, 200))
    query = db.query(models.BehaviorEvent).filter(
        models.BehaviorEvent.organization_id == organization_id,
        models.BehaviorEvent.anomaly_score >= float(min_anomaly_score or 0.0),
    )

    if event_type:
        query = query.filter(models.BehaviorEvent.event_type == event_type)
    if severity:
        query = query.filter(models.BehaviorEvent.severity == severity)
    if reviewed is not None:
        query = query.filter(models.BehaviorEvent.reviewed == bool(reviewed))

    total = query.count()
    rows = query.order_by(models.BehaviorEvent.created_at.desc()).limit(bounded_limit).all()

    anomaly_count = sum(1 for row in rows if row.event_type == "anomaly")
    critical_count = sum(1 for row in rows if (row.severity or "").lower() == "critical")

    return schemas.BehaviorEventListResponse(
        total=total,
        anomaly_count=anomaly_count,
        critical_count=critical_count,
        items=[_behavior_item(row) for row in rows],
    )


def list_learning_signals(
    *,
    db: Session,
    organization_id: object,
    limit: int = 25,
    status: Optional[str] = None,
    min_priority: str = "low",
) -> schemas.ContinuousLearningSignalListResponse:
    bounded_limit = max(1, min(limit, 200))
    min_priority_rank = _priority_value(min_priority)

    query = db.query(models.ContinuousLearningSignal).filter(
        models.ContinuousLearningSignal.organization_id == organization_id,
    )

    if status:
        query = query.filter(models.ContinuousLearningSignal.status == status)

    rows = query.order_by(models.ContinuousLearningSignal.created_at.desc()).all()
    filtered = [row for row in rows if _priority_value(row.priority) >= min_priority_rank]
    sliced = filtered[:bounded_limit]

    open_count = sum(1 for row in filtered if row.status == "open")
    queued_count = sum(1 for row in filtered if row.status == "queued")

    return schemas.ContinuousLearningSignalListResponse(
        total=len(filtered),
        open_count=open_count,
        queued_count=queued_count,
        items=[_signal_item(row) for row in sliced],
    )


def queue_learning_signals(
    *,
    db: Session,
    organization_id: object,
    user_id: object,
    request: schemas.ContinuousLearningQueueRequest,
) -> schemas.ContinuousLearningQueueResponse:
    query = db.query(models.ContinuousLearningSignal).filter(
        models.ContinuousLearningSignal.organization_id == organization_id,
        models.ContinuousLearningSignal.status == "open",
    )

    if request.signal_ids:
        signal_ids = [str(item) for item in request.signal_ids]
        query = query.filter(models.ContinuousLearningSignal.id.in_(signal_ids))

    rows = query.order_by(models.ContinuousLearningSignal.created_at.asc()).all()
    min_priority_rank = _priority_value(request.min_priority)
    eligible = [row for row in rows if _priority_value(row.priority) >= min_priority_rank]

    if request.strategy not in {"anomaly_first", "balanced", "recent_first"}:
        raise ValueError("Unsupported queue strategy")

    selected = eligible[: request.max_samples]
    if not selected:
        raise ValueError("No eligible open signals matched the queue criteria")

    for row in selected:
        row.status = "queued"

    selected_ids = [row.id for row in selected]
    job = models.ActiveLearningJob(
        organization_id=organization_id,
        strategy=request.strategy,
        status="pending",
        n_samples=len(selected_ids),
        selected_samples=[str(item) for item in selected_ids],
        created_by=user_id,
    )
    db.add(job)
    for row in selected:
        row.details = {
            **(row.details or {}),
            "queued_at": datetime.now(timezone.utc).isoformat(),
            "queued_strategy": request.strategy,
            "active_learning_job_id": str(job.id),
        }
    db.commit()
    db.refresh(job)

    return schemas.ContinuousLearningQueueResponse(
        job_id=job.id,
        queued_signal_count=len(selected_ids),
        selected_signal_ids=selected_ids,
        strategy=request.strategy,
        training_recommended=len(selected_ids) >= 5 or any(_priority_value(row.priority) >= _priority_value("high") for row in selected),
    )


def mark_behavior_event_reviewed(
    *,
    db: Session,
    organization_id: object,
    event_id: object,
    reviewed: bool,
    notes: Optional[str],
    user_id: object,
) -> schemas.BehaviorEventItem:
    event = db.query(models.BehaviorEvent).filter(
        models.BehaviorEvent.organization_id == organization_id,
        models.BehaviorEvent.id == event_id,
    ).first()
    if event is None:
        raise ValueError("Behavior event not found")

    event.reviewed = bool(reviewed)
    details = dict(event.details or {})
    details.update({
        "reviewed_by": str(user_id),
        "reviewed_at": datetime.now(timezone.utc).isoformat(),
    })
    if notes:
        details["review_notes"] = notes
    event.details = details
    db.commit()
    db.refresh(event)
    return _behavior_item(event)


def update_learning_signal_status(
    *,
    db: Session,
    organization_id: object,
    signal_id: object,
    status: str,
    resolution: Optional[str],
    notes: Optional[str],
    user_id: object,
) -> schemas.ContinuousLearningSignalItem:
    valid_statuses = {"open", "queued", "reviewed", "resolved"}
    normalized_status = (status or "").strip().lower()
    if normalized_status not in valid_statuses:
        raise ValueError(f"Unsupported signal status '{status}'")

    signal = db.query(models.ContinuousLearningSignal).filter(
        models.ContinuousLearningSignal.organization_id == organization_id,
        models.ContinuousLearningSignal.id == signal_id,
    ).first()
    if signal is None:
        raise ValueError("Learning signal not found")

    signal.status = normalized_status
    details = dict(signal.details or {})
    details.update({
        "reviewed_by": str(user_id),
        "reviewed_at": datetime.now(timezone.utc).isoformat(),
    })
    if resolution:
        details["resolution"] = resolution
    if notes:
        details["review_notes"] = notes
    signal.details = details
    db.commit()
    db.refresh(signal)
    return _signal_item(signal)


def promote_learning_signal_to_sample(
    *,
    db: Session,
    organization_id: object,
    signal_id: object,
    request: schemas.ContinuousLearningSignalPromoteRequest,
    user_id: object,
) -> tuple[schemas.ContinuousLearningSignalItem, models.LearningSample]:
    signal = db.query(models.ContinuousLearningSignal).filter(
        models.ContinuousLearningSignal.organization_id == organization_id,
        models.ContinuousLearningSignal.id == signal_id,
    ).first()
    if signal is None:
        raise ValueError("Learning signal not found")

    visitor_log = None
    if signal.visitor_log_id:
        visitor_log = db.query(models.VisitorLog).filter(
            models.VisitorLog.organization_id == organization_id,
            models.VisitorLog.id == signal.visitor_log_id,
        ).first()

    visitor_id = request.visitor_id or signal.visitor_id or (visitor_log.visitor_id if visitor_log else None)
    if visitor_id is None:
        raise ValueError("Visitor not found for learning signal")

    face_data = None
    if visitor_log and visitor_log.face_data_id:
        face_data = db.query(models.FaceData).filter(
            models.FaceData.id == visitor_log.face_data_id,
            models.FaceData.visitor_id == visitor_id,
        ).first()
    if face_data is None:
        face_data = db.query(models.FaceData).filter(
            models.FaceData.visitor_id == visitor_id,
        ).order_by(models.FaceData.created_at.desc()).first()

    embedding = visitor_service._parse_embedding_payload(face_data.embedding if face_data else None)
    if embedding is None:
        raise ValueError("No embedding available for the selected learning signal")

    face_image_path = request.face_image_path
    if not face_image_path and visitor_log:
        face_image_path = visitor_log.face_image_path
    if not face_image_path and face_data:
        face_image_path = face_data.image_url
    if not face_image_path:
        raise ValueError("No face image path available for the learning sample")

    stored_embedding = visitor_service.serialize_embedding_for_storage(embedding)
    confidence = request.confidence
    if confidence is None:
        confidence = float(signal.confidence or 1.0)

    sample = models.LearningSample(
        visitor_id=visitor_id,
        face_image_path=face_image_path,
        embedding=stored_embedding,
        is_positive=bool(request.is_positive),
        source=request.source,
        confidence=float(confidence),
    )
    db.add(sample)

    db.flush()
    signal.status = "resolved"
    signal.details = {
        **(signal.details or {}),
        "resolved_at": datetime.now(timezone.utc).isoformat(),
        "resolved_by": str(user_id),
        "promoted_sample_id": str(sample.id),
    }
    db.commit()
    db.refresh(sample)
    db.refresh(signal)

    return _signal_item(signal), sample
