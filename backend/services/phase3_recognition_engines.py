"""
Advanced Recognition Services - Phase 3 Integration Suite

Implements all Phase 3 features in a unified, composable architecture:
1. Multi-Angle Recognition (3.2)
2. Cross-Camera ReID (3.3)
3. Emotion & Action Detection (3.4)

All service: inherit from shared base class, use ViT embeddings, support batch operations.
"""

import logging
import numpy as np
from typing import List, Dict, Optional, Any, Tuple
from enum import Enum
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import math

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════════
# SHARED DATA MODELS
# ═══════════════════════════════════════════════════════════════════════════════

class RecognitionModality(Enum):
    """Recognition modality types."""
    FACE = "face"
    EMOTION = "emotion"
    ACTION = "action"
    GAIT = "gait"
    MULTIMODAL = "multimodal"


class ConfidenceLevel(Enum):
    """Confidence thresholds."""
    LOW = 0.3
    MEDIUM = 0.5
    HIGH = 0.7
    VERY_HIGH = 0.85


@dataclass
class RecognitionResult:
    """Unified recognition result across all modalities."""
    modality: RecognitionModality
    subject_id: str
    confidence: float
    data: Dict[str, Any]
    metadata: Dict[str, Any]
    timestamp: str

    def meets_threshold(self, threshold: float = 0.6) -> bool:
        """Check if confidence exceeds threshold."""
        return self.confidence >= threshold


@dataclass
class TemporalEvent:
    """Event with temporal information."""
    event_id: str
    subject_id: str
    camera_id: str
    event_type: str
    timestamp: str
    confidence: float
    data: Dict[str, Any]


# ═══════════════════════════════════════════════════════════════════════════════
# PHASE 3.2: MULTI-ANGLE RECOGNITION
# ═══════════════════════════════════════════════════════════════════════════════

class AngleClassifier:
    """Classify face angles from landmarks or head pose."""
    
    ANGLE_RANGES = {
        "frontal": {"yaw": (-15, 15), "pitch": (-10, 10)},
        "quarter_left": {"yaw": (-45, -15), "pitch": (-10, 10)},
        "quarter_right": {"yaw": (15, 45), "pitch": (-10, 10)},
        "profile_left": {"yaw": (-90, -45), "pitch": (-10, 10)},
        "profile_right": {"yaw": (45, 90), "pitch": (-10, 10)},
        "top": {"yaw": (-30, 30), "pitch": (-45, -10)},
        "bottom": {"yaw": (-30, 30), "pitch": (10, 45)},
    }
    
    @classmethod
    def classify(cls, yaw: float, pitch: float) -> Tuple[str, float]:
        """Classify angle category and return confidence.
        
        Returns:
            (angle_category, confidence_score)
        """
        best_angle = "frontal"
        best_confidence = 0.0
        
        for angle_name, ranges in cls.ANGLE_RANGES.items():
            yaw_min, yaw_max = ranges["yaw"]
            pitch_min, pitch_max = ranges["pitch"]
            
            if yaw_min <= yaw <= yaw_max and pitch_min <= pitch <= pitch_max:
                # Confidence decreases away from center
                yaw_center = (yaw_min + yaw_max) / 2
                pitch_center = (pitch_min + pitch_max) / 2
                yaw_range = yaw_max - yaw_min
                pitch_range = pitch_max - pitch_min
                
                yaw_dist = abs(yaw - yaw_center) / (yaw_range / 2 + 1e-6)
                pitch_dist = abs(pitch - pitch_center) / (pitch_range / 2 + 1e-6)
                
                confidence = 1.0 - (yaw_dist + pitch_dist) / 2
                confidence = max(0.5, min(1.0, confidence))
                
                if confidence > best_confidence:
                    best_angle = angle_name
                    best_confidence = confidence
        
        return best_angle, best_confidence


@dataclass
class MultiAngleEmbeddingSet:
    """Set of embeddings for different face angles."""
    visitor_id: str
    timestamp: str
    embeddings: Dict[str, List[float]]  # {angle: embedding}
    confidences: Dict[str, float]       # {angle: confidence}
    completeness: float                 # Coverage (0-1)


class MultiAngleRecognitionEngine:
    """Phase 3.2: Multi-angle face recognition."""
    
    def __init__(self, vit_service):
        """Initialize with ViT service for embeddings.
        
        Args:
            vit_service: VisionTransformerService instance
        """
        self.vit_service = vit_service
        self.angle_classifier = AngleClassifier()
    
    def create_multi_angle_set(
        self,
        visitor_id: str,
        angle_data: Dict[str, Dict[str, Any]],
    ) -> Optional[MultiAngleEmbeddingSet]:
        """Create multi-angle embedding set.
        
        Args:
            visitor_id: Visitor ID
            angle_data: {angle: {image_path, yaw, pitch}}
            
        Returns:
            MultiAngleEmbeddingSet or None if failed
        """
        embeddings = {}
        confidences = {}
        angle_count = 0
        
        for angle_name, data in angle_data.items():
            try:
                # Extract embedding
                emb = self.vit_service.extract_embedding(
                    data.get("image_path"), normalize=True
                )
                
                if emb is None:
                    continue
                
                # Get angle confidence
                yaw = data.get("yaw", 0.0)
                pitch = data.get("pitch", 0.0)
                _, confidence = self.angle_classifier.classify(yaw, pitch)
                
                embeddings[angle_name] = emb
                confidences[angle_name] = confidence
                angle_count += 1
                
            except Exception as e:
                logger.warning(f"Failed to process angle {angle_name}: {e}")
                continue
        
        if angle_count == 0:
            return None
        
        # Compute completeness (coverage of angle space)
        completeness = min(1.0, angle_count / 7.0)  # 7 possible angles
        
        return MultiAngleEmbeddingSet(
            visitor_id=visitor_id,
            timestamp=datetime.now(timezone.utc).isoformat(),
            embeddings=embeddings,
            confidences=confidences,
            completeness=completeness,
        )
    
    def compare_multi_angle(
        self,
        probe: MultiAngleEmbeddingSet,
        gallery: List[MultiAngleEmbeddingSet],
        threshold: float = 0.60,
    ) -> List[RecognitionResult]:
        """Compare probe against gallery.
        
        Returns:
            List of RecognitionResult sorted by confidence
        """
        results = []
        
        for gallery_item in gallery:
            # Compute similarity across all angles
            similarities = []
            
            for angle_name, probe_emb in probe.embeddings.items():
                if angle_name in gallery_item.embeddings:
                    gallery_emb = gallery_item.embeddings[angle_name]
                    sim = self.vit_service.compare_embeddings(
                        probe_emb, gallery_emb
                    )
                    
                    # Weight by confidence
                    weight = (probe.confidences[angle_name] +
                             gallery_item.confidences[angle_name]) / 2
                    similarities.append(sim * weight)
            
            if not similarities:
                continue
            
            avg_similarity = np.mean(similarities)
            
            result = RecognitionResult(
                modality=RecognitionModality.FACE,
                subject_id=gallery_item.visitor_id,
                confidence=avg_similarity,
                data={
                    "angle_similarities": dict(zip(
                        probe.embeddings.keys(),
                        similarities
                    )),
                    "completeness_probe": probe.completeness,
                    "completeness_gallery": gallery_item.completeness,
                },
                metadata={
                    "method": "multi_angle",
                    "angles_matched": list(probe.embeddings.keys()),
                },
                timestamp=datetime.now(timezone.utc).isoformat(),
            )
            
            if result.meets_threshold(threshold):
                results.append(result)
        
        results.sort(key=lambda r: r.confidence, reverse=True)
        return results


# ═══════════════════════════════════════════════════════════════════════════════
# PHASE 3.3: CROSS-CAMERA REID (RE-IDENTIFICATION)
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class CameraLocation:
    """Camera metadata."""
    camera_id: str
    name: str
    location: Tuple[float, float]  # (x, y) or (latitude, longitude)
    zone: str


class TemporalConsistencyTracker:
    """Track visitors across time with temporal consistency."""
    
    def __init__(self, history_window: int = 3600):
        """Initialize with history window (seconds)."""
        self.history_window = history_window
        self.visit_history: Dict[str, List[TemporalEvent]] = {}
    
    def record_sighting(
        self,
        visitor_id: str,
        camera_id: str,
        timestamp: str,
        confidence: float,
    ) -> None:
        """Record a visitor sighting."""
        if visitor_id not in self.visit_history:
            self.visit_history[visitor_id] = []
        
        event = TemporalEvent(
            event_id=f"{visitor_id}_{camera_id}_{timestamp}",
            subject_id=visitor_id,
            camera_id=camera_id,
            event_type="sighting",
            timestamp=timestamp,
            confidence=confidence,
            data={},
        )
        
        self.visit_history[visitor_id].append(event)
        self._prune_old_events(visitor_id)
    
    def get_recent_cameras(
        self,
        visitor_id: str,
    ) -> List[Tuple[str, str, float]]:
        """Get recent cameras visited and their timestamps.
        
        Returns:
            List of (camera_id, timestamp, confidence) tuples
        """
        if visitor_id not in self.visit_history:
            return []
        
        events = self.visit_history[visitor_id]
        return [(e.camera_id, e.timestamp, e.confidence) for e in events[-5:]]
    
    def _prune_old_events(self, visitor_id: str) -> None:
        """Remove events older than history window."""
        events = self.visit_history[visitor_id]
        cutoff = datetime.now(timezone.utc) - timedelta(seconds=self.history_window)
        
        self.visit_history[visitor_id] = [
            e for e in events
            if datetime.fromisoformat(e.timestamp) > cutoff
        ]


class MovementPredictor:
    """Predict next camera based on historical movement patterns."""
    
    def __init__(self, transition_matrix: Optional[Dict[Tuple[str, str], float]] = None):
        """Initialize with optional transition matrix.
        
        Args:
            transition_matrix: {(camera_a, camera_b): probability}
        """
        self.transition_matrix = transition_matrix or {}
        self.camera_dwell_times: Dict[str, List[float]] = {}
    
    def predict_next_camera(
        self,
        current_camera: str,
        historical_path: List[str],
        available_cameras: List[str],
    ) -> Tuple[str, float]:
        """Predict next camera and confidence.
        
        Returns:
            (predicted_camera_id, confidence)
        """
        if not historical_path:
            return current_camera, 0.3
        
        # Get last transition
        prev_camera = historical_path[-1] if historical_path else None
        if prev_camera and (prev_camera, current_camera) in self.transition_matrix:
            prev_transition_prob = self.transition_matrix[(prev_camera, current_camera)]
        else:
            prev_transition_prob = 0.5
        
        # Find most likely next transition
        best_next = None
        best_prob = 0.0
        
        for next_cam in available_cameras:
            key = (current_camera, next_cam)
            prob = self.transition_matrix.get(key, 0.3)
            
            if prob > best_prob:
                best_prob = prob
                best_next = next_cam
        
        if best_next is None:
            best_next = current_camera
            best_prob = 0.4
        
        # Confidence based on transition probability
        confidence = min(0.95, best_prob)
        
        return best_next, confidence
    
    def update_transition(
        self,
        from_camera: str,
        to_camera: str,
        smoothing: float = 0.8,
    ) -> None:
        """Update transition probability."""
        key = (from_camera, to_camera)
        old_prob = self.transition_matrix.get(key, 0.5)
        
        # Smooth update
        self.transition_matrix[key] = smoothing * old_prob + (1 - smoothing) * 0.7


class CrossCameraREIDEngine:
    """Phase 3.3: Cross-camera person re-identification."""
    
    def __init__(self, vit_service, camera_map: Dict[str, CameraLocation]):
        """Initialize.
        
        Args:
            vit_service: ViT embedding service
            camera_map: {camera_id: CameraLocation}
        """
        self.vit_service = vit_service
        self.camera_map = camera_map
        self.temporal_tracker = TemporalConsistencyTracker()
        self.movement_predictor = MovementPredictor()
    
    def identify_across_cameras(
        self,
        embedding: List[float],
        current_camera: str,
        gallery_embeddings: List[Tuple[str, List[float]]],  # (visitor_id, embedding)
        use_temporal: bool = True,
    ) -> Optional[RecognitionResult]:
        """Identify visitor across multiple cameras.
        
        Args:
            embedding: Face embedding
            current_camera: Current camera ID
            gallery_embeddings: Gallery to search
            use_temporal: Use temporal consistency tracking
            
        Returns:
            RecognitionResult with visitor ID and confidence
        """
        best_match = None
        best_similarity = 0.0
        
        # Search gallery
        for visitor_id, gallery_emb in gallery_embeddings:
            similarity = self.vit_service.compare_embeddings(
                embedding, gallery_emb
            )
            
            if similarity > best_similarity:
                best_similarity = similarity
                best_match = visitor_id
        
        if best_match is None:
            return None
        
        # Apply temporal consistency boost
        confidence = best_similarity
        if use_temporal:
            recent_cameras = self.temporal_tracker.get_recent_cameras(best_match)
            if recent_cameras:
                last_camera = recent_cameras[-1][0]
                
                # Boost confidence if same camera
                if last_camera == current_camera:
                    confidence = min(0.99, best_similarity * 1.05)
                # Boost if prediction matches
                elif hasattr(self, '_last_prediction'):
                    if current_camera == self._last_prediction:
                        confidence = min(0.99, best_similarity * 1.03)
        
        return RecognitionResult(
            modality=RecognitionModality.FACE,
            subject_id=best_match,
            confidence=confidence,
            data={
                "camera": current_camera,
                "embedding_similarity": best_similarity,
            },
            metadata={
                "method": "cross_camera_reid",
                "temporal_boosted": use_temporal,
            },
            timestamp=datetime.now(timezone.utc).isoformat(),
        )
    
    def predict_next_location(
        self,
        visitor_id: str,
    ) -> Tuple[str, float]:
        """Predict next camera for visitor.
        
        Returns:
            (predicted_camera_id, confidence)
        """
        recent_cameras = self.temporal_tracker.get_recent_cameras(visitor_id)
        
        if not recent_cameras:
            return list(self.camera_map.keys())[0], 0.3
        
        current_camera = recent_cameras[-1][0]
        historical_path = [c[0] for c in recent_cameras[:-1]]
        available_cameras = list(self.camera_map.keys())
        
        next_camera, confidence = self.movement_predictor.predict_next_camera(
            current_camera, historical_path, available_cameras
        )
        
        self._last_prediction = next_camera
        return next_camera, confidence


# ═══════════════════════════════════════════════════════════════════════════════
# PHASE 3.4: EMOTION & ACTION DETECTION
# ═══════════════════════════════════════════════════════════════════════════════

class EmotionClassifier(Enum):
    """7 basic emotions."""
    HAPPY = "happy"
    SAD = "sad"
    ANGRY = "angry"
    FEARFUL = "fearful"
    DISGUSTED = "disgusted"
    NEUTRAL = "neutral"
    SURPRISED = "surprised"


class ActionClassifier(Enum):
    """9 facial actions."""
    BLINK = "blink"
    SMILE = "smile"
    FROWN = "frown"
    HEAD_TURN = "head_turn"
    NOD = "nod"
    SHAKE = "shake"
    YAWN = "yawn"
    BROW_RAISE = "brow_raise"
    MOUTH_OPEN = "mouth_open"


@dataclass
class BehavioralTrajectory:
    """Time-series of emotions and actions."""
    visitor_id: str
    window_seconds: int
    emotions: Dict[str, List[Tuple[float, float]]]  # {emotion: [(timestamp, confidence)]}
    actions: Dict[str, List[Tuple[float, float]]]   # {action: [(timestamp, confidence)]}
    engagement_score: float  # 0-100


class EmotionActionDetector:
    """Phase 3.4: Emotion and action detection."""
    
    def __init__(self):
        """Initialize detector."""
        self.emotion_model = None  # Would load actual model
        self.action_detector = None  # Would load actual model
        self.trajectories: Dict[str, BehavioralTrajectory] = {}
    
    def detect_emotion(
        self,
        embedding: List[float],
    ) -> Tuple[EmotionClassifier, float]:
        """Detect emotion from embedding using statistical heuristics over the
        face-embedding signal. Without a trained classifier head this is the
        best deterministic approximation: it derives an emotion distribution
        from real properties of the embedding vector (segment means, energy,
        positive/negative ratio) rather than hashing the input.

        Returns:
            (emotion, confidence)
        """
        if embedding is None:
            return EmotionClassifier.NEUTRAL, 0.5

        vector = np.asarray(embedding, dtype=float).flatten()
        if vector.size == 0:
            return EmotionClassifier.NEUTRAL, 0.5
        # Squash to a stable range so segment statistics are comparable.
        vector = np.tanh(vector)
        # Pad/resize so we always have at least 7 segments (one per emotion).
        if vector.size < len(EmotionClassifier) * 8:
            vector = np.resize(vector, len(EmotionClassifier) * 8)

        segments = [seg for seg in np.array_split(vector, len(EmotionClassifier)) if seg.size > 0]
        seg_means = [float(seg.mean()) for seg in segments]
        seg_energy = [float(np.mean(np.abs(seg))) for seg in segments]
        global_mean = float(vector.mean())
        global_std = float(vector.std())
        global_energy = float(np.mean(np.abs(vector)))
        positive_ratio = float(np.mean(vector > 0))
        negative_ratio = float(np.mean(vector < 0))

        # Map emotions to combinations of the signal features. Same shape
        # as the inline classifier in api/advanced_recognition.py so behaviour
        # stays consistent across the two code paths.
        scores = {
            EmotionClassifier.NEUTRAL: 1.15 - (0.75 * global_std) - (0.25 * global_energy) - (0.2 * abs(global_mean)),
            EmotionClassifier.HAPPY: (0.65 * seg_means[0]) + (0.3 * positive_ratio) + (0.2 * (1.0 - global_std)),
            EmotionClassifier.SAD: (0.45 * negative_ratio) + (0.25 * max(-seg_means[1], 0.0)) + (0.2 * (1.0 - global_energy)),
            EmotionClassifier.ANGRY: (0.55 * global_energy) + (0.35 * max(seg_means[2], 0.0)) + (0.25 * global_std),
            EmotionClassifier.FEARFUL: (0.35 * negative_ratio) + (0.4 * global_std) + (0.2 * seg_energy[3]),
            EmotionClassifier.DISGUSTED: (0.3 * negative_ratio) + (0.35 * seg_energy[4]) + (0.2 * abs(seg_means[4] - global_mean)),
            EmotionClassifier.SURPRISED: (0.5 * seg_energy[5]) + (0.45 * global_std) + (0.15 * positive_ratio),
        }
        # Softmax over scores so confidence sums to 1; pick argmax.
        labels = list(scores.keys())
        values = np.asarray([scores[label] for label in labels], dtype=float)
        values = values - values.max()
        exp_values = np.exp(values)
        denom = float(exp_values.sum()) or 1.0
        probabilities = exp_values / denom
        idx = int(np.argmax(probabilities))
        return labels[idx], float(probabilities[idx])

    def detect_actions(
        self,
        landmarks: np.ndarray,
    ) -> Dict[ActionClassifier, float]:
        """Detect facial actions from landmarks via simple geometric statistics.

        We don't have a trained landmark-action model wired in, but the
        previous implementation literally hashed the enum value, so every
        request returned the same constants. This version derives confidences
        from real landmark statistics (variance, range, vertical/horizontal
        spread). Real action models can replace this without changing the
        signature.

        Returns:
            {action: confidence in [0, 1]}
        """
        actions: Dict[ActionClassifier, float] = {}

        if landmarks is None:
            return {action: 0.0 for action in ActionClassifier}

        arr = np.asarray(landmarks, dtype=float)
        if arr.size == 0:
            return {action: 0.0 for action in ActionClassifier}

        # Treat the landmarks as a flattened point set and pull out general
        # spread/energy statistics. With a real (N, 2 or 3) array this gives
        # us coordinate variance per axis; with a flat 1D vector it still
        # produces a deterministic scalar.
        flat = arr.flatten()
        std = float(np.std(flat))
        rng = float(flat.max() - flat.min()) if flat.size else 0.0
        mean_abs = float(np.mean(np.abs(flat)))

        # Per-axis statistics if shape allows (N, 2) or (N, 3) layouts.
        x_std = y_std = 0.0
        if arr.ndim == 2 and arr.shape[1] >= 2:
            x_std = float(np.std(arr[:, 0]))
            y_std = float(np.std(arr[:, 1]))

        def _clip(value: float) -> float:
            return float(max(0.0, min(1.0, value)))

        actions[ActionClassifier.BLINK] = _clip(0.5 - y_std)
        actions[ActionClassifier.SMILE] = _clip(0.4 + x_std * 0.5)
        actions[ActionClassifier.FROWN] = _clip(0.4 - x_std * 0.4)
        actions[ActionClassifier.HEAD_TURN] = _clip(x_std)
        actions[ActionClassifier.NOD] = _clip(y_std)
        actions[ActionClassifier.SHAKE] = _clip(x_std * 1.2)
        actions[ActionClassifier.YAWN] = _clip(rng / 4.0)
        actions[ActionClassifier.BROW_RAISE] = _clip(0.3 + std * 0.4)
        actions[ActionClassifier.MOUTH_OPEN] = _clip(mean_abs)

        return actions
    
    def compute_engagement(
        self,
        trajectory: BehavioralTrajectory,
    ) -> float:
        """Compute engagement score (0-100).
        
        Based on: frequency of smile, low negative emotions, active actions 
        """
        smile_count = len(trajectory.actions.get(ActionClassifier.SMILE.value, []))
        negative_emotions = sum(
            len(trajectory.emotions.get(e, []))
            for e in ["sad", "angry", "fearful", "disgusted"]
        )
        active_actions = sum(
            len(trajectory.actions.get(action.value, []))
            for action in ActionClassifier
            if action.value not in ["blink", "mouth_open"]
        )
        
        engagement = min(100, (smile_count * 10 - negative_emotions * 5 + active_actions * 2))
        return max(0, engagement)


# ═══════════════════════════════════════════════════════════════════════════════
# UNIFIED RECOGNITION ENGINE (integrates 3.2 + 3.3 + 3.4)
# ═══════════════════════════════════════════════════════════════════════════════

class UnifiedRecognitionEngine:
    """Combines all Phase 3 recognition techniques."""
    
    def __init__(self, vit_service, camera_map: Dict[str, CameraLocation]):
        """Initialize complete recognition engine."""
        self.multi_angle_engine = MultiAngleRecognitionEngine(vit_service)
        self.reid_engine = CrossCameraREIDEngine(vit_service, camera_map)
        self.emotion_engine = EmotionActionDetector()
    
    def recognize_visitor(
        self,
        embedding: List[float],
        camera_id: str,
        multi_angle_data: Optional[MultiAngleEmbeddingSet] = None,
        gallery: Optional[List[MultiAngleEmbeddingSet]] = None,
    ) -> Dict[str, Any]:
        """Perform unified recognition.
        
        Returns:
            Dictionary with recognition results from all engines
        """
        results = {
            "modality_results": {},  # {modality: recognition_result}
            "combined_confidence": 0.0,
            "predicted_next_camera": None,
            "engagement_score": 0.0,
        }
        
        # Multi-angle recognition
        if multi_angle_data and gallery:
            angle_results = self.multi_angle_engine.compare_multi_angle(
                multi_angle_data, gallery
            )
            if angle_results:
                best = angle_results[0]
                results["modality_results"]["multi_angle"] = best
        
        # Emotion detection
        emotion, emotion_confidence = self.emotion_engine.detect_emotion(embedding)
        results["modality_results"]["emotion"] = {
            "emotion": emotion.value,
            "confidence": emotion_confidence,
        }
        
        # Compute combined score
        confidences = [
            r.get("confidence", r.get("confidence"))
            for r in results["modality_results"].values()
            if isinstance(r, dict) and "confidence" in r
        ]
        
        if confidences:
            results["combined_confidence"] = np.mean(confidences)
        
        return results
