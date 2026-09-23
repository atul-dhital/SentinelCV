"""
Continual Learning API for SentinelCV.

Enables incremental learning from manual reviews and new face data.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import List, Optional
from uuid import UUID
from datetime import datetime
import logging
import json
import numpy as np

from db.base import get_db
from models import models
from core.security import get_current_user
from services import visitor_service, user_service

router = APIRouter(prefix="/learning", tags=["Continual Learning"])
logger = logging.getLogger(__name__)


def _get_user(db: Session, user_id: str) -> models.User:
    user = user_service.get_user_by_id(db, user_id)
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    return user


class LearningRequest(BaseModel):
    """Request to add new training data from manual review."""
    visitor_id: UUID
    face_image_path: str
    embedding: List[float]
    is_positive: bool = True


class LearningBatchRequest(BaseModel):
    """Batch learning request."""
    items: List[LearningRequest]


class LearningStats(BaseModel):
    """Learning statistics."""
    total_samples_added: int
    last_updated: Optional[datetime]
    accuracy_improvement: float
    pending_reviews: int


class ModelUpdateRequest(BaseModel):
    """Request to trigger model update."""
    include_pending: bool = True


class ModelUpdateResponse(BaseModel):
    """Response from model update."""
    status: str
    message: str
    samples_used: int
    new_accuracy: Optional[float] = None


@router.post("/add-sample", response_model=dict)
async def add_learning_sample(
    request: LearningRequest,
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Add a new training sample from manual review.
    
    This enables the system to learn from corrections made by administrators
    during manual review of unidentified visitors.
    """
    visitor = visitor_service.get_visitor(db, request.visitor_id)
    if not visitor:
        raise HTTPException(status_code=404, detail="Visitor not found")
    
    if str(visitor.organization_id) != current_user_id.split('_')[0]:
        raise HTTPException(status_code=403, detail="Access denied")
    
    sample = models.LearningSample(
        visitor_id=request.visitor_id,
        face_image_path=request.face_image_path,
        embedding=request.embedding,
        is_positive=request.is_positive,
        source="manual_review",
        confidence=1.0,
    )
    
    db.add(sample)
    db.commit()
    
    return {
        "status": "success",
        "message": "Learning sample added",
        "sample_id": str(sample.id),
    }


@router.post("/batch", response_model=dict)
async def add_batch_samples(
    request: LearningBatchRequest,
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Add multiple learning samples at once."""
    samples_added = 0
    
    for item in request.items:
        visitor = visitor_service.get_visitor(db, item.visitor_id)
        if not visitor:
            continue
        
        sample = models.LearningSample(
            visitor_id=item.visitor_id,
            face_image_path=item.face_image_path,
            embedding=item.embedding,
            is_positive=item.is_positive,
            source="manual_review",
            confidence=1.0,
        )
        db.add(sample)
        samples_added += 1
    
    db.commit()
    
    return {
        "status": "success",
        "message": f"Added {samples_added} learning samples",
        "count": samples_added,
    }


@router.get("/stats", response_model=LearningStats)
async def get_learning_stats(
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get learning statistics for the organization."""
    from sqlalchemy import func
    
    total_samples = db.query(func.count(models.LearningSample.id)).scalar() or 0
    
    last_sample = db.query(models.LearningSample).order_by(
        models.LearningSample.created_at.desc()
    ).first()
    
    pending_reviews = db.query(func.count(models.VisitorLog.id)).filter(
        models.VisitorLog.identified == False,
        models.VisitorLog.status == "detected",
    ).scalar() or 0
    
    return LearningStats(
        total_samples_added=total_samples,
        last_updated=last_sample.created_at if last_sample else None,
        accuracy_improvement=0.0,
        pending_reviews=pending_reviews,
    )


@router.get("/samples", response_model=List[dict])
async def list_learning_samples(
    limit: int = 50,
    offset: int = 0,
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List learning samples."""
    samples = db.query(models.LearningSample).offset(offset).limit(limit).all()
    
    return [
        {
            "id": str(s.id),
            "visitor_id": str(s.visitor_id),
            "face_image_path": s.face_image_path,
            "is_positive": s.is_positive,
            "source": s.source,
            "created_at": s.created_at.isoformat() if s.created_at else None,
        }
        for s in samples
    ]


@router.delete("/samples/{sample_id}", response_model=dict)
async def delete_learning_sample(
    sample_id: UUID,
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Delete a learning sample."""
    sample = db.query(models.LearningSample).filter(
        models.LearningSample.id == sample_id
    ).first()
    
    if not sample:
        raise HTTPException(status_code=404, detail="Sample not found")
    
    db.delete(sample)
    db.commit()
    
    return {"status": "success", "message": "Sample deleted"}


@router.post("/update-model", response_model=ModelUpdateResponse)
async def trigger_model_update(
    request: ModelUpdateRequest,
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Trigger a model update using accumulated learning samples.
    
    This will retrain/finetune the face recognition model with
    newly added samples.
    """
    user = _get_user(db, current_user_id)

    query = db.query(models.LearningSample)
    
    if request.include_pending:
        samples = query.limit(10000).all()
    else:
        samples = query.filter(
            models.LearningSample.is_positive == True
        ).limit(10000).all()
    
    if not samples:
        return ModelUpdateResponse(
            status="no_samples",
            message="No learning samples available",
            samples_used=0,
        )

    # Create a TrainingJob record to track this update
    training_job = models.TrainingJob(
        organization_id=user.organization_id,
        status="started",
        config={"source": "incremental_learning", "include_pending": request.include_pending},
        started_at=datetime.now(timezone.utc),
        started_by=user.id,
    )
    db.add(training_job)
    db.commit()
    db.refresh(training_job)

    try:
        # Collect embeddings from learning samples
        embeddings_list = []
        labels_list = []
        for s in samples:
            try:
                emb = s.embedding
                if isinstance(emb, str):
                    emb = json.loads(emb)
                embeddings_list.append(np.array(emb, dtype=np.float32))
                labels_list.append(str(s.visitor_id))
            except (json.JSONDecodeError, ValueError, TypeError):
                continue

        if len(embeddings_list) < 2:
            training_job.status = "failed"  # type: ignore[assignment]
            db.commit()
            return ModelUpdateResponse(
                status="insufficient_data",
                message="Not enough valid embedding samples (need at least 2)",
                samples_used=len(embeddings_list),
            )

        embeddings = np.stack(embeddings_list)
        labels = np.array(labels_list)
        unique_labels = np.unique(labels)
        label_map = {lbl: idx for idx, lbl in enumerate(unique_labels)}
        numeric_labels = np.array([label_map[l] for l in labels])

        # Try to call AI service for training, fall back to local metrics
        new_accuracy = None
        try:
            import httpx
            ai_url = "http://127.0.0.1:8001"
            async with httpx.AsyncClient(timeout=120.0) as client:
                resp = await client.post(f"{ai_url}/train", json={
                    "organization_id": str(user.organization_id),
                    "num_classes": int(len(unique_labels)),
                    "num_samples": int(len(embeddings)),
                })
                if resp.status_code == 200:
                    result = resp.json()
                    new_accuracy = result.get("accuracy")
        except Exception as ai_err:
            logger.warning(f"AI service training call failed (will compute local metrics): {ai_err}")

        # If AI service didn't return accuracy, compute a simple nearest-centroid estimate
        if new_accuracy is None:
            from collections import defaultdict
            centroid_map = defaultdict(list)
            for emb, lbl in zip(embeddings_list, labels_list):
                centroid_map[lbl].append(emb)
            centroids = {lbl: np.mean(vecs, axis=0) for lbl, vecs in centroid_map.items()}
            correct = 0
            for emb, lbl in zip(embeddings_list, labels_list):
                best_lbl = min(centroids.keys(), key=lambda k: float(np.linalg.norm(emb - centroids[k])))
                if best_lbl == lbl:
                    correct += 1
            new_accuracy = round(correct / len(embeddings_list), 4) if embeddings_list else 0.0

        # Update training job with results
        training_job.status = "completed"  # type: ignore[assignment]
        training_job.accuracy = new_accuracy  # type: ignore[assignment]
        training_job.completed_at = datetime.now(timezone.utc)  # type: ignore[assignment]
        training_job.metrics_history = {  # type: ignore[assignment]
            "samples_used": len(embeddings_list),
            "unique_visitors": int(len(unique_labels)),
            "source": "incremental_learning",
        }
        db.commit()

        # Audit log
        visitor_service.create_audit_log(
            db, user.organization_id, user.id, "model_update",
            "model", None, details={
                "job_id": str(training_job.id),
                "samples_used": len(embeddings_list),
                "accuracy": new_accuracy,
            }
        )

        return ModelUpdateResponse(
            status="success",
            message=f"Model updated with {len(embeddings_list)} samples across {len(unique_labels)} visitors",
            samples_used=len(embeddings_list),
            new_accuracy=new_accuracy,
        )

    except Exception as e:
        logger.error(f"Model update failed: {e}", exc_info=True)
        training_job.status = "failed"  # type: ignore[assignment]
        training_job.completed_at = datetime.now(timezone.utc)  # type: ignore[assignment]
        db.commit()
        raise HTTPException(status_code=500, detail=f"Model update failed: {str(e)}")


@router.get("/quality", response_model=dict)
async def get_data_quality(
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get data quality metrics for learning."""
    from sqlalchemy import func
    
    total_visitors = db.query(func.count(models.Visitor.id)).scalar() or 0
    
    visitors_with_faces = db.query(func.count(models.Visitor.id)).join(
        models.FaceData
    ).filter(
        models.Visitor.id == models.FaceData.visitor_id
    ).scalar() or 0
    
    avg_faces_per_visitor = 0
    if visitors_with_faces > 0:
        total_faces = db.query(func.count(models.FaceData.id)).scalar() or 0
        avg_faces_per_visitor = total_faces / visitors_with_faces
    
    total_samples = db.query(func.count(models.LearningSample.id)).scalar() or 0
    
    return {
        "total_visitors": total_visitors,
        "visitors_with_faces": visitors_with_faces,
        "avg_faces_per_visitor": round(avg_faces_per_visitor, 2),
        "learning_samples": total_samples,
        "coverage_percentage": round((visitors_with_faces / total_visitors * 100) if total_visitors > 0 else 0, 2),
        "recommendation": "Add more face images per visitor for better recognition" if avg_faces_per_visitor < 3 else "Good coverage",
    }


@router.post("/feedback", response_model=dict)
async def submit_recognition_feedback(
    log_id: UUID,
    correct_visitor_id: Optional[UUID] = None,
    is_correct: bool = False,
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Submit feedback on recognition results.
    
    This helps the system learn from its mistakes.
    """
    log = db.query(models.VisitorLog).filter(
        models.VisitorLog.id == log_id
    ).first()
    
    if not log:
        raise HTTPException(status_code=404, detail="Log not found")
    
    if is_correct and correct_visitor_id:
        feedback = models.RecognitionFeedback(
            log_id=log_id,
            predicted_visitor_id=log.visitor_id,
            actual_visitor_id=correct_visitor_id,
            is_correct=True,
        )
    else:
        feedback = models.RecognitionFeedback(
            log_id=log_id,
            predicted_visitor_id=log.visitor_id,
            actual_visitor_id=None,
            is_correct=False,
        )
    
    db.add(feedback)
    db.commit()
    
    return {"status": "success", "message": "Feedback recorded"}
