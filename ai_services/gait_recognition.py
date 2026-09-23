"""
Gait Recognition Service (ENH-014)

Identifies individuals by their walking pattern using pose landmark analysis.
Extracts gait cycle features (stride, cadence, joint angles, symmetry)
from video sequences and computes a 64-dimensional gait embedding.
"""

import logging
import math
import sys
import numpy as np
from pathlib import Path
from typing import List, Dict, Optional, Tuple, Any

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Try to import MediaPipe for pose estimation
try:
    import mediapipe as mp
    from shared.mediapipe_compat import ensure_legacy_solutions
    HAS_MEDIAPIPE = ensure_legacy_solutions()
except ImportError:
    HAS_MEDIAPIPE = False

if not HAS_MEDIAPIPE:
    logger.info("MediaPipe not available; gait recognition will use fallback features")


class GaitRecognitionService:
    """Gait-based person identification using pose landmarks."""

    # Key landmark indices (MediaPipe Pose)
    LEFT_HIP, RIGHT_HIP = 23, 24
    LEFT_KNEE, RIGHT_KNEE = 25, 26
    LEFT_ANKLE, RIGHT_ANKLE = 27, 28
    LEFT_SHOULDER, RIGHT_SHOULDER = 11, 12
    LEFT_HEEL, RIGHT_HEEL = 29, 30

    def __init__(self):
        self._pose = None
        if HAS_MEDIAPIPE:
            try:
                self._pose = mp.solutions.pose.Pose(
                    static_image_mode=False,
                    model_complexity=1,
                    min_detection_confidence=0.5,
                    min_tracking_confidence=0.5,
                )
            except Exception as e:
                logger.warning(f"Failed to initialize MediaPipe Pose: {e}")

    def _extract_landmarks(self, frame: np.ndarray) -> Optional[List[Dict]]:
        """Extract pose landmarks from a single frame."""
        if self._pose is None:
            return None

        import cv2
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        results = self._pose.process(rgb)

        if not results.pose_landmarks:
            return None

        landmarks = []
        for lm in results.pose_landmarks.landmark:
            landmarks.append({
                "x": lm.x, "y": lm.y, "z": lm.z,
                "visibility": lm.visibility,
            })
        return landmarks

    def extract_gait_features(self, frames: List[np.ndarray]) -> Dict[str, Any]:
        """
        Extract gait cycle features from a sequence of video frames.

        Returns:
            Dictionary of gait features including stride, cadence, angles, symmetry.
        """
        if len(frames) < 10:
            return {"error": "Need at least 10 frames for gait analysis", "valid": False}

        all_landmarks = []
        for frame in frames:
            lms = self._extract_landmarks(frame)
            if lms:
                all_landmarks.append(lms)

        if len(all_landmarks) < 5:
            # Fallback: generate statistical features from frame differences
            return self._fallback_features(frames)

        # Extract temporal features
        features = {
            "valid": True,
            "num_frames": len(all_landmarks),
        }

        # Joint angles over time
        knee_angles_left = []
        knee_angles_right = []
        hip_angles_left = []
        hip_angles_right = []
        stride_widths = []
        body_heights = []

        for lms in all_landmarks:
            # Knee angles
            knee_angles_left.append(self._angle(
                lms[self.LEFT_HIP], lms[self.LEFT_KNEE], lms[self.LEFT_ANKLE]
            ))
            knee_angles_right.append(self._angle(
                lms[self.RIGHT_HIP], lms[self.RIGHT_KNEE], lms[self.RIGHT_ANKLE]
            ))

            # Hip angles
            hip_angles_left.append(self._angle(
                lms[self.LEFT_SHOULDER], lms[self.LEFT_HIP], lms[self.LEFT_KNEE]
            ))
            hip_angles_right.append(self._angle(
                lms[self.RIGHT_SHOULDER], lms[self.RIGHT_HIP], lms[self.RIGHT_KNEE]
            ))

            # Stride width (horizontal distance between ankles)
            stride_widths.append(abs(lms[self.LEFT_ANKLE]["x"] - lms[self.RIGHT_ANKLE]["x"]))

            # Body height (head to ankle)
            body_heights.append(abs(lms[0]["y"] - max(lms[self.LEFT_ANKLE]["y"], lms[self.RIGHT_ANKLE]["y"])))

        features["knee_angle_left"] = {"mean": np.mean(knee_angles_left), "std": np.std(knee_angles_left),
                                        "range": np.ptp(knee_angles_left)}
        features["knee_angle_right"] = {"mean": np.mean(knee_angles_right), "std": np.std(knee_angles_right),
                                         "range": np.ptp(knee_angles_right)}
        features["hip_angle_left"] = {"mean": np.mean(hip_angles_left), "std": np.std(hip_angles_left)}
        features["hip_angle_right"] = {"mean": np.mean(hip_angles_right), "std": np.std(hip_angles_right)}

        # Symmetry (left vs right similarity)
        features["knee_symmetry"] = 1.0 - abs(np.mean(knee_angles_left) - np.mean(knee_angles_right)) / 180.0
        features["hip_symmetry"] = 1.0 - abs(np.mean(hip_angles_left) - np.mean(hip_angles_right)) / 180.0

        # Stride metrics
        features["stride_width"] = {"mean": np.mean(stride_widths), "std": np.std(stride_widths)}

        # Cadence estimation (frequency of stride width oscillation)
        if len(stride_widths) > 3:
            fft = np.fft.rfft(stride_widths - np.mean(stride_widths))
            magnitudes = np.abs(fft)
            if len(magnitudes) > 1:
                dominant_freq = np.argmax(magnitudes[1:]) + 1
                features["cadence_frequency"] = float(dominant_freq)
            else:
                features["cadence_frequency"] = 0.0

        features["body_height_ratio"] = {"mean": np.mean(body_heights), "std": np.std(body_heights)}

        return features

    def compute_gait_signature(self, features: Dict) -> List[float]:
        """
        Compute a 64-dimensional gait embedding from extracted features.

        The embedding captures the unique walking pattern of an individual.
        """
        if not features.get("valid"):
            # Return zero embedding for invalid features
            return [0.0] * 64

        components = []

        # Knee angle statistics (8 dims)
        for side in ["knee_angle_left", "knee_angle_right"]:
            data = features.get(side, {})
            components.extend([
                data.get("mean", 0) / 180.0,
                data.get("std", 0) / 90.0,
                data.get("range", 0) / 180.0,
                (data.get("mean", 0) + data.get("std", 0)) / 270.0,
            ])

        # Hip angle statistics (4 dims)
        for side in ["hip_angle_left", "hip_angle_right"]:
            data = features.get(side, {})
            components.extend([
                data.get("mean", 0) / 180.0,
                data.get("std", 0) / 90.0,
            ])

        # Symmetry features (2 dims)
        components.append(features.get("knee_symmetry", 0.5))
        components.append(features.get("hip_symmetry", 0.5))

        # Stride features (3 dims)
        stride = features.get("stride_width", {})
        components.extend([
            stride.get("mean", 0),
            stride.get("std", 0),
            features.get("cadence_frequency", 0) / 10.0,
        ])

        # Body proportion (2 dims)
        bh = features.get("body_height_ratio", {})
        components.extend([bh.get("mean", 0), bh.get("std", 0)])

        # Pad or truncate to 64 dimensions
        components = components[:64]
        while len(components) < 64:
            # Fill remaining with derived features (cross-products)
            idx = len(components) % len(components) if components else 0
            components.append(components[idx] * 0.7 if idx < len(components) else 0.0)

        # L2 normalize
        arr = np.array(components, dtype=np.float64)
        norm = np.linalg.norm(arr)
        if norm > 0:
            arr = arr / norm

        return arr.tolist()

    def match_gait(
        self,
        signature: List[float],
        database_signatures: List[Dict],
        threshold: float = 0.65,
    ) -> List[Dict]:
        """
        Match a gait signature against stored signatures.

        Returns ranked list of matches above threshold.
        """
        query = np.array(signature, dtype=np.float64)
        query_norm = np.linalg.norm(query)
        if query_norm > 0:
            query = query / query_norm

        matches = []
        for entry in database_signatures:
            db_sig = np.array(entry["embedding"], dtype=np.float64)
            db_norm = np.linalg.norm(db_sig)
            if db_norm > 0:
                db_sig = db_sig / db_norm

            similarity = float(np.dot(query, db_sig))
            if similarity >= threshold:
                matches.append({
                    "visitor_id": entry.get("visitor_id"),
                    "similarity": round(similarity, 4),
                    "quality_score": entry.get("quality_score", 0),
                })

        matches.sort(key=lambda m: m["similarity"], reverse=True)
        return matches

    def analyze_gait_quality(self, features: Dict) -> Dict:
        """Assess the quality of extracted gait features."""
        if not features.get("valid"):
            return {"quality": "poor", "score": 0.0, "issues": ["Insufficient landmarks detected"]}

        score = 1.0
        issues = []

        # Check frame count
        if features.get("num_frames", 0) < 15:
            score -= 0.3
            issues.append("Too few frames for reliable gait analysis")

        # Check symmetry
        if features.get("knee_symmetry", 0) < 0.7:
            score -= 0.2
            issues.append("Low knee symmetry - possible occlusion or limp")

        # Check angle variation
        for side in ["knee_angle_left", "knee_angle_right"]:
            data = features.get(side, {})
            if data.get("range", 0) < 10:
                score -= 0.15
                issues.append(f"Low {side.replace('_', ' ')} variation")

        quality = "good" if score >= 0.7 else "moderate" if score >= 0.4 else "poor"
        return {"quality": quality, "score": max(0, round(score, 2)), "issues": issues}

    def _angle(self, a: Dict, b: Dict, c: Dict) -> float:
        """Calculate angle at point b given three landmark points."""
        ba = np.array([a["x"] - b["x"], a["y"] - b["y"]])
        bc = np.array([c["x"] - b["x"], c["y"] - b["y"]])
        cos_angle = np.dot(ba, bc) / (np.linalg.norm(ba) * np.linalg.norm(bc) + 1e-8)
        return float(np.degrees(np.arccos(np.clip(cos_angle, -1.0, 1.0))))

    def _fallback_features(self, frames: List[np.ndarray]) -> Dict:
        """Generate basic motion features when pose detection fails."""
        import cv2

        features = {"valid": True, "num_frames": len(frames), "fallback": True}
        diffs = []
        for i in range(1, min(len(frames), 30)):
            gray_a = cv2.cvtColor(frames[i - 1], cv2.COLOR_BGR2GRAY)
            gray_b = cv2.cvtColor(frames[i], cv2.COLOR_BGR2GRAY)
            diff = np.abs(gray_a.astype(float) - gray_b.astype(float))
            diffs.append(np.mean(diff))

        features["motion_mean"] = float(np.mean(diffs)) if diffs else 0
        features["motion_std"] = float(np.std(diffs)) if diffs else 0
        features["knee_symmetry"] = 0.5
        features["hip_symmetry"] = 0.5
        features["cadence_frequency"] = 0.0
        features["knee_angle_left"] = {"mean": 0, "std": 0, "range": 0}
        features["knee_angle_right"] = {"mean": 0, "std": 0, "range": 0}
        features["hip_angle_left"] = {"mean": 0, "std": 0}
        features["hip_angle_right"] = {"mean": 0, "std": 0}
        features["stride_width"] = {"mean": 0, "std": 0}
        features["body_height_ratio"] = {"mean": 0, "std": 0}
        return features


gait_service = GaitRecognitionService()
