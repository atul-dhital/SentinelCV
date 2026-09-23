from __future__ import annotations

import time
from typing import Any, Dict, Optional

import numpy as np

from pose_estimator import PoseEstimator


class ActionInferenceEngine:
    def __init__(self) -> None:
        self._pose_estimator = PoseEstimator()
        self.available = self._pose_estimator.available
        self._track_memory: Dict[str, Dict[str, float]] = {}

    def _infer_action_from_pose(
        self,
        pose: Dict[str, Any],
        track_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        keypoints = pose.get("keypoints", [])
        if not keypoints:
            return {
                "action": "unknown",
                "gesture": "none",
                "confidence": 0.0,
                "flags": {
                    "hand_raised": False,
                    "possible_wave": False,
                },
            }

        def get_point(idx: int) -> Optional[Dict[str, float]]:
            if idx < 0 or idx >= len(keypoints):
                return None
            item = keypoints[idx]
            return {
                "x": float(item.get("x", 0.0)),
                "y": float(item.get("y", 0.0)),
                "visibility": float(item.get("visibility", 0.0)),
            }

        left_wrist = get_point(15)
        right_wrist = get_point(16)
        left_shoulder = get_point(11)
        right_shoulder = get_point(12)

        hand_raised = False
        if left_wrist and left_shoulder and left_wrist["visibility"] > 0.4 and left_shoulder["visibility"] > 0.4:
            hand_raised = hand_raised or (left_wrist["y"] < left_shoulder["y"])
        if right_wrist and right_shoulder and right_wrist["visibility"] > 0.4 and right_shoulder["visibility"] > 0.4:
            hand_raised = hand_raised or (right_wrist["y"] < right_shoulder["y"])

        posture = pose.get("posture", "unknown")
        action = "standing_or_walking"
        if posture == "sitting_or_crouching":
            action = "sitting"
        if hand_raised:
            action = "hand_raised"

        gesture = "none"
        possible_wave = False
        chosen_wrist = right_wrist or left_wrist
        if track_id and chosen_wrist and hand_raised:
            now = time.time()
            previous = self._track_memory.get(track_id)
            current_x = chosen_wrist["x"]

            if previous:
                dx = current_x - previous.get("x", current_x)
                dt = now - previous.get("t", now)
                prev_dx = previous.get("dx", 0.0)
                if dt <= 2.0 and abs(dx) > 0.05 and (dx * prev_dx) < 0:
                    gesture = "wave"
                    action = "wave"
                    possible_wave = True

            self._track_memory[track_id] = {
                "x": current_x,
                "dx": current_x - (previous.get("x", current_x) if previous else current_x),
                "t": now,
            }

        confidence = float(pose.get("average_visibility", 0.0) or 0.0)
        if hand_raised:
            confidence = min(1.0, confidence + 0.1)
        if gesture == "wave":
            confidence = min(1.0, confidence + 0.15)

        return {
            "action": action,
            "gesture": gesture,
            "confidence": round(confidence, 4),
            "flags": {
                "hand_raised": hand_raised,
                "possible_wave": possible_wave,
            },
        }

    def infer(self, frame: np.ndarray, track_id: Optional[str] = None) -> Dict[str, Any]:
        started = time.perf_counter()

        if frame is None:
            return {
                "status": "error",
                "available": self.available,
                "message": "Missing frame",
                "action": "unknown",
                "gesture": "none",
                "confidence": 0.0,
                "pose": {},
                "processing_time_ms": 0.0,
            }

        if not self.available:
            return {
                "status": "unavailable",
                "available": False,
                "message": "Action inference requires MediaPipe runtime support",
                "action": "unknown",
                "gesture": "none",
                "confidence": 0.0,
                "pose": {},
                "processing_time_ms": round((time.perf_counter() - started) * 1000, 2),
            }

        pose_result = self._pose_estimator.estimate(frame)
        inference = self._infer_action_from_pose(pose_result, track_id=track_id)

        return {
            "status": "ok",
            "available": True,
            "message": "Action inferred",
            "action": inference["action"],
            "gesture": inference["gesture"],
            "confidence": inference["confidence"],
            "flags": inference["flags"],
            "pose": {
                "posture": pose_result.get("posture", "unknown"),
                "keypoint_count": pose_result.get("keypoint_count", 0),
                "average_visibility": pose_result.get("average_visibility", 0.0),
            },
            "processing_time_ms": round((time.perf_counter() - started) * 1000, 2),
        }
