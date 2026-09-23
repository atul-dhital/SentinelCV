"""
Multi-Angle Face Embedding Support for SentinelCV.

Enables storing and matching face embeddings from multiple angles.
"""

import cv2
import numpy as np
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass
from enum import Enum


class FaceAngle(Enum):
    """Face angle categories."""
    FRONTAL = "frontal"
    PROFILE_LEFT = "profile_left"
    PROFILE_RIGHT = "profile_right"
    HALF_LEFT = "half_left"
    HALF_RIGHT = "half_right"
    TOP_DOWN = "top_down"


@dataclass
class AngleEmbedding:
    """Face embedding with angle classification."""
    embedding: np.ndarray
    angle: FaceAngle
    confidence: float
    quality_score: float


class FaceAngleClassifier:
    """Classify face angle based on landmarks."""
    
    def __init__(self):
        self.angle_thresholds = {
            "yaw": 30,  # degrees
            "pitch": 20,
        }
        
    def classify_angle(self, landmarks: Dict) -> Tuple[FaceAngle, float]:
        """
        Classify face angle based on facial landmarks.
        
        Returns angle category and confidence score.
        """
        try:
            left_eye = landmarks.get("left_eye")
            right_eye = landmarks.get("right_eye")
            nose = landmarks.get("nose")
            
            if left_eye is None or right_eye is None:
                return FaceAngle.FRONTAL, 0.5
            
            eye_distance = np.linalg.norm(
                np.array(left_eye) - np.array(right_eye)
            )
            
            nose_x = nose[0] if nose else (left_eye[0] + right_eye[0]) / 2
            
            left_eye_x = left_eye[0]
            right_eye_x = right_eye[0]
            eye_center_x = (left_eye_x + right_eye_x) / 2
            
            nose_offset = (nose_x - eye_center_x) / eye_distance if eye_distance > 0 else 0
            
            if abs(nose_offset) < 0.1:
                return FaceAngle.FRONTAL, 0.9
            elif nose_offset < -0.2:
                if nose_offset < -0.4:
                    return FaceAngle.PROFILE_LEFT, 0.8
                return FaceAngle.HALF_LEFT, 0.7
            else:
                if nose_offset > 0.4:
                    return FaceAngle.PROFILE_RIGHT, 0.8
                return FaceAngle.HALF_RIGHT, 0.7
                
        except Exception:
            return FaceAngle.FRONTAL, 0.5
    
    def estimate_yaw(self, landmarks: Dict) -> float:
        """Estimate face yaw angle in degrees."""
        try:
            left_eye = landmarks.get("left_eye")
            right_eye = landmarks.get("right_eye")
            
            if left_eye is None or right_eye is None:
                return 0.0
            
            eye_distance = right_eye[0] - left_eye[0]
            if eye_distance == 0:
                return 0.0
            
            nose = landmarks.get("nose")
            if nose is None:
                return 0.0
            
            nose_center = (left_eye[0] + right_eye[0]) / 2
            offset = (nose[0] - nose_center) / eye_distance
            
            yaw = offset * 90
            return max(-90, min(90, yaw))
            
        except Exception:
            return 0.0
    
    def estimate_pitch(self, landmarks: Dict) -> float:
        """Estimate face pitch angle in degrees."""
        try:
            left_eye = landmarks.get("left_eye")
            right_eye = landmarks.get("right_eye")
            nose = landmarks.get("nose")
            mouth = landmarks.get("mouth")
            
            if None in [left_eye, right_eye, nose, mouth]:
                return 0.0
            
            eye_center_y = (left_eye[1] + right_eye[1]) / 2
            face_height = mouth[1] - eye_center_y
            
            if face_height == 0:
                return 0.0
            
            nose_offset = (nose[1] - eye_center_y) / face_height
            
            pitch = (nose_offset - 0.35) * 90
            return max(-90, min(90, pitch))
            
        except Exception:
            return 0.0


class MultiAngleEmbeddingStore:
    """Store and query multi-angle face embeddings."""
    
    def __init__(self):
        self.angle_classifier = FaceAngleClassifier()
        self._embeddings: Dict[str, List[AngleEmbedding]] = {}
        
    def add_embedding(self, visitor_id: str, embedding: np.ndarray, 
                     landmarks: Dict = None, quality_score: float = 0.5):
        """Add a face embedding with angle classification."""
        if visitor_id not in self._embeddings:
            self._embeddings[visitor_id] = []
        
        if landmarks:
            angle, confidence = self.angle_classifier.classify_angle(landmarks)
        else:
            angle = FaceAngle.FRONTAL
            confidence = 0.5
        
        angle_embedding = AngleEmbedding(
            embedding=embedding,
            angle=angle,
            confidence=confidence,
            quality_score=quality_score,
        )
        
        self._embeddings[visitor_id].append(angle_embedding)
        
        return angle_embedding
    
    def get_embeddings(self, visitor_id: str) -> List[AngleEmbedding]:
        """Get all embeddings for a visitor."""
        return self._embeddings.get(visitor_id, [])
    
    def get_best_embedding(self, visitor_id: str, 
                          target_angle: FaceAngle = FaceAngle.FRONTAL) -> Optional[np.ndarray]:
        """Get best embedding for a specific angle."""
        embeddings = self.get_embeddings(visitor_id)
        
        if not embeddings:
            return None
        
        if target_angle == FaceAngle.FRONTAL:
            frontal = [e for e in embeddings if e.angle == FaceAngle.FRONTAL]
            if frontal:
                return max(frontal, key=lambda x: x.quality_score).embedding
        
        return embeddings[0].embedding if embeddings else None
    
    def query_best_match(self, query_embedding: np.ndarray, 
                        embeddings: List[AngleEmbedding],
                        threshold: float = 0.6) -> Tuple[Optional[str], float]:
        """
        Find best matching embedding considering multiple angles.
        
        Returns best visitor_id and confidence.
        """
        if not embeddings:
            return None, 0.0
        
        best_score = 0.0
        best_embedding = None
        
        for angle_emb in embeddings:
            score = self._cosine_similarity(query_embedding, angle_emb.embedding)
            if score > best_score:
                best_score = score
                best_embedding = angle_emb
        
        if best_score >= threshold and best_embedding:
            return best_embedding.angle.value, best_score
        
        return None, best_score
    
    def _cosine_similarity(self, a: np.ndarray, b: np.ndarray) -> float:
        """Calculate cosine similarity between two vectors."""
        dot = np.dot(a, b)
        norm_a = np.linalg.norm(a)
        norm_b = np.linalg.norm(b)
        
        if norm_a == 0 or norm_b == 0:
            return 0.0
        
        return dot / (norm_a * norm_b)
    
    def get_angle_coverage(self, visitor_id: str) -> Dict[FaceAngle, int]:
        """Get coverage statistics for each angle category."""
        embeddings = self.get_embeddings(visitor_id)
        coverage = {angle: 0 for angle in FaceAngle}
        
        for emb in embeddings:
            coverage[emb.angle] += 1
        
        return coverage
    
    def needs_more_angles(self, visitor_id: str, 
                         min_per_angle: int = 1) -> List[FaceAngle]:
        """Determine which angle categories need more samples."""
        coverage = self.get_angle_coverage(visitor_id)
        
        needed = []
        for angle, count in coverage.items():
            if count < min_per_angle:
                needed.append(angle)
        
        return needed


def augment_embedding_for_angles(base_embedding: np.ndarray, 
                                  angles: List[FaceAngle] = None) -> List[np.ndarray]:
    """
    Generate augmented embeddings for different viewing angles.
    
    This is a simplified version - in production, you'd use a trained model.
    """
    if angles is None:
        angles = [FaceAngle.FRONTAL, FaceAngle.HALF_LEFT, FaceAngle.HALF_RIGHT]
    
    augmented = []
    
    for angle in angles:
        noise = np.random.normal(0, 0.02, base_embedding.shape)
        aug_emb = base_embedding + noise
        
        if angle in [FaceAngle.PROFILE_LEFT, FaceAngle.HALF_LEFT]:
            flip_aug = np.flip(aug_emb)
            aug_emb = 0.7 * aug_emb + 0.3 * flip_aug
        
        augmented.append(aug_emb)
    
    return augmented


_angle_classifier = FaceAngleClassifier()
_multi_angle_store = MultiAngleEmbeddingStore()


def get_angle_classifier() -> FaceAngleClassifier:
    return _angle_classifier


def get_multi_angle_store() -> MultiAngleEmbeddingStore:
    return _multi_angle_store
