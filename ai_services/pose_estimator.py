from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import cv2
import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

try:
    import mediapipe as mp
    from shared.mediapipe_compat import ensure_legacy_solutions
    if not ensure_legacy_solutions():
        mp = None
except Exception:
    mp = None


_POSE_INDEX = {
    "left_shoulder": 11,
    "right_shoulder": 12,
    "left_hip": 23,
    "right_hip": 24,
    "left_knee": 25,
    "right_knee": 26,
    "left_wrist": 15,
    "right_wrist": 16,
}


def _get_point(points: List[Dict[str, float]], name: str) -> Optional[Dict[str, float]]:
    idx = _POSE_INDEX.get(name)
    if idx is None or idx >= len(points):
        return None
    return points[idx]


class PoseEstimator:
    def __init__(self) -> None:
        self.available = mp is not None
        self._pose = None
        if self.available:
            self._pose = mp.solutions.pose.Pose(
                static_image_mode=False,
                model_complexity=1,
                smooth_landmarks=True,
                min_detection_confidence=0.5,
                min_tracking_confidence=0.5,
            )

    def _infer_posture(self, points: List[Dict[str, float]]) -> str:
        left_hip = _get_point(points, "left_hip")
        right_hip = _get_point(points, "right_hip")
        left_knee = _get_point(points, "left_knee")
        right_knee = _get_point(points, "right_knee")
        left_shoulder = _get_point(points, "left_shoulder")
        right_shoulder = _get_point(points, "right_shoulder")

        if not all((left_hip, right_hip, left_knee, right_knee, left_shoulder, right_shoulder)):
            return "unknown"

        hip_y = (left_hip["y"] + right_hip["y"]) / 2.0
        knee_y = (left_knee["y"] + right_knee["y"]) / 2.0
        shoulder_y = (left_shoulder["y"] + right_shoulder["y"]) / 2.0

        torso = max(0.001, hip_y - shoulder_y)
        leg = knee_y - hip_y
        ratio = leg / torso

        if ratio < 0.3:
            return "sitting_or_crouching"
        if ratio > 0.9:
            return "standing"
        return "transitioning"

    def estimate(self, frame: np.ndarray) -> Dict[str, Any]:
        started = time.perf_counter()

        if frame is None:
            return {
                "status": "error",
                "available": self.available,
                "message": "Missing frame",
                "posture": "unknown",
                "keypoint_count": 0,
                "average_visibility": 0.0,
                "keypoints": [],
                "processing_time_ms": 0.0,
            }

        if not self.available or self._pose is None:
            return {
                "status": "unavailable",
                "available": False,
                "message": "MediaPipe is not installed in this environment",
                "posture": "unknown",
                "keypoint_count": 0,
                "average_visibility": 0.0,
                "keypoints": [],
                "processing_time_ms": round((time.perf_counter() - started) * 1000, 2),
            }

        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        result = self._pose.process(rgb)
        if not result.pose_landmarks:
            return {
                "status": "ok",
                "available": True,
                "message": "No pose landmarks detected",
                "posture": "unknown",
                "keypoint_count": 0,
                "average_visibility": 0.0,
                "keypoints": [],
                "processing_time_ms": round((time.perf_counter() - started) * 1000, 2),
            }

        keypoints: List[Dict[str, float]] = []
        visibilities: List[float] = []
        for idx, landmark in enumerate(result.pose_landmarks.landmark):
            visibility = float(getattr(landmark, "visibility", 0.0) or 0.0)
            visibilities.append(visibility)
            keypoints.append(
                {
                    "id": float(idx),
                    "x": round(float(landmark.x), 4),
                    "y": round(float(landmark.y), 4),
                    "z": round(float(landmark.z), 4),
                    "visibility": round(visibility, 4),
                }
            )

        posture = self._infer_posture(keypoints)
        avg_visibility = round(sum(visibilities) / max(len(visibilities), 1), 4)

        return {
            "status": "ok",
            "available": True,
            "message": "Pose estimated",
            "posture": posture,
            "keypoint_count": len(keypoints),
            "average_visibility": avg_visibility,
            "keypoints": keypoints,
            "processing_time_ms": round((time.perf_counter() - started) * 1000, 2),
        }
