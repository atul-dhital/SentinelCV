"""
Multi-Angle Face Recognition Module
Stores and matches embeddings from multiple viewing angles
"""

import numpy as np
from typing import List, Dict, Tuple, Optional
from dataclasses import dataclass
from enum import Enum


class FaceAngle(Enum):
    """Face viewing angles"""
    FRONTAL = "frontal"
    PROFILE_LEFT = "profile_left"
    PROFILE_RIGHT = "profile_right"
    ANGLE_45_LEFT = "45_left"
    ANGLE_45_RIGHT = "45_right"
    TOP_DOWN = "top_down"


@dataclass
class MultiAngleEmbedding:
    """Face embedding from a specific angle"""
    embedding: np.ndarray
    angle: FaceAngle
    confidence: float
    quality_score: float
    timestamp: str


class MultiAngleFaceMatcher:
    """Match faces using multi-angle embeddings with consensus voting"""
    
    def __init__(self, min_angles: int = 1, consensus_threshold: float = 0.6):
        self.min_angles = min_angles
        self.consensus_threshold = consensus_threshold
        self.angle_weights = {
            FaceAngle.FRONTAL: 1.0,
            FaceAngle.ANGLE_45_LEFT: 0.8,
            FaceAngle.ANGLE_45_RIGHT: 0.8,
            FaceAngle.PROFILE_LEFT: 0.5,
            FaceAngle.PROFILE_RIGHT: 0.5,
            FaceAngle.TOP_DOWN: 0.3,
        }
    
    def detect_angle(self, face_bbox: Tuple[int, int, int, int], 
                    landmarks: np.ndarray = None) -> FaceAngle:
        """Detect face angle from bounding box and landmarks"""
        x1, y1, x2, y2 = face_bbox
        width = x2 - x1
        height = y2 - y1
        
        if landmarks is not None and len(landmarks) >= 5:
            left_eye = landmarks[0]
            right_eye = landmarks[1]
            nose = landmarks[2]
            
            eye_distance = np.linalg.norm(right_eye - left_eye)
            nose_offset = abs(nose[0] - (x1 + x2) / 2)
            offset_ratio = nose_offset / eye_distance if eye_distance > 0 else 0
            
            if offset_ratio < 0.1:
                return FaceAngle.FRONTAL
            elif offset_ratio < 0.25:
                if nose[0] > (x1 + x2) / 2:
                    return FaceAngle.ANGLE_45_RIGHT
                else:
                    return FaceAngle.ANGLE_45_LEFT
            else:
                if nose[0] > (x1 + x2) / 2:
                    return FaceAngle.PROFILE_RIGHT
                else:
                    return FaceAngle.PROFILE_LEFT
        
        if width > height * 1.3:
            return FaceAngle.PROFILE_LEFT if x1 < 320 else FaceAngle.PROFILE_RIGHT
        
        return FaceAngle.FRONTAL
    
    def calculate_consensus_score(self, 
                                 embeddings: List[MultiAngleEmbedding],
                                 query_embedding: np.ndarray) -> Tuple[float, Dict]:
        """Calculate consensus score from multiple angle matches"""
        if not embeddings:
            return 0.0, {}
        
        weighted_scores = []
        angle_scores = {}
        
        # Ensure query is numpy
        if not isinstance(query_embedding, np.ndarray):
            query_embedding = np.array(query_embedding)

        for stored_emb in embeddings:
            # Handle both list and numpy stored embeddings
            stored_v = stored_emb.embedding
            if not isinstance(stored_v, np.ndarray):
                stored_v = np.array(stored_v)
                
            similarity = self._cosine_similarity(query_embedding, stored_v)
            weight = self.angle_weights.get(stored_emb.angle, 0.5)
            
            weighted_score = similarity * weight * stored_emb.confidence
            weighted_scores.append(weighted_score)
            angle_scores[stored_emb.angle.value] = float(similarity)
        
        if not weighted_scores:
            return 0.0, angle_scores
        
        avg_score = np.mean(weighted_scores)
        max_score = np.max(weighted_scores)
        
        consensus_score = (avg_score + max_score) / 2
        
        return float(consensus_score), angle_scores
    
    def _cosine_similarity(self, emb1: np.ndarray, emb2: np.ndarray) -> float:
        """Calculate cosine similarity between two embeddings"""
        dot_product = np.dot(emb1, emb2)
        norm1 = np.linalg.norm(emb1)
        norm2 = np.linalg.norm(emb2)
        
        if norm1 == 0 or norm2 == 0:
            return 0.0
        
        return float(dot_product / (norm1 * norm2))
    
    def match_with_angles(self, 
                        query_embedding: np.ndarray,
                        stored_embeddings: List[MultiAngleEmbedding],
                        threshold: float = 0.6) -> Tuple[bool, float, Dict]:
        """Match query embedding against multi-angle stored embeddings"""
        
        score, angle_scores = self.calculate_consensus_score(
            stored_embeddings, query_embedding
        )
        
        if score >= threshold:
            return True, score, angle_scores
        else:
            return False, score, angle_scores

    def batch_match(self,
                    query_embedding: np.ndarray,
                    visitor_profiles: Dict[str, List[MultiAngleEmbedding]],
                    threshold: float = 0.6) -> Tuple[Optional[str], float, Dict]:
        """
        Match a query embedding against multiple visitor profiles.
        Returns (visitor_id, confidence, angle_scores)
        """
        best_visitor_id = None
        best_confidence = 0.0
        best_angle_scores = {}

        for visitor_id, embeddings in visitor_profiles.items():
            is_match, confidence, angle_scores = self.match_with_angles(
                query_embedding, embeddings, threshold
            )
            if is_match and confidence > best_confidence:
                best_confidence = confidence
                best_visitor_id = visitor_id
                best_angle_scores = angle_scores

        return best_visitor_id, best_confidence, best_angle_scores
    
    def get_best_angle_match(self,
                           query_embedding: np.ndarray,
                           stored_embeddings: List[MultiAngleEmbedding]) -> Tuple[Optional[MultiAngleEmbedding], float]:
        """Get the best matching embedding from any angle"""
        best_match = None
        best_score = 0.0
        
        for stored_emb in stored_embeddings:
            score = self._cosine_similarity(query_embedding, stored_emb.embedding)
            if score > best_score:
                best_score = score
                best_match = stored_emb
        
        return best_match, best_score


class EnsembleVoting:
    """Ensemble voting for improved recognition accuracy"""
    
    def __init__(self, voting_method: str = "weighted_average"):
        self.voting_method = voting_method
        self.model_weights = {}
    
    def add_model(self, model_name: str, weight: float = 1.0):
        """Add a model to the ensemble"""
        self.model_weights[model_name] = weight
    
    def vote(self, 
            predictions: Dict[str, Tuple[str, float]]) -> Tuple[str, float]:
        """
        Vote from multiple model predictions
        
        Args:
            predictions: Dict of {model_name: (class_id, confidence)}
        
        Returns:
            (final_class, final_confidence)
        """
        if not predictions:
            return "", 0.0
        
        if self.voting_method == "weighted_average":
            return self._weighted_average_vote(predictions)
        elif self.voting_method == "majority":
            return self._majority_vote(predictions)
        elif self.voting_method == "max_confidence":
            return self._max_confidence_vote(predictions)
        else:
            return self._weighted_average_vote(predictions)
    
    def _weighted_average_vote(self, predictions: Dict[str, Tuple[str, float]]) -> Tuple[str, float]:
        """Weighted average voting"""
        class_scores = {}
        total_weight = 0.0
        
        for model_name, (class_id, confidence) in predictions.items():
            weight = self.model_weights.get(model_name, 1.0)
            
            if class_id not in class_scores:
                class_scores[class_id] = 0.0
            
            class_scores[class_id] += confidence * weight
            total_weight += weight
        
        if total_weight == 0:
            return "", 0.0
        
        for class_id in class_scores:
            class_scores[class_id] /= total_weight
        
        best_class = max(class_scores, key=class_scores.get)
        best_score = class_scores[best_class]
        
        return best_class, best_score
    
    def _majority_vote(self, predictions: Dict[str, Tuple[str, float]]) -> Tuple[str, float]:
        """Majority voting"""
        class_votes = {}
        
        for model_name, (class_id, confidence) in predictions.items():
            if class_id not in class_votes:
                class_votes[class_id] = 0
            class_votes[class_id] += 1
        
        if not class_votes:
            return "", 0.0
        
        best_class = max(class_votes, key=class_votes.get)
        
        confidence_sum = sum(
            conf for cls, conf in predictions.values() if cls == best_class
        )
        confidence = confidence_sum / class_votes[best_class]
        
        return best_class, confidence
    
    def _max_confidence_vote(self, predictions: Dict[str, Tuple[str, float]]) -> Tuple[str, float]:
        """Take prediction with highest confidence"""
        best = max(predictions.items(), key=lambda x: x[1][1])
        return best[1]


def get_default_multiangle_config() -> dict:
    """Get default multi-angle configuration"""
    return {
        "enabled": True,
        "min_angles": 1,
        "consensus_threshold": 0.6,
        "angle_weights": {
            "frontal": 1.0,
            "45_left": 0.8,
            "45_right": 0.8,
            "profile_left": 0.5,
            "profile_right": 0.5,
            "top_down": 0.3,
        },
        "store_all_angles": True,
    }


def get_default_ensemble_config() -> dict:
    """Get default ensemble configuration"""
    return {
        "enabled": False,
        "voting_method": "weighted_average",
        "models": {
            "arcface": 1.0,
            "facenet": 0.8,
            "vggface": 0.7,
        },
    }
