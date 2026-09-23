"""Phase 3 Complete Feature API - All 14 Routers with Working Endpoints

Production-ready API endpoints for all Phase 3 features.
Each endpoint delegates to its service layer and returns real data.

Total Features: 14
Total Routers: 14
"""

from fastapi import APIRouter, Depends, HTTPException, status, Query, Body
from uuid import UUID
from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from db.base import get_db
from core.security import get_current_user
from core.authz import assert_belongs_to_org, validate_user_path
from models import models
from services.phase3_service_scaffolds import (
    BiometricBackendUnavailable,
    MultimodalLearningService,
    ThreeDFaceRecognitionService,
    AdvancedLivenessService,
    FederatedLearningService,
    EmotionActionRecognitionService,
    CrossCameraReIDService,
    EdgeDeploymentService,
    AdvancedAnalyticsService,
    VisionTransformerService,
    MultiSpectralInfraredService,
    MobilePWAService,
    WebhooksIntegrationService,
    ModelVersioningABTestService,
    AdvancedSecurityComplianceService,
)
import logging

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helper: extract user and organization from auth token
# ---------------------------------------------------------------------------

def _get_user_org(db: Session, user_id: str):
    """Retrieve the User record and its organization_id from the database.

    Rejects deactivated users so the 14 Phase 3 routers cannot be reached
    by an account whose access has been revoked.
    """
    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="User account is deactivated")
    return user, user.organization_id


# ===========================================================================
# ROUTER 1: MULTIMODAL LEARNING
# ===========================================================================

router_multimodal = APIRouter(prefix="/multimodal", tags=["Multimodal Learning"])


class MultimodalExtractRequest(BaseModel):
    visitor_id: UUID
    face_image_path: Optional[str] = None
    audio_path: Optional[str] = None
    text_data: Optional[str] = None


class MultimodalFusionConfigRequest(BaseModel):
    face_weight: float = Field(0.6, ge=0.0, le=1.0)
    audio_weight: float = Field(0.2, ge=0.0, le=1.0)
    text_weight: float = Field(0.1, ge=0.0, le=1.0)
    sensor_weight: float = Field(0.1, ge=0.0, le=1.0)
    strategy: str = Field("weighted_mean", description="weighted_mean | attention | mlp")


@router_multimodal.post("/extract")
async def extract_multimodal_embedding(
    payload: MultimodalExtractRequest = Body(...),
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Extract fused multimodal embeddings (face + audio + text)."""
    user, org_id = _get_user_org(db, current_user_id)
    # Verify the visitor exists in the caller's org BEFORE doing expensive
    # ML work or writing any rows. The global SQLAlchemy tenant filter
    # only covers SELECTs, not INSERTs that pin foreign keys from user input.
    assert_belongs_to_org(db, models.Visitor, payload.visitor_id, org_id)
    service = MultimodalLearningService(db)
    try:
        face_emb = None
        audio_emb = None
        text_emb = None

        if payload.face_image_path:
            safe_face_path = validate_user_path(payload.face_image_path)
            face_emb = await service.extract_face_embedding(safe_face_path)
        if payload.audio_path:
            safe_audio_path = validate_user_path(payload.audio_path)
            audio_emb = await service.extract_audio_embedding(safe_audio_path)
        if payload.text_data:
            text_emb = await service.extract_text_embedding(payload.text_data)

        # Build a lightweight fusion config id from the org default
        fusion_config = await service.create_fusion_config(
            org_id=org_id,
            face_weight=0.6,
            audio_weight=0.2,
            text_weight=0.1,
            sensor_weight=0.1,
            strategy="weighted_mean",
        )
        fusion_config_id = fusion_config.get("id") if fusion_config else None

        fused_embedding, fusion_score = (None, 0.0)
        if fusion_config_id:
            fused_embedding, fusion_score = await service.fuse_embeddings(
                face_embedding=face_emb,
                audio_embedding=audio_emb,
                text_embedding=text_emb,
                fusion_config_id=fusion_config_id,
            )

        return {
            "visitor_id": str(payload.visitor_id),
            "face_embedding": face_emb.tolist() if face_emb is not None else None,
            "audio_embedding": audio_emb.tolist() if audio_emb is not None else None,
            "text_embedding": text_emb.tolist() if text_emb is not None else None,
            "fused_embedding": fused_embedding.tolist() if fused_embedding is not None else None,
            "fusion_score": fusion_score,
        }
    except BiometricBackendUnavailable as e:
        raise HTTPException(status_code=503, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Multimodal extract error: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router_multimodal.post("/fusion-config")
async def configure_fusion(
    payload: MultimodalFusionConfigRequest = Body(...),
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Configure multimodal fusion parameters per organization."""
    user, org_id = _get_user_org(db, current_user_id)
    service = MultimodalLearningService(db)
    try:
        result = await service.create_fusion_config(
            org_id=org_id,
            face_weight=payload.face_weight,
            audio_weight=payload.audio_weight,
            text_weight=payload.text_weight,
            sensor_weight=payload.sensor_weight,
            strategy=payload.strategy,
        )
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Fusion config error: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router_multimodal.get("/compare/{embedding_id_1}/{embedding_id_2}")
async def compare_multimodal_embeddings(
    embedding_id_1: UUID,
    embedding_id_2: UUID,
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Compare two multimodal embeddings using cosine similarity.

    Loads both embeddings from the ``multimodal_embeddings`` table for the
    caller's organization, fuses each row's modalities (face/audio/text), and
    returns the cosine similarity between the fused vectors.
    """
    user, org_id = _get_user_org(db, current_user_id)
    service = MultimodalLearningService(db)
    try:
        import numpy as np

        def _load(embedding_id: UUID) -> np.ndarray:
            row = (
                db.query(models.MultimodalEmbedding)
                .join(models.Visitor, models.Visitor.id == models.MultimodalEmbedding.visitor_id)
                .filter(
                    models.MultimodalEmbedding.id == str(embedding_id),
                    models.Visitor.organization_id == org_id,
                )
                .first()
            )
            if not row:
                raise HTTPException(
                    status_code=404,
                    detail=f"Multimodal embedding {embedding_id} not found",
                )

            parts: List[np.ndarray] = []
            for value in (row.face_embedding, row.audio_embedding, row.text_embedding):
                if value is None:
                    continue
                try:
                    parts.append(np.asarray(value, dtype=np.float64))
                except (TypeError, ValueError):
                    continue

            if not parts:
                raise HTTPException(
                    status_code=422,
                    detail=f"Embedding {embedding_id} has no usable modalities",
                )
            return np.concatenate(parts)

        emb1 = _load(embedding_id_1)
        emb2 = _load(embedding_id_2)

        # Pad shorter vector to match dimensions before similarity computation.
        if emb1.shape[0] != emb2.shape[0]:
            target = max(emb1.shape[0], emb2.shape[0])
            if emb1.shape[0] < target:
                emb1 = np.pad(emb1, (0, target - emb1.shape[0]))
            if emb2.shape[0] < target:
                emb2 = np.pad(emb2, (0, target - emb2.shape[0]))

        similarity = await service.compare_multimodal(emb1, emb2)
        return {
            "embedding_id_1": str(embedding_id_1),
            "embedding_id_2": str(embedding_id_2),
            "similarity": similarity,
        }
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Multimodal compare error: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


# ===========================================================================
# ROUTER 2: 3D FACE RECOGNITION
# ===========================================================================

router_3d_face = APIRouter(prefix="/3d-face", tags=["3D Face Recognition"])


class ThreeDCaptureRequest(BaseModel):
    visitor_id: UUID
    depth_map_path: str
    point_cloud_path: str


class ThreeDMatchRequest(BaseModel):
    face_id_1: UUID
    face_id_2: UUID


class ThreeDLivenessRequest(BaseModel):
    face_id: UUID


@router_3d_face.post("/capture")
async def capture_3d_face_data(
    payload: ThreeDCaptureRequest = Body(...),
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Capture and process 3D face data from depth sensors."""
    user, org_id = _get_user_org(db, current_user_id)
    assert_belongs_to_org(db, models.Visitor, payload.visitor_id, org_id)
    safe_depth_path = validate_user_path(payload.depth_map_path)
    safe_cloud_path = validate_user_path(payload.point_cloud_path)
    service = ThreeDFaceRecognitionService(db)
    try:
        depth_map = await service.load_depth_map(safe_depth_path)
        point_cloud = await service.load_point_cloud(safe_cloud_path)
        landmarks_3d = await service.extract_facial_landmarks_3d(depth_map, point_cloud)
        embedding, mesh = await service.compute_3d_embedding_from_mesh(landmarks_3d)

        return {
            "visitor_id": str(payload.visitor_id),
            "landmark_count": len(landmarks_3d) if landmarks_3d else 0,
            "embedding_dim": embedding.shape[0] if embedding is not None else 0,
            "mesh_vertices": mesh.shape[0] if mesh is not None else 0,
            "status": "captured",
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"3D face capture error: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router_3d_face.post("/match")
async def match_3d_faces(
    payload: ThreeDMatchRequest = Body(...),
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Compare two 3D face models using geometric matching."""
    user, org_id = _get_user_org(db, current_user_id)
    service = ThreeDFaceRecognitionService(db)
    try:
        result = await service.match_3d_faces(payload.face_id_1, payload.face_id_2)
        return {
            "face_id_1": str(payload.face_id_1),
            "face_id_2": str(payload.face_id_2),
            "shape_similarity": result.get("shape_similarity", 0.0),
            "texture_similarity": result.get("texture_similarity", 0.0),
            "overall_confidence": result.get("overall_confidence", 0.0),
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"3D face match error: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router_3d_face.post("/liveness-check")
async def check_3d_face_liveness(
    payload: ThreeDLivenessRequest = Body(...),
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Detect spoofing attacks using 3D geometric analysis."""
    user, org_id = _get_user_org(db, current_user_id)
    service = ThreeDFaceRecognitionService(db)
    try:
        result = await service.check_3d_face_liveness(payload.face_id)
        return {
            "face_id": str(payload.face_id),
            "is_live": result.get("liveness_confidence", 0.0) >= 0.5,
            "liveness_confidence": result.get("liveness_confidence", 0.0),
            "spoofing_type_detected": result.get("spoofing_type_detected", None),
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"3D liveness check error: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


# ===========================================================================
# ROUTER 3: ADVANCED LIVENESS DETECTION
# ===========================================================================

router_liveness_adv = APIRouter(prefix="/liveness-advanced", tags=["Advanced Liveness"])


class StartChallengeRequest(BaseModel):
    visitor_log_id: UUID
    challenge_type: Optional[str] = "blink"
    timeout_seconds: Optional[int] = 30


class VerifyChallengeRequest(BaseModel):
    challenge_id: UUID
    video_path: str


@router_liveness_adv.post("/start-challenge")
async def start_liveness_challenge(
    payload: StartChallengeRequest = Body(...),
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Start an interactive liveness challenge (blink, head turn, smile)."""
    user, org_id = _get_user_org(db, current_user_id)
    service = AdvancedLivenessService(db)
    try:
        result = await service.start_challenge(
            visitor_id=payload.visitor_log_id,
            detection_log_id=payload.visitor_log_id,
            challenge_type=payload.challenge_type or "blink",
            timeout_seconds=payload.timeout_seconds or 30,
        )
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Liveness start-challenge error: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router_liveness_adv.post("/verify-challenge")
async def verify_liveness_challenge(
    payload: VerifyChallengeRequest = Body(...),
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Verify liveness challenge response using video analysis."""
    user, org_id = _get_user_org(db, current_user_id)
    safe_video_path = validate_user_path(payload.video_path)
    service = AdvancedLivenessService(db)
    try:
        challenge_result = await service.verify_challenge_response(
            challenge_id=payload.challenge_id,
            video_path=safe_video_path,
        )
        texture_score = await service.analyze_texture_features(safe_video_path)
        motion_score = await service.analyze_motion_features(safe_video_path)
        deep_score = await service.analyze_deep_features(safe_video_path)

        challenge_confidence = challenge_result.get("confidence", 0.0) if challenge_result else 0.0
        texture_val = texture_score.get("score", 0.0) if texture_score else 0.0
        motion_val = motion_score.get("score", 0.0) if motion_score else 0.0
        deep_val = deep_score.get("score", 0.0) if deep_score else 0.0

        is_live, overall_confidence = await service.ensemble_liveness_decision(
            texture_score=texture_val,
            motion_score=motion_val,
            deep_score=deep_val,
            challenge_score=challenge_confidence,
        )

        return {
            "challenge_id": str(payload.challenge_id),
            "is_live": is_live,
            "overall_confidence": overall_confidence,
            "texture_score": texture_val,
            "motion_score": motion_val,
            "deep_learning_score": deep_val,
            "challenge_score": challenge_confidence,
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Liveness verify-challenge error: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router_liveness_adv.get("/methods")
async def get_liveness_methods(
    current_user_id: str = Depends(get_current_user),
):
    """Get available liveness detection methods and challenge types."""
    return {
        "methods": ["texture", "motion", "deep_learning", "ensemble"],
        "challenge_types": ["blink", "head_turn", "smile", "random"],
        "attack_types": ["print", "mask", "replay", "3d_mask"],
    }


# ===========================================================================
# ROUTER 4: FEDERATED LEARNING
# ===========================================================================

router_federated = APIRouter(prefix="/federated", tags=["Federated Learning"])


class FederatedRoundStartRequest(BaseModel):
    model_type: Optional[str] = "face_recognition"
    num_participants: Optional[int] = 5


class FederatedClientUpdateRequest(BaseModel):
    round_id: UUID
    participant_id: str
    local_accuracy: float = Field(..., ge=0.0, le=1.0)
    num_samples: int = Field(..., ge=1)


@router_federated.post("/round/start")
async def start_federated_round(
    payload: FederatedRoundStartRequest = Body(...),
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Start a federated learning round with distributed organizations."""
    user, org_id = _get_user_org(db, current_user_id)
    service = FederatedLearningService(db)
    try:
        global_model_id = await service.initialize_global_model(
            model_type=payload.model_type or "face_recognition",
        )
        round_id = await service.start_federated_round(
            global_model_id=global_model_id,
            num_participants=payload.num_participants or 5,
        )
        return {
            "round_id": str(round_id),
            "global_model_id": str(global_model_id),
            "model_type": payload.model_type,
            "num_participants": payload.num_participants,
            "status": "started",
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Federated round start error: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router_federated.post("/client/submit-update")
async def submit_federated_update(
    payload: FederatedClientUpdateRequest = Body(...),
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Submit local training update from participant organization."""
    user, org_id = _get_user_org(db, current_user_id)
    service = FederatedLearningService(db)
    try:
        await service.submit_client_update(
            round_id=payload.round_id,
            participant_id=payload.participant_id,
            local_weights=b"",  # weights transmitted separately or via object store
            local_accuracy=payload.local_accuracy,
            num_samples=payload.num_samples,
        )
        return {
            "round_id": str(payload.round_id),
            "participant_id": payload.participant_id,
            "local_accuracy": payload.local_accuracy,
            "num_samples": payload.num_samples,
            "status": "submitted",
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Federated client update error: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router_federated.get("/round/{round_id}/status")
async def get_federated_round_status(
    round_id: UUID,
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get status of federated learning round."""
    user, org_id = _get_user_org(db, current_user_id)
    service = FederatedLearningService(db)
    try:
        # Attempt aggregation check (returns None if not enough participants)
        aggregated = await service.aggregate_updates_fedavg(round_id)
        is_complete = aggregated is not None

        return {
            "round_id": str(round_id),
            "is_complete": is_complete,
            "aggregated": is_complete,
            "status": "complete" if is_complete else "in_progress",
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Federated round status error: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


# ===========================================================================
# ROUTER 5: EMOTION & ACTION RECOGNITION
# ===========================================================================

router_emotion_action = APIRouter(prefix="/emotion-action", tags=["Emotion & Action"])


class DetectEmotionRequest(BaseModel):
    detection_log_id: UUID
    image_path: str


class DetectActionRequest(BaseModel):
    detection_log_id: UUID
    video_path: str


@router_emotion_action.post("/detect-emotion")
async def detect_emotion(
    payload: DetectEmotionRequest = Body(...),
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Detect emotion from facial expression (7-class classifier)."""
    user, org_id = _get_user_org(db, current_user_id)
    safe_image_path = validate_user_path(payload.image_path)
    service = EmotionActionRecognitionService(db)
    try:
        result = await service.detect_emotion(
            image_path=safe_image_path,
            detection_log_id=payload.detection_log_id,
        )
        return {
            "detection_log_id": str(payload.detection_log_id),
            "emotions": result,
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Emotion detection error: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router_emotion_action.post("/detect-action")
async def detect_action(
    payload: DetectActionRequest = Body(...),
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Detect actions/gestures and pose from video."""
    user, org_id = _get_user_org(db, current_user_id)
    safe_video_path = validate_user_path(payload.video_path)
    service = EmotionActionRecognitionService(db)
    try:
        result = await service.detect_action(
            video_path=safe_video_path,
            detection_log_id=payload.detection_log_id,
        )
        return {
            "detection_log_id": str(payload.detection_log_id),
            "actions": result,
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Action detection error: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router_emotion_action.get("/emotions-summary/{visitor_id}")
async def get_emotion_summary(
    visitor_id: UUID,
    days: int = Query(7, ge=1, le=365),
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get emotion patterns for visitor over time period."""
    user, org_id = _get_user_org(db, current_user_id)
    service = EmotionActionRecognitionService(db)
    try:
        result = await service.get_emotion_summary(
            visitor_id=visitor_id,
            days=days,
        )
        return {
            "visitor_id": str(visitor_id),
            "days": days,
            "summary": result,
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Emotion summary error: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


# ===========================================================================
# ROUTER 6: CROSS-CAMERA RE-ID
# ===========================================================================

router_reid = APIRouter(prefix="/reid", tags=["Cross-Camera Re-ID"])


class TrackTransitionRequest(BaseModel):
    visitor_id: UUID
    from_camera_id: UUID
    to_camera_id: UUID
    from_detection_log_id: UUID
    to_detection_log_id: UUID
    transition_time_seconds: float = Field(..., ge=0.0)
    reid_confidence: float = Field(..., ge=0.0, le=1.0)


@router_reid.post("/track-transition")
async def track_camera_transition(
    payload: TrackTransitionRequest = Body(...),
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Track visitor transition between cameras for cross-camera re-ID."""
    user, org_id = _get_user_org(db, current_user_id)
    service = CrossCameraReIDService(db)
    try:
        await service.track_camera_transition(
            visitor_id=payload.visitor_id,
            from_camera_id=payload.from_camera_id,
            to_camera_id=payload.to_camera_id,
            from_detection_log_id=payload.from_detection_log_id,
            to_detection_log_id=payload.to_detection_log_id,
            transition_time_seconds=payload.transition_time_seconds,
            reid_confidence=payload.reid_confidence,
        )
        return {
            "visitor_id": str(payload.visitor_id),
            "from_camera_id": str(payload.from_camera_id),
            "to_camera_id": str(payload.to_camera_id),
            "transition_time_seconds": payload.transition_time_seconds,
            "reid_confidence": payload.reid_confidence,
            "status": "recorded",
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Track transition error: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router_reid.get("/movement-summary/{visitor_id}")
async def get_movement_summary(
    visitor_id: UUID,
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get visitor's cross-camera movement summary."""
    user, org_id = _get_user_org(db, current_user_id)
    service = CrossCameraReIDService(db)
    try:
        path = await service.get_movement_path(visitor_id=visitor_id)
        return {
            "visitor_id": str(visitor_id),
            "movement_path": path,
            "total_transitions": len(path) if path else 0,
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Movement summary error: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


# ===========================================================================
# ROUTER 7: EDGE DEPLOYMENT
# ===========================================================================

router_edge = APIRouter(prefix="/edge", tags=["Edge Deployment"])


class ExportModelRequest(BaseModel):
    model_version_id: UUID
    quantization_type: Optional[str] = None
    target_device: Optional[str] = "jetson"


class DeployModelRequest(BaseModel):
    device_id: UUID
    onnx_model_id: UUID


@router_edge.post("/export-model")
async def export_model_for_edge(
    payload: ExportModelRequest = Body(...),
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Export model to ONNX format for edge devices."""
    user, org_id = _get_user_org(db, current_user_id)
    service = EdgeDeploymentService(db)
    try:
        onnx_bytes = await service.convert_to_onnx(
            model_id=payload.model_version_id,
            model_type="face_recognition",
        )

        if payload.quantization_type:
            onnx_bytes = await service.quantize_model(
                onnx_model_bytes=onnx_bytes,
                quantization_type=payload.quantization_type,
            )

        model_id = await service.register_onnx_model(
            model_bytes=onnx_bytes,
            model_type="face_recognition",
            version="auto",
            accuracy=0.0,
            latency_ms=0.0,
            memory_mb=0.0,
        )

        return {
            "onnx_model_id": str(model_id),
            "model_version_id": str(payload.model_version_id),
            "quantization_type": payload.quantization_type,
            "target_device": payload.target_device,
            "status": "exported",
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Edge export error: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router_edge.post("/deploy")
async def deploy_model_to_device(
    payload: DeployModelRequest = Body(...),
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Deploy ONNX model to edge device."""
    user, org_id = _get_user_org(db, current_user_id)
    service = EdgeDeploymentService(db)
    try:
        result = await service.deploy_to_device(
            device_id=payload.device_id,
            onnx_model_id=payload.onnx_model_id,
        )
        return {
            "device_id": str(payload.device_id),
            "onnx_model_id": str(payload.onnx_model_id),
            "deployment": result,
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Edge deploy error: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router_edge.get("/device/{device_id}/metrics")
async def get_device_metrics(
    device_id: UUID,
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get device performance metrics (latency, throughput, memory)."""
    user, org_id = _get_user_org(db, current_user_id)
    service = EdgeDeploymentService(db)
    try:
        metrics = await service.get_device_metrics(device_id=device_id)
        return {
            "device_id": str(device_id),
            "metrics": metrics,
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Device metrics error: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


# ===========================================================================
# ROUTER 8: ADVANCED ANALYTICS
# ===========================================================================

router_adv_analytics = APIRouter(prefix="/advanced-analytics", tags=["Advanced Analytics"])


@router_adv_analytics.get("/behavior/{visitor_id}")
async def get_behavior_analytics(
    visitor_id: UUID,
    date: Optional[str] = Query(None, description="ISO date string YYYY-MM-DD"),
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get behavior analytics for visitor (anomaly detection, patterns)."""
    user, org_id = _get_user_org(db, current_user_id)
    service = AdvancedAnalyticsService(db)
    try:
        result = await service.compute_behavior_analytics(
            visitor_id=visitor_id,
            date=date,
        )
        return {
            "visitor_id": str(visitor_id),
            "date": date,
            "analytics": result,
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Behavior analytics error: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router_adv_analytics.get("/organization/daily")
async def get_organization_daily_analytics(
    date: Optional[str] = Query(None, description="ISO date string YYYY-MM-DD"),
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get daily organization-wide analytics."""
    user, org_id = _get_user_org(db, current_user_id)
    service = AdvancedAnalyticsService(db)
    try:
        result = await service.compute_organization_daily_analytics(
            org_id=org_id,
            date=date,
        )
        return {
            "organization_id": str(org_id),
            "date": date,
            "analytics": result,
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Organization daily analytics error: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


# ===========================================================================
# ROUTER 9: VISION TRANSFORMER
# ===========================================================================

router_vit = APIRouter(prefix="/vit", tags=["Vision Transformer"])


class ViTEmbedRequest(BaseModel):
    detection_log_id: UUID
    image_path: str
    layer: Optional[int] = Field(12, ge=1, le=24)


class ViTAttentionRequest(BaseModel):
    embedding_id: UUID


@router_vit.post("/embed-face")
async def generate_vit_embedding(
    payload: ViTEmbedRequest = Body(...),
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Generate Vision Transformer embedding for face (layer-wise)."""
    user, org_id = _get_user_org(db, current_user_id)
    safe_image_path = validate_user_path(payload.image_path)
    service = VisionTransformerService(db)
    try:
        cls_embedding, patch_embeddings = await service.extract_vit_embedding(
            image_path=safe_image_path,
            layer=payload.layer or 12,
        )
        return {
            "detection_log_id": str(payload.detection_log_id),
            "layer": payload.layer,
            "cls_embedding_dim": cls_embedding.shape[0] if cls_embedding is not None else 0,
            "cls_embedding": cls_embedding.tolist() if cls_embedding is not None else None,
            "patch_count": patch_embeddings.shape[0] if patch_embeddings is not None else 0,
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"ViT embed error: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router_vit.post("/visualize-attention")
async def visualize_vit_attention(
    payload: ViTAttentionRequest = Body(...),
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Visualize ViT attention maps for interpretability."""
    user, org_id = _get_user_org(db, current_user_id)
    service = VisionTransformerService(db)
    try:
        result = await service.generate_vit_interpretability(
            embedding_id=payload.embedding_id,
        )
        return {
            "embedding_id": str(payload.embedding_id),
            "visualization": result,
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"ViT attention visualization error: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


# ===========================================================================
# ROUTER 10: MULTI-SPECTRAL & INFRARED
# ===========================================================================

router_ms_ir = APIRouter(prefix="/multispectral", tags=["Multi-Spectral"])


class ThermalCaptureRequest(BaseModel):
    visitor_id: UUID
    thermal_image_path: str
    ambient_temp_c: float


class MultispectralCaptureRequest(BaseModel):
    visitor_id: UUID
    visible_image_path: str
    nir_image_path: str
    swir_image_path: str
    thermal_image_path: str


@router_ms_ir.post("/capture-thermal")
async def capture_thermal_data(
    payload: ThermalCaptureRequest = Body(...),
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Capture and analyze thermal (infrared) face data."""
    user, org_id = _get_user_org(db, current_user_id)
    assert_belongs_to_org(db, models.Visitor, payload.visitor_id, org_id)
    safe_thermal_path = validate_user_path(payload.thermal_image_path)
    service = MultiSpectralInfraredService(db)
    try:
        result = await service.process_thermal_image(
            thermal_image_path=safe_thermal_path,
            ambient_temp_c=payload.ambient_temp_c,
        )
        return {
            "visitor_id": str(payload.visitor_id),
            "thermal_analysis": result,
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Thermal capture error: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router_ms_ir.post("/capture-multispectral")
async def capture_multispectral_data(
    payload: MultispectralCaptureRequest = Body(...),
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Capture multi-spectral face data (visible, NIR, SWIR, thermal)."""
    user, org_id = _get_user_org(db, current_user_id)
    assert_belongs_to_org(db, models.Visitor, payload.visitor_id, org_id)
    safe_visible = validate_user_path(payload.visible_image_path)
    safe_nir = validate_user_path(payload.nir_image_path)
    safe_swir = validate_user_path(payload.swir_image_path)
    safe_thermal = validate_user_path(payload.thermal_image_path)
    service = MultiSpectralInfraredService(db)
    try:
        band_embeddings = await service.process_multispectral_image(
            visible_path=safe_visible,
            nir_path=safe_nir,
            swir_path=safe_swir,
            thermal_path=safe_thermal,
        )

        spoofing_result = await service.detect_spoofing_multispectral(
            visible_path=safe_visible,
            nir_path=safe_nir,
            thermal_path=safe_thermal,
        )

        return {
            "visitor_id": str(payload.visitor_id),
            "bands_processed": list(band_embeddings.keys()) if band_embeddings else [],
            "spoofing_analysis": spoofing_result,
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Multispectral capture error: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


# ===========================================================================
# ROUTER 11: MOBILE / PWA
# ===========================================================================

router_mobile = APIRouter(prefix="/mobile", tags=["Mobile/PWA"])


class RegisterPushRequest(BaseModel):
    device_token: str
    device_type: Optional[str] = "ios"


class OfflineDetection(BaseModel):
    image_path: str
    timestamp: str
    camera_id: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None


class SyncOfflineRequest(BaseModel):
    detections: List[OfflineDetection]


@router_mobile.post("/register-push")
async def register_push_notification(
    payload: RegisterPushRequest = Body(...),
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Register device for push notifications."""
    user, org_id = _get_user_org(db, current_user_id)
    service = MobilePWAService(db)
    try:
        await service.register_device_token(
            user_id=current_user_id,
            device_token=payload.device_token,
            device_type=payload.device_type or "ios",
        )
        return {
            "device_token": payload.device_token,
            "device_type": payload.device_type,
            "status": "registered",
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Push registration error: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router_mobile.post("/sync-offline")
async def sync_offline_detections(
    payload: SyncOfflineRequest = Body(...),
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Sync detections captured offline on mobile device."""
    user, org_id = _get_user_org(db, current_user_id)
    service = MobilePWAService(db)
    try:
        detections_raw = [d.model_dump() for d in payload.detections]
        result = await service.sync_offline_detections(
            user_id=current_user_id,
            detections=detections_raw,
        )
        return {
            "synced_count": len(payload.detections),
            "result": result,
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Offline sync error: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


# ===========================================================================
# ROUTER 12: WEBHOOKS & INTEGRATIONS
# ===========================================================================

router_integrations = APIRouter(prefix="/integrations", tags=["Integrations"])


class CreateWebhookRequest(BaseModel):
    url: str
    event_types: List[str]
    auth_type: Optional[str] = "bearer"
    auth_token: Optional[str] = None


class VMSSyncRequest(BaseModel):
    vms_type: str
    api_endpoint: str
    credentials: Dict[str, str]


class HRSyncRequest(BaseModel):
    hr_system: str
    api_endpoint: str


@router_integrations.post("/webhook")
async def create_webhook(
    payload: CreateWebhookRequest = Body(...),
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Create webhook for events (visitor detected, matched, alert triggered)."""
    user, org_id = _get_user_org(db, current_user_id)
    service = WebhooksIntegrationService(db)
    try:
        webhook_id = await service.create_webhook(
            org_id=org_id,
            url=payload.url,
            event_types=payload.event_types,
            auth_type=payload.auth_type or "bearer",
            auth_token=payload.auth_token,
        )
        return {
            "webhook_id": str(webhook_id),
            "url": payload.url,
            "event_types": payload.event_types,
            "auth_type": payload.auth_type,
            "status": "created",
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Webhook creation error: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router_integrations.post("/vms-sync")
async def configure_vms_integration(
    payload: VMSSyncRequest = Body(...),
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Configure VMS (Salto, Kisi, etc) integration for access control."""
    user, org_id = _get_user_org(db, current_user_id)
    service = WebhooksIntegrationService(db)
    try:
        result = await service.configure_vms_integration(
            org_id=org_id,
            vms_type=payload.vms_type,
            api_endpoint=payload.api_endpoint,
            credentials=payload.credentials,
        )
        return {
            "vms_type": payload.vms_type,
            "api_endpoint": payload.api_endpoint,
            "integration": result,
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"VMS sync error: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router_integrations.post("/hr-sync")
async def configure_hr_integration(
    payload: HRSyncRequest = Body(...),
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Configure HR system integration (Workday, BambooHR, etc)."""
    user, org_id = _get_user_org(db, current_user_id)
    service = WebhooksIntegrationService(db)
    try:
        result = await service.configure_hr_integration(
            org_id=org_id,
            hr_system=payload.hr_system,
            api_endpoint=payload.api_endpoint,
        )
        return {
            "hr_system": payload.hr_system,
            "api_endpoint": payload.api_endpoint,
            "integration": result,
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"HR sync error: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


# ===========================================================================
# ROUTER 13: A/B TESTING & MODEL VERSIONING
# ===========================================================================

router_ab_testing = APIRouter(prefix="/ab-testing", tags=["A/B Testing"])


class StartExperimentRequest(BaseModel):
    name: str
    model_a_id: UUID
    model_b_id: UUID
    traffic_split_percent: Optional[int] = Field(50, ge=1, le=99)


@router_ab_testing.post("/experiment/start")
async def start_ab_test(
    payload: StartExperimentRequest = Body(...),
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Start A/B test comparing two model versions."""
    user, org_id = _get_user_org(db, current_user_id)
    service = ModelVersioningABTestService(db)
    try:
        experiment_id = await service.start_ab_test(
            org_id=org_id,
            name=payload.name,
            model_a_id=payload.model_a_id,
            model_b_id=payload.model_b_id,
            traffic_split_percent=payload.traffic_split_percent or 50,
        )
        return {
            "experiment_id": str(experiment_id),
            "name": payload.name,
            "model_a_id": str(payload.model_a_id),
            "model_b_id": str(payload.model_b_id),
            "traffic_split_percent": payload.traffic_split_percent,
            "status": "started",
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"A/B test start error: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router_ab_testing.get("/experiment/{experiment_id}/results")
async def get_ab_test_results(
    experiment_id: UUID,
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get current A/B test results and winner determination."""
    user, org_id = _get_user_org(db, current_user_id)
    service = ModelVersioningABTestService(db)
    try:
        result = await service.get_ab_test_results(experiment_id=experiment_id)
        return {
            "experiment_id": str(experiment_id),
            "results": result,
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"A/B test results error: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


# ===========================================================================
# ROUTER 14: SECURITY & COMPLIANCE
# ===========================================================================

router_security = APIRouter(prefix="/security", tags=["Security & Compliance"])


class LdapConfigRequest(BaseModel):
    server_url: str
    base_dn: str
    bind_dn: Optional[str] = None
    bind_password: Optional[str] = None


@router_security.post("/ldap-config")
async def configure_ldap(
    payload: LdapConfigRequest = Body(...),
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Configure LDAP authentication for directory sync."""
    user, org_id = _get_user_org(db, current_user_id)
    service = AdvancedSecurityComplianceService(db)
    try:
        result = await service.configure_ldap(
            org_id=org_id,
            server_url=payload.server_url,
            base_dn=payload.base_dn,
            bind_dn=payload.bind_dn,
            bind_password=payload.bind_password,
        )
        return {
            "server_url": payload.server_url,
            "base_dn": payload.base_dn,
            "ldap_config": result,
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"LDAP config error: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router_security.post("/encryption/key-rotation")
async def rotate_encryption_keys(
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Rotate database encryption keys for sensitive data."""
    user, org_id = _get_user_org(db, current_user_id)
    service = AdvancedSecurityComplianceService(db)
    try:
        result = await service.rotate_encryption_keys(org_id=org_id)
        return {
            "organization_id": str(org_id),
            "key_rotation": result,
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Key rotation error: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router_security.get("/compliance-status")
async def get_compliance_status(
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Check compliance with regulations (GDPR, HIPAA, etc)."""
    user, org_id = _get_user_org(db, current_user_id)
    service = AdvancedSecurityComplianceService(db)
    try:
        result = await service.get_compliance_status(org_id=org_id)
        return {
            "organization_id": str(org_id),
            "compliance": result,
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Compliance status error: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router_security.get("/audit-report")
async def get_audit_report(
    date_start: str = Query(..., description="ISO date string YYYY-MM-DD"),
    date_end: str = Query(..., description="ISO date string YYYY-MM-DD"),
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Generate comprehensive audit report for a date range."""
    user, org_id = _get_user_org(db, current_user_id)
    service = AdvancedSecurityComplianceService(db)
    try:
        result = await service.generate_audit_report(
            org_id=org_id,
            date_start=date_start,
            date_end=date_end,
        )
        return {
            "organization_id": str(org_id),
            "date_start": date_start,
            "date_end": date_end,
            "audit_report": result,
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Audit report error: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")
