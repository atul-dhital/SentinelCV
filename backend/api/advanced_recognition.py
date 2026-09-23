"""
Phase 3 Advanced Recognition API Endpoints

Unified REST API for:
- Phase 3.2: Multi-Angle Recognition
- Phase 3.3: Cross-Camera ReID
- Phase 3.4: Emotion & Action Detection

All endpoints under /recognition/advanced/
"""

import hashlib
import os
import logging
import sys
import numpy as np
from enum import Enum
from typing import List, Optional, Dict, Any, Tuple
from dataclasses import dataclass, field
from collections import defaultdict
from uuid import UUID
from fastapi import APIRouter, Body, HTTPException, Depends, Query, File, Request, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from datetime import datetime, timezone

from db.base import get_db
from core.security import get_current_user

_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from ai_services.vit_engine import ViTEmbeddingService
from models import models

logger = logging.getLogger(__name__)

SUPPORTED_MULTI_ANGLE_LABELS = (
    "frontal",
    "45_left",
    "45_right",
    "profile",
)

_multi_angle_registry: Dict[str, "MultiAngleEmbeddingSet"] = {}
_emotion_history: Dict[str, List[Dict[str, Any]]] = defaultdict(list)


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _stable_seed(text: str) -> int:
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return int(digest[:16], 16)


def _vector_from_seed(seed_text: str, dimensions: int) -> List[float]:
    rng = np.random.default_rng(_stable_seed(seed_text))
    return rng.normal(0.0, 1.0, dimensions).astype(float).tolist()


def _normalize_vector(values: List[float]) -> List[float]:
    array = np.asarray(values, dtype=float)
    norm = float(np.linalg.norm(array))
    if norm <= 1e-12:
        return array.tolist()
    return (array / norm).astype(float).tolist()


def _normalize_angle_name(raw_name: str, yaw: float = 0.0) -> str:
    cleaned = (raw_name or "").strip().lower().replace("-", "_").replace(" ", "_")
    aliases = {
        "front": "frontal",
        "front_face": "frontal",
        "frontal_face": "frontal",
        "profile_left": "profile",
        "profile_right": "profile",
        "left_profile": "profile",
        "right_profile": "profile",
        "side": "profile",
        "tilted_left": "45_left",
        "tilted_right": "45_right",
        "three_quarter_left": "45_left",
        "three_quarter_right": "45_right",
        "45_degree_left": "45_left",
        "45_degree_right": "45_right",
    }
    if cleaned in SUPPORTED_MULTI_ANGLE_LABELS:
        return cleaned
    if cleaned in aliases:
        return aliases[cleaned]
    if cleaned == "profile":
        return "profile"
    if yaw <= -30.0:
        return "45_left" if yaw > -65.0 else "profile"
    if yaw >= 30.0:
        return "45_right" if yaw < 65.0 else "profile"
    return "frontal"


def _cosine_similarity(left: List[float], right: List[float]) -> float:
    if not left or not right:
        return 0.0
    dim = min(len(left), len(right))
    if dim == 0:
        return 0.0
    l = np.asarray(left[:dim], dtype=float)
    r = np.asarray(right[:dim], dtype=float)
    left_norm = float(np.linalg.norm(l))
    right_norm = float(np.linalg.norm(r))
    if left_norm <= 1e-12 or right_norm <= 1e-12:
        return 0.0
    return float(np.dot(l, r) / (left_norm * right_norm))


def _average_vectors(vectors: List[List[float]]) -> List[float]:
    if not vectors:
        return []
    min_dim = min(len(vector) for vector in vectors if vector)
    if min_dim <= 0:
        return []
    trimmed = np.asarray([vector[:min_dim] for vector in vectors], dtype=float)
    averaged = trimmed.mean(axis=0)
    return _normalize_vector(averaged.tolist())


def _softmax_distribution(scores: Dict[str, float]) -> Dict[str, float]:
    if not scores:
        return {}
    labels = list(scores.keys())
    values = np.asarray([float(scores[label]) for label in labels], dtype=float)
    values = values - float(values.max(initial=0.0))
    exp_values = np.exp(values)
    denominator = float(exp_values.sum())
    if denominator <= 1e-12:
        uniform = 1.0 / max(len(labels), 1)
        return {label: uniform for label in labels}
    return {
        label: float(exp_values[idx] / denominator)
        for idx, label in enumerate(labels)
    }


def _record_emotion_event(visitor_id: str, emotion: "EmotionLabel", confidence: float):
    if not visitor_id:
        return
    _emotion_history[visitor_id].append(
        {
            "timestamp": _utcnow_iso(),
            "emotion": emotion.value,
            "confidence": float(confidence),
        }
    )
    _emotion_history[visitor_id] = _emotion_history[visitor_id][-100:]


def _persist_emotion_behavior_event(
    db: Session,
    visitor_id: str,
    profile: Dict[str, Any],
    *,
    camera_id: Optional[str] = None,
    source: str = "advanced_recognition",
) -> Optional[models.BehaviorEvent]:
    visitor_uuid = _parse_uuid(visitor_id)
    if visitor_uuid is None:
        return None

    visitor = db.query(models.Visitor).filter(
        models.Visitor.id == str(visitor_uuid),
    ).first()
    if visitor is None:
        return None

    camera_uuid = _parse_uuid(camera_id)
    event = models.BehaviorEvent(
        organization_id=visitor.organization_id,
        visitor_id=visitor.id,
        camera_id=str(camera_uuid) if camera_uuid is not None else None,
        event_type="behavior",
        source=source,
        action=str(profile.get("dominant_emotion") or "neutral"),
        confidence=float(profile.get("confidence") or 0.0),
        anomaly_score=0.0,
        anomaly_label="emotion_observation",
        severity="info",
        details={
            "emotions": dict(profile.get("emotions") or {}),
            "dominant_emotion": profile.get("dominant_emotion"),
            "valence": float(profile.get("valence") or 0.0),
            "arousal": float(profile.get("arousal") or 0.0),
            "stability": float(profile.get("stability") or 0.0),
            "intensity": float(profile.get("intensity") or 0.0),
        },
    )
    db.add(event)
    db.commit()
    db.refresh(event)
    return event


def reset_runtime_state():
    """Clear in-memory registries used by the advanced recognition demo runtime."""
    global _vit_service, _unified_engine, _camera_map
    _multi_angle_registry.clear()
    _emotion_history.clear()
    _vit_service = None
    _unified_engine = None
    _camera_map = {}


# ─────────────────────────────────────────────────────────────────────────────
# INLINE ENGINE ADAPTERS (shared ViT service + in-process heuristics)
# ─────────────────────────────────────────────────────────────────────────────

class EmotionLabel(Enum):
    HAPPY = "happy"
    SAD = "sad"
    ANGRY = "angry"
    SURPRISED = "surprised"
    NEUTRAL = "neutral"
    FEAR = "fear"
    DISGUST = "disgust"


@dataclass
class RecognitionResult:
    subject_id: Optional[str] = None
    confidence: float = 0.0
    camera_id: str = ""
    timestamp: str = ""


@dataclass
class CameraLocation:
    camera_id: str = ""
    name: str = ""
    location: tuple = (0.0, 0.0)
    zone: str = ""


@dataclass
class MultiAngleEmbeddingSet:
    visitor_id: str = ""
    embeddings: Dict[str, Any] = field(default_factory=dict)
    completeness: float = 0.0
    timestamp: str = ""


class EmotionClassifier:
    """Classifies emotions from face embeddings."""

    VALENCE_MAP: Dict[EmotionLabel, float] = {
        EmotionLabel.HAPPY: 0.8,
        EmotionLabel.SURPRISED: 0.35,
        EmotionLabel.NEUTRAL: 0.0,
        EmotionLabel.SAD: -0.6,
        EmotionLabel.ANGRY: -0.7,
        EmotionLabel.FEAR: -0.5,
        EmotionLabel.DISGUST: -0.45,
    }
    AROUSAL_MAP: Dict[EmotionLabel, float] = {
        EmotionLabel.HAPPY: 0.55,
        EmotionLabel.SURPRISED: 0.9,
        EmotionLabel.NEUTRAL: 0.15,
        EmotionLabel.SAD: 0.2,
        EmotionLabel.ANGRY: 0.85,
        EmotionLabel.FEAR: 0.78,
        EmotionLabel.DISGUST: 0.45,
    }

    def classify_distribution(self, embedding: List[float]) -> Dict[EmotionLabel, float]:
        if not embedding:
            return {EmotionLabel.NEUTRAL: 1.0}

        vector = np.asarray([float(value) for value in embedding], dtype=float)
        if vector.size < len(EmotionLabel):
            vector = np.resize(vector, len(EmotionLabel) * 8)
        vector = np.tanh(vector)
        segments = [segment for segment in np.array_split(vector, len(EmotionLabel)) if segment.size > 0]

        segment_means = [float(segment.mean()) for segment in segments]
        segment_energy = [float(np.mean(np.abs(segment))) for segment in segments]
        global_mean = float(vector.mean())
        global_std = float(vector.std())
        global_energy = float(np.mean(np.abs(vector)))
        positive_ratio = float(np.mean(vector > 0))
        negative_ratio = float(np.mean(vector < 0))

        raw_scores = {
            EmotionLabel.NEUTRAL.value: 1.15 - (0.75 * global_std) - (0.25 * global_energy) - (0.2 * abs(global_mean)),
            EmotionLabel.HAPPY.value: (0.65 * segment_means[1]) + (0.3 * positive_ratio) + (0.2 * (1.0 - global_std)),
            EmotionLabel.SAD.value: (0.45 * negative_ratio) + (0.25 * max(-segment_means[2], 0.0)) + (0.2 * (1.0 - global_energy)),
            EmotionLabel.ANGRY.value: (0.55 * global_energy) + (0.35 * max(segment_means[3], 0.0)) + (0.25 * global_std),
            EmotionLabel.SURPRISED.value: (0.5 * segment_energy[6]) + (0.45 * global_std) + (0.15 * positive_ratio),
            EmotionLabel.FEAR.value: (0.35 * negative_ratio) + (0.4 * global_std) + (0.2 * segment_energy[4]),
            EmotionLabel.DISGUST.value: (0.3 * negative_ratio) + (0.35 * segment_energy[5]) + (0.2 * abs(segment_means[5] - global_mean)),
        }
        probabilities = _softmax_distribution(raw_scores)
        return {
            EmotionLabel(label): float(probability)
            for label, probability in probabilities.items()
        }

    def describe(self, embedding: List[float]) -> Dict[str, Any]:
        distribution = self.classify_distribution(embedding)
        dominant_emotion = max(distribution, key=distribution.get)
        confidence = float(distribution.get(dominant_emotion, 0.0))
        valence = float(sum(distribution[label] * self.VALENCE_MAP[label] for label in distribution))
        arousal = float(sum(distribution[label] * self.AROUSAL_MAP[label] for label in distribution))
        stability = float(max(0.0, min(1.0, 1.0 - np.std(list(distribution.values())) * 2.25)))
        intensity = float(min(1.0, max(confidence, (confidence * 0.7) + (arousal * 0.3))))
        return {
            "dominant_emotion": dominant_emotion.value,
            "confidence": confidence,
            "intensity": intensity,
            "valence": valence,
            "arousal": arousal,
            "stability": stability,
            "emotions": {
                label.value: round(float(probability), 4)
                for label, probability in distribution.items()
            },
        }

    def classify(self, embedding: List[float]) -> Tuple[EmotionLabel, float]:
        summary = self.describe(embedding)
        return EmotionLabel(summary["dominant_emotion"]), float(summary["confidence"])


class ActionClassifier:
    """Classifies actions from face/body embeddings."""

    def classify(self, embedding: List[float]) -> Dict[str, float]:
        if not embedding:
            return {"standing": 1.0, "walking": 0.0, "talking": 0.0, "other": 0.0}
        movement = abs(float(sum(embedding[:8])))
        walking = min(0.6, (movement % 1.0) * 0.4)
        talking = min(0.3, abs(float(sum(embedding[8:16]))) % 0.3)
        other = min(0.2, abs(float(sum(embedding[16:24]))) % 0.2)
        standing = max(0.0, 1.0 - walking - talking - other)
        raw_actions = {
            "standing": standing,
            "walking": walking,
            "talking": talking,
            "other": other,
        }
        total = sum(raw_actions.values()) or 1.0
        return {key: float(value / total) for key, value in raw_actions.items()}


class TemporalTracker:
    """Tracks visitor movement across cameras over time."""

    def __init__(self):
        self._history: Dict[str, List[Tuple[str, str, float]]] = {}

    def record(self, visitor_id: str, camera_id: str, confidence: float):
        if visitor_id not in self._history:
            self._history[visitor_id] = []
        self._history[visitor_id].append((camera_id, _utcnow_iso(), confidence))

    def get_recent_cameras(self, visitor_id: str) -> List[Tuple[str, str, float]]:
        return self._history.get(visitor_id, [])[-10:]


class MultiAngleRecognitionEngine:
    """Handles multi-angle face embedding creation and matching."""

    def __init__(self, vit_service=None):
        self.vit_service = vit_service

    def create_multi_angle_set(
        self,
        visitor_id: str,
        angle_data: Dict[str, Any],
        *,
        register: bool = True,
    ) -> MultiAngleEmbeddingSet:
        embeddings: Dict[str, Any] = {}
        for angle_name, data in angle_data.items():
            yaw = float(data.get("yaw", 0.0))
            pitch = float(data.get("pitch", 0.0))
            roll = float(data.get("roll", 0.0))
            normalized_angle = _normalize_angle_name(angle_name, yaw)
            angle_confidence = self._estimate_angle_confidence(normalized_angle, yaw, pitch)
            if data.get("image_path"):
                embedding = self.vit_service.extract_embedding(str(data["image_path"]))[:512]
            else:
                seed = (
                    f"{visitor_id}|{normalized_angle}|"
                    f"{yaw:.4f}|{pitch:.4f}|{roll:.4f}"
                )
                embedding = _vector_from_seed(seed, 512)
            embeddings[normalized_angle] = {
                "embedding": _normalize_vector(embedding),
                "yaw": yaw,
                "pitch": pitch,
                "roll": roll,
                "source_angle": angle_name,
                "image_path": data.get("image_path"),
                "confidence": angle_confidence,
            }

        unique_angles = [angle for angle in embeddings if angle in SUPPORTED_MULTI_ANGLE_LABELS]
        completeness = min(len(unique_angles) / len(SUPPORTED_MULTI_ANGLE_LABELS), 1.0)
        embedding_set = MultiAngleEmbeddingSet(
            visitor_id=visitor_id,
            embeddings=embeddings,
            completeness=completeness,
            timestamp=_utcnow_iso(),
        )
        if register:
            _multi_angle_registry[visitor_id] = embedding_set
        return embedding_set

    def _estimate_angle_confidence(self, angle_name: str, yaw: float, pitch: float) -> float:
        expected_yaw = {
            "frontal": 0.0,
            "45_left": -45.0,
            "45_right": 45.0,
            "profile": 75.0,
        }.get(angle_name, 0.0)
        yaw_error = abs(abs(yaw) - abs(expected_yaw)) if angle_name == "profile" else abs(yaw - expected_yaw)
        pitch_penalty = min(abs(pitch) / 25.0, 1.0) * 0.2
        confidence = 0.95 - min(yaw_error / 90.0, 1.0) * 0.35 - pitch_penalty
        return float(max(0.55, min(confidence, 0.98)))


class CrossCameraREIDEngine:
    """Cross-camera re-identification engine."""

    def __init__(self, cameras: Dict[str, CameraLocation] = None):
        self.cameras = cameras or {}
        self.temporal_tracker = TemporalTracker()

    def identify_across_cameras(
        self,
        embedding: List[float],
        current_camera: str,
        gallery: List[Any],
        use_temporal: bool = True,
    ) -> Optional[RecognitionResult]:
        normalized_embedding = _normalize_vector([float(value) for value in embedding]) if embedding else []
        gallery_vectors: List[Tuple[str, List[float]]] = []

        if gallery:
            for item in gallery:
                if isinstance(item, dict):
                    visitor_id = item.get("visitor_id")
                    vector = item.get("embedding")
                    if not vector:
                        multi_angle_set = item.get("multi_angle_set")
                        if isinstance(multi_angle_set, MultiAngleEmbeddingSet):
                            vectors = [
                                _extract_angle_embedding(payload)
                                for payload in multi_angle_set.embeddings.values()
                            ]
                            vector = _average_vectors([candidate for candidate in vectors if candidate])
                    if visitor_id and vector:
                        gallery_vectors.append((str(visitor_id), [float(v) for v in vector]))

        if not gallery_vectors:
            for visitor_id, embedding_set in _multi_angle_registry.items():
                vectors = []
                for payload in embedding_set.embeddings.values():
                    if isinstance(payload, dict):
                        candidate = payload.get("embedding")
                    else:
                        candidate = payload
                    if candidate:
                        vectors.append([float(value) for value in candidate])
                averaged = _average_vectors(vectors)
                if averaged:
                    gallery_vectors.append((visitor_id, averaged))

        if not gallery_vectors or not normalized_embedding:
            return RecognitionResult(
                subject_id=None,
                confidence=0.0,
                camera_id=current_camera,
                timestamp=_utcnow_iso(),
            )

        best_match: Optional[str] = None
        best_score = 0.0
        for visitor_id, candidate in gallery_vectors:
            score = _cosine_similarity(normalized_embedding, candidate)
            if use_temporal:
                recent_cameras = self.temporal_tracker.get_recent_cameras(visitor_id)
                if recent_cameras:
                    last_camera = recent_cameras[-1][0]
                    if last_camera == current_camera:
                        score = min(0.99, score * 1.04)
                    else:
                        predicted_camera, _ = self.predict_next_location(visitor_id)
                        if predicted_camera == current_camera:
                            score = min(0.99, score * 1.02)
            if score > best_score:
                best_match = visitor_id
                best_score = score

        if best_match and best_score >= 0.62:
            confidence = float(min(0.99, max(0.62, best_score)))
            if use_temporal:
                self.temporal_tracker.record(best_match, current_camera, confidence)
            return RecognitionResult(
                subject_id=best_match,
                confidence=confidence,
                camera_id=current_camera,
                timestamp=_utcnow_iso(),
            )

        return RecognitionResult(
            subject_id=None,
            confidence=float(max(0.0, min(best_score, 0.61))),
            camera_id=current_camera,
            timestamp=_utcnow_iso(),
        )

    def predict_next_location(
        self, visitor_id: str
    ) -> Tuple[Optional[str], Optional[float]]:
        recent = self.temporal_tracker.get_recent_cameras(visitor_id)
        if not recent:
            return None, None
        camera_ids = list(self.cameras.keys())
        if camera_ids:
            last_camera = recent[-1][0]
            try:
                current_index = camera_ids.index(last_camera)
            except ValueError:
                current_index = -1
            predicted = camera_ids[(current_index + 1) % len(camera_ids)]
            confidence = min(0.85, 0.45 + len(recent) * 0.05)
            return predicted, float(confidence)
        return None, None


class EmotionActionDetector:
    """Detects emotions and actions from embeddings."""

    def __init__(self):
        self.emotion_classifier = EmotionClassifier()
        self.action_classifier = ActionClassifier()

    def detect_emotion_profile(self, embedding: List[float]) -> Dict[str, Any]:
        return self.emotion_classifier.describe(embedding)

    def detect_emotion(self, embedding: List[float]) -> Tuple[EmotionLabel, float]:
        return self.emotion_classifier.classify(embedding)

    def detect_actions(self, embedding: List[float]) -> Dict[str, float]:
        return self.action_classifier.classify(embedding)

    def compute_behavioral_score(
        self,
        emotion_profile: Dict[str, Any],
        actions: Dict[str, float],
    ) -> Dict[str, float]:
        emotions = emotion_profile.get("emotions", {})
        positive_signal = float(emotions.get("happy", 0.0)) + (0.45 * float(emotions.get("surprised", 0.0)))
        negative_signal = (
            float(emotions.get("sad", 0.0))
            + float(emotions.get("angry", 0.0))
            + float(emotions.get("fear", 0.0))
            + float(emotions.get("disgust", 0.0))
        )
        attentiveness = min(
            1.0,
            (0.45 * float(actions.get("standing", 0.0)))
            + (0.35 * float(actions.get("talking", 0.0)))
            + (0.2 * (1.0 - float(actions.get("other", 0.0)))),
        )
        emotional_stability = float(max(0.0, min(1.0, emotion_profile.get("stability", 0.0))))
        engagement = max(
            0.0,
            min(
                100.0,
                (
                    (positive_signal * 45.0)
                    + (attentiveness * 35.0)
                    + (emotional_stability * 20.0)
                    - (negative_signal * 18.0)
                ),
            ),
        )
        return {
            "engagement_score": round(float(engagement), 2),
            "emotional_stability": round(emotional_stability, 4),
            "attentiveness": round(attentiveness, 4),
        }


class VisionTransformerService(ViTEmbeddingService):
    """Advanced-recognition ViT adapter.

    Reuses the shared Vision Transformer implementation instead of keeping a
    second in-file stub. The base service already falls back deterministically
    when timm/torch are unavailable.
    """

    pass


class UnifiedRecognitionEngine:
    """Combines multi-angle, ReID, and emotion/action detection."""

    def __init__(self, vit_service=None, cameras: Dict[str, CameraLocation] = None):
        self.vit_service = vit_service or VisionTransformerService()
        self.multi_angle_engine = MultiAngleRecognitionEngine(self.vit_service)
        self.reid_engine = CrossCameraREIDEngine(cameras or {})
        self.emotion_engine = EmotionActionDetector()

    def recognize_visitor(
        self, embedding: List[float], camera_id: str
    ) -> Dict[str, Any]:
        reid_result = self.reid_engine.identify_across_cameras(
            embedding,
            camera_id,
            gallery=[],
            use_temporal=True,
        )
        emotion, emotion_conf = self.emotion_engine.detect_emotion(embedding)
        actions = self.emotion_engine.detect_actions(embedding)
        predicted_for = reid_result.subject_id if reid_result and reid_result.subject_id else "unknown"
        next_cam, next_conf = self.reid_engine.predict_next_location(predicted_for)

        reid_confidence = reid_result.confidence if reid_result else 0.0
        combined_confidence = max(
            0.0,
            min(1.0, (0.55 * reid_confidence) + (0.45 * float(emotion_conf))),
        )

        return {
            "visitor_id": reid_result.subject_id if reid_result else None,
            "combined_confidence": combined_confidence,
            "modality_results": {
                "multi_angle": {"confidence": reid_confidence},
                "emotion": {
                    "emotion": emotion.value,
                    "confidence": float(emotion_conf),
                },
                "actions": actions,
            },
            "predicted_next_camera": next_cam,
            "predicted_confidence": next_conf,
        }


# ─────────────────────────────────────────────────────────────────────────────
# ROUTER
# ─────────────────────────────────────────────────────────────────────────────

router = APIRouter(prefix="/recognition/advanced", tags=["Phase 3 Advanced"])

# Global service instances
_vit_service: Optional[VisionTransformerService] = None
_unified_engine: Optional[UnifiedRecognitionEngine] = None
_camera_map: Dict[str, CameraLocation] = {}


# ─────────────────────────────────────────────────────────────────────────────
# REQUEST/RESPONSE SCHEMAS
# ─────────────────────────────────────────────────────────────────────────────

class AngleData(BaseModel):
    """Face angle data."""
    angle_name: str
    image_path: Optional[str] = None
    yaw: float = 0.0
    pitch: float = 0.0
    roll: float = 0.0


class MultiAngleRequest(BaseModel):
    """Request for multi-angle recognition."""
    visitor_id: str
    angle_data: List[AngleData]
    threshold: float = 0.60


class MultiAngleResponse(BaseModel):
    """Multi-angle recognition response."""
    visitor_id: str
    completeness: float
    angles_processed: int
    timestamp: str


class CameraInfo(BaseModel):
    """Camera metadata."""
    camera_id: str
    name: str
    location: tuple
    zone: str


class CrossCameraREIDRequest(BaseModel):
    """Request for cross-camera tracking."""
    embedding: List[float]
    current_camera: str
    use_temporal: bool = True


class CrossCameraREIDResponse(BaseModel):
    """Cross-camera ReID response."""
    visitor_id: Optional[str]
    confidence: float
    camera: str
    predicted_next_camera: Optional[str]
    predicted_confidence: Optional[float]


class EmotionDetectionResponse(BaseModel):
    """Emotion detection response.

    `method` documents how the result was produced. It is currently a
    deterministic heuristic over ViT embeddings (no trained emotion classifier);
    consumers should not treat it as trained-model output. See docs/MODEL_WEIGHTS.md.
    """
    emotion: str
    confidence: float
    intensity: float
    method: str = "heuristic_embedding_v1"


class ActionDetectionResponse(BaseModel):
    """Detected actions."""
    actions: Dict[str, float]
    primary_action: str
    action_confidence: float


class BehavioralScore(BaseModel):
    """Behavioral metrics."""
    engagement_score: float
    emotional_stability: float
    attentiveness: float
    overall_sentiment: str


class UnifiedRecognitionRequest(BaseModel):
    """Request for unified recognition."""
    embedding: List[float]
    camera_id: str
    visitor_id: Optional[str] = None
    multi_angle_data: Optional[List[AngleData]] = None
    include_emotion: bool = True
    include_behavior: bool = True


class UnifiedRecognitionResponse(BaseModel):
    """Unified recognition response."""
    visitor_id: Optional[str]
    multi_angle_confidence: Optional[float]
    emotion: Optional[str]
    emotion_confidence: Optional[float]
    engagement_score: Optional[float]
    combined_confidence: float
    predicted_next_camera: Optional[str]
    predicted_confidence: Optional[float]


# ─────────────────────────────────────────────────────────────────────────────
# HELPER FUNCTIONS
# ─────────────────────────────────────────────────────────────────────────────

def get_vit_service() -> VisionTransformerService:
    """Get or initialize ViT service."""
    global _vit_service
    if _vit_service is None:
        _vit_service = VisionTransformerService()
    return _vit_service


def get_unified_engine(
    camera_map: Optional[Dict[str, CameraLocation]] = None,
) -> UnifiedRecognitionEngine:
    """Get or initialize unified recognition engine."""
    global _unified_engine, _camera_map
    if camera_map:
        _camera_map = dict(camera_map)
    elif not _camera_map:
        _camera_map = _get_cameras()

    if _unified_engine is None:
        vit = get_vit_service()
        _unified_engine = UnifiedRecognitionEngine(vit, dict(_camera_map))
    elif camera_map:
        _unified_engine.reid_engine.cameras = dict(_camera_map)
    return _unified_engine


def _get_cameras() -> Dict[str, CameraLocation]:
    """Get camera map."""
    return {
        "entrance": CameraLocation(
            camera_id="entrance",
            name="Main Entrance",
            location=(40.7128, -74.0060),
            zone="entry",
        ),
        "lobby": CameraLocation(
            camera_id="lobby",
            name="Lobby",
            location=(40.7129, -74.0061),
            zone="main",
        ),
        "exit": CameraLocation(
            camera_id="exit",
            name="Exit",
            location=(40.7130, -74.0062),
            zone="exit",
        ),
    }


def _parse_uuid(value: Optional[str]) -> Optional[UUID]:
    if value in (None, ""):
        return None
    try:
        return UUID(str(value))
    except (TypeError, ValueError):
        return None


def _coerce_embedding(values: Any) -> List[float]:
    if values is None:
        return []
    try:
        return _normalize_vector([float(value) for value in values])
    except (TypeError, ValueError):
        return []


def _get_user_record(db: Session, user_id: str) -> models.User:
    user = db.query(models.User).filter(models.User.id == user_id).first()
    if user is None:
        raise HTTPException(status_code=401, detail="User not found")
    return user


def _build_camera_map(
    db: Optional[Session] = None,
    organization_id: Optional[object] = None,
) -> Dict[str, CameraLocation]:
    camera_map = dict(_get_cameras())
    if db is None or organization_id is None:
        return camera_map

    rows = db.query(models.Camera).filter(
        models.Camera.organization_id == organization_id
    ).limit(10000).all()
    for camera in rows:
        camera_map[str(camera.id)] = CameraLocation(
            camera_id=str(camera.id),
            name=camera.name,
            location=(0.0, 0.0),
            zone=camera.location or "custom",
        )
    return camera_map


def _merge_multi_angle_set(
    records: Dict[str, Dict[str, Any]],
    visitor_id: str,
    embedding_set: MultiAngleEmbeddingSet,
) -> None:
    record = records.setdefault(
        visitor_id,
        {
            "visitor_id": visitor_id,
            "vectors": [],
            "angles": {},
            "primary_embedding": None,
        },
    )
    for angle_name, payload in embedding_set.embeddings.items():
        if not isinstance(payload, dict):
            continue
        embedding = _coerce_embedding(payload.get("embedding"))
        if not embedding:
            continue

        candidate = {
            "embedding": embedding,
            "confidence": float(payload.get("confidence") or 0.75),
            "image_path": payload.get("image_path"),
            "source_angle": payload.get("source_angle", angle_name),
        }
        existing = record["angles"].get(angle_name)
        if existing is None or candidate["confidence"] >= float(existing.get("confidence") or 0.0):
            record["angles"][angle_name] = candidate
        record["vectors"].append(embedding)

    frontal_payload = record["angles"].get("frontal")
    if frontal_payload:
        record["primary_embedding"] = frontal_payload["embedding"]
    elif record["primary_embedding"] is None:
        record["primary_embedding"] = _average_vectors(record["vectors"])


def _build_gallery_records(db: Session, organization_id: object) -> List[Dict[str, Any]]:
    records: Dict[str, Dict[str, Any]] = {}

    rows = (
        db.query(models.FaceData, models.Visitor)
        .join(models.Visitor, models.FaceData.visitor_id == models.Visitor.id)
        .filter(
            models.Visitor.organization_id == organization_id,
            models.Visitor.is_active == True,
        )
        .limit(100000).all()
    )

    for face_data, visitor in rows:
        visitor_id = str(visitor.id)
        record = records.setdefault(
            visitor_id,
            {
                "visitor_id": visitor_id,
                "visitor_name": visitor.name,
                "vectors": [],
                "angles": {},
                "primary_embedding": None,
            },
        )
        embedding = _coerce_embedding(face_data.embedding)
        if not embedding:
            continue

        normalized_angle = _normalize_angle_name(str(face_data.face_angle or "frontal"))
        quality_score = float(face_data.quality_score or 0.75)
        candidate = {
            "embedding": embedding,
            "confidence": max(0.55, min(0.98, quality_score if quality_score > 0 else 0.75)),
            "image_path": face_data.image_url,
            "source_angle": normalized_angle,
        }
        existing = record["angles"].get(normalized_angle)
        existing_score = float(existing.get("confidence") or 0.0) if existing else 0.0
        if existing is None or face_data.is_primary or candidate["confidence"] >= existing_score:
            record["angles"][normalized_angle] = candidate
        record["vectors"].append(embedding)

        if face_data.is_primary or record["primary_embedding"] is None:
            record["primary_embedding"] = embedding

    for visitor_id, embedding_set in _multi_angle_registry.items():
        _merge_multi_angle_set(records, visitor_id, embedding_set)

    gallery_records: List[Dict[str, Any]] = []
    for visitor_id, record in records.items():
        angles = record.get("angles", {})
        primary_embedding = record.get("primary_embedding") or _average_vectors(record.get("vectors", []))
        if not primary_embedding:
            continue
        multi_angle_set = MultiAngleEmbeddingSet(
            visitor_id=visitor_id,
            embeddings=angles,
            completeness=min(len(angles) / len(SUPPORTED_MULTI_ANGLE_LABELS), 1.0),
            timestamp=_utcnow_iso(),
        )
        gallery_records.append(
            {
                "visitor_id": visitor_id,
                "visitor_name": record.get("visitor_name"),
                "embedding": primary_embedding,
                "multi_angle_set": multi_angle_set,
                "registered_angles": sorted(angles.keys()),
            }
        )
    return gallery_records


def _persist_multi_angle_set(
    db: Session,
    organization_id: object,
    embedding_set: MultiAngleEmbeddingSet,
) -> bool:
    visitor_uuid = _parse_uuid(embedding_set.visitor_id)
    if visitor_uuid is None:
        return False
    visitor_key = str(visitor_uuid)

    visitor = db.query(models.Visitor).filter(
        models.Visitor.id == visitor_key,
        models.Visitor.organization_id == organization_id,
    ).first()
    if visitor is None:
        return False

    updated = False
    for angle_name, payload in embedding_set.embeddings.items():
        if not isinstance(payload, dict):
            continue
        embedding = _coerce_embedding(payload.get("embedding"))
        if not embedding:
            continue

        row = db.query(models.FaceData).filter(
            models.FaceData.visitor_id == visitor_key,
            models.FaceData.face_angle == angle_name,
        ).order_by(models.FaceData.created_at.desc()).first()

        quality_score = float(payload.get("confidence") or 0.75)
        if row is None:
            row = models.FaceData(
                visitor_id=visitor.id,
                embedding=embedding,
                image_url=payload.get("image_path"),
                quality_score=quality_score,
                face_angle=angle_name,
                is_primary=angle_name == "frontal",
            )
            db.add(row)
        else:
            row.embedding = embedding
            row.image_url = payload.get("image_path") or row.image_url
            row.quality_score = max(float(row.quality_score or 0.0), quality_score)
            if angle_name == "frontal":
                row.is_primary = True
        updated = True

    if updated:
        db.commit()
    return updated


def _extract_angle_embedding(payload: Any) -> List[float]:
    if isinstance(payload, dict):
        return _coerce_embedding(payload.get("embedding"))
    return _coerce_embedding(payload)


def _match_multi_angle_probe(
    probe_set: Optional[MultiAngleEmbeddingSet],
    gallery_records: List[Dict[str, Any]],
    *,
    threshold: float = 0.60,
) -> Dict[str, Any]:
    if probe_set is None:
        return {"matched": False, "visitor_id": None, "confidence": 0.0, "angles_matched": [], "angle_scores": {}}

    probe_vectors = [
        _extract_angle_embedding(payload)
        for payload in probe_set.embeddings.values()
    ]
    probe_average = _average_vectors([vector for vector in probe_vectors if vector])

    best_match = {"matched": False, "visitor_id": None, "confidence": 0.0, "angles_matched": [], "angle_scores": {}}
    angle_weights = {
        "frontal": 1.0,
        "45_left": 1.15,
        "45_right": 1.15,
        "profile": 1.3,
    }

    for record in gallery_records:
        gallery_set = record.get("multi_angle_set")
        if not isinstance(gallery_set, MultiAngleEmbeddingSet):
            continue

        weighted_sum = 0.0
        total_weight = 0.0
        angle_scores: Dict[str, float] = {}
        for angle_name, probe_payload in probe_set.embeddings.items():
            probe_embedding = _extract_angle_embedding(probe_payload)
            candidate_payload = gallery_set.embeddings.get(angle_name)
            candidate_embedding = _extract_angle_embedding(candidate_payload)
            if not probe_embedding or not candidate_embedding:
                continue

            similarity = _cosine_similarity(probe_embedding, candidate_embedding)
            probe_confidence = float(probe_payload.get("confidence") or 0.75) if isinstance(probe_payload, dict) else 0.75
            candidate_confidence = float(candidate_payload.get("confidence") or 0.75) if isinstance(candidate_payload, dict) else 0.75
            weight = angle_weights.get(angle_name, 1.0) * (0.5 + ((probe_confidence + candidate_confidence) / 2.0))

            weighted_sum += similarity * weight
            total_weight += weight
            angle_scores[angle_name] = round(similarity, 4)

        aggregate_similarity = _cosine_similarity(probe_average, record.get("embedding", [])) if probe_average else 0.0
        if total_weight > 0:
            consensus = weighted_sum / total_weight
            coverage = len(angle_scores) / max(len(probe_set.embeddings), 1)
            combined_confidence = (consensus * (0.75 + (0.15 * coverage))) + (aggregate_similarity * 0.25)
        else:
            combined_confidence = aggregate_similarity

        completeness_bonus = 0.05 * min(probe_set.completeness, gallery_set.completeness)
        final_confidence = float(min(0.99, max(0.0, combined_confidence + completeness_bonus)))
        if final_confidence > best_match["confidence"]:
            best_match = {
                "matched": final_confidence >= threshold,
                "visitor_id": record["visitor_id"],
                "confidence": final_confidence,
                "angles_matched": sorted(angle_scores.keys()),
                "angle_scores": angle_scores,
            }

    return best_match


def _record_transition_summary_from_tracker(
    db: Session,
    organization_id: object,
    visitor_id: str,
    history: List[Tuple[str, str, float]],
) -> None:
    if len(history) < 2:
        return

    current_entry = history[-1]
    previous_entry: Optional[Tuple[str, str, float]] = None
    for candidate in reversed(history[:-1]):
        if candidate[0] != current_entry[0]:
            previous_entry = candidate
            break
    if previous_entry is None:
        return

    visitor_uuid = _parse_uuid(visitor_id)
    previous_camera_uuid = _parse_uuid(previous_entry[0])
    current_camera_uuid = _parse_uuid(current_entry[0])
    if visitor_uuid is None or previous_camera_uuid is None or current_camera_uuid is None:
        return
    if previous_camera_uuid == current_camera_uuid:
        return
    visitor_key = str(visitor_uuid)
    previous_camera_key = str(previous_camera_uuid)
    current_camera_key = str(current_camera_uuid)

    previous_timestamp = datetime.fromisoformat(previous_entry[1])
    current_timestamp = datetime.fromisoformat(current_entry[1])
    transition_seconds = max((current_timestamp - previous_timestamp).total_seconds(), 0.0)
    confidence = float(current_entry[2] or 0.0)

    row = db.query(models.CrossCameraMovementSummary).filter(
        models.CrossCameraMovementSummary.organization_id == organization_id,
        models.CrossCameraMovementSummary.visitor_id == visitor_key,
        models.CrossCameraMovementSummary.from_camera_id == previous_camera_key,
        models.CrossCameraMovementSummary.to_camera_id == current_camera_key,
    ).first()

    if row is None:
        row = models.CrossCameraMovementSummary(
            organization_id=organization_id,
            visitor_id=visitor_key,
            from_camera_id=previous_camera_key,
            to_camera_id=current_camera_key,
            first_seen=previous_timestamp,
            last_seen=current_timestamp,
            transition_count=1,
            sightings=1,
            average_confidence=confidence,
            avg_transition_seconds=transition_seconds,
            reid_score=confidence,
            source="advanced_recognition",
            details={"tracker": "runtime_temporal_history"},
        )
        db.add(row)
    else:
        row.first_seen = min(row.first_seen, previous_timestamp)
        row.last_seen = max(row.last_seen, current_timestamp)
        row.transition_count = int(row.transition_count or 0) + 1
        row.sightings = int(row.sightings or 0) + 1
        previous_avg = float(row.average_confidence or 0.0)
        count = max(int(row.sightings or 1), 1)
        row.average_confidence = ((previous_avg * (count - 1)) + confidence) / count
        row.avg_transition_seconds = transition_seconds
        row.reid_score = max(float(row.reid_score or 0.0), confidence)
        row.source = "advanced_recognition"
    db.commit()


# ─────────────────────────────────────────────────────────────────────────────
# ENDPOINTS: MULTI-ANGLE RECOGNITION (Phase 3.2)
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/multi-angle/register", response_model=MultiAngleResponse)
async def register_multi_angle(
    request: MultiAngleRequest,
    db: Session = Depends(get_db),
    current_user_id: str = Depends(get_current_user),
):
    """Register multi-angle embeddings for a visitor."""
    try:
        user = _get_user_record(db, current_user_id)
        engine = get_unified_engine(_build_camera_map(db, user.organization_id))

        angle_data = {}
        for angle in request.angle_data:
            angle_data[angle.angle_name] = {
                "image_path": angle.image_path,
                "yaw": angle.yaw,
                "pitch": angle.pitch,
                "roll": angle.roll,
            }

        embedding_set = engine.multi_angle_engine.create_multi_angle_set(
            request.visitor_id, angle_data
        )

        if not embedding_set:
            raise HTTPException(
                status_code=400,
                detail="Failed to create multi-angle embeddings",
            )

        _persist_multi_angle_set(db, user.organization_id, embedding_set)

        return MultiAngleResponse(
            visitor_id=request.visitor_id,
            completeness=embedding_set.completeness,
            angles_processed=len(embedding_set.embeddings),
            timestamp=embedding_set.timestamp,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Multi-angle registration failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/multi-angle/stats")
async def get_multi_angle_stats(
    db: Session = Depends(get_db),
    current_user_id: str = Depends(get_current_user),
):
    """Get statistics about multi-angle coverage."""
    try:
        user = _get_user_record(db, current_user_id)
        gallery_records = _build_gallery_records(db, user.organization_id)
        angle_distribution: Dict[str, int] = {label: 0 for label in SUPPORTED_MULTI_ANGLE_LABELS}
        completeness_values: List[float] = []
        for record in gallery_records:
            embedding_set = record.get("multi_angle_set")
            if not isinstance(embedding_set, MultiAngleEmbeddingSet):
                continue
            completeness_values.append(float(embedding_set.completeness))
            for angle_name in embedding_set.embeddings.keys():
                angle_distribution[angle_name] = angle_distribution.get(angle_name, 0) + 1

        return {
            "total_visitors": len(gallery_records),
            "average_completeness": float(sum(completeness_values) / len(completeness_values)) if completeness_values else 0.0,
            "angle_distribution": angle_distribution,
            "registered_visitors": sorted(record["visitor_id"] for record in gallery_records),
        }
    except Exception as e:
        logger.error(f"Failed to get multi-angle stats: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ─────────────────────────────────────────────────────────────────────────────
# ENDPOINTS: CROSS-CAMERA REID (Phase 3.3)
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/reid/identify", response_model=CrossCameraREIDResponse)
async def reid_identify(
    request: CrossCameraREIDRequest,
    db: Session = Depends(get_db),
    current_user_id: str = Depends(get_current_user),
):
    """Identify visitor across cameras using ReID."""
    try:
        user = _get_user_record(db, current_user_id)
        engine = get_unified_engine(_build_camera_map(db, user.organization_id))
        gallery = _build_gallery_records(db, user.organization_id)

        result = engine.reid_engine.identify_across_cameras(
            request.embedding,
            request.current_camera,
            gallery,
            use_temporal=request.use_temporal,
        )

        next_camera, next_confidence = (None, None)
        if result and result.subject_id:
            next_camera, next_confidence = engine.reid_engine.predict_next_location(
                result.subject_id
            )
            history = engine.reid_engine.temporal_tracker.get_recent_cameras(result.subject_id)
            _record_transition_summary_from_tracker(
                db,
                user.organization_id,
                result.subject_id,
                history,
            )

        return CrossCameraREIDResponse(
            visitor_id=result.subject_id if result else None,
            confidence=result.confidence if result else 0.0,
            camera=request.current_camera,
            predicted_next_camera=next_camera,
            predicted_confidence=next_confidence,
        )

    except Exception as e:
        logger.error(f"ReID identification failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/reid/track/{visitor_id}")
async def reid_track(
    visitor_id: str,
    db: Session = Depends(get_db),
    current_user_id: str = Depends(get_current_user),
):
    """Get visitor's movement history across cameras."""
    try:
        user = _get_user_record(db, current_user_id)
        engine = get_unified_engine(_build_camera_map(db, user.organization_id))

        recent_cameras = engine.reid_engine.temporal_tracker.get_recent_cameras(
            visitor_id
        )

        next_camera, confidence = engine.reid_engine.predict_next_location(visitor_id)
        visitor_uuid = _parse_uuid(visitor_id)
        persisted_rows = []
        if visitor_uuid is not None:
            persisted_rows = db.query(models.CrossCameraMovementSummary).filter(
                models.CrossCameraMovementSummary.organization_id == user.organization_id,
                models.CrossCameraMovementSummary.visitor_id == visitor_uuid,
            ).order_by(models.CrossCameraMovementSummary.updated_at.desc()).limit(10).all()

        return {
            "visitor_id": visitor_id,
            "recent_path": [
                {"camera": cam, "timestamp": ts, "confidence": conf}
                for cam, ts, conf in recent_cameras
            ],
            "persisted_movements": [
                {
                    "from_camera": str(row.from_camera_id),
                    "to_camera": str(row.to_camera_id),
                    "transition_count": int(row.transition_count or 0),
                    "reid_score": float(row.reid_score or 0.0),
                }
                for row in persisted_rows
            ],
            "predicted_next_camera": next_camera,
            "predicted_confidence": confidence,
        }

    except Exception as e:
        logger.error(f"Failed to track visitor: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/cameras")
async def list_cameras():
    """Get list of all cameras and their locations."""
    camera_data = _get_cameras()

    return {
        "cameras": [
            {
                "camera_id": cam.camera_id,
                "name": cam.name,
                "location": cam.location,
                "zone": cam.zone,
            }
            for cam in camera_data.values()
        ]
    }


# ─────────────────────────────────────────────────────────────────────────────
# ENDPOINTS: EMOTION & ACTION DETECTION (Phase 3.4)
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/emotion/detect", response_model=EmotionDetectionResponse)
async def detect_emotion(
    embedding: Optional[List[float]] = Body(default=None),
    file: UploadFile = File(None),
    visitor_id: Optional[str] = Query(default=None),
    db: Session = Depends(get_db),
    request: Request = None,
    current_user_id: str = Depends(get_current_user),
):
    """Detect emotion from face embedding or uploaded image."""
    try:
        user = _get_user_record(db, current_user_id)
        if visitor_id:
            visitor = db.query(models.Visitor).filter(models.Visitor.id == visitor_id).first()
            if not visitor or visitor.organization_id != user.organization_id:
                raise HTTPException(status_code=404, detail="Visitor not found")

        engine = get_unified_engine()
        real_result = None

        if file:
            import tempfile
            import shutil
            import os
            import cv2
            from services.emotion_model_service import get_emotion_model_service

            with tempfile.NamedTemporaryFile(delete=False) as tmp:
                shutil.copyfileobj(file.file, tmp)
                tmp_path = tmp.name
            try:
                embedding = engine.multi_angle_engine.vit_service.extract_embedding(
                    tmp_path
                )
                # Trained FER on the image; returns None -> heuristic fallback.
                image_bgr = cv2.imread(tmp_path)
                if image_bgr is not None:
                    real_result = get_emotion_model_service().detect(image_bgr)
            finally:
                os.unlink(tmp_path)

        if not embedding and request is not None:
            try:
                raw_payload = await request.json()
            except Exception:
                raw_payload = None

            if isinstance(raw_payload, list):
                embedding = [float(value) for value in raw_payload]
            elif isinstance(raw_payload, dict) and isinstance(raw_payload.get("embedding"), list):
                embedding = [float(value) for value in raw_payload["embedding"]]

        if not embedding and real_result is None:
            raise HTTPException(
                status_code=400, detail="Could not extract embedding"
            )

        # Heuristic profile is used for behavior-event persistence; the trained
        # model (when available) overrides the user-facing emotion/confidence.
        if embedding:
            emotion_profile = engine.emotion_engine.detect_emotion_profile(embedding)
        else:
            emotion_profile = {
                "dominant_emotion": real_result["emotion"],
                "confidence": real_result["confidence"],
                "scores": real_result.get("scores", {}),
            }

        if real_result is not None:
            emotion = EmotionLabel(real_result["emotion"])
            confidence = float(real_result["confidence"])
            method = real_result["method"]
            emotion_profile["dominant_emotion"] = emotion.value
            emotion_profile["confidence"] = confidence
        else:
            emotion = EmotionLabel(emotion_profile["dominant_emotion"])
            confidence = float(emotion_profile["confidence"])
            method = "heuristic_embedding_v1"

        if visitor_id:
            _record_emotion_event(visitor_id, emotion, confidence)
            _persist_emotion_behavior_event(
                db,
                visitor_id,
                emotion_profile,
                source="advanced_recognition_emotion_api",
            )

        return EmotionDetectionResponse(
            emotion=emotion.value,
            confidence=confidence,
            intensity=float(emotion_profile.get("intensity") or confidence),
            method=method,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Emotion detection failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/emotion/history/{visitor_id}")
async def get_emotion_history(
    visitor_id: str,
    window_seconds: int = Query(300),
    db: Session = Depends(get_db),
    current_user_id: str = Depends(get_current_user),
):
    """Get emotion history for visitor."""
    try:
        user = _get_user_record(db, current_user_id)
        cutoff = datetime.now(timezone.utc).timestamp() - max(window_seconds, 0)
        recent_events = []
        for event in _emotion_history.get(visitor_id, []):
            event_dt = datetime.fromisoformat(event["timestamp"])
            if event_dt.timestamp() >= cutoff:
                recent_events.append(event)

        visitor_uuid = _parse_uuid(visitor_id)
        if visitor_uuid is not None:
            persisted_rows = db.query(models.BehaviorEvent).filter(
                models.BehaviorEvent.organization_id == user.organization_id,
                models.BehaviorEvent.visitor_id == str(visitor_uuid),
                models.BehaviorEvent.source.in_([
                    "advanced_recognition",
                    "advanced_recognition_emotion_api",
                    "emotion_detection",
                ]),
                models.BehaviorEvent.created_at >= datetime.fromtimestamp(cutoff, timezone.utc),
            ).order_by(models.BehaviorEvent.created_at.desc()).limit(100).all()
            for row in persisted_rows:
                details = dict(row.details or {})
                recent_events.append(
                    {
                        "timestamp": row.created_at.isoformat() if row.created_at else _utcnow_iso(),
                        "emotion": details.get("dominant_emotion") or row.action or "neutral",
                        "confidence": float(row.confidence or 0.0),
                        "source": row.source,
                        "valence": float(details.get("valence") or 0.0),
                        "arousal": float(details.get("arousal") or 0.0),
                    }
                )

        recent_events.sort(key=lambda item: item.get("timestamp", ""), reverse=False)

        emotion_counts: Dict[str, int] = {}
        valence_samples: List[float] = []
        arousal_samples: List[float] = []
        for event in recent_events:
            emotion_name = str(event["emotion"])
            emotion_counts[emotion_name] = emotion_counts.get(emotion_name, 0) + 1
            if event.get("valence") is not None:
                valence_samples.append(float(event["valence"]))
            if event.get("arousal") is not None:
                arousal_samples.append(float(event["arousal"]))

        average_emotion = None
        if emotion_counts:
            average_emotion = max(emotion_counts, key=emotion_counts.get)

        confidence_values = [float(event.get("confidence") or 0.0) for event in recent_events]
        emotional_stability = 0.0
        if emotion_counts and recent_events:
            dominant_share = max(emotion_counts.values()) / len(recent_events)
            confidence_stability = 1.0 - min(np.std(confidence_values) * 2.0, 1.0)
            emotional_stability = float(max(0.0, min(1.0, (0.6 * dominant_share) + (0.4 * confidence_stability))))

        return {
            "visitor_id": visitor_id,
            "window_seconds": window_seconds,
            "emotions": emotion_counts,
            "average_emotion": average_emotion,
            "average_confidence": float(sum(confidence_values) / len(confidence_values)) if confidence_values else 0.0,
            "average_valence": float(sum(valence_samples) / len(valence_samples)) if valence_samples else 0.0,
            "average_arousal": float(sum(arousal_samples) / len(arousal_samples)) if arousal_samples else 0.0,
            "emotional_stability": emotional_stability,
            "event_count": len(recent_events),
            "recent_events": recent_events[-20:],
        }
    except Exception as e:
        logger.error(f"Failed to get emotion history: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ─────────────────────────────────────────────────────────────────────────────
# ENDPOINTS: UNIFIED RECOGNITION
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/recognize", response_model=UnifiedRecognitionResponse)
async def unified_recognize(
    request: UnifiedRecognitionRequest,
    db: Session = Depends(get_db),
    current_user_id: str = Depends(get_current_user),
):
    """Perform unified recognition combining all Phase 3 techniques."""
    try:
        user = _get_user_record(db, current_user_id)
        engine = get_unified_engine(_build_camera_map(db, user.organization_id))
        gallery_records = _build_gallery_records(db, user.organization_id)

        probe_set: Optional[MultiAngleEmbeddingSet] = None
        angle_payload: Dict[str, Dict[str, Any]] = {}
        if request.multi_angle_data:
            angle_payload = {
                angle.angle_name: {
                    "image_path": angle.image_path,
                    "yaw": angle.yaw,
                    "pitch": angle.pitch,
                    "roll": angle.roll,
                }
                for angle in request.multi_angle_data
            }
            probe_visitor_id = request.visitor_id or f"probe-{_stable_seed(request.camera_id + str(len(request.embedding)))}"
            probe_set = engine.multi_angle_engine.create_multi_angle_set(
                probe_visitor_id,
                angle_payload,
                register=False,
            )

        multi_angle_match = _match_multi_angle_probe(
            probe_set,
            gallery_records,
        )
        reid_result = engine.reid_engine.identify_across_cameras(
            request.embedding,
            request.camera_id,
            gallery_records,
            use_temporal=True,
        )

        emotion_profile = engine.emotion_engine.detect_emotion_profile(request.embedding)
        emotion = EmotionLabel(emotion_profile["dominant_emotion"])
        emotion_confidence = float(emotion_profile["confidence"])
        action_scores = engine.emotion_engine.detect_actions(request.embedding) if request.include_behavior else {}
        behavioral_score = engine.emotion_engine.compute_behavioral_score(
            emotion_profile,
            action_scores,
        )

        reid_confidence = reid_result.confidence if reid_result else 0.0
        reid_visitor_id = reid_result.subject_id if reid_result else None
        multi_angle_confidence = multi_angle_match.get("confidence") if multi_angle_match.get("matched") else None
        matched_visitor_id = multi_angle_match.get("visitor_id") if multi_angle_match.get("matched") else None

        inferred_visitor_id = reid_visitor_id
        if multi_angle_confidence is not None and (
            inferred_visitor_id is None
            or float(multi_angle_confidence) >= (reid_confidence + 0.03)
        ):
            inferred_visitor_id = matched_visitor_id

        if reid_visitor_id and matched_visitor_id and reid_visitor_id == matched_visitor_id:
            identity_confidence = max(reid_confidence, float(multi_angle_confidence or 0.0))
            combined_confidence = min(
                0.99,
                (0.4 * identity_confidence)
                + (0.2 * reid_confidence)
                + (0.15 * float(multi_angle_confidence or 0.0))
                + (0.25 * float(emotion_confidence)),
            )
        else:
            combined_confidence = min(
                0.99,
                (0.45 * reid_confidence)
                + (0.2 * float(multi_angle_confidence or 0.0))
                + (0.35 * float(emotion_confidence)),
            )

        predicted_next_camera, predicted_confidence = (None, None)
        if inferred_visitor_id:
            predicted_next_camera, predicted_confidence = engine.reid_engine.predict_next_location(
                inferred_visitor_id
            )

        unified_result = {
            "visitor_id": inferred_visitor_id,
            "combined_confidence": float(max(0.0, combined_confidence)),
            "predicted_next_camera": predicted_next_camera,
            "predicted_confidence": predicted_confidence,
            "modality_results": {
                "multi_angle": {
                    "confidence": multi_angle_confidence,
                    "angles_matched": multi_angle_match.get("angles_matched", []),
                },
                "emotion": {
                    "emotion": emotion.value,
                    "confidence": float(emotion_confidence),
                    "valence": float(emotion_profile.get("valence") or 0.0),
                    "arousal": float(emotion_profile.get("arousal") or 0.0),
                    "stability": float(emotion_profile.get("stability") or 0.0),
                },
                "actions": action_scores,
                "behavior": behavioral_score,
            },
        }

        resolved_visitor_id = request.visitor_id or unified_result.get("visitor_id")
        if resolved_visitor_id:
            emotion_payload = unified_result["modality_results"].get("emotion", {})
            emotion_name = emotion_payload.get("emotion")
            if emotion_name:
                emotion_enum = EmotionLabel(emotion_name)
                _record_emotion_event(
                    resolved_visitor_id,
                    emotion_enum,
                    float(emotion_payload.get("confidence") or 0.0),
                )
                _persist_emotion_behavior_event(
                    db,
                    resolved_visitor_id,
                    emotion_profile,
                    camera_id=request.camera_id,
                    source="advanced_recognition",
                )
            engine.reid_engine.temporal_tracker.record(
                resolved_visitor_id,
                request.camera_id,
                float(unified_result.get("combined_confidence") or 0.0),
            )
            history = engine.reid_engine.temporal_tracker.get_recent_cameras(resolved_visitor_id)
            _record_transition_summary_from_tracker(
                db,
                user.organization_id,
                resolved_visitor_id,
                history,
            )
            if request.multi_angle_data and probe_set and request.visitor_id:
                stored_set = MultiAngleEmbeddingSet(
                    visitor_id=request.visitor_id,
                    embeddings=probe_set.embeddings,
                    completeness=probe_set.completeness,
                    timestamp=probe_set.timestamp,
                )
                _multi_angle_registry[request.visitor_id] = stored_set
                _persist_multi_angle_set(db, user.organization_id, stored_set)

        predicted_confidence = unified_result.get("predicted_confidence")

        return UnifiedRecognitionResponse(
            visitor_id=resolved_visitor_id,
            multi_angle_confidence=unified_result["modality_results"]
            .get("multi_angle", {})
            .get("confidence"),
            emotion=unified_result["modality_results"]
            .get("emotion", {})
            .get("emotion"),
            emotion_confidence=unified_result["modality_results"]
            .get("emotion", {})
            .get("confidence"),
            engagement_score=unified_result["modality_results"]
            .get("behavior", {})
            .get("engagement_score"),
            combined_confidence=unified_result["combined_confidence"],
            predicted_next_camera=unified_result.get("predicted_next_camera"),
            predicted_confidence=predicted_confidence,
        )

    except Exception as e:
        logger.error(f"Unified recognition failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ─────────────────────────────────────────────────────────────────────────────
# HEALTH CHECK
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/health")
async def advanced_recognition_health():
    """Check health of advanced recognition services."""
    try:
        vit = get_vit_service()
        return {
            "status": "healthy",
            "services": {
                "vit_loaded": vit.model is not None,
                "multi_angle": True,
                "reid": True,
                "emotion_action": True,
            },
            "runtime_state": {
                "registered_multi_angle_visitors": len(_multi_angle_registry),
                "tracked_emotion_histories": len(_emotion_history),
            },
        }
    except Exception as e:
        return {
            "status": "unhealthy",
            "error": str(e),
        }
