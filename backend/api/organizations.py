from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from db.base import get_db
from models import models
from schemas import schemas
from services import user_service, visitor_service
from core.security import get_current_user
from uuid import UUID
from sqlalchemy import func

router = APIRouter(prefix="/organizations", tags=["Organizations"])


def _get_user(db: Session, user_id: str) -> models.User:
    user = user_service.get_user_by_id(db, user_id)
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    return user


@router.get("/me", response_model=schemas.Organization)
async def get_my_organization(
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get current user's organization."""
    user = _get_user(db, current_user_id)
    org = db.query(models.Organization).filter(
        models.Organization.id == user.organization_id
    ).first()
    if not org:
        raise HTTPException(status_code=404, detail="Organization not found")
    return org


@router.put("/me", response_model=schemas.Organization)
async def update_my_organization(
    update_data: schemas.OrganizationUpdate,
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Update current user's organization settings. Admin only."""
    user = _get_user(db, current_user_id)
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Only admins can update organization settings")

    org = db.query(models.Organization).filter(
        models.Organization.id == user.organization_id
    ).first()
    if not org:
        raise HTTPException(status_code=404, detail="Organization not found")

    update_dict = update_data.model_dump(exclude_unset=True)
    for key, value in update_dict.items():
        setattr(org, key, value)

    db.commit()
    db.refresh(org)

    visitor_service.create_audit_log(
        db, user.organization_id, user.id, "update", "organization", str(org.id)
    )
    return org


@router.get("/me/stats", response_model=schemas.OrganizationStats)
async def get_organization_stats(
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get detailed organization statistics."""
    user = _get_user(db, current_user_id)
    org_id = user.organization_id

    user_count = db.query(func.count(models.User.id)).filter(
        models.User.organization_id == org_id
    ).scalar() or 0

    visitor_count = db.query(func.count(models.Visitor.id)).filter(
        models.Visitor.organization_id == org_id
    ).scalar() or 0

    known_visitor_count = db.query(func.count(models.Visitor.id)).filter(
        models.Visitor.organization_id == org_id,
        models.Visitor.is_known == True
    ).scalar() or 0

    total_logs = db.query(func.count(models.VisitorLog.id)).filter(
        models.VisitorLog.organization_id == org_id
    ).scalar() or 0

    identified_logs = db.query(func.count(models.VisitorLog.id)).filter(
        models.VisitorLog.organization_id == org_id,
        models.VisitorLog.status.in_(["identified", "reviewed"])
    ).scalar() or 0

    unidentified_logs = db.query(func.count(models.VisitorLog.id)).filter(
        models.VisitorLog.organization_id == org_id,
        models.VisitorLog.status == "unidentified"
    ).scalar() or 0

    embedding_count = db.query(func.count(models.FaceData.id)).join(
        models.Visitor
    ).filter(
        models.Visitor.organization_id == org_id
    ).scalar() or 0

    camera_count = db.query(func.count(models.Camera.id)).filter(
        models.Camera.organization_id == org_id
    ).scalar() or 0

    return schemas.OrganizationStats(
        user_count=user_count,
        visitor_count=visitor_count,
        known_visitor_count=known_visitor_count,
        total_logs=total_logs,
        identified_logs=identified_logs,
        unidentified_logs=unidentified_logs,
        embedding_count=embedding_count,
        camera_count=camera_count,
    )
