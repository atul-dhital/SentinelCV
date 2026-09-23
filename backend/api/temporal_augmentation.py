from datetime import datetime, timezone
"""S21: Temporal Augmentation — expression recognition and face sequence generation (US-FUT-021)."""

from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy.orm import Session
from db.base import get_db
from models import models
from schemas import schemas
from services import user_service, temporal_augmentation_service, video_queue_service
from core.security import get_current_user
from typing import List, Optional
import uuid

router = APIRouter(prefix="/temporal-augmentation", tags=["Temporal Augmentation"])


def _get_user(db: Session, user_id: str) -> models.User:
    user = user_service.get_user_by_id(db, user_id)
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    return user


@router.get("/config", response_model=schemas.TemporalAugmentationConfig)
async def get_temporal_config(
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Retrieve the temporal face augmentation configuration."""
    user = _get_user(db, current_user_id)
    config = db.query(models.TemporalAugmentationConfig).filter_by(
        organization_id=user.organization_id
    ).first()
    
    if not config:
        config = models.TemporalAugmentationConfig(organization_id=user.organization_id)
        db.add(config)
        db.commit()
        db.refresh(config)
        
    return config


@router.post("/config", response_model=schemas.TemporalAugmentationConfig)
async def update_temporal_config(
    config_update: schemas.TemporalAugmentationConfigUpdate,
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Update temporal face augmentation configuration."""
    user = _get_user(db, current_user_id)
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Only admins can update temporal config")
        
    config = db.query(models.TemporalAugmentationConfig).filter_by(
        organization_id=user.organization_id
    ).first()
    
    if not config:
        config = models.TemporalAugmentationConfig(organization_id=user.organization_id)
        db.add(config)
        
    for key, value in config_update.model_dump(exclude_unset=True).items():
        setattr(config, key, value)
        
    db.commit()
    db.refresh(config)
    return config


@router.post("/augment", response_model=schemas.AugmentationJob)
async def start_augmentation(
    input_video_path: str,
    background_tasks: BackgroundTasks,
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Start a new temporal face augmentation job (US-FUT-021)."""
    user = _get_user(db, current_user_id)
    
    config = db.query(models.TemporalAugmentationConfig).filter_by(
        organization_id=user.organization_id
    ).first()
    
    if not config:
        config = models.TemporalAugmentationConfig(organization_id=user.organization_id)
        db.add(config)
        db.commit()
    
    # Create job record
    job = models.AugmentationJob(
        id=str(uuid.uuid4()),
        organization_id=user.organization_id,
        config_id=config.id,
        input_video_path=input_video_path,
        status="pending"
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    queue_status = video_queue_service.get_job_queue_status("temporal")
    if queue_status.get("mode") == "redis":
        enqueued, _enqueue_message = video_queue_service.enqueue_temporal_job(
            str(user.organization_id),
            str(job.id),
            str(config.id),
            input_video_path,
        )
        if enqueued:
            return job

    service = temporal_augmentation_service.TemporalAugmentationService()
    background_tasks.add_task(service.run_augmentation_job, job.id)

    return job


@router.get("/metrics", response_model=List[schemas.ExpressionMetrics])
async def list_expression_metrics(
    job_id: Optional[str] = None,
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List aggregate expression metrics for temporal augmentation jobs."""
    user = _get_user(db, current_user_id)
    query = db.query(models.ExpressionMetrics).filter_by(
        organization_id=user.organization_id
    )
    if job_id:
        query = query.filter_by(job_id=job_id)
    return query.order_by(models.ExpressionMetrics.measurement_timestamp.desc()).limit(10000).all()


@router.post("/jobs/{job_id}/cancel", response_model=schemas.AugmentationJob)
async def cancel_augmentation_job(
    job_id: str,
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Cancel a running or pending temporal augmentation job."""
    user = _get_user(db, current_user_id)
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Only admins can cancel augmentation jobs")

    job = db.query(models.AugmentationJob).filter_by(
        id=job_id,
        organization_id=user.organization_id,
    ).first()
    if not job:
        raise HTTPException(status_code=404, detail="Augmentation job not found")
    if job.status in {"completed", "failed", "cancelled"}:
        return job

    job.status = "cancelled"
    job.completed_at = datetime.now(timezone.utc)
    if job.started_at:
        started_at = job.started_at
        if started_at.tzinfo is None:
            started_at = started_at.replace(tzinfo=timezone.utc)
        job.duration_seconds = (job.completed_at - started_at).total_seconds()
    db.commit()
    db.refresh(job)
    return job


@router.get("/jobs/{job_id}", response_model=schemas.AugmentationJob)
async def get_job_status(
    job_id: str,
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get the status and progress of a temporal augmentation job."""
    user = _get_user(db, current_user_id)
    job = db.query(models.AugmentationJob).filter_by(
        id=job_id,
        organization_id=user.organization_id
    ).first()
    
    if not job:
        raise HTTPException(status_code=404, detail="Augmentation job not found")
        
    return job


@router.get("/sequences", response_model=List[schemas.GeneratedSequence])
async def list_generated_sequences(
    job_id: Optional[str] = None,
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List generated facial expression sequences."""
    user = _get_user(db, current_user_id)
    query = db.query(models.GeneratedSequence).filter_by(
        organization_id=user.organization_id
    )
    if job_id:
        query = query.filter_by(job_id=job_id)
    
    return query.limit(10000).all()
