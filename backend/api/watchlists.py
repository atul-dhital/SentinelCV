"""Watchlist API (G2) — manage VIP / banned / person-of-interest entries.

When an identified visitor is on an active watchlist, the live recognition path
(`backend/api/camera.py`) raises a typed ``watchlist`` alert.
"""

from datetime import datetime
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from core.security import get_current_user
from db.base import get_db
from models import models
from services import user_service, visitor_service

router = APIRouter(prefix="/watchlists", tags=["Watchlists"])

VALID_CATEGORIES = {"vip", "banned", "poi"}
VALID_SEVERITIES = {"low", "medium", "high", "critical"}


class WatchlistCreate(BaseModel):
    visitor_id: str
    category: str = "poi"
    severity: str = "medium"
    reason: Optional[str] = None


class WatchlistUpdate(BaseModel):
    category: Optional[str] = None
    severity: Optional[str] = None
    reason: Optional[str] = None
    is_active: Optional[bool] = None


class WatchlistResponse(BaseModel):
    id: str
    visitor_id: str
    visitor_name: Optional[str] = None
    category: str
    severity: str
    reason: Optional[str] = None
    is_active: bool
    created_at: Optional[datetime] = None


def _get_user(db: Session, user_id: str) -> models.User:
    user = user_service.get_user_by_id(db, user_id)
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    return user


def _to_response(entry: models.Watchlist, visitor_name: Optional[str]) -> WatchlistResponse:
    return WatchlistResponse(
        id=str(entry.id),
        visitor_id=str(entry.visitor_id),
        visitor_name=visitor_name,
        category=entry.category,
        severity=entry.severity,
        reason=entry.reason,
        is_active=bool(entry.is_active),
        created_at=entry.created_at,
    )


@router.get("/", response_model=List[WatchlistResponse])
async def list_watchlist(
    category: Optional[str] = None,
    active_only: bool = True,
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    user = _get_user(db, current_user_id)
    q = (
        db.query(models.Watchlist, models.Visitor.name)
        .outerjoin(models.Visitor, models.Watchlist.visitor_id == models.Visitor.id)
        .filter(models.Watchlist.organization_id == user.organization_id)
    )
    if active_only:
        q = q.filter(models.Watchlist.is_active == True)
    if category:
        q = q.filter(models.Watchlist.category == category)
    rows = q.order_by(models.Watchlist.created_at.desc()).limit(1000).all()
    return [_to_response(entry, name) for entry, name in rows]


@router.post("/", response_model=WatchlistResponse, status_code=201)
async def add_to_watchlist(
    payload: WatchlistCreate,
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    user = _get_user(db, current_user_id)

    if payload.category not in VALID_CATEGORIES:
        raise HTTPException(status_code=400, detail=f"category must be one of {sorted(VALID_CATEGORIES)}")
    if payload.severity not in VALID_SEVERITIES:
        raise HTTPException(status_code=400, detail=f"severity must be one of {sorted(VALID_SEVERITIES)}")

    visitor = visitor_service.get_visitor(db, UUID(payload.visitor_id))
    if not visitor or visitor.organization_id != user.organization_id:
        raise HTTPException(status_code=404, detail="Visitor not found")

    # Reactivate an existing entry for this visitor instead of duplicating.
    entry = (
        db.query(models.Watchlist)
        .filter(
            models.Watchlist.organization_id == user.organization_id,
            models.Watchlist.visitor_id == visitor.id,
        )
        .first()
    )
    if entry:
        entry.category = payload.category
        entry.severity = payload.severity
        entry.reason = payload.reason
        entry.is_active = True
    else:
        entry = models.Watchlist(
            organization_id=user.organization_id,
            visitor_id=visitor.id,
            category=payload.category,
            severity=payload.severity,
            reason=payload.reason,
            created_by=user.id,
            is_active=True,
        )
        db.add(entry)
    db.commit()
    db.refresh(entry)

    visitor_service.create_audit_log(
        db, user.organization_id, user.id, "create", "watchlist", str(entry.id),
        details={"visitor_id": str(visitor.id), "category": entry.category},
    )
    return _to_response(entry, visitor.name)


@router.patch("/{watchlist_id}", response_model=WatchlistResponse)
async def update_watchlist(
    watchlist_id: UUID,
    payload: WatchlistUpdate,
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    user = _get_user(db, current_user_id)
    entry = (
        db.query(models.Watchlist)
        .filter(
            models.Watchlist.id == watchlist_id,
            models.Watchlist.organization_id == user.organization_id,
        )
        .first()
    )
    if not entry:
        raise HTTPException(status_code=404, detail="Watchlist entry not found")

    if payload.category is not None:
        if payload.category not in VALID_CATEGORIES:
            raise HTTPException(status_code=400, detail=f"category must be one of {sorted(VALID_CATEGORIES)}")
        entry.category = payload.category
    if payload.severity is not None:
        if payload.severity not in VALID_SEVERITIES:
            raise HTTPException(status_code=400, detail=f"severity must be one of {sorted(VALID_SEVERITIES)}")
        entry.severity = payload.severity
    if payload.reason is not None:
        entry.reason = payload.reason
    if payload.is_active is not None:
        entry.is_active = payload.is_active
    db.commit()
    db.refresh(entry)

    visitor = visitor_service.get_visitor(db, entry.visitor_id)
    return _to_response(entry, visitor.name if visitor else None)


@router.delete("/{watchlist_id}")
async def remove_from_watchlist(
    watchlist_id: UUID,
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    user = _get_user(db, current_user_id)
    entry = (
        db.query(models.Watchlist)
        .filter(
            models.Watchlist.id == watchlist_id,
            models.Watchlist.organization_id == user.organization_id,
        )
        .first()
    )
    if not entry:
        raise HTTPException(status_code=404, detail="Watchlist entry not found")
    db.delete(entry)
    db.commit()
    visitor_service.create_audit_log(
        db, user.organization_id, user.id, "delete", "watchlist", str(watchlist_id),
    )
    return {"message": "Removed from watchlist"}
