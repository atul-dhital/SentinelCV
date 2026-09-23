from datetime import datetime, timedelta, timezone
"""S17: Data Quality Assurance — duplicate detection, stale data, consistency, deduplication."""

from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy.orm import Session
from sqlalchemy import func
from db.base import get_db
from models import models
from schemas import schemas
from services import user_service, visitor_service
from services.data_quality_service import DataQualityAuditService
from core.security import get_current_user
from typing import List, Dict
import uuid
import datetime

router = APIRouter(prefix="/data-quality", tags=["Data Quality"])


def _get_user(db: Session, user_id: str) -> models.User:
    user = user_service.get_user_by_id(db, user_id)
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    return user


@router.get("/config", response_model=schemas.DataQualityConfig)
async def get_quality_config(
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Retrieve the data quality configuration for the organization."""
    user = _get_user(db, current_user_id)
    config = db.query(models.DataQualityConfig).filter_by(
        organization_id=user.organization_id
    ).first()
    
    if not config:
        config = models.DataQualityConfig(organization_id=user.organization_id)
        db.add(config)
        db.commit()
        db.refresh(config)
        
    return config


@router.post("/config", response_model=schemas.DataQualityConfig)
async def update_quality_config(
    config_update: schemas.DataQualityConfigUpdate,
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Update the data quality configuration."""
    user = _get_user(db, current_user_id)
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Only admins can update quality config")
        
    config = db.query(models.DataQualityConfig).filter_by(
        organization_id=user.organization_id
    ).first()
    
    if not config:
        config = models.DataQualityConfig(organization_id=user.organization_id)
        db.add(config)
        
    for key, value in config_update.model_dump(exclude_unset=True).items():
        setattr(config, key, value)
        
    db.commit()
    db.refresh(config)
    return config


@router.post("/audit", response_model=schemas.DataQualityAuditJob)
async def start_quality_audit(
    dataset_name: str,
    background_tasks: BackgroundTasks,
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Start a new automated data quality audit job (US-FUT-022)."""
    user = _get_user(db, current_user_id)
    
    config = db.query(models.DataQualityConfig).filter_by(
        organization_id=user.organization_id
    ).first()
    
    if not config:
        config = models.DataQualityConfig(organization_id=user.organization_id)
        db.add(config)
        db.commit()
    
    # Create audit job record
    job = models.DataQualityAuditJob(
        id=str(uuid.uuid4()),
        organization_id=user.organization_id,
        config_id=config.id,
        dataset_name=dataset_name,
        status="pending"
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    
    # Start background task
    service = DataQualityAuditService(db, user.organization_id)
    background_tasks.add_task(service.run_full_audit, job.id)
    
    return job


@router.get("/audit/{job_id}", response_model=schemas.DataQualityAuditJobDetailed)
async def get_audit_job_status(
    job_id: str,
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get the status and results of a quality audit job."""
    user = _get_user(db, current_user_id)
    job = db.query(models.DataQualityAuditJob).filter_by(
        id=job_id,
        organization_id=user.organization_id
    ).first()
    
    if not job:
        raise HTTPException(status_code=404, detail="Audit job not found")
        
    return job


@router.get("/report", response_model=schemas.DataQualityReport)
async def get_current_quality_report(
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get summarized quality metrics based on the latest completed audit."""
    user = _get_user(db, current_user_id)
    
    latest_job = db.query(models.DataQualityAuditJob).filter_by(
        organization_id=user.organization_id,
        status="completed"
    ).order_by(models.DataQualityAuditJob.completed_at.desc()).first()
    
    if not latest_job:
        # Fallback to simple scan if no audit job has run
        return await _get_simple_report(db, user.organization_id)
        
    return schemas.DataQualityReport(
        uniqueness_score=latest_job.uniqueness_score,
        quality_score=latest_job.quality_score,
        balance_score=latest_job.balance_score,
        overall_health_score=latest_job.overall_health_score,
        duplicate_count=latest_job.duplicate_count,
        low_quality_count=latest_job.low_quality_count,
        total_issues=latest_job.duplicate_count + latest_job.low_quality_count,
        last_audited_at=latest_job.completed_at
    )


async def _get_simple_report(db: Session, org_id: str) -> schemas.DataQualityReport:
    """Fallback simple report when no deep audit has run."""
    # This maintains backward compatibility with the previous simpler logic
    faces = db.query(models.FaceData).join(models.Visitor).filter(
        models.Visitor.organization_id == org_id
    ).count()
    
    return schemas.DataQualityReport(
        uniqueness_score=100.0,
        quality_score=100.0,
        balance_score=100.0,
        overall_health_score=100.0,
        duplicate_count=0,
        low_quality_count=0,
        total_issues=0,
        last_audited_at=None
    )


@router.get("/trends", response_model=List[schemas.QualityTrendItem])
async def get_quality_trends(
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get data quality trends over the past few months."""
    user = _get_user(db, current_user_id)
    trends = db.query(models.QualityTrendAnalysis).filter_by(
        organization_id=user.organization_id
    ).order_by(models.QualityTrendAnalysis.month_year.desc()).limit(12).all()
    
    return trends
