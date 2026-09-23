"""Alert Configuration & Rules Management API

Endpoints for configuring alert thresholds, rules, and triggers.
Fixes BROKEN-007: Alert threshold configuration functionality (Phase 1)

Features:
- Create/read/update/delete alert rules
- Configure organization-wide alert settings
- Enable/disable specific alert types
- Set confidence thresholds per rule
- Configure actions (email, webhook, silence)
- Time-based rules (business hours, specific days)
- Rate limiting (max alerts per hour)
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from uuid import UUID
from typing import List, Optional
from datetime import datetime, timedelta, timezone

from db.base import get_db
from core.security import get_current_user
from services import user_service
from models import models
from schemas import schemas

router = APIRouter(prefix="/alerts", tags=["alerts"])


def _get_user(db: Session, user_id: str) -> models.User:
    user = user_service.get_user_by_id(db, user_id)
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    return user


def _require_admin(user: models.User) -> None:
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin only")


# ─── Alert Configuration Endpoints ──────────────────────────────────────────


@router.get("/config", response_model=schemas.AlertConfigResponse)
def get_alert_config(
    db: Session = Depends(get_db),
    current_user_id: str = Depends(get_current_user),
):
    """Get organization's alert configuration."""
    user = _get_user(db, current_user_id)
    config = db.query(models.AlertConfig).filter(
        models.AlertConfig.organization_id == user.organization_id
    ).first()
    
    if not config:
        # Create default config if it doesn't exist
        config = models.AlertConfig(
            organization_id=user.organization_id,
            alerts_enabled=True,
            email_alerts_enabled=True,
            webhook_alerts_enabled=True,
            min_confidence_threshold=0.5,
            alert_duplicate_window_seconds=300,
            enabled_alert_types=["known", "unknown"],
            default_action="email"
        )
        db.add(config)
        db.commit()
        db.refresh(config)
    
    return config


@router.put("/config", response_model=schemas.AlertConfigResponse)
def update_alert_config(
    request: schemas.AlertConfigUpdate,
    db: Session = Depends(get_db),
    current_user_id: str = Depends(get_current_user),
):
    """Update organization's alert configuration."""
    user = _get_user(db, current_user_id)
    _require_admin(user)
    config = db.query(models.AlertConfig).filter(
        models.AlertConfig.organization_id == user.organization_id
    ).first()
    
    if not config:
        config = models.AlertConfig(organization_id=user.organization_id)
        db.add(config)
    
    # Update only provided fields
    update_data = request.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(config, field, value)
    
    config.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(config)
    
    return config


# ─── Alert Rule Endpoints ──────────────────────────────────────────────────


@router.get("/rules", response_model=List[schemas.AlertRuleResponse])
def list_alert_rules(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    is_active: Optional[bool] = Query(None),
    trigger_type: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    current_user_id: str = Depends(get_current_user),
):
    """List alert rules for organization."""
    user = _get_user(db, current_user_id)
    query = db.query(models.AlertRule).filter(
        models.AlertRule.organization_id == user.organization_id
    )
    
    if is_active is not None:
        query = query.filter(models.AlertRule.is_active == is_active)
    
    if trigger_type:
        query = query.filter(models.AlertRule.trigger_type == trigger_type)
    
    rules = query.order_by(models.AlertRule.order).offset(skip).limit(limit).all()
    return rules


@router.post("/rules", response_model=schemas.AlertRuleResponse)
def create_alert_rule(
    request: schemas.AlertRuleCreate,
    db: Session = Depends(get_db),
    current_user_id: str = Depends(get_current_user),
):
    """Create a new alert rule."""
    user = _get_user(db, current_user_id)
    _require_admin(user)
    # Get or create alert config
    config = db.query(models.AlertConfig).filter(
        models.AlertConfig.organization_id == user.organization_id
    ).first()
    
    if not config:
        config = models.AlertConfig(organization_id=user.organization_id)
        db.add(config)
        db.commit()
        db.refresh(config)
    
    # Get max order for this config
    max_order = db.query(models.AlertRule).filter(
        models.AlertRule.alert_config_id == config.id
    ).count()
    
    # Create rule
    rule = models.AlertRule(
        organization_id=user.organization_id,
        alert_config_id=config.id,
        **request.model_dump()
    )
    rule.order = max_order
    
    db.add(rule)
    db.commit()
    db.refresh(rule)
    
    return rule


@router.get("/rules/{rule_id}", response_model=schemas.AlertRuleResponse)
def get_alert_rule(
    rule_id: UUID,
    db: Session = Depends(get_db),
    current_user_id: str = Depends(get_current_user),
):
    """Get a specific alert rule."""
    user = _get_user(db, current_user_id)
    rule = db.query(models.AlertRule).filter(
        models.AlertRule.id == rule_id,
        models.AlertRule.organization_id == user.organization_id
    ).first()
    
    if not rule:
        raise HTTPException(status_code=404, detail="Alert rule not found")
    
    return rule


@router.put("/rules/{rule_id}", response_model=schemas.AlertRuleResponse)
def update_alert_rule(
    rule_id: UUID,
    request: schemas.AlertRuleUpdate,
    db: Session = Depends(get_db),
    current_user_id: str = Depends(get_current_user),
):
    """Update an alert rule."""
    user = _get_user(db, current_user_id)
    _require_admin(user)
    rule = db.query(models.AlertRule).filter(
        models.AlertRule.id == rule_id,
        models.AlertRule.organization_id == user.organization_id
    ).first()
    
    if not rule:
        raise HTTPException(status_code=404, detail="Alert rule not found")
    
    # Update provided fields
    update_data = request.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(rule, field, value)
    
    rule.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(rule)
    
    return rule


@router.delete("/rules/{rule_id}")
def delete_alert_rule(
    rule_id: UUID,
    db: Session = Depends(get_db),
    current_user_id: str = Depends(get_current_user),
):
    """Delete an alert rule."""
    user = _get_user(db, current_user_id)
    _require_admin(user)
    rule = db.query(models.AlertRule).filter(
        models.AlertRule.id == rule_id,
        models.AlertRule.organization_id == user.organization_id
    ).first()
    
    if not rule:
        raise HTTPException(status_code=404, detail="Alert rule not found")
    
    db.delete(rule)
    db.commit()
    
    return {"detail": "Alert rule deleted"}


@router.post("/rules/{rule_id}/activate")
def activate_alert_rule(
    rule_id: UUID,
    db: Session = Depends(get_db),
    current_user_id: str = Depends(get_current_user),
):
    """Activate an alert rule."""
    user = _get_user(db, current_user_id)
    _require_admin(user)
    rule = db.query(models.AlertRule).filter(
        models.AlertRule.id == rule_id,
        models.AlertRule.organization_id == user.organization_id
    ).first()
    
    if not rule:
        raise HTTPException(status_code=404, detail="Alert rule not found")
    
    rule.is_active = True
    rule.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(rule)
    
    return rule


@router.post("/rules/{rule_id}/deactivate")
def deactivate_alert_rule(
    rule_id: UUID,
    db: Session = Depends(get_db),
    current_user_id: str = Depends(get_current_user),
):
    """Deactivate an alert rule."""
    user = _get_user(db, current_user_id)
    _require_admin(user)
    rule = db.query(models.AlertRule).filter(
        models.AlertRule.id == rule_id,
        models.AlertRule.organization_id == user.organization_id
    ).first()
    
    if not rule:
        raise HTTPException(status_code=404, detail="Alert rule not found")
    
    rule.is_active = False
    rule.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(rule)
    
    return rule


@router.post("/rules/reorder")
def reorder_alert_rules(
    rule_order: List[UUID],
    db: Session = Depends(get_db),
    current_user_id: str = Depends(get_current_user),
):
    """Reorder alert rules for execution priority."""
    user = _get_user(db, current_user_id)
    _require_admin(user)
    for order_index, rule_id in enumerate(rule_order):
        rule = db.query(models.AlertRule).filter(
            models.AlertRule.id == rule_id,
            models.AlertRule.organization_id == user.organization_id
        ).first()
        
        if rule:
            rule.order = order_index
            db.add(rule)
    
    db.commit()
    return {"detail": f"Reordered {len(rule_order)} alert rules"}


# ─── Alert History & Analytics ────────────────────────────────────────────


@router.get("/triggers", response_model=List[dict])
def get_alert_triggers(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    rule_id: Optional[UUID] = Query(None),
    days: int = Query(7, ge=1, le=90),
    db: Session = Depends(get_db),
    current_user_id: str = Depends(get_current_user),
):
    """Get alert trigger history.
    
    Returns recent VisitorAlert records for the organization, optionally
    filtered by alert type and time window.
    """
    user = _get_user(db, current_user_id)
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)

    # VisitorAlert does not have organization_id directly — join through
    # CameraSession to scope by organization.
    query = (
        db.query(models.VisitorAlert)
        .join(models.CameraSession, models.VisitorAlert.session_id == models.CameraSession.id)
        .join(models.Camera, models.CameraSession.camera_id == models.Camera.id)
        .filter(
            models.Camera.organization_id == user.organization_id,
            models.VisitorAlert.timestamp >= cutoff,
        )
    )

    if rule_id:
        # Filter by alert_type derived from rule if caller provides one
        query = query.filter(models.VisitorAlert.alert_type == str(rule_id))

    alerts = query.order_by(
        models.VisitorAlert.timestamp.desc()
    ).offset(skip).limit(limit).all()

    return [
        {
            "id": str(a.id),
            "session_id": str(a.session_id) if a.session_id else None,
            "visitor_id": str(a.visitor_id) if a.visitor_id else None,
            "alert_type": a.alert_type,
            "message": a.message,
            "created_at": a.timestamp.isoformat() if a.timestamp else None,
        }
        for a in alerts
    ]


@router.get("/stats")
def get_alert_statistics(
    days: int = Query(7, ge=1, le=90),
    db: Session = Depends(get_db),
    current_user_id: str = Depends(get_current_user),
):
    """Get alert statistics for organization."""
    user = _get_user(db, current_user_id)
    config = db.query(models.AlertConfig).filter(
        models.AlertConfig.organization_id == user.organization_id
    ).first()
    
    rules = []
    if config:
        rules = db.query(models.AlertRule).filter(
            models.AlertRule.alert_config_id == config.id
        ).limit(10000).all()
    
    return {
        "organization_id": str(user.organization_id),
        "alerts_enabled": config.alerts_enabled if config else False,
        "total_rules": len(rules),
        "active_rules": sum(1 for r in rules if r.is_active),
        "by_trigger_type": _count_by_field(rules, "trigger_type") if rules else {}
    }


def _count_by_field(items, field):
    """Helper to count items by field value."""
    counts = {}
    for item in items:
        value = getattr(item, field, None)
        counts[value] = counts.get(value, 0) + 1
    return counts
