"""
S29: Liveness Detection API Router (US-FUT-042)

Endpoints for liveness detection configuration, execution, and monitoring.
"""

from fastapi import APIRouter, Body, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List, Optional
import logging
from datetime import datetime, timedelta, timezone
import time
import os
import base64
import math
import cv2
import numpy as np
import httpx
from pydantic import BaseModel

from db.base import get_db
from core.security import get_current_user
from models.models import User, VisitorLog, LivenessChallenge, FutureEnhancement
from schemas.schemas import (
    LivenessConfig,
    LivenessScoreResponse,
    LivenessScoreCreateRequest,
    LivenessDetectionRequest,
    LivenessDetectionResult,
    LivenessStatistics,
    LivenessDetectionReport,
    LivenessReportItem,
)
from services.liveness_service import (
    LivenessDetectionService,
    create_liveness_score,
    get_liveness_scores,
    get_liveness_statistics as _svc_get_liveness_statistics,
    create_liveness_challenge,
    complete_liveness_challenge,
)
from services import user_service, visitor_service

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/liveness", tags=["Liveness Detection"])
AI_SERVICE_URL = os.getenv("AI_SERVICE_URL", "http://127.0.0.1:8001")

# Initialize service with default config
liveness_service = LivenessDetectionService()


class StartChallengeRequest(BaseModel):
    visitor_log_id: str
    challenge_type: str = "blink"


class VerifyChallengeRequest(BaseModel):
    challenge_id: str
    video_path: Optional[str] = None
    video_frame: Optional[str] = None
    video_frames: Optional[List[str]] = None


def _get_user(db: Session, user_id: str) -> User:
    """Fetch the User ORM object from a user_id string."""
    user = user_service.get_user_by_id(db, user_id)
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    return user


def _ensure_org_config(db: Session, organization_id: str) -> LivenessDetectionService:
    """
    Ensure the liveness_service has loaded the organization-specific config.
    
    Returns a service instance with the org-specific config loaded.
    For now, returns the global instance but with org config loaded.
    """
    db_config = _load_config_from_db(db, str(organization_id))
    if db_config is not None:
        liveness_service.config = db_config
    return liveness_service


def _decode_frame(frame_data: str) -> Optional[np.ndarray]:
    try:
        payload = frame_data.split(",", 1)[1] if "," in frame_data else frame_data
        img_bytes = base64.b64decode(payload)
        arr = np.frombuffer(img_bytes, np.uint8)
        return cv2.imdecode(arr, cv2.IMREAD_COLOR)
    except Exception:
        return None


def _encode_frame(frame: np.ndarray) -> Optional[str]:
    try:
        ok, encoded = cv2.imencode(".jpg", frame)
        if not ok:
            return None
        return f"data:image/jpeg;base64,{base64.b64encode(encoded.tobytes()).decode('ascii')}"
    except Exception:
        return None


def _parse_face_bbox(bbox: dict) -> tuple[int, int, int, int]:
    if {"x", "y", "w", "h"}.issubset(bbox):
        x = int(float(bbox.get("x", 0) or 0))
        y = int(float(bbox.get("y", 0) or 0))
        w = int(float(bbox.get("w", 0) or 0))
        h = int(float(bbox.get("h", 0) or 0))
        return x, y, w, h

    if {"x1", "y1", "x2", "y2"}.issubset(bbox):
        x1 = int(float(bbox.get("x1", 0) or 0))
        y1 = int(float(bbox.get("y1", 0) or 0))
        x2 = int(float(bbox.get("x2", 0) or 0))
        y2 = int(float(bbox.get("y2", 0) or 0))
        return x1, y1, max(0, x2 - x1), max(0, y2 - y1)

    return 0, 0, 0, 0


def _is_suspicious_full_frame_detection(face: dict, frame: np.ndarray) -> bool:
    bbox = face.get("bbox", {}) or {}
    x, y, w, h = _parse_face_bbox(bbox)
    if w <= 0 or h <= 0:
        return True

    frame_height, frame_width = frame.shape[:2]
    frame_area = max(1, frame_height * frame_width)
    bbox_area_ratio = (w * h) / frame_area
    confidence = float(face.get("confidence", 0.0) or 0.0)

    return confidence <= 0.0 and bbox_area_ratio >= 0.95


def _extract_face_frame(frame: np.ndarray) -> Optional[np.ndarray]:
    frame_payload = _encode_frame(frame)
    if not frame_payload:
        return None

    try:
        with httpx.Client(timeout=10.0) as client:
            response = client.post(
                f"{AI_SERVICE_URL}/realtime/frame-full-process",
                json={"frame_data": frame_payload},
            )
    except Exception as exc:
        logger.debug("AI-assisted face crop unavailable during liveness verification: %s", exc)
        return None

    if response.status_code != 200:
        return None

    try:
        faces = response.json().get("faces", [])
    except Exception:
        return None

    candidate_faces = [
        face for face in faces if not _is_suspicious_full_frame_detection(face, frame)
    ]
    if not candidate_faces:
        return None

    primary_face = max(
        candidate_faces,
        key=lambda face: (
            _parse_face_bbox(face.get("bbox", {}) or {})[2]
            * _parse_face_bbox(face.get("bbox", {}) or {})[3]
        ),
    )

    face_crop_b64 = primary_face.get("face_crop_b64")
    if face_crop_b64:
        decoded = _decode_frame(face_crop_b64)
        if decoded is not None:
            return decoded

    x, y, w, h = _parse_face_bbox(primary_face.get("bbox", {}) or {})
    x = max(0, x)
    y = max(0, y)
    w = max(0, w)
    h = max(0, h)
    if w <= 0 or h <= 0:
        return None

    height, width = frame.shape[:2]
    x2 = min(width, x + w)
    y2 = min(height, y + h)
    if x2 <= x or y2 <= y:
        return None

    return frame[y:y2, x:x2]


def _prepare_challenge_frames(frames: List[np.ndarray], max_frames: int = 18) -> tuple[List[np.ndarray], dict]:
    if not frames:
        return frames, {"sampled_frame_count": 0, "face_crops_applied": 0}

    if len(frames) > max_frames:
        step = max(1, math.ceil(len(frames) / max_frames))
        sampled_frames = frames[::step][:max_frames]
    else:
        sampled_frames = frames

    prepared_frames: List[np.ndarray] = []
    face_crops_applied = 0
    for frame in sampled_frames:
        cropped = _extract_face_frame(frame)
        if cropped is not None:
            prepared_frames.append(cropped)
            face_crops_applied += 1
        else:
            prepared_frames.append(frame)

    return prepared_frames, {
        "sampled_frame_count": len(sampled_frames),
        "face_crops_applied": face_crops_applied,
    }


def _read_video_frames(video_path: str, max_frames: int = 60, stride: int = 2) -> List[np.ndarray]:
    frames: List[np.ndarray] = []
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        return frames

    idx = 0
    try:
        while len(frames) < max_frames:
            ok, frame = cap.read()
            if not ok or frame is None:
                break
            idx += 1
            if stride > 1 and (idx % stride) != 0:
                continue
            frames.append(frame)
    finally:
        cap.release()
    return frames


# ─── Config Persistence Helpers ───────────────────────────────────────────────

_LIVENESS_STORY_ID = "US-FUT-042"
_LIVENESS_CATEGORY = "liveness"


def _load_config_from_db(db: Session, organization_id: str) -> Optional[LivenessConfig]:
    """Load persisted liveness config from the FutureEnhancement table."""
    row = db.query(FutureEnhancement).filter(
        FutureEnhancement.organization_id == organization_id,
        FutureEnhancement.story_id == _LIVENESS_STORY_ID,
    ).first()
    if row and row.config:
        try:
            config_data = row.config if isinstance(row.config, dict) else {}
            return LivenessConfig(**config_data)
        except Exception:
            pass
    return None


def _save_config_to_db(
    db: Session, organization_id: str, config: LivenessConfig,
) -> None:
    """Persist liveness config to the FutureEnhancement table."""
    row = db.query(FutureEnhancement).filter(
        FutureEnhancement.organization_id == organization_id,
        FutureEnhancement.story_id == _LIVENESS_STORY_ID,
    ).first()

    config_dict = config.model_dump()
    if row:
        row.config = config_dict  # type: ignore[assignment]
        row.status = "deployed"  # type: ignore[assignment]
        row.enabled = True  # type: ignore[assignment]
    else:
        row = FutureEnhancement(
            organization_id=organization_id,
            story_id=_LIVENESS_STORY_ID,
            category=_LIVENESS_CATEGORY,
            title="Liveness Detection & Anti-Spoofing",
            description="Configuration for liveness detection methods and thresholds",
            status="deployed",
            priority="high",
            config=config_dict,
            enabled=True,
        )
        db.add(row)
    db.commit()


# ─── Configuration Endpoints ──────────────────────────────────────────────────


@router.get("/config", response_model=LivenessConfig)
def get_liveness_config(
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Get current liveness detection configuration.
    
    Returns the active configuration for the organization.
    """
    try:
        user = _get_user(db, current_user_id)
        # Load from FutureEnhancement config in database (org-specific)
        db_config = _load_config_from_db(db, str(user.organization_id))
        if db_config is not None:
            liveness_service.config = db_config
        return liveness_service.config
    except Exception as e:
        logger.error(f"Failed to get liveness config: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve configuration",
        )


@router.put("/config", response_model=LivenessConfig)
def update_liveness_config(
    config: LivenessConfig,
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Update liveness detection configuration.
    
    Allows customization of detection methods, thresholds, and spoofing detection.
    Requires admin role.
    """
    user = _get_user(db, current_user_id)
    if user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only admin users can modify configuration",
        )

    try:
        # Persist to FutureEnhancement.config JSONB field and update in-memory
        _save_config_to_db(db, str(user.organization_id), config)
        liveness_service.config = config
        logger.info(f"Updated liveness config by user {user.email}")
        return config
    except Exception as e:
        logger.error(f"Failed to update liveness config: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update configuration",
        )


# ─── Detection Endpoints ──────────────────────────────────────────────────────


@router.post("/detect", response_model=LivenessDetectionResult)
def detect_liveness(
    request: LivenessDetectionRequest,
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Perform liveness detection on a visitor log entry.
    
    Accepts video file path or base64 frame data and detects if the face is real
    or a spoofing attack (print, replay, mask).
    
    Methods:
    - texture: LBP-based texture analysis
    - motion: Optical flow and eye blink detection
    - deep_learning: CNN-based classifier
    
    Returns ensemble result combining all enabled methods.
    """
    try:
        user = _get_user(db, current_user_id)
        # Ensure org-specific config is loaded
        service = _ensure_org_config(db, user.organization_id)
        start_time = time.perf_counter()
        
        # Verify visitor log exists
        log = db.query(VisitorLog).filter(
            VisitorLog.id == request.visitor_log_id,
            VisitorLog.organization_id == user.organization_id,
        ).first()

        if not log:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Visitor log not found",
            )

        frame: Optional[np.ndarray] = None
        frames: Optional[List[np.ndarray]] = None

        if request.frame_data:
            frame = _decode_frame(request.frame_data)
            if frame is None:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Invalid frame_data payload",
                )

        if request.video_path:
            if not os.path.exists(request.video_path):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="video_path not found",
                )
            frames = _read_video_frames(request.video_path)
            if frames and frame is None:
                frame = frames[0]

        if service.config.video_required:
            if not frames or len(frames) < service.config.min_video_frames:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=(
                        f"Insufficient video frames: {len(frames) if frames else 0}. "
                        f"Minimum required is {service.config.min_video_frames}."
                    ),
                )

        if frame is None and not frames:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Provide either frame_data or video_path",
            )

        result = service.ensemble_detection(
            frame=frame,
            frames=frames,
            methods=request.methods,
        )

        processing_time_ms = (time.perf_counter() - start_time) * 1000.0
        details = result.details or {}
        score_details = details.get("individual_scores", {})
        motion_details = details.get("motion", {})
        quality_metrics = result.quality_metrics or {}

        method_used = "ensemble"
        methods = request.methods or []
        if len(methods) == 1:
            method_used = methods[0]

        rejection_reason = None
        if not result.is_live:
            rejection_reason = "attack_detected" if result.attack_detected else "low_confidence"

        attack_indicators = {}
        if result.attack_detected and result.attack_type:
            attack_indicators[result.attack_type] = float(result.score)

        create_liveness_score(
            db=db,
            organization_id=str(user.organization_id),
            visitor_log_id=request.visitor_log_id,
            request=LivenessScoreCreateRequest(
                visitor_log_id=request.visitor_log_id,
                is_live=result.is_live,
                overall_score=float(result.score),
                rejection_reason=rejection_reason,
                texture_score=score_details.get("texture"),
                motion_score=score_details.get("motion"),
                deep_learning_score=score_details.get("deep_learning"),
                video_duration_frames=motion_details.get("video_duration_frames"),
                has_sufficient_motion=(
                    score_details.get("motion") is not None
                    and score_details.get("motion") >= service.config.motion_score_threshold
                ),
                blink_count=motion_details.get("blink_count"),
                attack_indicators=attack_indicators,
                illumination_score=quality_metrics.get("illumination_score"),
                blur_score=quality_metrics.get("blur_score"),
                noise_level=quality_metrics.get("noise_level"),
                challenge_type=request.challenge_type,
                method_used=method_used,
                model_version=details.get("deep_learning", {}).get("model_version"),
                processing_time_ms=processing_time_ms,
            ),
        )

        logger.info(
            f"Liveness detection for log {request.visitor_log_id}: "
            f"is_live={result.is_live}, score={result.score}"
        )
        return result

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Liveness detection failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Detection failed",
        )


@router.post("/detect/texture", response_model=dict)
def detect_texture_based(
    request: LivenessDetectionRequest,
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Texture-based liveness detection only (LBP analysis).
    """
    try:
        if not request.frame_data:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="frame_data is required for texture detection",
            )
        frame = _decode_frame(request.frame_data)
        if frame is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid frame_data payload",
            )

        score, details = liveness_service.detect_liveness_texture_based(frame)
        return {
            "method": "texture",
            "score": score,
            "details": details,
        }
    except Exception as e:
        logger.error(f"Texture detection failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Texture detection failed",
        )


@router.post("/detect/motion", response_model=dict)
def detect_motion_based(
    request: LivenessDetectionRequest,
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Motion-based liveness detection only (optical flow, eye blink).
    """
    try:
        if request.video_path:
            if not os.path.exists(request.video_path):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="video_path not found",
                )
            frames = _read_video_frames(request.video_path)
        elif request.frame_data:
            frame = _decode_frame(request.frame_data)
            if frame is None:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Invalid frame_data payload",
                )
            frames = [frame, frame.copy()]
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Provide video_path or frame_data",
            )

        if len(frames) < 2:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Not enough frames for motion detection",
            )

        score, details = liveness_service.detect_liveness_motion_based(frames)
        return {
            "method": "motion",
            "score": score,
            "details": details,
        }
    except Exception as e:
        logger.error(f"Motion detection failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Motion detection failed",
        )


@router.post("/detect/deep-learning", response_model=dict)
def detect_deep_learning(
    request: LivenessDetectionRequest,
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Deep learning-based liveness detection using CNN model.
    """
    try:
        if not request.frame_data:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="frame_data is required for deep-learning detection",
            )
        frame = _decode_frame(request.frame_data)
        if frame is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid frame_data payload",
            )

        score, details = liveness_service.detect_liveness_deep_learning(frame)
        return {
            "method": "deep_learning",
            "score": score,
            "model_version": details.get("model_version", "liveness_v1_quality"),
            "details": details,
        }
    except Exception as e:
        logger.error(f"Deep learning detection failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Deep learning detection failed",
        )


# ─── Score Retrieval Endpoints ───────────────────────────────────────────────


@router.get("/scores", response_model=List[LivenessScoreResponse])
def list_liveness_scores(
    visitor_log_id: Optional[str] = None,
    is_live: Optional[bool] = None,
    limit: int = 100,
    offset: int = 0,
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    List liveness scores with optional filters.
    
    Filters:
    - visitor_log_id: Filter by specific visitor log
    - is_live: Filter by liveness result (True/False)
    - limit: Max results (default 100)
    - offset: For pagination
    """
    try:
        user = _get_user(db, current_user_id)
        scores = get_liveness_scores(
            db,
            user.organization_id,
            visitor_log_id=visitor_log_id,
            is_live=is_live,
            limit=limit,
            offset=offset,
        )

        return [
            LivenessScoreResponse(
                id=str(score.id),
                visitor_log_id=str(score.visitor_log_id),
                is_live=score.is_live,
                overall_score=score.overall_score,
                rejection_reason=score.rejection_reason,
                texture_score=score.texture_score,
                motion_score=score.motion_score,
                deep_learning_score=score.deep_learning_score,
                video_duration_frames=score.video_duration_frames,
                has_sufficient_motion=score.has_sufficient_motion,
                blink_count=score.blink_count,
                attack_indicators=score.attack_indicators or {},
                face_size=score.face_size,
                illumination_score=score.illumination_score,
                blur_score=score.blur_score,
                noise_level=score.noise_level,
                challenge_type=score.challenge_type,
                challenge_passed=score.challenge_passed,
                challenge_attempts=score.challenge_attempts,
                method_used=score.method_used,
                model_version=score.model_version,
                processing_time_ms=score.processing_time_ms,
                created_at=score.created_at,
            )
            for score in scores
        ]
    except Exception as e:
        logger.error(f"Failed to retrieve liveness scores: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve scores",
        )


@router.get("/scores/{score_id}", response_model=LivenessScoreResponse)
def get_liveness_score(
    score_id: str,
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Get a specific liveness score by ID.
    """
    try:
        from models.models import LivenessScore
        user = _get_user(db, current_user_id)

        score = db.query(LivenessScore).filter(
            LivenessScore.id == score_id,
            LivenessScore.organization_id == user.organization_id,
        ).first()

        if not score:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Liveness score not found",
            )

        return LivenessScoreResponse(
            id=str(score.id),
            visitor_log_id=str(score.visitor_log_id),
            is_live=score.is_live,
            overall_score=score.overall_score,
            rejection_reason=score.rejection_reason,
            texture_score=score.texture_score,
            motion_score=score.motion_score,
            deep_learning_score=score.deep_learning_score,
            video_duration_frames=score.video_duration_frames,
            has_sufficient_motion=score.has_sufficient_motion,
            blink_count=score.blink_count,
            attack_indicators=score.attack_indicators or {},
            face_size=score.face_size,
            illumination_score=score.illumination_score,
            blur_score=score.blur_score,
            noise_level=score.noise_level,
            challenge_type=score.challenge_type,
            challenge_passed=score.challenge_passed,
            challenge_attempts=score.challenge_attempts,
            method_used=score.method_used,
            model_version=score.model_version,
            processing_time_ms=score.processing_time_ms,
            created_at=score.created_at,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to retrieve liveness score: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve score",
        )


# ─── Analytics & Reporting Endpoints ─────────────────────────────────────────


@router.get("/statistics", response_model=LivenessStatistics)
def get_liveness_statistics_endpoint(
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Get liveness detection statistics for the organization.
    
    Includes:
    - Total detections
    - Live vs spoof breakdown
    - Average liveness score
    - Attack detection rate
    - Method distribution
    """
    try:
        user = _get_user(db, current_user_id)
        stats = _svc_get_liveness_statistics(db, user.organization_id)
        return stats
    except Exception as e:
        logger.error(f"Failed to calculate statistics: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to calculate statistics",
        )


@router.get("/report", response_model=LivenessDetectionReport)
def get_liveness_report_endpoint(
    days: int = 7,
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Generate liveness detection report for the specified period.
    
    Parameters:
    - days: Number of days to look back (default 7)
    
    Report includes detailed statistics, detection breakdown, and trends.
    """
    try:
        from models.models import LivenessScore
        user = _get_user(db, current_user_id)

        period_end = datetime.now(timezone.utc)
        period_start = period_end - timedelta(days=days)

        scores = (
            db.query(LivenessScore)
            .filter(
                LivenessScore.organization_id == user.organization_id,
                LivenessScore.created_at >= period_start,
                LivenessScore.created_at <= period_end,
            )
            .order_by(LivenessScore.created_at.desc())
            .limit(10000).all()
        )

        # Build report items
        report_items = []
        for score in scores:
            visitor_log = db.query(VisitorLog).filter(
                VisitorLog.id == score.visitor_log_id
            ).first()

            visitor_name = None
            if visitor_log and visitor_log.visitor:
                visitor_name = visitor_log.visitor.name

            report_items.append(
                LivenessReportItem(
                    timestamp=score.created_at,
                    visitor_name=visitor_name,
                    is_live=score.is_live,
                    score=score.overall_score,
                    method=score.method_used,
                    rejection_reason=score.rejection_reason,
                    attack_detected=bool(score.attack_indicators),
                )
            )

        # Calculate statistics
        stats = _svc_get_liveness_statistics(db, user.organization_id)

        # Generate summary
        summary = (
            f"Period: {period_start.date()} to {period_end.date()}\n"
            f"Total Detections: {len(report_items)}\n"
            f"Live: {sum(1 for item in report_items if item.is_live)}\n"
            f"Spoofs: {sum(1 for item in report_items if not item.is_live)}\n"
            f"Attacks Detected: {sum(1 for item in report_items if item.attack_detected)}\n"
            f"Average Score: {stats.average_liveness_score:.2f}\n"
        )

        return LivenessDetectionReport(
            organization_id=str(user.organization_id),
            period_start=period_start,
            period_end=period_end,
            statistics=stats,
            detections=report_items,
            summary=summary,
        )

    except Exception as e:
        logger.error(f"Failed to generate report: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to generate report",
        )


# ─── Challenge-Response Endpoints ────────────────────────────────────────────


@router.post("/challenge/start", response_model=dict)
def start_challenge(
    request: Optional[StartChallengeRequest] = Body(default=None),
    visitor_log_id: Optional[str] = None,
    challenge_type: Optional[str] = None,
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Start a liveness challenge for a specific visitor log.
    
    Creates a persistent challenge session in the database and returns
    the challenge_id that must be passed to /challenge/verify.

    Challenge types:
    - blink: User must blink
    - head_turn: User must turn head
    - smile: User must smile
    """
    if request is not None:
        visitor_log_id = request.visitor_log_id
        challenge_type = request.challenge_type

    if not visitor_log_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="visitor_log_id is required",
        )

    challenge_type = challenge_type or "blink"
    valid_types = {"blink", "head_turn", "smile"}
    if challenge_type not in valid_types:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid challenge_type. Must be one of: {', '.join(valid_types)}",
        )

    try:
        user = _get_user(db, current_user_id)
        log = db.query(VisitorLog).filter(
            VisitorLog.id == visitor_log_id,
            VisitorLog.organization_id == user.organization_id,
        ).first()

        if not log:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Visitor log not found",
            )

        challenge = create_liveness_challenge(
            db=db,
            organization_id=str(user.organization_id),
            visitor_log_id=visitor_log_id,
            challenge_type=challenge_type,
        )

        return {
            "challenge_id": str(challenge.id),
            "challenge_type": challenge_type,
            "instruction": challenge.instruction,
            "timeout_seconds": challenge.timeout_seconds,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to start challenge: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to start challenge",
        )


@router.post("/challenge/verify", response_model=dict)
def verify_challenge(
    request: Optional[VerifyChallengeRequest] = Body(default=None),
    challenge_id: Optional[str] = None,
    video_path: Optional[str] = None,
    video_frame: Optional[str] = None,
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Verify completion of a liveness challenge.
    
    Supports two modes:
    1. File-based: video_path points to a video file on disk
    2. Frame-based: video_frame is base64-encoded image data from browser
    
    Loads the video, extracts frames, then uses the appropriate detection
    method (blink detection, optical-flow head-turn, or smile brightness
    analysis) to determine whether the user performed the challenge action.
    """
    if request is not None:
        challenge_id = request.challenge_id
        video_path = request.video_path
        video_frame = request.video_frame
        video_frames = request.video_frames
    else:
        video_frames = None

    if not challenge_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="challenge_id is required",
        )

    try:
        user = _get_user(db, current_user_id)
        # Ensure org-specific config is loaded
        service = _ensure_org_config(db, user.organization_id)
        
        # 1. Load the challenge from DB
        challenge = db.query(LivenessChallenge).filter(
            LivenessChallenge.id == challenge_id,
            LivenessChallenge.organization_id == user.organization_id,
        ).first()

        if not challenge:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Challenge not found",
            )

        if str(challenge.status) not in ("pending", "failed"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Challenge is already {challenge.status}",
            )

        # 2. Load video frames
        frames = []
        
        if video_frames:
            decoded_frames: List[np.ndarray] = []
            for frame_payload in video_frames:
                frame = _decode_frame(frame_payload)
                if frame is None:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="Invalid base64 frame data in video_frames",
                    )
                decoded_frames.append(frame)
            frames = decoded_frames
        elif video_frame:
            # Mode 1: Single base64 frame from browser
            frame = _decode_frame(video_frame)
            if frame is None:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Invalid base64 frame data",
                )
            frames = [frame]
        elif video_path:
            # Mode 2: Video file on disk
            if not os.path.exists(video_path):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="video_path not found on disk",
                )
            frames = _read_video_frames(video_path, max_frames=90, stride=1)
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Must provide either video_path or video_frame",
            )

        if len(frames) < 1:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No frames available for verification",
            )

        frames, preprocessing_details = _prepare_challenge_frames(frames)

        # 3. Run challenge-specific verification
        # For single-frame scenarios, run liveness detection instead
        if len(frames) == 1:
            # Single frame: use deep learning & texture for blink/smile, texture for head_turn
            frame = frames[0]
            if str(challenge.challenge_type) == "smile":
                # Smile detection: check for brightness change in lower face
                passed, confidence, details = service.verify_challenge(
                    challenge_type="smile",
                    frames=frames,
                )
            else:
                # For other challenges, do general liveness check
                result = service.ensemble_detection(frame=frame)
                # Convert to challenge result format
                passed = result.is_live
                confidence = result.score
                details = {
                    "method": "texture_deep_learning",
                    "is_live": result.is_live,
                    "ensemble_details": result.details,
                }
        else:
            # Multiple frames: full challenge verification
            passed, confidence, details = service.verify_challenge(
                challenge_type=str(challenge.challenge_type),
                frames=frames,
            )

        if isinstance(details, dict):
            details.update(preprocessing_details)

        # 4. Persist result
        complete_liveness_challenge(db, challenge, passed, confidence, details)

        # 5. Write an audit record so operators can see liveness outcomes in
        #    the visitor log history.  The challenge links to a visitor_log_id
        #    when it was started; use that to tie the result back to the log.
        visitor_log_id = getattr(challenge, "visitor_log_id", None)
        if visitor_log_id:
            visitor_service.create_audit_log(
                db,
                user.organization_id,
                user.id,
                "liveness_challenge_completed",
                "visitor_log",
                str(visitor_log_id),
                details={
                    "challenge_id": str(challenge_id),
                    "challenge_type": str(challenge.challenge_type),
                    "verified": passed,
                    "confidence": round(confidence, 4),
                    "attempts": challenge.attempts,
                },
            )

        return {
            "challenge_id": challenge_id,
            "verified": passed,
            "confidence": round(confidence, 4),
            "details": details,
            "attempts": challenge.attempts,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to verify challenge: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to verify challenge",
        )


# ─── Health Check ──────────────────────────────────────────────────────────────


@router.get("/health", response_model=dict)
def health_check():
    """
    Health check for liveness detection service.
    """
    return {
        "status": "ok",
        "service": "liveness_detection",
        "methods_available": [
            "texture",
            "motion",
            "deep_learning",
            "ensemble",
            "challenge",
        ],
        "version": "1.0",
    }
