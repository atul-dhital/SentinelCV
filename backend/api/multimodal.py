"""Multimodal learning API (US-FUT-001)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from core.security import get_current_user
from db.base import get_db
from models import models
from services import user_service
from services.multimodal_service import multimodal_service

router = APIRouter(prefix="/multimodal", tags=["Multimodal Learning"])


def _get_user(db: Session, user_id: str) -> models.User:
    user = user_service.get_user_by_id(db, user_id)
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    return user


def _raise_from_value_error(exc: ValueError) -> None:
    detail = str(exc)
    status_code = 404 if "not found" in detail.lower() else 400
    raise HTTPException(status_code=status_code, detail=detail)


class FusionConfigRequest(BaseModel):
    face_weight: float = Field(0.6, ge=0.0)
    audio_weight: float = Field(0.2, ge=0.0)
    text_weight: float = Field(0.1, ge=0.0)
    sensor_weight: float = Field(0.1, ge=0.0)
    fusion_strategy: str = Field("weighted_mean", max_length=50)
    fusion_threshold: float = Field(0.7, ge=0.0, le=1.0)
    require_face: bool = True
    require_audio: bool = False
    require_text: bool = False


class FusionConfigResponse(BaseModel):
    id: UUID
    organization_id: UUID
    face_weight: float
    audio_weight: float
    text_weight: float
    sensor_weight: float
    fusion_strategy: str
    fusion_threshold: float
    require_face: bool
    require_audio: bool
    require_text: bool
    created_at: datetime
    updated_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class MultimodalEmbeddingCreateRequest(BaseModel):
    visitor_id: UUID
    detection_log_id: Optional[UUID] = None
    face_embedding: Optional[List[float]] = None
    audio_embedding: Optional[List[float]] = None
    text_embedding: Optional[List[float]] = None
    sensor_data: Optional[Dict[str, Any]] = None
    embedding_model_version: str = "1.0"
    face_confidence: Optional[float] = Field(None, ge=0.0, le=1.0)
    audio_confidence: Optional[float] = Field(None, ge=0.0, le=1.0)
    text_confidence: Optional[float] = Field(None, ge=0.0, le=1.0)
    sensor_confidence: Optional[float] = Field(None, ge=0.0, le=1.0)


class MultimodalEmbeddingResponse(BaseModel):
    id: UUID
    visitor_id: UUID
    detection_log_id: Optional[UUID] = None
    fusion_score: float
    audio_present: bool
    text_present: bool
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class AutoMultimodalEmbeddingRequest(BaseModel):
    visitor_id: UUID
    detection_log_id: Optional[UUID] = None
    sensor_data: Optional[Dict[str, Any]] = None
    embedding_model_version: str = "auto-fused-v1"


class VisitorMultimodalProfileResponse(BaseModel):
    visitor_id: UUID
    visitor_name: Optional[str] = None
    latest_embedding_id: Optional[UUID] = None
    fusion_score: float = 0.0
    modalities_present: Dict[str, bool]
    modality_counts: Dict[str, int]
    latest_modalities: Dict[str, Optional[float]]
    derived_modalities: List[str] = Field(default_factory=list)


class AudioFeatureCreateRequest(BaseModel):
    visitor_id: UUID
    detection_log_id: Optional[UUID] = None
    mfcc_features: Optional[List[float]] = None
    spectral_energy: Optional[float] = None
    zero_crossing_rate: Optional[float] = None
    voice_confidence: float = Field(0.0, ge=0.0, le=1.0)
    pitch_frequency: Optional[float] = None
    audio_duration_ms: Optional[int] = None


class AudioFeatureResponse(BaseModel):
    id: UUID
    visitor_id: UUID
    detection_log_id: Optional[UUID] = None
    voice_confidence: float
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class TextBioFeatureCreateRequest(BaseModel):
    visitor_id: UUID
    name: Optional[str] = None
    department: Optional[str] = None
    position: Optional[str] = None
    phone_number: Optional[str] = None
    email: Optional[str] = None
    notes: Optional[str] = None
    text_embedding: Optional[List[float]] = None
    embedding_confidence: float = Field(0.0, ge=0.0, le=1.0)


class TextBioFeatureResponse(BaseModel):
    id: UUID
    visitor_id: UUID
    embedding_confidence: float
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class CompareEmbeddingsRequest(BaseModel):
    embedding_a_id: UUID
    embedding_b_id: UUID
    config_id: Optional[UUID] = None


class CompareEmbeddingsResponse(BaseModel):
    overall_similarity: float
    modalities: Dict[str, float]
    weights: Dict[str, float]
    fusion_strategy: str


class MultimodalInferenceRequest(BaseModel):
    face_embedding: Optional[List[float]] = None
    audio_embedding: Optional[List[float]] = None
    text_embedding: Optional[List[float]] = None
    text_hint: Optional[str] = None
    sensor_data: Optional[Dict[str, Any]] = None
    candidate_visitor_ids: Optional[List[UUID]] = None
    top_k: int = Field(5, ge=1, le=50)


class MultimodalInferenceCandidate(BaseModel):
    visitor_id: UUID
    visitor_name: Optional[str] = None
    score: float
    modality_coverage: float
    meets_threshold: bool
    modalities: Dict[str, float]
    source: str


class MultimodalInferenceResponse(BaseModel):
    match_found: bool
    threshold: float
    fusion_strategy: str
    query_modalities: List[str]
    top_candidate: Optional[MultimodalInferenceCandidate] = None
    candidates: List[MultimodalInferenceCandidate] = Field(default_factory=list)


@router.post(
    "/fusion-config",
    response_model=FusionConfigResponse,
    status_code=status.HTTP_201_CREATED,
)
def upsert_fusion_config(
    request: FusionConfigRequest,
    db: Session = Depends(get_db),
    current_user_id: str = Depends(get_current_user),
):
    """Create or update the multimodal fusion configuration."""
    user = _get_user(db, current_user_id)
    try:
        config = multimodal_service.upsert_fusion_config(
            db=db,
            organization_id=user.organization_id,
            face_weight=request.face_weight,
            audio_weight=request.audio_weight,
            text_weight=request.text_weight,
            sensor_weight=request.sensor_weight,
            fusion_strategy=request.fusion_strategy,
            fusion_threshold=request.fusion_threshold,
            require_face=request.require_face,
            require_audio=request.require_audio,
            require_text=request.require_text,
        )
    except ValueError as exc:
        _raise_from_value_error(exc)
    return config


@router.get("/fusion-config", response_model=FusionConfigResponse)
def get_fusion_config(
    db: Session = Depends(get_db),
    current_user_id: str = Depends(get_current_user),
):
    """Fetch the latest fusion configuration."""
    user = _get_user(db, current_user_id)
    config = multimodal_service.ensure_fusion_config(db, user.organization_id)
    return config


@router.post(
    "/embeddings",
    response_model=MultimodalEmbeddingResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_multimodal_embedding(
    request: MultimodalEmbeddingCreateRequest,
    db: Session = Depends(get_db),
    current_user_id: str = Depends(get_current_user),
):
    """Store a multimodal embedding for a visitor."""
    user = _get_user(db, current_user_id)
    try:
        record = multimodal_service.create_multimodal_embedding(
            db=db,
            organization_id=user.organization_id,
            visitor_id=request.visitor_id,
            detection_log_id=request.detection_log_id,
            face_embedding=request.face_embedding,
            audio_embedding=request.audio_embedding,
            text_embedding=request.text_embedding,
            sensor_data=request.sensor_data,
            embedding_model_version=request.embedding_model_version,
            face_confidence=request.face_confidence,
            audio_confidence=request.audio_confidence,
            text_confidence=request.text_confidence,
            sensor_confidence=request.sensor_confidence,
        )
    except ValueError as exc:
        _raise_from_value_error(exc)
    return record


@router.get("/embeddings/{embedding_id}", response_model=MultimodalEmbeddingResponse)
def get_multimodal_embedding(
    embedding_id: UUID,
    db: Session = Depends(get_db),
    current_user_id: str = Depends(get_current_user),
):
    """Fetch a multimodal embedding by ID."""
    user = _get_user(db, current_user_id)
    record = multimodal_service.get_multimodal_embedding(
        db, user.organization_id, embedding_id
    )
    if record is None:
        raise HTTPException(status_code=404, detail="Multimodal embedding not found")
    return record


@router.post(
    "/embeddings/auto",
    response_model=MultimodalEmbeddingResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_auto_multimodal_embedding(
    request: AutoMultimodalEmbeddingRequest,
    db: Session = Depends(get_db),
    current_user_id: str = Depends(get_current_user),
):
    """Build a multimodal embedding from the latest visitor face/audio/text records."""
    user = _get_user(db, current_user_id)
    try:
        record = multimodal_service.build_visitor_multimodal_embedding(
            db=db,
            organization_id=user.organization_id,
            visitor_id=request.visitor_id,
            detection_log_id=request.detection_log_id,
            sensor_data=request.sensor_data,
            embedding_model_version=request.embedding_model_version,
        )
    except ValueError as exc:
        _raise_from_value_error(exc)
    return record


@router.get(
    "/visitors/{visitor_id}/profile",
    response_model=VisitorMultimodalProfileResponse,
)
def get_visitor_multimodal_profile(
    visitor_id: UUID,
    db: Session = Depends(get_db),
    current_user_id: str = Depends(get_current_user),
):
    """Return the latest multimodal profile summary for a visitor."""
    user = _get_user(db, current_user_id)
    try:
        profile = multimodal_service.get_visitor_multimodal_profile(
            db=db,
            organization_id=user.organization_id,
            visitor_id=visitor_id,
        )
    except ValueError as exc:
        _raise_from_value_error(exc)
    return profile


@router.post("/compare", response_model=CompareEmbeddingsResponse)
def compare_embeddings(
    request: CompareEmbeddingsRequest,
    db: Session = Depends(get_db),
    current_user_id: str = Depends(get_current_user),
):
    """Compare two multimodal embeddings."""
    user = _get_user(db, current_user_id)
    try:
        result = multimodal_service.compare_embeddings(
            db=db,
            organization_id=user.organization_id,
            embedding_a_id=request.embedding_a_id,
            embedding_b_id=request.embedding_b_id,
            config_id=request.config_id,
        )
    except ValueError as exc:
        _raise_from_value_error(exc)
    return result


@router.post("/infer", response_model=MultimodalInferenceResponse)
def infer_multimodal_identity(
    request: MultimodalInferenceRequest,
    db: Session = Depends(get_db),
    current_user_id: str = Depends(get_current_user),
):
    """Infer likely identity candidates using multimodal fusion scoring."""
    user = _get_user(db, current_user_id)
    try:
        result = multimodal_service.infer_identity(
            db=db,
            organization_id=user.organization_id,
            face_embedding=request.face_embedding,
            audio_embedding=request.audio_embedding,
            text_embedding=request.text_embedding,
            text_hint=request.text_hint,
            sensor_data=request.sensor_data,
            candidate_visitor_ids=request.candidate_visitor_ids,
            top_k=request.top_k,
        )
    except ValueError as exc:
        _raise_from_value_error(exc)
    return result


@router.post(
    "/audio-features",
    response_model=AudioFeatureResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_audio_features(
    request: AudioFeatureCreateRequest,
    db: Session = Depends(get_db),
    current_user_id: str = Depends(get_current_user),
):
    """Store audio feature metadata for a visitor."""
    user = _get_user(db, current_user_id)
    try:
        record = multimodal_service.create_audio_features(
            db=db,
            organization_id=user.organization_id,
            visitor_id=request.visitor_id,
            detection_log_id=request.detection_log_id,
            mfcc_features=request.mfcc_features,
            spectral_energy=request.spectral_energy,
            zero_crossing_rate=request.zero_crossing_rate,
            voice_confidence=request.voice_confidence,
            pitch_frequency=request.pitch_frequency,
            audio_duration_ms=request.audio_duration_ms,
        )
    except ValueError as exc:
        _raise_from_value_error(exc)
    return record


@router.post(
    "/text-bio",
    response_model=TextBioFeatureResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_text_bio_features(
    request: TextBioFeatureCreateRequest,
    db: Session = Depends(get_db),
    current_user_id: str = Depends(get_current_user),
):
    """Store text/bio-derived embeddings for a visitor."""
    user = _get_user(db, current_user_id)
    try:
        record = multimodal_service.create_text_bio_features(
            db=db,
            organization_id=user.organization_id,
            visitor_id=request.visitor_id,
            name=request.name,
            department=request.department,
            position=request.position,
            phone_number=request.phone_number,
            email=request.email,
            notes=request.notes,
            text_embedding=request.text_embedding,
            embedding_confidence=request.embedding_confidence,
        )
    except ValueError as exc:
        _raise_from_value_error(exc)
    return record
