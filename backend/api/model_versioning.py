"""
Model Versioning & A/B Testing API

Endpoints for managing model versions, promotion, rollback,
and A/B testing experiments.
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import Optional, List
from pydantic import BaseModel
from datetime import datetime
from uuid import UUID

from db.base import get_db
from core.security import get_current_user
from services import user_service
from services import model_versioning_service as mvs
from models import models

router = APIRouter(prefix="/model-versions", tags=["Model Versioning & A/B Testing"])


def _get_user(db: Session, user_id: str) -> models.User:
    user = user_service.get_user_by_id(db, user_id)
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    return user


# ── Schemas ─────────────────────────────────────────────────────────────

class RegisterModelRequest(BaseModel):
    name: str
    version: str
    model_type: str  # face_recognition, person_detection, liveness
    file_path: str
    metrics: dict = {}

class ModelVersionResponse(BaseModel):
    id: str
    name: str
    version: str
    model_type: str
    file_path: str
    accuracy: Optional[float] = None
    precision: Optional[float] = None
    recall: Optional[float] = None
    f1_score: Optional[float] = None
    is_active: bool
    is_production: bool
    created_at: Optional[datetime] = None

class CreateExperimentRequest(BaseModel):
    name: str
    description: str = ""
    model_a_id: str
    model_b_id: str
    traffic_split_percent: int = 50

class RecordResultRequest(BaseModel):
    model_version_id: str
    visitor_log_id: str
    predicted_correctly: bool
    confidence: float
    latency_ms: float


# ── Model Version Endpoints ─────────────────────────────────────────────

@router.post("", response_model=ModelVersionResponse)
def register_model(
    request: RegisterModelRequest,
    db: Session = Depends(get_db),
    current_user_id: str = Depends(get_current_user),
):
    """Register a new model version."""
    user = _get_user(db, current_user_id)
    model = mvs.register_model(
        db, str(user.organization_id),
        request.name, request.version, request.model_type,
        request.file_path, request.metrics,
    )
    return _model_to_response(model)


@router.get("", response_model=List[ModelVersionResponse])
def list_model_versions(
    model_type: Optional[str] = None,
    limit: int = Query(50, le=200),
    db: Session = Depends(get_db),
    current_user_id: str = Depends(get_current_user),
):
    """List model versions."""
    user = _get_user(db, current_user_id)
    versions = mvs.list_versions(db, str(user.organization_id), model_type, limit)
    return [_model_to_response(v) for v in versions]


@router.get("/ab-tests")
def list_ab_tests(
    db: Session = Depends(get_db),
    current_user_id: str = Depends(get_current_user),
):
    """List A/B test experiments."""
    user = _get_user(db, current_user_id)
    from models.models import ABTestExperiment
    experiments = db.query(ABTestExperiment).filter(
        ABTestExperiment.organization_id == user.organization_id
    ).order_by(ABTestExperiment.created_at.desc()).limit(10000).all()
    return [
        {"id": str(e.id), "name": e.name, "status": e.status,
         "traffic_split": e.traffic_split_percent, "created_at": e.created_at}
        for e in experiments
    ]


@router.get("/{version_id}", response_model=ModelVersionResponse)
def get_model_version(
    version_id: UUID,
    db: Session = Depends(get_db),
    current_user_id: str = Depends(get_current_user),
):
    """Get a specific model version."""
    user = _get_user(db, current_user_id)
    from models.models import ModelVersion
    model = db.query(ModelVersion).filter(
        ModelVersion.id == version_id,
        ModelVersion.organization_id == user.organization_id,
    ).first()
    if not model:
        raise HTTPException(status_code=404, detail="Model version not found")
    return _model_to_response(model)


@router.post("/{version_id}/promote")
def promote_model(
    version_id: UUID,
    db: Session = Depends(get_db),
    current_user_id: str = Depends(get_current_user),
):
    """Promote a model version to production."""
    user = _get_user(db, current_user_id)
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin only")
    model = mvs.promote_to_production(db, str(user.organization_id), str(version_id))
    return {"message": f"Model {model.name} v{model.version} promoted to production", "model": _model_to_response(model)}


@router.post("/{version_id}/rollback")
def rollback_model(
    version_id: UUID,
    db: Session = Depends(get_db),
    current_user_id: str = Depends(get_current_user),
):
    """Rollback to a specific model version."""
    user = _get_user(db, current_user_id)
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin only")
    model = mvs.rollback_model(db, str(user.organization_id), str(version_id))
    return {"message": f"Rolled back to {model.name} v{model.version}", "model": _model_to_response(model)}


@router.get("/compare/{version_a_id}/{version_b_id}")
def compare_models(
    version_a_id: str,
    version_b_id: str,
    db: Session = Depends(get_db),
    current_user_id: str = Depends(get_current_user),
):
    """Compare metrics between two model versions."""
    user = _get_user(db, current_user_id)
    return mvs.compare_versions(db, str(user.organization_id), version_a_id, version_b_id)


# ── A/B Test Endpoints ──────────────────────────────────────────────────

@router.post("/ab-tests")
def create_ab_test(
    request: CreateExperimentRequest,
    db: Session = Depends(get_db),
    current_user_id: str = Depends(get_current_user),
):
    """Create a new A/B test experiment."""
    user = _get_user(db, current_user_id)
    exp = mvs.create_experiment(
        db, str(user.organization_id),
        request.name, request.description,
        request.model_a_id, request.model_b_id,
        request.traffic_split_percent,
    )
    return {"id": str(exp.id), "name": exp.name, "status": exp.status}


@router.post("/ab-tests/{experiment_id}/start")
def start_ab_test(
    experiment_id: str,
    db: Session = Depends(get_db),
    current_user_id: str = Depends(get_current_user),
):
    """Start an A/B test experiment."""
    exp = mvs.start_experiment(db, experiment_id)
    return {"id": str(exp.id), "status": exp.status}


@router.post("/ab-tests/{experiment_id}/record")
def record_ab_result(
    experiment_id: str,
    request: RecordResultRequest,
    db: Session = Depends(get_db),
    current_user_id: str = Depends(get_current_user),
):
    """Record an A/B test result."""
    result = mvs.record_ab_result(
        db, experiment_id, request.model_version_id,
        request.visitor_log_id, request.predicted_correctly,
        request.confidence, request.latency_ms,
    )
    return {"id": str(result.id), "recorded": True}


@router.get("/ab-tests/{experiment_id}/results")
def get_ab_results(
    experiment_id: str,
    db: Session = Depends(get_db),
    current_user_id: str = Depends(get_current_user),
):
    """Get A/B test results with statistical analysis."""
    return mvs.get_experiment_results(db, experiment_id)


@router.post("/ab-tests/{experiment_id}/conclude")
def conclude_ab_test(
    experiment_id: str,
    db: Session = Depends(get_db),
    current_user_id: str = Depends(get_current_user),
):
    """Conclude an experiment and determine the winner."""
    user = _get_user(db, current_user_id)
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin only")
    return mvs.conclude_experiment(db, experiment_id)


# ── AdaFace endpoints ─────────────────────────────────────────────────────


@router.get("/adaface/status")
def adaface_status(current_user_id: str = Depends(get_current_user)):
    """Get AdaFace model status and configuration."""
    try:
        import sys, os
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "ai_services"))
        from adaface_service import adaface_service
        adaface_service.load_model()
        return adaface_service.get_status()
    except ImportError:
        return {
            "model": "AdaFace",
            "available": False,
            "note": "adaface_service module not found",
        }


@router.post("/adaface/benchmark")
def adaface_benchmark(
    num_test_images: int = Query(10, ge=1, le=100),
    current_user_id: str = Depends(get_current_user),
):
    """Run AdaFace benchmark with synthetic test images."""
    import numpy as np
    try:
        import sys, os
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "ai_services"))
        from adaface_service import adaface_service
        adaface_service.load_model()

        test_images = [
            np.random.randint(0, 255, (160, 160, 3), dtype=np.uint8)
            for _ in range(num_test_images)
        ]
        return adaface_service.benchmark(test_images)
    except ImportError:
        return {"error": "adaface_service not available"}


def _model_to_response(model) -> ModelVersionResponse:
    return ModelVersionResponse(
        id=str(model.id),
        name=model.name,
        version=model.version,
        model_type=model.model_type,
        file_path=model.file_path,
        accuracy=model.accuracy,
        precision=model.precision,
        recall=model.recall,
        f1_score=model.f1_score,
        is_active=model.is_active,
        is_production=model.is_production,
        created_at=model.created_at,
    )
