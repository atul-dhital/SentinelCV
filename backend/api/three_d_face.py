"""3D face recognition API (US-FUT-033)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from core.security import get_current_user
from db.base import get_db
from models import models
from services import user_service
from services.three_d_face_service import three_d_face_service

router = APIRouter(prefix="/3d-face", tags=["3D Face Recognition"])


def _get_user(db: Session, user_id: str) -> models.User:
    user = user_service.get_user_by_id(db, user_id)
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    return user


def _raise_from_value_error(exc: ValueError) -> None:
    detail = str(exc)
    status_code = 404 if "not found" in detail.lower() else 400
    raise HTTPException(status_code=status_code, detail=detail)


class ThreeDFaceCreateRequest(BaseModel):
    visitor_id: UUID
    detection_log_id: Optional[UUID] = None
    depth_map_path: Optional[str] = None
    point_cloud_path: Optional[str] = None
    face_mesh: Optional[Dict[str, Any]] = None
    texture_map_path: Optional[str] = None
    face_width_mm: Optional[float] = None
    face_height_mm: Optional[float] = None
    face_depth_mm: Optional[float] = None
    forehead_width_mm: Optional[float] = None
    nose_height_mm: Optional[float] = None
    embedding_3d: Optional[list[float]] = None
    embedding_confidence: float = Field(0.0, ge=0.0, le=1.0)
    capture_quality_score: float = Field(0.0, ge=0.0, le=1.0)
    mesh_density: Optional[int] = None
    depth_map_resolution: Optional[str] = None


class ThreeDFaceResponse(BaseModel):
    id: UUID
    visitor_id: UUID
    detection_log_id: Optional[UUID] = None
    embedding_confidence: float
    capture_quality_score: float
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ThreeDFaceCompareRequest(BaseModel):
    face_data_1_id: UUID
    face_data_2_id: UUID
    match_threshold: float = Field(0.75, ge=0.0, le=1.0)


class ThreeDFaceCompareResponse(BaseModel):
    id: UUID
    face_data_1_id: UUID
    face_data_2_id: UUID
    euclidean_distance: Optional[float] = None
    cosine_similarity: Optional[float] = None
    l2_distance: Optional[float] = None
    shape_similarity: Optional[float] = None
    texture_similarity: Optional[float] = None
    geometric_liveness_score: Optional[float] = None
    match_confidence: float
    is_same_person: bool
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ThreeDFaceLivenessRequest(BaseModel):
    face_data_id: UUID


class ThreeDFaceLivenessResponse(BaseModel):
    face_data_id: UUID
    geometric_liveness_score: float


class ThreeDFaceIdentifyMatch(BaseModel):
    face_data_id: UUID
    visitor_id: UUID
    match_confidence: float
    cosine_similarity: Optional[float] = None
    shape_similarity: Optional[float] = None
    texture_similarity: Optional[float] = None
    geometric_liveness_score: Optional[float] = None
    is_same_person: bool


class ThreeDFaceIdentifyResponse(BaseModel):
    probe_face_data_id: UUID
    matches: list[ThreeDFaceIdentifyMatch]


@router.post(
    "/capture",
    response_model=ThreeDFaceResponse,
    status_code=status.HTTP_201_CREATED,
)
def capture_three_d_face(
    request: ThreeDFaceCreateRequest,
    db: Session = Depends(get_db),
    current_user_id: str = Depends(get_current_user),
):
    """Store a 3D face capture and optional embedding."""
    user = _get_user(db, current_user_id)
    try:
        record = three_d_face_service.create_face_data(
            db=db,
            organization_id=user.organization_id,
            visitor_id=request.visitor_id,
            detection_log_id=request.detection_log_id,
            depth_map_path=request.depth_map_path,
            point_cloud_path=request.point_cloud_path,
            face_mesh=request.face_mesh,
            texture_map_path=request.texture_map_path,
            face_width_mm=request.face_width_mm,
            face_height_mm=request.face_height_mm,
            face_depth_mm=request.face_depth_mm,
            forehead_width_mm=request.forehead_width_mm,
            nose_height_mm=request.nose_height_mm,
            embedding_3d=request.embedding_3d,
            embedding_confidence=request.embedding_confidence,
            capture_quality_score=request.capture_quality_score,
            mesh_density=request.mesh_density,
            depth_map_resolution=request.depth_map_resolution,
        )
    except ValueError as exc:
        _raise_from_value_error(exc)
    return record


@router.post("/compare", response_model=ThreeDFaceCompareResponse)
def compare_three_d_faces(
    request: ThreeDFaceCompareRequest,
    db: Session = Depends(get_db),
    current_user_id: str = Depends(get_current_user),
):
    """Compare two 3D face captures."""
    user = _get_user(db, current_user_id)
    try:
        comparison = three_d_face_service.compare_faces(
            db=db,
            organization_id=user.organization_id,
            face_data_1_id=request.face_data_1_id,
            face_data_2_id=request.face_data_2_id,
            match_threshold=request.match_threshold,
        )
    except ValueError as exc:
        _raise_from_value_error(exc)
    return comparison


@router.post("/liveness-check", response_model=ThreeDFaceLivenessResponse)
def three_d_liveness_check(
    request: ThreeDFaceLivenessRequest,
    db: Session = Depends(get_db),
    current_user_id: str = Depends(get_current_user),
):
    """Compute a geometric liveness score for a 3D capture."""
    user = _get_user(db, current_user_id)
    try:
        result = three_d_face_service.compute_liveness_score(
            db=db,
            organization_id=user.organization_id,
            face_data_id=request.face_data_id,
        )
    except ValueError as exc:
        _raise_from_value_error(exc)
    return result


@router.get("/identify/{face_data_id}", response_model=ThreeDFaceIdentifyResponse)
def identify_three_d_face(
    face_data_id: UUID,
    limit: int = 5,
    match_threshold: float = Query(default=0.75, ge=0.0, le=1.0),
    db: Session = Depends(get_db),
    current_user_id: str = Depends(get_current_user),
):
    """Find the closest 3D face matches for a probe capture."""
    user = _get_user(db, current_user_id)
    try:
        result = three_d_face_service.identify_face_data(
            db=db,
            organization_id=user.organization_id,
            probe_face_data_id=face_data_id,
            limit=limit,
            match_threshold=match_threshold,
        )
    except ValueError as exc:
        _raise_from_value_error(exc)
    return result
