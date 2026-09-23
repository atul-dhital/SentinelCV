from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from db.base import get_db
from models import models
from schemas import schemas
from services import user_service, visitor_service
from core.security import get_current_active_user, require_role, verify_password, get_password_hash
from uuid import UUID
from typing import List, Optional
import hashlib

router = APIRouter(prefix="/users", tags=["Users"])


@router.get("/", response_model=List[schemas.UserWithOrg])
async def list_users(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    current_user=Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """List users in the caller's organization (paginated)."""
    users = (
        db.query(models.User)
        .filter(models.User.organization_id == current_user.organization_id)
        .order_by(models.User.email)
        .offset(skip)
        .limit(limit)
        .all()
    )
    return users


@router.get("/me", response_model=schemas.UserWithOrg)
async def get_current_user_full(current_user=Depends(get_current_active_user)):
    """Get current user details."""
    return current_user


@router.get("/me/sessions", response_model=List[schemas.UserSession])
async def list_my_sessions(
    token_hash_hint: Optional[str] = Query(None, include_in_schema=False),
    current_user=Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """List all active refresh-token sessions for the current user."""
    now = datetime.now(timezone.utc)
    sessions = (
        db.query(models.RefreshTokenSession)
        .filter(
            models.RefreshTokenSession.user_id == current_user.id,
            models.RefreshTokenSession.revoked_at.is_(None),
            models.RefreshTokenSession.expires_at > now,
        )
        .order_by(models.RefreshTokenSession.last_used_at.desc())
        .limit(10000).all()
    )
    return [
        schemas.UserSession(
            jti=s.token_jti,
            ip_address=s.ip_address,
            user_agent=s.user_agent,
            created_at=s.created_at,
            last_used_at=s.last_used_at,
            expires_at=s.expires_at,
            is_current=(s.token_jti == token_hash_hint),
        )
        for s in sessions
    ]


@router.delete("/me/sessions/{jti}")
async def revoke_session(
    jti: str,
    current_user=Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """Revoke a specific refresh-token session by JTI."""
    session = (
        db.query(models.RefreshTokenSession)
        .filter(
            models.RefreshTokenSession.user_id == current_user.id,
            models.RefreshTokenSession.token_jti == jti,
            models.RefreshTokenSession.revoked_at.is_(None),
        )
        .first()
    )
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    session.revoked_at = datetime.now(timezone.utc)
    session.revoke_reason = "user_revoked"
    db.commit()
    return {"message": "Session revoked"}


@router.post("/me/change-password")
async def change_password(
    data: schemas.ChangePasswordRequest,
    current_user=Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """Change the current user's password. Requires the existing password."""
    if not verify_password(data.current_password, current_user.password_hash):
        raise HTTPException(status_code=400, detail="Current password is incorrect")
    current_user.password_hash = get_password_hash(data.new_password)
    db.commit()
    visitor_service.create_audit_log(
        db, current_user.organization_id, current_user.id,
        "change_password", "user", str(current_user.id),
    )
    return {"message": "Password updated successfully"}


@router.get("/{user_id}", response_model=schemas.UserWithOrg)
async def get_user(
    user_id: UUID,
    current_user=Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """Get a single user by ID (org-scoped)."""
    user = db.query(models.User).filter(
        models.User.id == user_id,
        models.User.organization_id == current_user.organization_id,
    ).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user


@router.post("/", response_model=schemas.UserWithOrg)
async def create_user(
    new_user: schemas.UserCreate,
    current_user=Depends(require_role("admin")),
    db: Session = Depends(get_db),
):
    """Create a new user in the organization. Admin only."""
    existing = user_service.get_user_by_email(db, new_user.email)
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")

    new_user.organization_id = current_user.organization_id
    db_user = user_service.create_user(db, new_user)

    visitor_service.create_audit_log(
        db, current_user.organization_id, current_user.id,
        "create", "user", str(db_user.id),
        details={"email": new_user.email, "role": new_user.role},
    )
    return db_user


@router.put("/{user_id}", response_model=schemas.UserWithOrg)
async def update_user(
    user_id: UUID,
    update_data: schemas.UserUpdate,
    current_user=Depends(require_role("admin")),
    db: Session = Depends(get_db),
):
    """Update a user's role, active status, or full name. Admin only."""
    user = db.query(models.User).filter(
        models.User.id == user_id,
        models.User.organization_id == current_user.organization_id,
    ).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    if str(user.id) == str(current_user.id) and update_data.is_active is False:
        raise HTTPException(status_code=400, detail="Cannot deactivate yourself")

    update_dict = update_data.model_dump(exclude_unset=True)
    before = {k: getattr(user, k) for k in update_dict}
    for key, value in update_dict.items():
        setattr(user, key, value)
    db.commit()
    db.refresh(user)

    visitor_service.create_audit_log(
        db, current_user.organization_id, current_user.id,
        "update", "user", str(user_id),
        details={"before": {k: str(v) for k, v in before.items()},
                 "after": {k: str(update_dict[k]) for k in update_dict}},
    )
    return user


@router.delete("/{user_id}")
async def delete_user(
    user_id: UUID,
    current_user=Depends(require_role("admin")),
    db: Session = Depends(get_db),
):
    """Delete a user. Admin only."""
    user = db.query(models.User).filter(
        models.User.id == user_id,
        models.User.organization_id == current_user.organization_id,
    ).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    if str(user.id) == str(current_user.id):
        raise HTTPException(status_code=400, detail="Cannot delete yourself")

    visitor_service.create_audit_log(
        db, current_user.organization_id, current_user.id,
        "delete", "user", str(user_id),
        details={"email": user.email, "role": user.role},
    )
    db.delete(user)
    db.commit()
    return {"message": "User deleted"}
