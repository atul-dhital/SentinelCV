"""Face search API (G1) — find historical detection sightings by uploading a photo.

The live recognition path already stores a real pgvector ``embedding_snapshot``
on every ``DetectionLog`` (see ``models.DetectionLog``), so this endpoint just
embeds the query image via the AI service and runs an org-scoped cosine search
across that history. Postgres uses pgvector ANN; SQLite falls back to a bounded
Python cosine scan so the feature still works in dev/test.
"""

import math
import os
from typing import List, Optional
from uuid import uuid4

import httpx
from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from pydantic import BaseModel
from sqlalchemy.orm import Session

from core.security import get_current_user
from core.storage import storage
from db.base import IS_SQLITE, get_db
from models import models
from services import user_service, visitor_service

router = APIRouter(prefix="/search", tags=["Face Search"])

AI_SERVICE_URL = os.getenv("AI_SERVICE_URL", "http://127.0.0.1:8001")


class FaceSightingResult(BaseModel):
    detection_log_id: str
    session_id: Optional[str] = None
    camera_id: Optional[str] = None
    visitor_id: Optional[str] = None
    visitor_name: Optional[str] = None
    identified: bool = False
    confidence: float = 0.0
    similarity: float = 0.0
    face_image_path: Optional[str] = None
    timestamp: Optional[str] = None


class FaceSearchResponse(BaseModel):
    query_face_detected: bool
    total_candidates: int
    results: List[FaceSightingResult]


def _get_user(db: Session, user_id: str) -> models.User:
    user = user_service.get_user_by_id(db, user_id)
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    return user


async def _embed_uploaded_image(contents: bytes, content_type: Optional[str]) -> Optional[list]:
    """Persist the query image, ask the AI service for its embedding, then clean up."""
    relative_path = f"face_images/search_{uuid4().hex}.jpg"
    saved = str(storage.save_file(relative_path, contents, content_type=content_type or "image/jpeg"))
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(f"{AI_SERVICE_URL}/embed-face", json={"image_path": saved})
        if resp.status_code != 200:
            return None
        data = resp.json()
        if data.get("error"):
            return None
        return data.get("embedding")
    except httpx.RequestError:
        raise HTTPException(status_code=503, detail="AI service unavailable")
    finally:
        try:
            storage.delete_file(relative_path)
        except Exception:
            pass


def _base_query(db: Session, org_id):
    return (
        db.query(models.DetectionLog, models.CameraSession, models.Visitor)
        .join(models.CameraSession, models.DetectionLog.session_id == models.CameraSession.id)
        .outerjoin(models.Visitor, models.DetectionLog.visitor_id == models.Visitor.id)
        .filter(models.CameraSession.organization_id == org_id)
    )


def _search_pgvector(db: Session, org_id, embedding: list, limit: int):
    query_vec = [float(v) for v in embedding]
    distance = models.DetectionLog.embedding_snapshot.cosine_distance(query_vec)
    rows = (
        _base_query(db, org_id)
        .add_columns(distance.label("distance"))
        .filter(models.DetectionLog.embedding_snapshot.isnot(None))
        .order_by(distance.asc())
        .limit(limit)
        .all()
    )
    out = []
    for det, sess, vis, dist in rows:
        sim = max(0.0, min(1.0, 1.0 - float(dist))) if dist is not None else 0.0
        out.append((det, sess, vis, sim))
    return out


def _search_sqlite(db: Session, org_id, embedding: list, limit: int):
    rows = (
        _base_query(db, org_id)
        .order_by(models.DetectionLog.timestamp.desc())
        .limit(5000)
        .all()
    )
    q_norm = math.sqrt(sum(v * v for v in embedding)) or 1.0
    scored = []
    for det, sess, vis in rows:
        stored = visitor_service.parse_embedding_payload(det.embedding_snapshot)
        if not stored:
            continue
        dims = min(len(embedding), len(stored))
        dot = sum(embedding[i] * stored[i] for i in range(dims))
        s_norm = math.sqrt(sum(s * s for s in stored[:dims])) or 1.0
        scored.append((det, sess, vis, max(0.0, dot / (q_norm * s_norm))))
    scored.sort(key=lambda r: r[3], reverse=True)
    return scored[:limit]


@router.post("/face", response_model=FaceSearchResponse)
async def search_by_face(
    file: UploadFile = File(...),
    limit: int = Query(20, ge=1, le=100),
    min_similarity: float = Query(0.0, ge=0.0, le=1.0),
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Upload a face photo; return historical detection sightings ranked by similarity."""
    user = _get_user(db, current_user_id)

    contents = await file.read()
    if not contents:
        raise HTTPException(status_code=400, detail="Empty file")

    embedding = await _embed_uploaded_image(contents, file.content_type)
    if not embedding:
        return FaceSearchResponse(query_face_detected=False, total_candidates=0, results=[])

    if IS_SQLITE:
        matches = _search_sqlite(db, user.organization_id, embedding, limit)
    else:
        matches = _search_pgvector(db, user.organization_id, embedding, limit)

    results: List[FaceSightingResult] = []
    for det, sess, vis, sim in matches:
        if sim < min_similarity:
            continue
        results.append(FaceSightingResult(
            detection_log_id=str(det.id),
            session_id=str(det.session_id) if det.session_id else None,
            camera_id=str(sess.camera_id) if sess and sess.camera_id else None,
            visitor_id=str(det.visitor_id) if det.visitor_id else None,
            visitor_name=vis.name if vis else None,
            identified=bool(det.identified),
            confidence=float(det.confidence or 0.0),
            similarity=round(float(sim), 4),
            face_image_path=det.face_image_path,
            timestamp=det.timestamp.isoformat() if det.timestamp else None,
        ))

    return FaceSearchResponse(
        query_face_detected=True,
        total_candidates=len(matches),
        results=results,
    )
