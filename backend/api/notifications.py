"""S22: Notifications — in-app notification center."""

import os
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Header, Request
from sqlalchemy.orm import Session
from sqlalchemy import func
from db.base import get_db
from models import models
from schemas import schemas
from services import user_service
from services.redis_service import get_redis_service
from core.security import get_current_user
from uuid import UUID
from typing import List, Optional

_INTERNAL_KEY_RATE_LIMIT = int(os.getenv("INTERNAL_KEY_RATE_LIMIT", "300"))
_INTERNAL_KEY_RATE_WINDOW = int(os.getenv("INTERNAL_KEY_RATE_WINDOW_SECONDS", "60"))


def _require_internal_key(
    request: Request,
    x_internal_api_key: Optional[str] = Header(None, alias="X-Internal-API-Key"),
) -> None:
    from core.security import verify_internal_key
    if not verify_internal_key(x_internal_api_key):
        raise HTTPException(status_code=401, detail="Invalid or missing internal API key")
    client_ip = (request.headers.get("x-forwarded-for", "").split(",")[0].strip()
                 or (request.client.host if request.client else "unknown"))
    result = get_redis_service().check_rate_limit(
        key=f"internal_key:{client_ip}",
        max_requests=_INTERNAL_KEY_RATE_LIMIT,
        window_seconds=_INTERNAL_KEY_RATE_WINDOW,
    )
    if not result.get("allowed", True):
        raise HTTPException(status_code=429, detail="Rate limit exceeded for internal API key")

router = APIRouter(prefix="/notifications", tags=["Notifications"])


def _get_user(db: Session, user_id: str) -> models.User:
    user = user_service.get_user_by_id(db, user_id)
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    return user


@router.get("/", response_model=List[schemas.NotificationResponse])
async def list_notifications(
    unread_only: bool = False,
    limit: int = 50,
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get notifications for the current user."""
    user = _get_user(db, current_user_id)
    query = db.query(models.Notification).filter(
        models.Notification.organization_id == user.organization_id,
        (models.Notification.user_id == user.id) | (models.Notification.user_id.is_(None)),
    )
    if unread_only:
        query = query.filter(models.Notification.is_read == False)
    notifications = query.order_by(
        models.Notification.created_at.desc()
    ).limit(limit).all()
    return notifications


@router.get("/unread-count")
async def get_unread_count(
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get count of unread notifications."""
    user = _get_user(db, current_user_id)
    count = db.query(func.count(models.Notification.id)).filter(
        models.Notification.organization_id == user.organization_id,
        (models.Notification.user_id == user.id) | (models.Notification.user_id.is_(None)),
        models.Notification.is_read == False,
    ).scalar() or 0
    return {"count": count}


@router.put("/{notification_id}/read")
async def mark_notification_read(
    notification_id: UUID,
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Mark a notification as read."""
    user = _get_user(db, current_user_id)
    notification = db.query(models.Notification).filter(
        models.Notification.id == notification_id,
        models.Notification.organization_id == user.organization_id,
    ).first()
    if not notification:
        raise HTTPException(status_code=404, detail="Notification not found")

    notification.is_read = True
    db.commit()
    return {"message": "Notification marked as read"}


@router.put("/read-all")
async def mark_all_read(
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Mark all notifications as read for the current user."""
    user = _get_user(db, current_user_id)
    db.query(models.Notification).filter(
        models.Notification.organization_id == user.organization_id,
        (models.Notification.user_id == user.id) | (models.Notification.user_id.is_(None)),
        models.Notification.is_read == False,
    ).update({"is_read": True}, synchronize_session=False)
    db.commit()
    return {"message": "All notifications marked as read"}


@router.delete("/{notification_id}")
async def delete_notification(
    notification_id: UUID,
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Delete a notification."""
    user = _get_user(db, current_user_id)
    notification = db.query(models.Notification).filter(
        models.Notification.id == notification_id,
        models.Notification.organization_id == user.organization_id,
    ).first()
    if not notification:
        raise HTTPException(status_code=404, detail="Notification not found")

    db.delete(notification)
    db.commit()
    return {"message": "Notification deleted"}


@router.post("/", response_model=schemas.NotificationResponse, status_code=201)
async def create_notification(
    payload: schemas.NotificationCreate,
    _: None = Depends(_require_internal_key),
    db: Session = Depends(get_db),
):
    """Create a notification. Internal services only (requires X-Internal-API-Key)."""
    org_exists = db.query(models.Organization.id).filter(
        models.Organization.id == payload.organization_id
    ).first()
    if not org_exists:
        raise HTTPException(status_code=404, detail="Organization not found")

    if payload.user_id is not None:
        user_exists = db.query(models.User.id).filter(
            models.User.id == payload.user_id,
            models.User.organization_id == payload.organization_id,
        ).first()
        if not user_exists:
            raise HTTPException(status_code=404, detail="User not found in organization")

    notification = models.Notification(
        organization_id=payload.organization_id,
        user_id=payload.user_id,
        title=payload.title,
        message=payload.message,
        notification_type=payload.notification_type,
        link=payload.link,
        is_read=False,
        created_at=datetime.now(timezone.utc),
    )
    db.add(notification)
    db.commit()
    db.refresh(notification)
    return notification


@router.get("/preferences", response_model=schemas.NotificationPreferences)
async def get_notification_preferences(
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get notification preferences for the organization."""
    user = _get_user(db, current_user_id)
    org = db.query(models.Organization).filter(
        models.Organization.id == user.organization_id
    ).first()
    settings = org.settings or {} if org else {}
    prefs = settings.get("notification_preferences", {})
    return schemas.NotificationPreferences(
        browser_push=prefs.get("browser_push", True),
        email_alerts=prefs.get("email_alerts", True),
        unidentified_alerts=prefs.get("unidentified_alerts", True),
        system_alerts=prefs.get("system_alerts", True),
    )


@router.put("/preferences", response_model=schemas.NotificationPreferences)
async def update_notification_preferences(
    prefs: schemas.NotificationPreferences,
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Update notification preferences. Admin only."""
    user = _get_user(db, current_user_id)
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin only")

    org = db.query(models.Organization).filter(
        models.Organization.id == user.organization_id
    ).first()
    if not org:
        raise HTTPException(status_code=404, detail="Organization not found")

    settings = org.settings or {}
    settings["notification_preferences"] = prefs.model_dump()
    org.settings = settings
    db.commit()
    return prefs
