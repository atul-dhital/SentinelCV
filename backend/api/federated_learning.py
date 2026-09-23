"""
Federated Learning API (ENH-016)

Endpoints for managing federated learning rounds, submitting updates,
and aggregating models using FedAvg.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional, List

from db.base import get_db
from core.security import get_current_user
from services import user_service
from services.federated_learning_service import federated_learning_service
from models import models

router = APIRouter(prefix="/federated", tags=["Federated Learning"])


def _get_user(db: Session, user_id: str) -> models.User:
    user = user_service.get_user_by_id(db, user_id)
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    return user


def _raise_from_value_error(exc: ValueError) -> None:
    detail = str(exc)
    status_code = 404 if "not found" in detail.lower() else 400
    raise HTTPException(status_code=status_code, detail=detail)


class InitRoundRequest(BaseModel):
    model_type: str = "face_recognition"
    num_participants: int = 3
    config: Optional[dict] = None

class SubmitUpdateRequest(BaseModel):
    round_id: str
    participant_id: str
    weight_deltas: List[float]
    local_accuracy: float
    local_loss: float = 0.0
    num_samples: int = 100


@router.post("/rounds")
def initialize_round(
    request: InitRoundRequest,
    db: Session = Depends(get_db),
    current_user_id: str = Depends(get_current_user),
):
    """Initialize a new federated learning round."""
    user = _get_user(db, current_user_id)
    fl_round = federated_learning_service.initialize_round(
        db, str(user.organization_id),
        request.model_type, request.num_participants, request.config,
    )
    return {
        "round_id": str(fl_round.id),
        "round_number": fl_round.round_number,
        "status": fl_round.status,
        "config": fl_round.config,
    }


@router.get("/rounds")
def list_rounds(
    limit: int = 20,
    db: Session = Depends(get_db),
    current_user_id: str = Depends(get_current_user),
):
    """List federated learning rounds."""
    user = _get_user(db, current_user_id)
    return federated_learning_service.list_rounds(db, str(user.organization_id), limit)


@router.get("/rounds/{round_id}")
def get_round_status(
    round_id: str,
    db: Session = Depends(get_db),
    current_user_id: str = Depends(get_current_user),
):
    """Get status of a federated learning round."""
    user = _get_user(db, current_user_id)
    try:
        return federated_learning_service.get_round_status(
            db,
            str(user.organization_id),
            round_id,
        )
    except ValueError as exc:
        _raise_from_value_error(exc)


@router.post("/rounds/{round_id}/submit")
def submit_update(
    round_id: str,
    request: SubmitUpdateRequest,
    db: Session = Depends(get_db),
    current_user_id: str = Depends(get_current_user),
):
    """Submit a local training update."""
    user = _get_user(db, current_user_id)
    try:
        update = federated_learning_service.submit_local_update(
            db,
            str(user.organization_id),
            round_id,
            request.participant_id,
            request.weight_deltas,
            request.local_accuracy,
            request.local_loss,
            request.num_samples,
        )
    except ValueError as exc:
        _raise_from_value_error(exc)
    return {"update_id": str(update.id), "participant_id": update.participant_id}


@router.post("/rounds/{round_id}/aggregate")
def aggregate_round(
    round_id: str,
    db: Session = Depends(get_db),
    current_user_id: str = Depends(get_current_user),
):
    """Aggregate updates using FedAvg."""
    user = _get_user(db, current_user_id)
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin only")
    try:
        return federated_learning_service.aggregate_updates(
            db,
            str(user.organization_id),
            round_id,
        )
    except ValueError as exc:
        _raise_from_value_error(exc)


@router.get("/quantum/similarity")
def quantum_similarity(
    threshold: float = 0.6,
    db: Session = Depends(get_db),
    current_user_id: str = Depends(get_current_user),
):
    """Get quantum-inspired similarity search info and speedup estimates."""
    from services.quantum_similarity_service import quantum_similarity_service
    from models.models import FaceData

    user = _get_user(db, current_user_id)
    face_count = db.query(FaceData).join(models.Visitor).filter(
        models.Visitor.organization_id == user.organization_id
    ).count()

    return quantum_similarity_service.estimate_speedup(max(1, face_count))


@router.post("/quantum/cluster")
def quantum_cluster(
    n_clusters: int = 3,
    db: Session = Depends(get_db),
    current_user_id: str = Depends(get_current_user),
):
    """Run quantum-inspired clustering on visitor embeddings."""
    from services.quantum_similarity_service import quantum_similarity_service
    from models.models import FaceData
    import json

    user = _get_user(db, current_user_id)
    faces = db.query(FaceData).join(models.Visitor).filter(
        models.Visitor.organization_id == user.organization_id
    ).limit(500).all()

    embeddings = []
    for f in faces:
        emb = f.embedding
        if isinstance(emb, str):
            try:
                emb = json.loads(emb)
            except (json.JSONDecodeError, TypeError):
                continue
        if isinstance(emb, list) and len(emb) > 0:
            embeddings.append(emb)

    if len(embeddings) < 2:
        return {"error": "Need at least 2 embeddings for clustering"}

    return quantum_similarity_service.quantum_clustering(embeddings, n_clusters)
