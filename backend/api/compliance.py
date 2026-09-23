from datetime import datetime, timedelta, timezone
"""S20: Security & Compliance — encryption verification, retention, GDPR."""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import func
from db.base import get_db
from models import models
from schemas import schemas
from services import user_service, visitor_service
from core.security import get_current_user, decrypt_embedding
from uuid import UUID
from typing import List, Optional
import datetime
import json
from core.storage import storage

router = APIRouter(prefix="/compliance", tags=["Compliance"])


def _get_user(db: Session, user_id: str) -> models.User:
    user = user_service.get_user_by_id(db, user_id)
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    return user


def _require_admin(user: models.User) -> None:
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin only")


@router.get("/encryption-verify", response_model=schemas.EncryptionVerification)
async def verify_encryption(
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """US-SEC-001: Verify that all face embeddings are encrypted at rest."""
    user = _get_user(db, current_user_id)
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin only")

    face_records = db.query(models.FaceData).join(
        models.Visitor
    ).filter(
        models.Visitor.organization_id == user.organization_id
    ).limit(100000).all()

    total = len(face_records)
    encrypted = 0
    unencrypted = 0

    for face in face_records:
        if not face.embedding:
            continue
        raw = face.embedding if isinstance(face.embedding, str) else str(face.embedding)
        try:
            decrypt_embedding(raw)
            encrypted += 1
        except Exception:
            # If decrypt fails, it's either plain text or corrupted
            try:
                json.loads(raw)
                unencrypted += 1  # Valid JSON = unencrypted
            except Exception:
                unencrypted += 1  # Corrupted

    if unencrypted == 0 and total > 0:
        status = "passed"
    elif unencrypted > 0:
        status = "warning"
    else:
        status = "passed"

    visitor_service.create_audit_log(
        db, user.organization_id, user.id, "encryption_verify",
        "system", None,
        details={"total": total, "encrypted": encrypted, "unencrypted": unencrypted},
    )

    return schemas.EncryptionVerification(
        encryption_enabled=True,
        total_embeddings=total,
        encrypted_count=encrypted,
        unencrypted_count=unencrypted,
        verification_status=status,
    )


# ── Retention Policies ───────────────────────────────────────────────────────


@router.get("/retention-policies", response_model=List[schemas.RetentionPolicyResponse])
async def list_retention_policies(
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List data retention policies."""
    user = _get_user(db, current_user_id)
    _require_admin(user)
    policies = db.query(models.DataRetentionPolicy).filter(
        models.DataRetentionPolicy.organization_id == user.organization_id
    ).limit(1000).all()
    return policies


@router.post("/retention-policies", response_model=schemas.RetentionPolicyResponse)
async def create_retention_policy(
    data: schemas.RetentionPolicyCreate,
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Create or update a data retention policy. Admin only."""
    user = _get_user(db, current_user_id)
    _require_admin(user)

    if data.entity_type not in ("visitor_logs", "face_data", "audit_logs"):
        raise HTTPException(status_code=400, detail="Invalid entity_type. Must be: visitor_logs, face_data, audit_logs")

    # Upsert — update existing or create new
    existing = db.query(models.DataRetentionPolicy).filter(
        models.DataRetentionPolicy.organization_id == user.organization_id,
        models.DataRetentionPolicy.entity_type == data.entity_type,
    ).first()

    if existing:
        existing.retention_days = data.retention_days
        existing.auto_delete = data.auto_delete
        db.commit()
        db.refresh(existing)
        return existing

    policy = models.DataRetentionPolicy(
        organization_id=user.organization_id,
        entity_type=data.entity_type,
        retention_days=data.retention_days,
        auto_delete=data.auto_delete,
    )
    db.add(policy)
    db.commit()
    db.refresh(policy)

    visitor_service.create_audit_log(
        db, user.organization_id, user.id, "create_retention_policy",
        "retention_policy", str(policy.id),
        details={"entity_type": data.entity_type, "retention_days": data.retention_days},
    )
    return policy


@router.post("/retention-cleanup", response_model=List[schemas.RetentionCleanupResult])
async def run_retention_cleanup(
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """US-SEC-003: Run retention policy cleanup. Deletes data older than retention period. Admin only."""
    user = _get_user(db, current_user_id)
    _require_admin(user)

    policies = db.query(models.DataRetentionPolicy).filter(
        models.DataRetentionPolicy.organization_id == user.organization_id,
        models.DataRetentionPolicy.auto_delete == True,
    ).limit(1000).all()

    results = []
    for policy in policies:
        cutoff = datetime.datetime.now(timezone.utc) - datetime.timedelta(days=policy.retention_days)
        deleted = 0

        if policy.entity_type == "audit_logs":
            deleted = db.query(models.AuditLog).filter(
                models.AuditLog.organization_id == user.organization_id,
                models.AuditLog.timestamp < cutoff,
            ).delete(synchronize_session=False)

        elif policy.entity_type == "face_data":
            face_ids = db.query(models.FaceData.id).join(
                models.Visitor
            ).filter(
                models.Visitor.organization_id == user.organization_id,
                models.FaceData.created_at < cutoff,
            ).limit(100000).all()
            for (fid,) in face_ids:
                face = db.query(models.FaceData).filter(models.FaceData.id == fid).first()
                if face:
                    if face.image_url:
                        storage.delete_file(face.image_url)
                    db.delete(face)
                    deleted += 1

        # Note: visitor_logs are immutable — we skip actual deletion but record the intent
        elif policy.entity_type == "visitor_logs":
            # Count but don't delete (immutable)
            count = db.query(func.count(models.VisitorLog.id)).filter(
                models.VisitorLog.organization_id == user.organization_id,
                models.VisitorLog.timestamp < cutoff,
            ).scalar() or 0
            deleted = 0  # Logs are immutable

        policy.last_cleanup_at = datetime.datetime.now(timezone.utc)
        results.append(schemas.RetentionCleanupResult(
            entity_type=policy.entity_type,
            records_deleted=deleted,
            cutoff_date=cutoff,
        ))

    db.commit()

    visitor_service.create_audit_log(
        db, user.organization_id, user.id, "retention_cleanup",
        "system", None,
        details={"results": [r.model_dump(mode="json") for r in results]},
    )
    return results


# ── GDPR Compliance ──────────────────────────────────────────────────────────


@router.get("/gdpr/export/{visitor_id}", response_model=schemas.GdprExportResponse)
async def gdpr_export_visitor_data(
    visitor_id: UUID,
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """US-SEC-004: Export all data for a visitor (GDPR data portability). Admin only."""
    user = _get_user(db, current_user_id)
    _require_admin(user)
    visitor = db.query(models.Visitor).filter(
        models.Visitor.id == visitor_id,
        models.Visitor.organization_id == user.organization_id,
    ).first()
    if not visitor:
        raise HTTPException(status_code=404, detail="Visitor not found")

    # Collect all visitor data
    logs = db.query(models.VisitorLog).filter(
        models.VisitorLog.visitor_id == visitor_id
    ).limit(500000).all()
    face_data = db.query(models.FaceData).filter(
        models.FaceData.visitor_id == visitor_id
    ).limit(10000).all()

    export_data = {
        "visitor": {
            "id": str(visitor.id),
            "name": visitor.name,
            "email": visitor.email,
            "phone": visitor.phone,
            "description": visitor.description,
            "notes": visitor.notes,
            "is_known": visitor.is_known,
            "created_at": visitor.created_at.isoformat() if visitor.created_at else None,
            "updated_at": visitor.updated_at.isoformat() if visitor.updated_at else None,
            "last_detected_at": visitor.last_detected_at.isoformat() if visitor.last_detected_at else None,
            "detection_count": visitor.detection_count,
        },
        "face_data": [
            {
                "id": str(f.id),
                "image_url": f.image_url,
                "quality_score": f.quality_score,
                "created_at": f.created_at.isoformat() if f.created_at else None,
            }
            for f in face_data
        ],
        "visit_logs": [
            {
                "id": str(l.id),
                "timestamp": l.timestamp.isoformat() if l.timestamp else None,
                "confidence": l.confidence,
                "status": l.status,
                "camera_id": str(l.camera_id) if l.camera_id else None,
            }
            for l in logs
        ],
    }

    visitor_service.create_audit_log(
        db, user.organization_id, user.id, "gdpr_export",
        "visitor", str(visitor_id),
    )

    return schemas.GdprExportResponse(
        visitor_id=str(visitor_id),
        data=export_data,
        exported_at=datetime.datetime.now(timezone.utc),
    )


@router.delete("/gdpr/delete/{visitor_id}", response_model=schemas.GdprDeleteResponse)
async def gdpr_delete_visitor_data(
    visitor_id: UUID,
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """US-SEC-004: Complete deletion of visitor data (GDPR right to be forgotten).
    Admin only. Removes visitor, face data, and nullifies log references.
    """
    user = _get_user(db, current_user_id)
    _require_admin(user)

    visitor = db.query(models.Visitor).filter(
        models.Visitor.id == visitor_id,
        models.Visitor.organization_id == user.organization_id,
    ).first()
    if not visitor:
        raise HTTPException(status_code=404, detail="Visitor not found")

    records_deleted = {}

    # Delete face images from disk
    face_data = db.query(models.FaceData).filter(
        models.FaceData.visitor_id == visitor_id
    ).limit(10000).all()
    for f in face_data:
        if f.image_url:
            storage.delete_file(f.image_url)
    records_deleted["face_data"] = len(face_data)

    # Nullify visitor references in logs (logs are immutable — can't delete)
    log_count = db.query(models.VisitorLog).filter(
        models.VisitorLog.visitor_id == visitor_id
    ).update({"visitor_id": None, "identified": False, "status": "unidentified"})
    records_deleted["visitor_logs_anonymized"] = log_count

    # Nullify detection log references
    det_count = db.query(models.DetectionLog).filter(
        models.DetectionLog.visitor_id == visitor_id
    ).update({"visitor_id": None, "identified": False})
    records_deleted["detection_logs_anonymized"] = det_count

    # Delete the visitor (cascades face_data)
    db.delete(visitor)
    db.commit()
    records_deleted["visitor"] = 1

    visitor_service.create_audit_log(
        db, user.organization_id, user.id, "gdpr_delete",
        "visitor", str(visitor_id),
        details={"records_deleted": records_deleted},
    )

    return schemas.GdprDeleteResponse(
        visitor_id=str(visitor_id),
        records_deleted=records_deleted,
        deleted_at=datetime.datetime.now(timezone.utc),
    )


# ── Consent Management (US-FUT-028) ────────────────────────────────────────────


@router.get("/consent/", response_model=schemas.ConsentListResponse)
async def list_consent_records(
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    subject_type: Optional[str] = Query(None),
    consent_type: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """US-FUT-028: List consent records with filtering."""
    user = _get_user(db, current_user_id)
    
    query = db.query(models.ConsentRecord).filter(
        models.ConsentRecord.organization_id == user.organization_id,
    )
    
    if subject_type:
        query = query.filter(models.ConsentRecord.subject_type == subject_type)
    if consent_type:
        query = query.filter(models.ConsentRecord.consent_type == consent_type)
    if status:
        query = query.filter(models.ConsentRecord.status == status)
    
    total = query.count()
    pages = (total + limit - 1) // limit
    skip = (page - 1) * limit
    
    records = query.order_by(models.ConsentRecord.created_at.desc()).offset(skip).limit(limit).all()
    
    return schemas.ConsentListResponse(
        items=records,
        total=total,
        page=page,
        limit=limit,
        pages=pages,
    )


@router.post("/consent/", response_model=schemas.ConsentRecordResponse)
async def create_consent_record(
    data: schemas.ConsentRecordCreate,
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """US-FUT-028: Record a new consent grant. Admin only."""
    user = _get_user(db, current_user_id)
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin only")
    
    now = datetime.datetime.now(timezone.utc)
    
    record = models.ConsentRecord(
        organization_id=user.organization_id,
        subject_type=data.subject_type,
        subject_id=data.subject_id,
        user_id=data.user_id,
        consent_type=data.consent_type,
        consent_version=data.consent_version,
        consent_source=data.consent_source,
        status="granted",
        granted_at=now,
        granted_by=user.id,
        retention_days=data.retention_days,
        ip_address=data.ip_address,
        user_agent=data.user_agent,
        notes=data.notes,
    )
    
    if data.expires_at:
        record.expires_at = data.expires_at
    
    db.add(record)
    db.commit()
    db.refresh(record)
    
    visitor_service.create_audit_log(
        db, user.organization_id, user.id, "consent_granted",
        "consent_record", str(record.id),
        details={"consent_type": data.consent_type, "subject_type": data.subject_type},
    )
    
    return record


@router.put("/consent/{record_id}", response_model=schemas.ConsentRecordResponse)
async def update_consent_record(
    record_id: str,
    data: schemas.ConsentRecordUpdate,
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """US-FUT-028: Update consent status (revoke, expire, etc). Admin only."""
    user = _get_user(db, current_user_id)
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin only")
    
    record = db.query(models.ConsentRecord).filter(
        models.ConsentRecord.id == record_id,
        models.ConsentRecord.organization_id == user.organization_id,
    ).first()
    
    if not record:
        raise HTTPException(status_code=404, detail="Consent record not found")
    
    if data.status:
        if data.status == "revoked" and record.status != "revoked":
            record.revoked_at = datetime.datetime.now(timezone.utc)
            record.revoked_by = user.id
        elif data.status == "expired" and record.status != "expired":
            record.expires_at = datetime.datetime.now(timezone.utc)
        record.status = data.status
    
    if data.expires_at is not None:
        record.expires_at = data.expires_at
    if data.retention_days is not None:
        record.retention_days = data.retention_days
    if data.notes is not None:
        record.notes = data.notes
    
    db.commit()
    db.refresh(record)
    
    visitor_service.create_audit_log(
        db, user.organization_id, user.id, f"consent_{data.status or 'updated'}",
        "consent_record", str(record.id),
        details={"new_status": data.status},
    )
    
    return record


@router.delete("/consent/{record_id}")
async def delete_consent_record(
    record_id: str,
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """US-FUT-028: Delete a consent record. Admin only."""
    user = _get_user(db, current_user_id)
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin only")
    
    record = db.query(models.ConsentRecord).filter(
        models.ConsentRecord.id == record_id,
        models.ConsentRecord.organization_id == user.organization_id,
    ).first()
    
    if not record:
        raise HTTPException(status_code=404, detail="Consent record not found")
    
    db.delete(record)
    db.commit()
    
    return {"detail": "Consent record deleted"}
