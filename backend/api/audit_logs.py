import csv
import io
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from db.base import get_db
from models import models
from schemas import schemas
from services import user_service, visitor_service
from core.security import get_current_user
from typing import List, Optional

router = APIRouter(prefix="/audit-logs", tags=["Audit Logs"])


def _get_user(db: Session, user_id: str) -> models.User:
    user = user_service.get_user_by_id(db, user_id)
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    return user


@router.get("/", response_model=schemas.PaginatedResponse)
async def list_audit_logs(
    skip: int = 0,
    limit: int = 50,
    search: Optional[str] = None,
    action: Optional[str] = None,
    user_id: Optional[str] = None,
    date_from: Optional[datetime] = None,
    date_to: Optional[datetime] = None,
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List audit logs for the organization. Admin only."""
    user = _get_user(db, current_user_id)
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Only admins can view audit logs")

    logs, total = visitor_service.get_audit_logs(
        db,
        user.organization_id,
        skip=skip,
        limit=limit,
        search=search,
        action=action,
        user_id=user_id,
        date_from=date_from,
        date_to=date_to,
    )

    pages = (total + limit - 1) // limit if limit > 0 else 1
    page = (skip // limit) + 1 if limit > 0 else 1

    return schemas.PaginatedResponse(
        items=[schemas.AuditLog.model_validate(log) for log in logs],
        total=total,
        page=page,
        limit=limit,
        pages=pages,
    )


@router.get("/export")
async def export_audit_logs(
    search: Optional[str] = None,
    action: Optional[str] = None,
    user_id: Optional[str] = None,
    date_from: Optional[datetime] = None,
    date_to: Optional[datetime] = None,
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Export audit logs as CSV. Admin only."""
    user = _get_user(db, current_user_id)
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Only admins can export audit logs")

    logs, _ = visitor_service.get_audit_logs(
        db,
        user.organization_id,
        skip=0,
        limit=10_000,
        search=search,
        action=action,
        user_id=user_id,
        date_from=date_from,
        date_to=date_to,
    )

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["id", "timestamp", "action", "entity_type", "entity_id", "user_id", "details"])
    for log in logs:
        import json as _json
        writer.writerow([
            str(log.id),
            log.timestamp.isoformat() if log.timestamp else "",
            log.action or "",
            log.entity_type or "",
            log.entity_id or "",
            str(log.user_id) if log.user_id else "",
            _json.dumps(log.details) if log.details else "{}",
        ])

    output.seek(0)
    filename = f"audit_logs_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )
