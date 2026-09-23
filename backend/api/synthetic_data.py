from datetime import datetime, timezone
"""S17b: Synthetic Data Generation API (US-FUT-019)."""

from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy.orm import Session
from db.base import get_db
from models import models
from schemas import schemas
from services import user_service, video_queue_service
from services.synthetic_data_service import SyntheticDataService
from core.security import get_current_user
from typing import List, Optional
import uuid

router = APIRouter(prefix="/synthetic-data", tags=["Synthetic Data"])


def _get_user(db: Session, user_id: str) -> models.User:
    user = user_service.get_user_by_id(db, user_id)
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    return user


@router.get("/config", response_model=schemas.SyntheticDataConfig)
async def get_synthetic_config(
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Retrieve the synthetic data generation configuration."""
    user = _get_user(db, current_user_id)
    config = db.query(models.SyntheticDataConfig).filter_by(
        organization_id=user.organization_id
    ).first()
    
    if not config:
        config = models.SyntheticDataConfig(organization_id=user.organization_id)
        db.add(config)
        db.commit()
        db.refresh(config)
        
    return config


@router.post("/config", response_model=schemas.SyntheticDataConfig)
async def update_synthetic_config(
    config_update: schemas.SyntheticDataConfigUpdate,
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Update synthetic data generation configuration."""
    user = _get_user(db, current_user_id)
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Only admins can update synthetic config")
        
    config = db.query(models.SyntheticDataConfig).filter_by(
        organization_id=user.organization_id
    ).first()
    
    if not config:
        config = models.SyntheticDataConfig(organization_id=user.organization_id)
        db.add(config)
        
    for key, value in config_update.model_dump(exclude_unset=True).items():
        setattr(config, key, value)
        
    db.commit()
    db.refresh(config)
    return config


@router.post("/generate", response_model=schemas.SynthesisJob)
async def start_synthesis(
    total_samples: int,
    background_tasks: BackgroundTasks,
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Start a new GAN-based synthetic data generation job (US-FUT-019)."""
    user = _get_user(db, current_user_id)
    
    config = db.query(models.SyntheticDataConfig).filter_by(
        organization_id=user.organization_id
    ).first()
    
    if not config:
        config = models.SyntheticDataConfig(organization_id=user.organization_id)
        db.add(config)
        db.commit()
    
    # Create job record
    job = models.SynthesisJob(
        id=str(uuid.uuid4()),
        organization_id=user.organization_id,
        config_id=config.id,
        total_target=total_samples,
        status="pending"
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    queue_status = video_queue_service.get_job_queue_status("synthetic")
    if queue_status.get("mode") == "redis":
        enqueued, _enqueue_message = video_queue_service.enqueue_synthetic_job(
            str(user.organization_id),
            str(job.id),
            str(config.id),
            int(total_samples),
        )
        if enqueued:
            return job

    service = SyntheticDataService()
    background_tasks.add_task(service.run_synthesis_job, job.id)

    return job


@router.get("/metrics", response_model=List[schemas.QualityMetricsSynthetic])
async def list_quality_metrics(
    job_id: Optional[str] = None,
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List aggregate quality metrics for synthetic generation jobs."""
    user = _get_user(db, current_user_id)
    query = db.query(models.QualityMetricsSynthetic).filter_by(
        organization_id=user.organization_id
    )
    if job_id:
        query = query.filter_by(job_id=job_id)
    return query.order_by(models.QualityMetricsSynthetic.measurement_timestamp.desc()).limit(10000).all()


@router.post("/jobs/{job_id}/cancel", response_model=schemas.SynthesisJob)
async def cancel_synthesis_job(
    job_id: str,
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Cancel a running or pending synthesis job."""
    user = _get_user(db, current_user_id)
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Only admins can cancel synthesis jobs")

    job = db.query(models.SynthesisJob).filter_by(
        id=job_id,
        organization_id=user.organization_id,
    ).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.status in {"completed", "failed", "cancelled"}:
        return job

    job.status = "cancelled"
    job.completed_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(job)
    return job


@router.get("/jobs/{job_id}", response_model=schemas.SynthesisJob)
async def get_job_status(
    job_id: str,
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get status and progress of a synthesis job."""
    user = _get_user(db, current_user_id)
    job = db.query(models.SynthesisJob).filter_by(
        id=job_id,
        organization_id=user.organization_id
    ).first()
    
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
        
    return job


@router.get("/images", response_model=List[schemas.GeneratedImage])
async def list_generated_images(
    job_id: Optional[str] = None,
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List generated synthetic images."""
    user = _get_user(db, current_user_id)
    query = db.query(models.GeneratedImage).filter_by(
        organization_id=user.organization_id
    )
    if job_id:
        query = query.filter_by(job_id=job_id)
    
    return query.limit(10000).all()
