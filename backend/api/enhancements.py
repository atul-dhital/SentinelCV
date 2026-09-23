"""
Future Enhancements API Endpoints
"""
import uuid
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List
from datetime import datetime, timedelta

from db.base import get_db
from models.enhancements import (
    Enhancement, EnhancementConfig, Metric, BiasAudit,
    ExplainabilityResult, RateLimit, SustainabilityMetric
)
from models import models as core_models
from schemas.enhancements_schemas import (
    EnhancementCreate, EnhancementUpdate, EnhancementResponse,
    EnhancementConfigResponse, MetricResponse, MetricsListResponse,
    BiasAuditResponse, BiasAuditListResponse, ExplainabilityResponse,
    RateLimitCreate, RateLimitUpdate, RateLimitResponse,
    SustainabilityMetricResponse, RoadmapResponse, RoadmapPhase, RoadmapItem,
    PriorityMatrixResponse, PriorityMatrixItem,
    AugmentationConfigSchema, ModelArchConfigSchema, TrainingConfigSchema,
    RobustnessConfigSchema, AccuracyConfigSchema, PerformanceConfigSchema
)
from services import user_service
from core.security import get_current_user

router = APIRouter(prefix="/enhancements", tags=["enhancements"])


def _get_user(db: Session, user_id: str) -> core_models.User:
    """Every route below previously trusted a client-supplied org_id query
    param with no authentication at all — a cross-tenant read/write hole.
    Org id must always come from the authenticated user, never the request."""
    user = user_service.get_user_by_id(db, user_id)
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    return user


def _require_admin(user: core_models.User) -> None:
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin only")


def _map_phase_from_roadmap_phase(roadmap_phase: str | None) -> int:
    if roadmap_phase == "short_term":
        return 1
    if roadmap_phase == "medium_term":
        return 2
    if roadmap_phase == "long_term":
        return 3
    return 4


def _effort_weeks_from_priority(priority: str | None) -> int:
    if priority == "critical":
        return 2
    if priority == "high":
        return 4
    if priority == "medium":
        return 6
    return 8

# ========== ENHANCEMENTS ENDPOINTS ==========

@router.get("/", response_model=List[EnhancementResponse])
def get_enhancements(
    skip: int = 0,
    limit: int = 50,
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get all enhancements for an organization"""
    org_id = _get_user(db, current_user_id).organization_id
    enhancements = db.query(Enhancement).filter(
        Enhancement.organization_id == org_id
    ).offset(skip).limit(limit).all()

    if enhancements:
        return enhancements

    # Fallback to S26/S27 seeded enhancement catalog if dedicated table is empty.
    future_items = db.query(core_models.FutureEnhancement).filter(
        core_models.FutureEnhancement.organization_id == org_id
    ).offset(skip).limit(limit).all()

    return [
        {
            "id": item.story_id,
            "name": item.title,
            "description": item.description,
            "category": item.category,
            "priority": item.priority,
            "status": item.status,
            "enabled": item.enabled,
            "estimated_effort_weeks": _effort_weeks_from_priority(item.priority),
            "phase": _map_phase_from_roadmap_phase(item.roadmap_phase),
            "created_at": item.created_at,
            "updated_at": item.updated_at,
        }
        for item in future_items
    ]


@router.get("/roadmap", response_model=RoadmapResponse)
def get_roadmap(
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get project roadmap with phases and timeline"""
    org_id = _get_user(db, current_user_id).organization_id
    enhancements = db.query(Enhancement).filter(
        Enhancement.organization_id == org_id
    ).limit(1000).all()

    if not enhancements:
        future_items = db.query(core_models.FutureEnhancement).filter(
            core_models.FutureEnhancement.organization_id == org_id
        ).limit(1000).all()

        grouped = {1: [], 2: [], 3: [], 4: []}
        for item in future_items:
            phase_num = _map_phase_from_roadmap_phase(item.roadmap_phase)
            grouped.setdefault(phase_num, []).append(item)

        phase_names = {
            1: "Quick Wins (1-3 months)",
            2: "Core Improvements (3-6 months)",
            3: "Advanced Features (6-12 months)",
            4: "Future-Ready (12-24 months)",
        }
        duration_labels = {
            1: "1-3 months",
            2: "3-6 months",
            3: "6-12 months",
            4: "12-24 months",
        }

        roadmap_phases = []
        for phase_num in [1, 2, 3, 4]:
            phase_items = grouped.get(phase_num, [])
            items = [
                RoadmapItem(
                    task_id=item.story_id,
                    task_name=item.title,
                    phase=phase_num,
                    effort_weeks=_effort_weeks_from_priority(item.priority),
                    status=item.status,
                    priority=item.priority,
                )
                for item in phase_items
            ]

            roadmap_phases.append(
                RoadmapPhase(
                    phase_number=phase_num,
                    phase_name=phase_names[phase_num],
                    duration_months=duration_labels[phase_num],
                    items=items,
                    total_items=len(items),
                )
            )

        return RoadmapResponse(
            phases=roadmap_phases,
            total_enhancements=len(future_items),
        )
    
    # Group by phase
    phases = {}
    for enh in enhancements:
        phase = enh.phase or 0
        if phase not in phases:
            phases[phase] = []
        phases[phase].append(enh)
    
    # Create roadmap
    phase_names = {
        1: "Quick Wins (1-3 months)",
        2: "Core Improvements (3-6 months)",
        3: "Advanced Features (6-12 months)",
        4: "Future-Ready (12-24 months)"
    }
    
    roadmap_phases = []
    for phase_num in sorted(phases.keys()):
        items = []
        for enh in phases[phase_num]:
            items.append(RoadmapItem(
                task_id=enh.id,
                task_name=enh.name,
                phase=enh.phase,
                effort_weeks=enh.estimated_effort_weeks or 0,
                status=enh.status,
                priority=enh.priority
            ))
        
        roadmap_phases.append(RoadmapPhase(
            phase_number=phase_num,
            phase_name=phase_names.get(phase_num, f"Phase {phase_num}"),
            duration_months="",
            items=items,
            total_items=len(items)
        ))
    
    return RoadmapResponse(
        phases=roadmap_phases,
        total_enhancements=len(enhancements)
    )


@router.get("/priority-matrix", response_model=PriorityMatrixResponse)
def get_priority_matrix(
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get enhancements organized by priority"""
    org_id = _get_user(db, current_user_id).organization_id
    enhancements = db.query(Enhancement).filter(
        Enhancement.organization_id == org_id
    ).limit(1000).all()

    if not enhancements:
        future_items = db.query(core_models.FutureEnhancement).filter(
            core_models.FutureEnhancement.organization_id == org_id
        ).limit(1000).all()

        matrix = {
            "critical": [],
            "high": [],
            "medium": [],
            "low": []
        }

        for item in future_items:
            priority = (item.priority or "low").lower()
            matrix.setdefault(priority, []).append(
                PriorityMatrixItem(
                    id=item.story_id,
                    name=item.title,
                    priority=item.priority,
                    impact="high" if priority in {"critical", "high"} else "medium",
                    effort=f"{_effort_weeks_from_priority(item.priority)}w",
                    roi=0.9 if priority == "critical" else (0.8 if priority == "high" else 0.6),
                )
            )

        return PriorityMatrixResponse(**matrix)
    
    matrix = {
        "critical": [],
        "high": [],
        "medium": [],
        "low": []
    }
    
    for enh in enhancements:
        priority = enh.priority.lower()
        item = PriorityMatrixItem(
            id=enh.id,
            name=enh.name,
            priority=enh.priority,
            impact="high",  # Could be computed from metadata
            effort=f"{enh.estimated_effort_weeks}w" if enh.estimated_effort_weeks else "TBD",
            roi=0.85  # Could be computed
        )
        if priority in matrix:
            matrix[priority].append(item)
    
    return PriorityMatrixResponse(**matrix)


@router.post("/", response_model=EnhancementResponse)
def create_enhancement(
    enhancement: EnhancementCreate,
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Create a new enhancement"""
    user = _get_user(db, current_user_id)
    _require_admin(user)
    org_id = user.organization_id
    enh = Enhancement(
        id=f"US-FUT-{str(uuid.uuid4())[:8].upper()}",
        organization_id=org_id,
        name=enhancement.name,
        description=enhancement.description,
        category=enhancement.category,
        priority=enhancement.priority,
        estimated_effort_weeks=enhancement.estimated_effort_weeks,
        phase=enhancement.phase
    )
    db.add(enh)
    db.commit()
    db.refresh(enh)
    return enh


@router.patch("/{enhancement_id}", response_model=EnhancementResponse)
def update_enhancement(
    enhancement_id: str,
    update: EnhancementUpdate,
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Update an enhancement"""
    user = _get_user(db, current_user_id)
    _require_admin(user)
    org_id = user.organization_id
    enh = db.query(Enhancement).filter(
        Enhancement.id == enhancement_id,
        Enhancement.organization_id == org_id
    ).first()
    
    if not enh:
        raise HTTPException(status_code=404, detail="Enhancement not found")
    
    if update.status:
        enh.status = update.status
    if update.enabled is not None:
        enh.enabled = update.enabled
    if update.priority:
        enh.priority = update.priority
    
    enh.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(enh)
    return enh


# ========== AUGMENTATION CONFIGURATION ==========

@router.get("/config/augmentation/default")
def get_default_augmentation():
    """Get default augmentation configuration"""
    return {
        "rotation_enabled": True,
        "rotation_angle_range": [-15, 15],
        "flip_enabled": True,
        "flip_probability": 0.5,
        "scale_enabled": True,
        "scale_factor_range": [0.9, 1.1],
        "color_jitter_enabled": True,
        "jitter_intensity": 0.2,
        "cutout_enabled": True,
        "cutout_percentage": 0.3,
        "mixup_enabled": False,
        "mixup_alpha": 0.2,
        "cutmix_enabled": False,
        "cutmix_alpha": 1.0,
        "quality_checks_enabled": True,
        "auto_balance_demographics": False
    }


@router.post("/config/augmentation")
def save_augmentation_config(
    config: dict,
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Save augmentation configuration"""
    user = _get_user(db, current_user_id)
    _require_admin(user)
    org_id = user.organization_id
    config_record = db.query(EnhancementConfig).filter(
        EnhancementConfig.organization_id == org_id,
        EnhancementConfig.category == "augmentation"
    ).first()
    
    if not config_record:
        config_record = EnhancementConfig(
            id=str(uuid.uuid4()),
            organization_id=org_id,
            category="augmentation",
            enabled=config.get("enabled", True)
        )
        db.add(config_record)
    
    config_record.config_data = config
    config_record.enabled = config.get("enabled", True)
    config_record.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(config_record)
    
    return {
        "status": "saved",
        "category": "augmentation",
        "config": config_record.config_data
    }


# ========== MULTI-ANGLE CONFIGURATION ==========

@router.get("/config/multi-angle/default")
def get_default_multiangle():
    """Get default multi-angle configuration"""
    return {
        "enabled": True,
        "min_angles": 1,
        "consensus_threshold": 0.6,
        "angle_weights": {
            "frontal": 1.0,
            "45_left": 0.8,
            "45_right": 0.8,
            "profile_left": 0.5,
            "profile_right": 0.5,
            "top_down": 0.3,
        },
        "store_all_angles": True,
    }


@router.post("/config/multi-angle")
def save_multiangle_config(
    config: dict,
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Save multi-angle configuration"""
    user = _get_user(db, current_user_id)
    _require_admin(user)
    org_id = user.organization_id
    config_record = db.query(EnhancementConfig).filter(
        EnhancementConfig.organization_id == org_id,
        EnhancementConfig.category == "multi_angle"
    ).first()
    
    if not config_record:
        config_record = EnhancementConfig(
            id=str(uuid.uuid4()),
            organization_id=org_id,
            category="multi_angle",
            enabled=config.get("enabled", True)
        )
        db.add(config_record)
    
    config_record.config_data = config
    config_record.enabled = config.get("enabled", True)
    config_record.updated_at = datetime.now(timezone.utc)
    db.commit()
    
    return {
        "status": "saved",
        "category": "multi_angle",
        "config": config_record.config_data
    }


# ========== CONTINUAL LEARNING CONFIGURATION ==========

@router.get("/config/continual-learning/default")
def get_default_continual_learning():
    """Get default continual learning configuration"""
    return {
        "enabled": True,
        "memory_size": 1000,
        "min_confidence": 0.7,
        "auto_verify_manual": True,
        "retrain_threshold": 0.3,
        "retrain_min_samples": 10,
    }


@router.post("/config/continual-learning")
def save_continual_learning_config(
    config: dict,
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Save continual learning configuration"""
    user = _get_user(db, current_user_id)
    _require_admin(user)
    org_id = user.organization_id
    config_record = db.query(EnhancementConfig).filter(
        EnhancementConfig.organization_id == org_id,
        EnhancementConfig.category == "continual_learning"
    ).first()
    
    if not config_record:
        config_record = EnhancementConfig(
            id=str(uuid.uuid4()),
            organization_id=org_id,
            category="continual_learning",
            enabled=config.get("enabled", True)
        )
        db.add(config_record)
    
    config_record.config_data = config
    config_record.enabled = config.get("enabled", True)
    config_record.updated_at = datetime.now(timezone.utc)
    db.commit()
    
    return {
        "status": "saved",
        "category": "continual_learning",
        "config": config_record.config_data
    }


# ========== CONFIGURATION ENDPOINTS ==========

@router.get("/config/{category}", response_model=EnhancementConfigResponse)
def get_config(
    category: str,
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get configuration for a specific category"""
    org_id = _get_user(db, current_user_id).organization_id
    config = db.query(EnhancementConfig).filter(
        EnhancementConfig.organization_id == org_id,
        EnhancementConfig.category == category
    ).first()
    
    if not config:
        # Return default config
        config = EnhancementConfig(
            id=str(uuid.uuid4()),
            organization_id=org_id,
            category=category,
            config_data={},
            enabled=False
        )
        db.add(config)
        db.commit()
    
    return config


@router.post("/config/{category}", response_model=EnhancementConfigResponse)
def save_config(
    category: str,
    config_data: dict,
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Save configuration for a category"""
    user = _get_user(db, current_user_id)
    _require_admin(user)
    org_id = user.organization_id
    config = db.query(EnhancementConfig).filter(
        EnhancementConfig.organization_id == org_id,
        EnhancementConfig.category == category
    ).first()
    
    if not config:
        config = EnhancementConfig(
            id=str(uuid.uuid4()),
            organization_id=org_id,
            category=category
        )
        db.add(config)
    
    config.config_data = config_data
    config.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(config)
    return config


# ========== METRICS ENDPOINTS ==========

@router.get("/metrics", response_model=MetricsListResponse)
def get_metrics(
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get all metrics for organization"""
    org_id = _get_user(db, current_user_id).organization_id
    metrics = db.query(Metric).filter(
        Metric.organization_id == org_id
    ).limit(10000).all()
    
    summary = {
        "total_metrics": len(metrics),
        "metrics_on_target": sum(1 for m in metrics if m.current_value and m.target_value and m.current_value >= m.target_value)
    }
    
    return MetricsListResponse(
        metrics=metrics,
        summary=summary
    )


@router.post("/metrics/{metric_name}")
def update_metric(
    metric_name: str,
    value: float,
    target: float = None,
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Update a metric value"""
    user = _get_user(db, current_user_id)
    _require_admin(user)
    org_id = user.organization_id
    metric = db.query(Metric).filter(
        Metric.organization_id == org_id,
        Metric.metric_name == metric_name
    ).first()
    
    if not metric:
        metric = Metric(
            id=str(uuid.uuid4()),
            organization_id=org_id,
            metric_name=metric_name
        )
        db.add(metric)
    
    metric.current_value = value
    if target is not None:
        metric.target_value = target
    metric.timestamp = datetime.now(timezone.utc)
    db.commit()
    db.refresh(metric)
    return metric


# ========== BIAS AUDIT ENDPOINTS ==========

@router.get("/bias-audit", response_model=BiasAuditListResponse)
def get_bias_audit(
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get bias audit results"""
    org_id = _get_user(db, current_user_id).organization_id
    audits = db.query(BiasAudit).filter(
        BiasAudit.organization_id == org_id
    ).limit(10000).all()
    
    summary = {
        "total_groups": len(audits),
        "avg_accuracy": sum(a.accuracy_rate or 0 for a in audits) / len(audits) if audits else 0,
        "groups_below_95": sum(1 for a in audits if a.accuracy_rate and a.accuracy_rate < 0.95)
    }
    
    return BiasAuditListResponse(audits=audits, summary=summary)


@router.post("/bias-audit/{demographic_group}")
def create_bias_audit(
    demographic_group: str,
    audit_data: dict,
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Create bias audit result"""
    user = _get_user(db, current_user_id)
    _require_admin(user)
    org_id = user.organization_id
    audit = BiasAudit(
        id=str(uuid.uuid4()),
        organization_id=org_id,
        demographic_group=demographic_group,
        accuracy_rate=audit_data.get("accuracy_rate"),
        false_positive_rate=audit_data.get("false_positive_rate"),
        false_negative_rate=audit_data.get("false_negative_rate"),
        inference_count=audit_data.get("inference_count", 0)
    )
    db.add(audit)
    db.commit()
    db.refresh(audit)
    return audit


# ========== EXPLAINABILITY ENDPOINTS ==========

@router.get("/explainability/{detection_id}", response_model=ExplainabilityResponse)
def get_explainability(
    detection_id: str,
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get explainability analysis for a detection"""
    org_id = _get_user(db, current_user_id).organization_id
    result = db.query(ExplainabilityResult).filter(
        ExplainabilityResult.organization_id == org_id,
        ExplainabilityResult.detection_id == detection_id
    ).first()
    
    if not result:
        raise HTTPException(status_code=404, detail="Explainability result not found")
    
    return result


@router.post("/explainability/{detection_id}", response_model=ExplainabilityResponse)
def create_explainability(
    detection_id: str,
    method: str,
    explanation: dict,
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Create explainability analysis"""
    user = _get_user(db, current_user_id)
    _require_admin(user)
    org_id = user.organization_id
    result = ExplainabilityResult(
        id=str(uuid.uuid4()),
        organization_id=org_id,
        detection_id=detection_id,
        method=method,
        explanation_data=explanation
    )
    db.add(result)
    db.commit()
    db.refresh(result)
    return result


# ========== RATE LIMITS ENDPOINTS ==========

@router.get("/rate-limits", response_model=List[RateLimitResponse])
def get_rate_limits(
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get all rate limit rules"""
    org_id = _get_user(db, current_user_id).organization_id
    limits = db.query(RateLimit).filter(
        RateLimit.organization_id == org_id
    ).limit(1000).all()

    if limits:
        return limits

    # Fallback to S26/S27 rate_limit_rules table
    fallback_limits = db.query(core_models.RateLimitRule).filter(
        core_models.RateLimitRule.organization_id == org_id
    ).limit(1000).all()

    return [
        {
            "id": str(item.id),
            "endpoint_pattern": item.endpoint_pattern,
            "max_requests": item.max_requests,
            "time_window_seconds": item.window_seconds,
            "active": item.is_active,
            "created_at": item.created_at,
            "updated_at": item.created_at,
        }
        for item in fallback_limits
    ]


@router.post("/rate-limits", response_model=RateLimitResponse)
def create_rate_limit(
    limit: RateLimitCreate,
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Create a new rate limit rule"""
    user = _get_user(db, current_user_id)
    _require_admin(user)
    org_id = user.organization_id
    rate_limit = RateLimit(
        id=str(uuid.uuid4()),
        organization_id=org_id,
        endpoint_pattern=limit.endpoint_pattern,
        max_requests=limit.max_requests,
        time_window_seconds=limit.time_window_seconds
    )
    db.add(rate_limit)
    db.commit()
    db.refresh(rate_limit)
    return rate_limit


@router.patch("/rate-limits/{rate_limit_id}", response_model=RateLimitResponse)
def update_rate_limit(
    rate_limit_id: str,
    update: RateLimitUpdate,
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Update a rate limit rule"""
    user = _get_user(db, current_user_id)
    _require_admin(user)
    org_id = user.organization_id
    limit = db.query(RateLimit).filter(
        RateLimit.id == rate_limit_id,
        RateLimit.organization_id == org_id
    ).first()
    
    if not limit:
        raise HTTPException(status_code=404, detail="Rate limit not found")
    
    if update.max_requests:
        limit.max_requests = update.max_requests
    if update.time_window_seconds:
        limit.time_window_seconds = update.time_window_seconds
    if update.active is not None:
        limit.active = update.active
    
    limit.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(limit)
    return limit


@router.delete("/rate-limits/{rate_limit_id}")
def delete_rate_limit(
    rate_limit_id: str,
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Delete a rate limit rule"""
    user = _get_user(db, current_user_id)
    _require_admin(user)
    org_id = user.organization_id
    limit = db.query(RateLimit).filter(
        RateLimit.id == rate_limit_id,
        RateLimit.organization_id == org_id
    ).first()
    
    if not limit:
        raise HTTPException(status_code=404, detail="Rate limit not found")
    
    db.delete(limit)
    db.commit()
    return {"message": "Rate limit deleted"}


# ========== SUSTAINABILITY ENDPOINTS ==========

@router.get("/sustainability", response_model=SustainabilityMetricResponse)
def get_sustainability(
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get sustainability metrics for current period"""
    org_id = _get_user(db, current_user_id).organization_id
    today = datetime.now(timezone.utc)
    month_start = today.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    
    metric = db.query(SustainabilityMetric).filter(
        SustainabilityMetric.organization_id == org_id,
        SustainabilityMetric.period_start <= today,
        SustainabilityMetric.period_end >= today
    ).first()
    
    if not metric:
        # Fallback to S26/S27 carbon metrics for current period.
        carbon = db.query(core_models.CarbonMetrics).filter(
            core_models.CarbonMetrics.organization_id == org_id,
            core_models.CarbonMetrics.period_start <= today,
            core_models.CarbonMetrics.period_end >= today,
        ).first()

        if carbon:
            return {
                "id": str(carbon.id),
                "gpu_hours": carbon.gpu_hours,
                "cpu_hours": carbon.cpu_hours,
                "kwh_consumed": carbon.estimated_kwh,
                "co2_kg": carbon.estimated_co2_kg,
                "training_runs": carbon.training_runs,
                "inference_count": carbon.inference_count,
                "period_start": carbon.period_start,
                "period_end": carbon.period_end,
                "created_at": carbon.created_at,
            }

        # Return default/empty payload if no fallback data exists.
        return {
            "id": str(uuid.uuid4()),
            "gpu_hours": 0.0,
            "cpu_hours": 0.0,
            "kwh_consumed": 0.0,
            "co2_kg": 0.0,
            "training_runs": 0,
            "inference_count": 0,
            "period_start": month_start,
            "period_end": today.replace(day=28) if today.month < 12 else today,
            "created_at": today,
        }

    return metric


@router.post("/sustainability/update")
def update_sustainability(
    update_data: dict,
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Update sustainability metrics"""
    user = _get_user(db, current_user_id)
    _require_admin(user)
    org_id = user.organization_id
    today = datetime.now(timezone.utc)
    month_start = today.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    
    metric = db.query(SustainabilityMetric).filter(
        SustainabilityMetric.organization_id == org_id,
        SustainabilityMetric.period_start <= today,
        SustainabilityMetric.period_end >= today
    ).first()
    
    if not metric:
        metric = SustainabilityMetric(
            id=str(uuid.uuid4()),
            organization_id=org_id,
            period_start=month_start,
            period_end=today
        )
        db.add(metric)
    
    # Update values
    metric.gpu_hours = metric.gpu_hours + update_data.get("gpu_hours", 0)
    metric.cpu_hours = metric.cpu_hours + update_data.get("cpu_hours", 0)
    metric.kwh_consumed = metric.kwh_consumed + update_data.get("kwh_consumed", 0)
    metric.co2_kg = metric.co2_kg + update_data.get("co2_kg", 0)
    metric.training_runs = metric.training_runs + update_data.get("training_runs", 0)
    metric.inference_count = metric.inference_count + update_data.get("inference_count", 0)
    
    db.commit()
    db.refresh(metric)
    return metric
