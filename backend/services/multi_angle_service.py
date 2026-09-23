"""
Multi-Angle Face Recognition Service (US-FUT-025)

Handles simultaneous face recognition from multiple angles (frontal, 45-left/right, profile).
Includes angle estimation, frame capture buffering, DB-backed gallery loading, and
consensus-based voting across angles.
"""

import json
import logging
import math
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from sqlalchemy.orm import Session

from models.models import FaceData, MultiAngleRecognitionConfig, Visitor

logger = logging.getLogger(__name__)


class FaceAngleDetector:
    """Detect head pose angle (yaw) from facial landmarks.

    Uses cv2.solvePnP with a standard 3-D face model when 5 landmarks are
    available (InsightFace / RetinaFace sparse format: left-eye, right-eye,
    nose-tip, left-mouth, right-mouth).  Falls back to geometric heuristics
    for dense landmark sets or when OpenCV is unavailable.
    """

    # Canonical 3-D face model points (mm) in a head-centred coordinate system.
    # Matches the 5-point sparse landmark order used by InsightFace/RetinaFace.
    _MODEL_POINTS_3D = np.array([
        [-30.0,  40.0, -10.0],   # left eye centre
        [ 30.0,  40.0, -10.0],   # right eye centre
        [  0.0,   0.0,   0.0],   # nose tip  (origin)
        [-20.0, -40.0, -10.0],   # left mouth corner
        [ 20.0, -40.0, -10.0],   # right mouth corner
    ], dtype=np.float32)

    ANGLE_CLASSES = {
        "frontal": (0, 30),
        "45_left": (-60, -30),
        "45_right": (30, 60),
        "profile": (-180, 180),
    }

    def __init__(self):
        try:
            import cv2 as _cv2  # noqa: F401 — verify cv2 importable at init
            self._cv2_available = True
        except ImportError:
            self._cv2_available = False

    def estimate_head_yaw(self, landmarks_2d: Any) -> float:
        """Return yaw in degrees (-90 … +90) from 2-D facial landmarks.

        Tries cv2.solvePnP first (accurate), then structured 5-point heuristic,
        then generic symmetry heuristic for any landmark layout.
        """
        if landmarks_2d is None:
            return 0.0

        try:
            landmarks = [
                [float(point[0]), float(point[1])]
                for point in landmarks_2d
                if point is not None and len(point) >= 2
            ]
        except Exception:
            return 0.0

        if len(landmarks) < 3:
            return 0.0

        if len(landmarks) == 5 and self._cv2_available:
            yaw = self._solvepnp_yaw(landmarks)
            if yaw is not None:
                return yaw

        return self._heuristic_yaw(landmarks)

    def _solvepnp_yaw(self, landmarks: List[List[float]]) -> Optional[float]:
        """Use cv2.solvePnP to estimate yaw from 5 sparse landmarks."""
        try:
            import cv2

            pts_2d = np.array(landmarks, dtype=np.float32)
            # Build a plausible camera matrix from the 2-D bounding box.
            x_coords = pts_2d[:, 0]
            y_coords = pts_2d[:, 1]
            face_width = float(max(x_coords) - min(x_coords))
            face_height = float(max(y_coords) - min(y_coords))
            if face_width < 1.0 or face_height < 1.0:
                return None

            focal = max(face_width, face_height) * 2.0
            cx = float(min(x_coords) + face_width / 2.0)
            cy = float(min(y_coords) + face_height / 2.0)
            camera_matrix = np.array([
                [focal, 0.0,   cx],
                [0.0,   focal, cy],
                [0.0,   0.0,   1.0],
            ], dtype=np.float32)
            dist_coeffs = np.zeros((4, 1), dtype=np.float32)

            success, rvec, _ = cv2.solvePnP(
                self._MODEL_POINTS_3D,
                pts_2d,
                camera_matrix,
                dist_coeffs,
                flags=cv2.SOLVEPNP_ITERATIVE,
            )
            if not success:
                return None

            rmat, _ = cv2.Rodrigues(rvec)
            # Decompose rotation matrix → Euler angles (yaw around Y-axis)
            sy = math.sqrt(rmat[0, 0] ** 2 + rmat[1, 0] ** 2)
            if sy > 1e-6:
                yaw_rad = math.atan2(-rmat[2, 0], sy)
            else:
                yaw_rad = math.atan2(-rmat[2, 0], sy)

            yaw_deg = math.degrees(yaw_rad)
            return float(max(-90.0, min(90.0, yaw_deg)))
        except Exception as exc:
            logger.debug("solvePnP yaw estimation failed: %s", exc)
            return None

    def _heuristic_yaw(self, landmarks: List[List[float]]) -> float:
        """Geometric symmetry heuristic — works for any number of landmarks."""
        x_coords = [p[0] for p in landmarks]
        y_coords = [p[1] for p in landmarks]
        face_width = float(max(x_coords) - min(x_coords))
        face_height = float(max(y_coords) - min(y_coords))
        if face_width <= 1e-6 or face_height <= 1e-6:
            return 0.0

        if len(landmarks) >= 5:
            eye_points = sorted(landmarks[:2], key=lambda p: p[0])
            mouth_points = sorted(landmarks[3:5], key=lambda p: p[0])
            left_eye = eye_points[0]
            right_eye = eye_points[1]
            nose = landmarks[2]
            left_mouth = mouth_points[0]
            right_mouth = mouth_points[1]

            center_x = float(min(x_coords) + face_width / 2.0)
            interocular = max(abs(right_eye[0] - left_eye[0]), 1e-6)
            nose_offset = (nose[0] - center_x) / max(face_width / 2.0, 1e-6)
            eye_slope = (right_eye[1] - left_eye[1]) / interocular
            mouth_mid_x = (left_mouth[0] + right_mouth[0]) / 2.0
            mouth_offset = (nose[0] - mouth_mid_x) / max(face_width / 2.0, 1e-6)

            yaw = (nose_offset * 78.0) + (mouth_offset * 18.0) + (eye_slope * 6.0)
            if abs(yaw) >= 3.0:
                return float(max(-90.0, min(90.0, yaw)))

        center_x = float(min(x_coords) + face_width / 2.0)
        sorted_y = sorted(y_coords)
        median_y = sorted_y[len(sorted_y) // 2]
        center_scores = [
            abs(x - center_x) + 0.35 * abs(y - median_y)
            for x, y in zip(x_coords, y_coords)
        ]
        nose_idx = min(range(len(center_scores)), key=lambda idx: center_scores[idx])

        left_x = min(x_coords)
        right_x = max(x_coords)
        nose_x = float(x_coords[nose_idx])

        left_span = max(nose_x - left_x, 1e-6)
        right_span = max(right_x - nose_x, 1e-6)
        balance = (right_span - left_span) / max(face_width, 1e-6)
        return float(max(-90.0, min(90.0, balance * 180.0)))
        
    def classify_angle(self, yaw: float) -> Tuple[str, float]:
        """Classify face angle into a category and confidence score."""
        if -30.0 <= yaw <= 30.0:
            confidence = max(0.55, 1.0 - (abs(yaw) / 30.0) * 0.45)
            return "frontal", confidence
        if yaw <= -60.0 or yaw >= 60.0:
            distance_from_profile = min(abs(abs(yaw) - 90.0), 30.0)
            confidence = max(0.55, 1.0 - (distance_from_profile / 30.0) * 0.45)
            return "profile", confidence

        for angle_class, (min_yaw, max_yaw) in self.ANGLE_CLASSES.items():
            if angle_class in {"profile", "frontal"}:
                continue
            if min_yaw <= yaw <= max_yaw:
                center = (min_yaw + max_yaw) / 2
                dist_from_center = abs(yaw - center)
                max_dist = (max_yaw - min_yaw) / 2
                confidence = max(0.5, 1.0 - (dist_from_center / (max_dist or 1.0) * 0.5))
                return angle_class, confidence
        return "unknown", 0.0


class MultiAngleFrameCapture:
    """Buffer frames captured at different facial angles."""
    
    def __init__(self, required_angles: List[str]):
        self.required_angles = required_angles
        self.angle_frames = {angle: None for angle in required_angles}
        self.angle_confidences = {angle: 0.0 for angle in required_angles}
        self.detector = FaceAngleDetector()
        
    def add_frame(
        self,
        frame: Any,
        landmarks: Any,
        embedding: Any
    ) -> Dict[str, bool]:
        """Try to capture frame for each required angle category."""
        yaw = self.detector.estimate_head_yaw(landmarks)
        angle_class, confidence = self.detector.classify_angle(yaw)
        
        captured = {}
        if angle_class in self.angle_frames:
            # Capture if no frame yet or higher confidence
            if (self.angle_frames[angle_class] is None or 
                confidence > self.angle_confidences[angle_class]):
                
                self.angle_frames[angle_class] = {
                    "frame": frame.copy(),
                    "landmarks": landmarks.copy(),
                    "embedding": embedding.copy(),
                    "yaw": yaw,
                    "confidence": confidence
                }
                self.angle_confidences[angle_class] = confidence
                captured[angle_class] = True
                
        return captured
    
    def is_complete(self) -> bool:
        """Check if all required angles have been captured."""
        return all(self.angle_frames[angle] is not None for angle in self.required_angles)


class MultiAngleRecognitionService:
    """Orchestrates the multi-angle face identification process."""
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.angle_detector = FaceAngleDetector()
    
    def perform_consensus_identification(
        self,
        angle_capture: MultiAngleFrameCapture,
        db_embeddings: Optional[List[Any]] = None,
        db: Optional[Session] = None,
        organization_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Identify a person by achieving consensus across multiple view angles.

        Strategy: Compare each captured angle against the visitor gallery
        and perform weighted consensus voting. The gallery can be passed in
        explicitly via ``db_embeddings`` or loaded from the database when
        a ``db`` session and ``organization_id`` are provided.
        """
        captured_angles = [a for a in angle_capture.required_angles if angle_capture.angle_frames[a] is not None]
        if not captured_angles:
            return {"visitor_id": None, "confidence": 0.0, "angles_used": []}

        if db_embeddings is None and db is not None and organization_id is not None:
            db_embeddings = self.load_visitor_gallery(db, organization_id)
        elif db_embeddings is None:
            db_embeddings = []

        per_angle_matches = {}
        visitor_votes = {}

        for angle in captured_angles:
            data = angle_capture.angle_frames[angle]
            embedding = data["embedding"]

            match = self._match_embedding(embedding, db_embeddings)
            
            if match["matched"]:
                vid = match["visitor_id"]
                conf = match["confidence"]
                
                per_angle_matches[angle] = match
                
                # Weight vote by angle confidence and match confidence
                weight = data["confidence"] * conf
                visitor_votes[vid] = visitor_votes.get(vid, 0.0) + weight
        
        if not visitor_votes:
            return {"visitor_id": None, "confidence": 0.0, "angles_used": captured_angles}
            
        # Select winner by consensus
        winner_id = max(visitor_votes, key=visitor_votes.get)
        total_votes = sum(visitor_votes.values())
        final_confidence = visitor_votes[winner_id] / total_votes
        
        return {
            "visitor_id": winner_id,
            "confidence": final_confidence,
            "angles_used": captured_angles,
            "matches": per_angle_matches
        }
        
    def load_visitor_gallery(
        self,
        db: Session,
        organization_id: str,
    ) -> List[Dict[str, Any]]:
        """Load all visitor face embeddings for an organization.

        Returns a list of ``{"visitor_id", "embedding", "angle"}`` dicts that
        can be passed directly to ``perform_consensus_identification``. Each
        ``FaceData`` row contributes one entry per stored angle so per-angle
        matching can prefer same-angle gallery items if needed.
        """
        gallery: List[Dict[str, Any]] = []

        rows = (
            db.query(FaceData)
            .join(Visitor, Visitor.id == FaceData.visitor_id)
            .filter(Visitor.organization_id == organization_id)
            .all()
        )

        for row in rows:
            embedding_value = getattr(row, "embedding", None)
            if embedding_value is None:
                continue

            # Embeddings can be stored as a Python list (pgvector) or as a
            # JSON-serialized string when running on SQLite. Normalize both.
            if isinstance(embedding_value, str):
                try:
                    embedding_value = json.loads(embedding_value)
                except (TypeError, ValueError):
                    continue

            try:
                embedding_floats = [float(value) for value in embedding_value]
            except (TypeError, ValueError):
                continue

            if not embedding_floats:
                continue

            gallery.append(
                {
                    "visitor_id": str(row.visitor_id),
                    "embedding": embedding_floats,
                    "angle": getattr(row, "face_angle", None) or "frontal",
                }
            )

        logger.debug(
            "Loaded %d gallery embeddings for organization %s",
            len(gallery),
            organization_id,
        )
        return gallery

    def _match_embedding(self, embedding: Any, db_embeddings: List[Any]) -> Dict[str, Any]:
        """Match an embedding against a list of DB embeddings using cosine similarity.

        Supported item shapes:
        - {"visitor_id": "...", "embedding": [...]}
        - {"visitor_id": "...", "vector": [...]}
        - (visitor_id, embedding)
        """
        if embedding is None:
            return {"matched": False, "visitor_id": None, "confidence": 0.0}

        try:
            query_vec = [float(value) for value in embedding]
        except Exception:
            return {"matched": False, "visitor_id": None, "confidence": 0.0}

        query_norm = math.sqrt(sum(value * value for value in query_vec))
        if query_norm == 0.0:
            return {"matched": False, "visitor_id": None, "confidence": 0.0}

        best_visitor_id: Optional[str] = None
        best_score = -1.0

        for item in db_embeddings:
            visitor_id = None
            candidate_embedding = None

            if isinstance(item, dict):
                visitor_id = item.get("visitor_id") or item.get("id")
                candidate_embedding = item.get("embedding", item.get("vector"))
            elif isinstance(item, (tuple, list)) and len(item) >= 2:
                visitor_id = item[0]
                candidate_embedding = item[1]

            if visitor_id is None or candidate_embedding is None:
                continue

            try:
                candidate_vec = [float(value) for value in candidate_embedding]
            except Exception:
                continue
            dim = min(len(query_vec), len(candidate_vec))
            if dim == 0:
                continue

            q = query_vec[:dim]
            c = candidate_vec[:dim]
            candidate_norm = math.sqrt(sum(value * value for value in c))
            if candidate_norm == 0.0:
                continue

            q_norm = math.sqrt(sum(value * value for value in q))
            if q_norm == 0.0:
                continue
            similarity = float(sum(a * b for a, b in zip(q, c)) / (q_norm * candidate_norm))
            if similarity > best_score:
                best_score = similarity
                best_visitor_id = str(visitor_id)

        if best_visitor_id is None:
            return {"matched": False, "visitor_id": None, "confidence": 0.0}

        confidence = max(0.0, min(1.0, best_score))
        return {
            "matched": confidence >= 0.6,
            "visitor_id": best_visitor_id,
            "confidence": confidence,
        }

    def get_weighted_consensus(self, angle_similarities: List[Tuple[str, float]]) -> float:
        """
        Calculate weighted consensus across multiple angles.
        Angles that are typically harder to recognize (profile, 45_left/right) 
        are given slightly more weight if they match, as they imply higher discriminatory power.
        """
        if not angle_similarities:
            return 0.0

        WEIGHTS = {
            "frontal": 1.0,
            "45_left": 1.2,
            "45_right": 1.2,
            "profile": 1.4,
            "unknown": 0.8
        }

        total_weighted_score = 0.0
        total_weight = 0.0

        for angle, similarity in angle_similarities:
            w = WEIGHTS.get(angle, 1.0)
            total_weighted_score += similarity * w
            total_weight += w

        return total_weighted_score / total_weight if total_weight > 0 else 0.0


# Export singleton instance for use in other services
multi_angle_matcher = MultiAngleRecognitionService(config={})
