from datetime import datetime, timedelta, timezone
"""S15: Recommendation System — face quality, accuracy alerts, threshold optimization."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import func
from db.base import get_db
from models import models
from schemas import schemas
from services import user_service, visitor_service
from core.security import get_current_user, decrypt_embedding
from typing import List
import datetime
import json
import math
import os
from core.paths import FACE_IMAGE_DIR

router = APIRouter(prefix="/recommendations", tags=["Recommendations"])


def _get_user(db: Session, user_id: str) -> models.User:
    user = user_service.get_user_by_id(db, user_id)
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    return user


def _embedding_diversity(embeddings: list) -> float:
    """Compute average pairwise cosine distance among embeddings (0 = identical, 1 = diverse)."""
    if len(embeddings) < 2:
        return 0.0
    total_dist = 0.0
    count = 0
    for i in range(len(embeddings)):
        for j in range(i + 1, len(embeddings)):
            a, b = embeddings[i], embeddings[j]
            dot = sum(x * y for x, y in zip(a, b))
            na = math.sqrt(sum(x * x for x in a))
            nb = math.sqrt(sum(x * x for x in b))
            if na > 0 and nb > 0:
                sim = dot / (na * nb)
                total_dist += 1 - sim
                count += 1
    return total_dist / count if count > 0 else 0.0


def _analyze_threshold_effectiveness(
    current_threshold: float,
    logs: list[models.VisitorLog],
) -> dict | None:
    """Summarize threshold performance and suggest an adjusted value when data supports it."""
    if not logs:
        return None

    identified_confs = [l.confidence for l in logs if l.identified and l.confidence > 0]
    unidentified_confs = [l.confidence for l in logs if not l.identified and l.confidence > 0]

    avg_identified = sum(identified_confs) / len(identified_confs) if identified_confs else 0
    avg_unidentified = sum(unidentified_confs) / len(unidentified_confs) if unidentified_confs else 0

    if avg_identified > 0 and avg_unidentified > 0:
        suggested = (avg_identified + avg_unidentified) / 2
    elif avg_identified > 0:
        suggested = max(0.5, avg_identified - 0.15)
    else:
        return None

    suggested = round(max(0.4, min(0.95, suggested)), 2)
    return {
        "current_threshold": round(current_threshold, 2),
        "suggested_threshold": suggested,
        "avg_identified_confidence": round(avg_identified, 3),
        "avg_unidentified_confidence": round(avg_unidentified, 3),
        "total_logs_analyzed": len(logs),
        "identified_count": len(identified_confs),
        "unidentified_count": len(unidentified_confs),
    }


def _threshold_tuning_recommendation(
    org: models.Organization | None,
    threshold_analysis: dict | None,
) -> schemas.Recommendation | None:
    """Convert threshold analysis into an actionable recommendation card."""
    if not threshold_analysis or not org:
        return None

    current_threshold = threshold_analysis["current_threshold"]
    suggested_threshold = threshold_analysis["suggested_threshold"]
    delta = abs(suggested_threshold - current_threshold)

    if delta < 0.05:
        return None

    direction = "lower" if suggested_threshold < current_threshold else "raise"
    severity = "warning" if delta >= 0.1 else "info"

    return schemas.Recommendation(
        type="threshold_tuning",
        severity=severity,
        title=f"Suggested confidence threshold: {suggested_threshold:.2f}",
        message=(
            f"Based on the last {threshold_analysis['total_logs_analyzed']} logs, consider {direction}ing "
            f"the organization threshold from {current_threshold:.2f} to {suggested_threshold:.2f}."
        ),
        entity_type="organization",
        entity_name=org.name,
        action="adjust_threshold",
    )


def _best_practice_recommendations(
    org: models.Organization,
    db: Session,
) -> list[schemas.Recommendation]:
    """Emit lightweight best-practice suggestions that are immediately actionable."""
    recs: list[schemas.Recommendation] = []
    settings = org.settings or {}
    liveness = settings.get("liveness", {})

    if not liveness.get("enabled", True):
        recs.append(
            schemas.Recommendation(
                type="best_practice",
                severity="info",
                title="Enable liveness detection",
                message=(
                    "Liveness checks are disabled. Enabling them helps reject spoofed photos and replay attacks."
                ),
                entity_type="organization",
                entity_name=org.name,
                action="review_settings",
            )
        )

    if not org.notification_unidentified:
        recs.append(
            schemas.Recommendation(
                type="best_practice",
                severity="info",
                title="Enable unidentified visitor alerts",
                message=(
                    "Unidentified visitor alerts are off. Turning them on helps security staff respond faster."
                ),
                entity_type="organization",
                entity_name=org.name,
                action="review_settings",
            )
        )

    known_visitors = db.query(func.count(models.Visitor.id)).filter(
        models.Visitor.organization_id == org.id,
        models.Visitor.is_known == True,
    ).scalar() or 0
    known_face_images = db.query(func.count(models.FaceData.id)).join(
        models.Visitor
    ).filter(
        models.Visitor.organization_id == org.id,
        models.Visitor.is_known == True,
    ).scalar() or 0
    avg_images = known_face_images / known_visitors if known_visitors else 0
    if known_visitors and avg_images < 3:
        recs.append(
            schemas.Recommendation(
                type="best_practice",
                severity="info",
                title="Collect more varied face images",
                message=(
                    f"Known visitors currently average {avg_images:.1f} face images each. "
                    "Aim for at least 3 images per visitor from different angles and lighting."
                ),
                action="add_diverse_images",
            )
        )

    return recs


@router.get("/", response_model=schemas.RecommendationsResponse)
async def get_all_recommendations(
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get all system recommendations for the organization."""
    user = _get_user(db, current_user_id)
    org_id = user.organization_id
    recs: List[schemas.Recommendation] = []

    # 1. Face quality recommendations (US-REC-001)
    visitors = db.query(models.Visitor).filter(
        models.Visitor.organization_id == org_id
    ).limit(100000).all()
    face_summaries = visitor_service.get_face_summary_for_visitors(
        db, [v.id for v in visitors]
    )
    for v in visitors:
        face_data = db.query(models.FaceData).filter(
            models.FaceData.visitor_id == v.id
        ).limit(10000).all()
        low_quality = [f for f in face_data if f.quality_score < 0.5]
        summary = face_summaries.get(str(v.id), {})
        if low_quality:
            recs.append(schemas.Recommendation(
                type="face_quality",
                severity="warning",
                title=f"Low quality face images for {v.name or 'Unknown'}",
                message=f"{len(low_quality)} of {len(face_data)} face images have low quality scores. Consider re-uploading higher resolution photos.",
                entity_id=str(v.id),
                entity_type="visitor",
                entity_name=v.name or "Unknown",
                entity_image_url=summary.get("primary_face_image_url"),
                action="upload_better_images",
            ))

    recent_logs = db.query(models.VisitorLog).filter(
        models.VisitorLog.organization_id == org_id,
        models.VisitorLog.timestamp >= datetime.datetime.now(timezone.utc) - datetime.timedelta(days=7),
    ).limit(100000).all()

    # 2. Low accuracy alerts (US-REC-002)
    if recent_logs:
        identified = sum(1 for l in recent_logs if l.identified)
        accuracy = identified / len(recent_logs) if recent_logs else 0
        if accuracy < 0.5:
            recs.append(schemas.Recommendation(
                type="low_accuracy",
                severity="critical",
                title="Low recognition accuracy detected",
                message=f"Recognition accuracy is {accuracy:.0%} over the last 7 days. Consider adding more training images or adjusting thresholds.",
                action="retrain_model",
            ))
        elif accuracy < 0.7:
            recs.append(schemas.Recommendation(
                type="low_accuracy",
                severity="warning",
                title="Below-average recognition accuracy",
                message=f"Recognition accuracy is {accuracy:.0%} over the last 7 days.",
                action="review_settings",
            ))

    # 3. Missing visitor recommendations (US-REC-003)
    visitors_no_faces = db.query(models.Visitor).filter(
        models.Visitor.organization_id == org_id,
        models.Visitor.is_known == True,
    ).limit(100000).all()
    for v in visitors_no_faces:
        face_count = db.query(func.count(models.FaceData.id)).filter(
            models.FaceData.visitor_id == v.id
        ).scalar() or 0
        if face_count == 0:
            summary = face_summaries.get(str(v.id), {})
            recs.append(schemas.Recommendation(
                type="missing_visitor",
                severity="warning",
                title=f"No face data for known visitor: {v.name or 'Unknown'}",
                message="This visitor is marked as known but has no face data registered. They cannot be identified automatically.",
                entity_id=str(v.id),
                entity_type="visitor",
                entity_name=v.name or "Unknown",
                entity_image_url=summary.get("primary_face_image_url"),
                action="register_face",
            ))

    # 4. Threshold optimization (US-REC-004)
    org = db.query(models.Organization).filter(
        models.Organization.id == org_id
    ).first()
    if org and recent_logs:
        high_conf = sum(1 for l in recent_logs if l.confidence > 0.8 and l.identified)
        low_conf_identified = sum(1 for l in recent_logs if 0.5 <= l.confidence <= 0.65 and l.identified)
        if low_conf_identified > len(recent_logs) * 0.2:
            recs.append(schemas.Recommendation(
                type="threshold",
                severity="info",
                title="Consider lowering confidence threshold",
                message=f"Many identifications ({low_conf_identified}) are near the current threshold. Lowering it slightly may improve recall.",
                action="adjust_threshold",
            ))
        unidentified_high = sum(1 for l in recent_logs if not l.identified and l.confidence > 0.5)
        if unidentified_high > 10:
            recs.append(schemas.Recommendation(
                type="threshold",
                severity="info",
                title="Consider reviewing unidentified detections",
                message=f"{unidentified_high} unidentified detections have moderate confidence. They may be known visitors needing face registration.",
                action="review_unidentified",
            ))

        threshold_analysis = _analyze_threshold_effectiveness(org.face_confidence_threshold if org else 0.6, recent_logs)
        threshold_rec = _threshold_tuning_recommendation(org, threshold_analysis)
        if threshold_rec:
            recs.append(threshold_rec)

    # 5. Diversity analysis (US-REC-005)
    for v in visitors:
        face_data = db.query(models.FaceData).filter(
            models.FaceData.visitor_id == v.id
        ).limit(10000).all()
        if len(face_data) >= 3:
            embeddings = []
            for f in face_data:
                if f.embedding:
                    try:
                        raw = f.embedding if isinstance(f.embedding, str) else str(f.embedding)
                        try:
                            dec = decrypt_embedding(raw)
                            emb = json.loads(dec)
                        except Exception:
                            emb = json.loads(raw)
                        embeddings.append(emb)
                    except Exception:
                        pass
            if len(embeddings) >= 3:
                diversity = _embedding_diversity(embeddings)
                if diversity < 0.05:
                    recs.append(schemas.Recommendation(
                        type="diversity",
                        severity="info",
                        title=f"Low face data diversity for {v.name or 'Unknown'}",
                        message="Face images are very similar. Adding images from different angles/lighting will improve recognition.",
                        entity_id=str(v.id),
                        entity_type="visitor",
                        entity_name=v.name or "Unknown",
                        entity_image_url=face_summaries.get(str(v.id), {}).get("primary_face_image_url"),
                        action="add_diverse_images",
                    ))

    # 6. Performance recommendations (US-REC-006)
    total_embeddings = db.query(func.count(models.FaceData.id)).join(
        models.Visitor
    ).filter(models.Visitor.organization_id == org_id).scalar() or 0
    if total_embeddings > 1000:
        recs.append(schemas.Recommendation(
            type="performance",
            severity="info",
            title="Large embedding database",
            message=f"You have {total_embeddings} face embeddings. Consider using PostgreSQL with pgvector for faster searches.",
            action="upgrade_database",
        ))

    data_dir = FACE_IMAGE_DIR
    total_size = 0
    if os.path.exists(data_dir):
        for dirpath, dirnames, filenames in os.walk(data_dir):
            for f in filenames:
                fp = os.path.join(dirpath, f)
                total_size += os.path.getsize(fp)
    if total_size > 500 * 1024 * 1024:  # 500MB
        recs.append(schemas.Recommendation(
            type="performance",
            severity="warning",
            title="High storage usage for face images",
            message=f"Face image storage is using {total_size / (1024*1024):.0f}MB. Consider archiving old data.",
            action="archive_data",
        ))

    if org:
        recs.extend(_best_practice_recommendations(org, db))

    return schemas.RecommendationsResponse(
        recommendations=recs,
        generated_at=datetime.datetime.now(timezone.utc),
    )


@router.get("/face-quality", response_model=List[schemas.Recommendation])
async def get_face_quality_recommendations(
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """US-REC-001: Get face quality recommendations for all visitors."""
    user = _get_user(db, current_user_id)
    recs = []
    visitors = db.query(models.Visitor).filter(
        models.Visitor.organization_id == user.organization_id
    ).limit(100000).all()
    for v in visitors:
        face_data = db.query(models.FaceData).filter(
            models.FaceData.visitor_id == v.id
        ).limit(10000).all()
        if not face_data:
            continue
        low_q = [f for f in face_data if f.quality_score < 0.5]
        if low_q:
            recs.append(schemas.Recommendation(
                type="face_quality",
                severity="warning",
                title=f"Low quality images: {v.name or 'Unknown'}",
                message=f"{len(low_q)}/{len(face_data)} images below quality threshold.",
                entity_id=str(v.id),
                entity_type="visitor",
                entity_name=v.name or "Unknown",
                entity_image_url=visitor_service.get_face_summary_for_visitor(db, v.id).get("primary_face_image_url"),
                action="upload_better_images",
            ))
    return recs


@router.get("/threshold-optimization")
async def get_threshold_optimization(
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """US-REC-004: Analyze current threshold effectiveness and suggest optimal value."""
    user = _get_user(db, current_user_id)
    org = db.query(models.Organization).filter(
        models.Organization.id == user.organization_id
    ).first()
    current_threshold = org.face_confidence_threshold if org else 0.6

    logs = db.query(models.VisitorLog).filter(
        models.VisitorLog.organization_id == user.organization_id,
        models.VisitorLog.timestamp >= datetime.datetime.now(timezone.utc) - datetime.timedelta(days=30),
    ).limit(500000).all()

    threshold_analysis = _analyze_threshold_effectiveness(current_threshold, logs)

    if not threshold_analysis:
        return {
            "current_threshold": current_threshold,
            "suggested_threshold": current_threshold,
            "analysis": "Not enough data to analyze threshold effectiveness.",
            "total_logs_analyzed": 0,
        }

    return {
        **threshold_analysis,
        "analysis": (
            "Threshold tuning data looks healthy."
            if abs(threshold_analysis["suggested_threshold"] - threshold_analysis["current_threshold"]) < 0.05
            else "Threshold tuning recommendation generated from recent logs."
        ),
    }
