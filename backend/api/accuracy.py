from datetime import datetime, timedelta, timezone
"""S16: Accuracy Improvement Features — adaptive thresholds, liveness, anti-spoofing, continuous learning."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import func
from db.base import get_db
from models import models
from schemas import schemas
from services import user_service, visitor_service
from core.security import get_current_user
from uuid import UUID
import datetime

router = APIRouter(prefix="/accuracy", tags=["Accuracy"])


def _get_user(db: Session, user_id: str) -> models.User:
    user = user_service.get_user_by_id(db, user_id)
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    return user


@router.get("/stats", response_model=schemas.AccuracyStatsResponse)
async def get_accuracy_stats(
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get overall recognition accuracy statistics."""
    user = _get_user(db, current_user_id)
    org_id = user.organization_id

    total = db.query(func.count(models.VisitorLog.id)).filter(
        models.VisitorLog.organization_id == org_id
    ).scalar() or 0

    identified = db.query(func.count(models.VisitorLog.id)).filter(
        models.VisitorLog.organization_id == org_id,
        models.VisitorLog.status.in_(["identified", "reviewed"]),
    ).scalar() or 0

    reviewed = db.query(func.count(models.VisitorLog.id)).filter(
        models.VisitorLog.organization_id == org_id,
        models.VisitorLog.status == "reviewed",
    ).scalar() or 0

    avg_conf = db.query(func.avg(models.VisitorLog.confidence)).filter(
        models.VisitorLog.organization_id == org_id,
        models.VisitorLog.identified == True,
    ).scalar() or 0.0

    custom_thresh = db.query(func.count(models.Visitor.id)).filter(
        models.Visitor.organization_id == org_id,
        models.Visitor.custom_threshold.isnot(None),
    ).scalar() or 0

    auto_learn = db.query(func.count(models.Visitor.id)).filter(
        models.Visitor.organization_id == org_id,
        models.Visitor.auto_learn == True,
    ).scalar() or 0

    accuracy = identified / total if total > 0 else 0.0

    return schemas.AccuracyStatsResponse(
        overall_accuracy=round(accuracy, 4),
        total_identifications=total,
        correct_identifications=identified,
        false_positives=0,  # Would need manual review data
        avg_confidence=round(float(avg_conf), 4),
        visitors_with_custom_threshold=custom_thresh,
        auto_learn_enabled_count=auto_learn,
    )


@router.put("/visitor/{visitor_id}/threshold", response_model=dict)
async def set_visitor_threshold(
    visitor_id: UUID,
    data: schemas.AdaptiveThresholdUpdate,
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """US-ACC-002: Set adaptive recognition threshold for a specific visitor."""
    user = _get_user(db, current_user_id)
    visitor = db.query(models.Visitor).filter(
        models.Visitor.id == visitor_id,
        models.Visitor.organization_id == user.organization_id,
    ).first()
    if not visitor:
        raise HTTPException(status_code=404, detail="Visitor not found")

    if data.custom_threshold is not None:
        if not 0.3 <= data.custom_threshold <= 0.99:
            raise HTTPException(status_code=400, detail="Threshold must be between 0.3 and 0.99")
        visitor.custom_threshold = data.custom_threshold

    if data.auto_learn is not None:
        visitor.auto_learn = data.auto_learn

    db.commit()
    db.refresh(visitor)

    visitor_service.create_audit_log(
        db, user.organization_id, user.id, "update_threshold",
        "visitor", str(visitor_id),
        details={"custom_threshold": visitor.custom_threshold, "auto_learn": visitor.auto_learn},
    )

    return {
        "visitor_id": str(visitor_id),
        "custom_threshold": visitor.custom_threshold,
        "auto_learn": visitor.auto_learn,
        "message": "Visitor recognition settings updated",
    }


@router.get("/liveness-config", response_model=schemas.LivenessConfig)
async def get_liveness_config(
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """US-ACC-004: Get liveness detection configuration."""
    user = _get_user(db, current_user_id)
    org = db.query(models.Organization).filter(
        models.Organization.id == user.organization_id
    ).first()
    settings = org.settings or {} if org else {}
    liveness = settings.get("liveness", {})
    return schemas.LivenessConfig(
        enabled=liveness.get("enabled", True),
        min_face_size=liveness.get("min_face_size", 80),
        blink_detection=liveness.get("blink_detection", False),
        texture_analysis=liveness.get("texture_analysis", True),
    )


@router.put("/liveness-config", response_model=schemas.LivenessConfig)
async def update_liveness_config(
    config: schemas.LivenessConfig,
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """US-ACC-004: Update liveness detection configuration. Admin only."""
    user = _get_user(db, current_user_id)
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Only admins can update liveness config")

    org = db.query(models.Organization).filter(
        models.Organization.id == user.organization_id
    ).first()
    if not org:
        raise HTTPException(status_code=404, detail="Organization not found")

    settings = org.settings or {}
    settings["liveness"] = config.model_dump()
    org.settings = settings
    db.commit()

    visitor_service.create_audit_log(
        db, user.organization_id, user.id, "update_liveness_config",
        "organization", str(org.id),
    )
    return config


@router.get("/anti-spoofing-config")
async def get_anti_spoofing_config(
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """US-ACC-005: Get anti-spoofing configuration."""
    user = _get_user(db, current_user_id)
    org = db.query(models.Organization).filter(
        models.Organization.id == user.organization_id
    ).first()
    settings = org.settings or {} if org else {}
    spoofing = settings.get("anti_spoofing", {})
    return {
        "enabled": spoofing.get("enabled", True),
        "photo_detection": spoofing.get("photo_detection", True),
        "video_replay_detection": spoofing.get("video_replay_detection", True),
        "min_confidence": spoofing.get("min_confidence", 0.7),
    }


@router.put("/anti-spoofing-config")
async def update_anti_spoofing_config(
    config: dict,
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """US-ACC-005: Update anti-spoofing configuration. Admin only."""
    user = _get_user(db, current_user_id)
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Only admins can update anti-spoofing config")

    org = db.query(models.Organization).filter(
        models.Organization.id == user.organization_id
    ).first()
    if not org:
        raise HTTPException(status_code=404, detail="Organization not found")

    settings = org.settings or {}
    settings["anti_spoofing"] = {
        "enabled": config.get("enabled", True),
        "photo_detection": config.get("photo_detection", True),
        "video_replay_detection": config.get("video_replay_detection", True),
        "min_confidence": config.get("min_confidence", 0.7),
    }
    org.settings = settings
    db.commit()

    visitor_service.create_audit_log(
        db, user.organization_id, user.id, "update_anti_spoofing",
        "organization", str(org.id),
    )
    return settings["anti_spoofing"]


@router.post("/continuous-learning/{log_id}")
async def trigger_continuous_learning(
    log_id: UUID,
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """US-ACC-003: Manually trigger continuous learning from a confirmed log.
    If the visitor has auto_learn enabled, the face from the log is added as training data.
    """
    user = _get_user(db, current_user_id)
    log = db.query(models.VisitorLog).filter(
        models.VisitorLog.id == log_id,
        models.VisitorLog.organization_id == user.organization_id,
    ).first()
    if not log:
        raise HTTPException(status_code=404, detail="Log not found")
    if not log.visitor_id:
        raise HTTPException(status_code=400, detail="Log has no assigned visitor")

    visitor = db.query(models.Visitor).filter(
        models.Visitor.id == log.visitor_id
    ).first()
    if not visitor:
        raise HTTPException(status_code=404, detail="Visitor not found")

    if not visitor.auto_learn:
        return {
            "message": "Auto-learn is disabled for this visitor",
            "visitor_id": str(visitor.id),
            "auto_learn": False,
        }

    # Check if the log has a face image we can use
    if not log.face_image_path:
        return {"message": "No face image available for this log entry"}

    # Try to get the embedding from linked FaceData, or from the latest FaceData for the visitor
    embedding = None
    face_data = None
    if log.face_data_id:
        face_data = db.query(models.FaceData).filter(
            models.FaceData.id == log.face_data_id
        ).first()
    if not face_data:
        # Fallback: get most recent FaceData for this visitor
        face_data = db.query(models.FaceData).filter(
            models.FaceData.visitor_id == log.visitor_id
        ).order_by(models.FaceData.created_at.desc()).first()

    if face_data and face_data.embedding:
        import json as _json
        try:
            emb = face_data.embedding
            if isinstance(emb, str):
                emb = _json.loads(emb)
            embedding = emb
        except (ValueError, TypeError):
            embedding = None

    if embedding is None:
        return {
            "message": "No embedding data available for this log entry. Cannot create learning sample.",
            "visitor_id": str(visitor.id),
            "log_id": str(log_id),
        }

    # Create a LearningSample record
    sample = models.LearningSample(
        visitor_id=str(log.visitor_id),
        face_image_path=str(log.face_image_path),
        embedding=embedding,
        is_positive=True,
        source="continuous_learning",
        confidence=float(log.confidence) if log.confidence else 1.0,
    )
    db.add(sample)

    visitor_service.create_audit_log(
        db, user.organization_id, user.id, "continuous_learning",
        "visitor", str(visitor.id),
        details={"log_id": str(log_id), "face_image": log.face_image_path, "sample_created": True},
    )

    db.commit()

    return {
        "message": "Learning sample created from confirmed log",
        "visitor_id": str(visitor.id),
        "log_id": str(log_id),
        "sample_id": str(sample.id),
        "face_image": log.face_image_path,
    }
