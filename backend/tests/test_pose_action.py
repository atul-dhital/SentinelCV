"""Tests for real pose-based action recognition.

- Pose service: lazy/fail-soft/singleton; runs on a frame without error.
- Action inference: the geometric classifier produces *differentiated* output
  for distinct real-keypoint geometries (proves it is not the random fallback).
"""

import numpy as np
import pytest

from services.pose_estimation_service import (
    PoseEstimationService,
    get_pose_service,
    _COCO_KEYPOINTS,
)
from services.phase3_service_scaffolds import EmotionActionRecognitionService


def test_disabled_returns_none_without_download(monkeypatch):
    monkeypatch.setenv("ENABLE_REAL_POSE_MODEL", "0")
    svc = PoseEstimationService()
    assert svc.available() is False
    assert svc.extract_from_frame(np.zeros((64, 64, 3), dtype=np.uint8)) is None


def test_singleton_identity():
    assert get_pose_service() is get_pose_service()


def test_coco_keypoint_count():
    assert len(_COCO_KEYPOINTS) == 17


def test_action_inference_is_real_and_differentiated():
    """Real geometric classifier must distinguish sitting vs standing poses."""
    svc = EmotionActionRecognitionService(db=None)

    def kp(hip_y, knee_y):
        return {
            "left_hip": {"x": 100, "y": hip_y, "confidence": 0.9},
            "right_hip": {"x": 140, "y": hip_y, "confidence": 0.9},
            "left_knee": {"x": 100, "y": knee_y, "confidence": 0.9},
            "right_knee": {"x": 140, "y": knee_y, "confidence": 0.9},
            "left_shoulder": {"x": 100, "y": hip_y - 120, "confidence": 0.9},
            "left_wrist": {"x": 100, "y": hip_y - 60, "confidence": 0.9},
            "right_wrist": {"x": 140, "y": hip_y - 60, "confidence": 0.9},
        }

    sitting = svc._infer_action_from_pose(kp(hip_y=300, knee_y=320))   # knees ~ hips
    standing = svc._infer_action_from_pose(kp(hip_y=300, knee_y=440))  # knees far below

    assert sitting["sitting"] > sitting["standing"]
    assert standing["standing"] > standing["sitting"]
    # Distinct geometries must yield distinct dominant actions (not constant).
    assert max(sitting, key=sitting.get) != max(standing, key=standing.get)


def test_pose_model_runs_on_frame_if_available():
    svc = PoseEstimationService()
    if not svc.available():
        pytest.skip("Pose model not available in this environment")
    # Random noise: model runs without error; no real person -> None (fail-soft).
    out = svc.extract_from_frame(np.random.randint(0, 255, (256, 256, 3), dtype=np.uint8))
    assert out is None or set(out.keys()) == set(_COCO_KEYPOINTS)
