"""Real human-pose keypoint extraction (torchvision Keypoint R-CNN).

Provides genuine 17-point COCO pose keypoints from an image or video frame, used
to drive the existing geometric action classifier
(`EmotionActionRecognitionService._infer_action_from_pose`). This is the working
real-pose path in environments where MediaPipe is unavailable/broken.

Lazy load, env-gated (`ENABLE_REAL_POSE_MODEL=0` forces fallback), fail-soft to
None so callers degrade to the prior simulation rather than erroring.

Output keypoint dict matches the format the action service already expects:
    {part_name: {"x": float, "y": float, "confidence": float}}
"""

from __future__ import annotations

import logging
import math
import os
import threading
from typing import Dict, List, Optional

import numpy as np

logger = logging.getLogger(__name__)

# torchvision Keypoint R-CNN returns keypoints in this COCO order.
_COCO_KEYPOINTS: List[str] = [
    "nose", "left_eye", "right_eye", "left_ear", "right_ear",
    "left_shoulder", "right_shoulder", "left_elbow", "right_elbow",
    "left_wrist", "right_wrist", "left_hip", "right_hip",
    "left_knee", "right_knee", "left_ankle", "right_ankle",
]
_IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".bmp", ".webp")


def _sigmoid(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-x))


class PoseEstimationService:
    """Lazy, fail-soft wrapper around torchvision Keypoint R-CNN."""

    def __init__(self) -> None:
        self.enabled = os.getenv("ENABLE_REAL_POSE_MODEL", "1") == "1"
        self._model = None
        self._load_attempted = False
        self._lock = threading.Lock()

    def _ensure_loaded(self) -> bool:
        if self._model is not None:
            return True
        if not self.enabled or self._load_attempted:
            return self._model is not None
        with self._lock:
            if self._model is not None:
                return True
            if self._load_attempted:
                return False
            self._load_attempted = True
            try:
                import torch  # noqa: F401
                from torchvision.models.detection import (
                    keypointrcnn_resnet50_fpn,
                    KeypointRCNN_ResNet50_FPN_Weights,
                )

                logger.info("Loading pose model: torchvision Keypoint R-CNN")
                weights = KeypointRCNN_ResNet50_FPN_Weights.DEFAULT
                self._model = keypointrcnn_resnet50_fpn(weights=weights)
                self._model.eval()
                logger.info("Pose model loaded")
                return True
            except Exception as exc:  # noqa: BLE001 - fail soft
                logger.warning("Pose model unavailable, will use fallback: %s", exc)
                self.enabled = False
                self._model = None
                return False

    def available(self) -> bool:
        return self._ensure_loaded()

    def extract_from_frame(self, frame_bgr: np.ndarray, min_box_score: float = 0.7) -> Optional[Dict]:
        """Return COCO keypoint dict for the highest-scoring person, or None."""
        if frame_bgr is None or not self._ensure_loaded():
            return None
        try:
            import torch

            rgb = np.ascontiguousarray(frame_bgr[:, :, ::-1])  # BGR -> RGB
            tensor = torch.from_numpy(rgb).permute(2, 0, 1).float() / 255.0
            with torch.no_grad():
                out = self._model([tensor])[0]

            scores = out.get("scores")
            kps = out.get("keypoints")
            kps_scores = out.get("keypoints_scores")
            if scores is None or kps is None or scores.numel() == 0:
                return None
            best = int(torch.argmax(scores).item())
            if float(scores[best].item()) < min_box_score:
                return None

            person_kps = kps[best].cpu().numpy()          # (17, 3): x, y, vis
            person_kscore = (
                kps_scores[best].cpu().numpy() if kps_scores is not None else None
            )
            result: Dict[str, Dict[str, float]] = {}
            for i, part in enumerate(_COCO_KEYPOINTS):
                conf = _sigmoid(float(person_kscore[i])) if person_kscore is not None else 1.0
                result[part] = {
                    "x": round(float(person_kps[i][0]), 1),
                    "y": round(float(person_kps[i][1]), 1),
                    "confidence": round(conf, 3),
                }
            return result
        except Exception as exc:  # noqa: BLE001 - fail soft
            logger.warning("Pose extraction failed: %s", exc)
            return None

    def extract_from_video(self, path: str, max_frames: int = 8) -> Optional[Dict]:
        """Sample frames from a video (or read a single image) and return the
        last frame's keypoints. Returns None if no person is found anywhere.
        """
        if not path or not os.path.exists(path) or not self._ensure_loaded():
            return None
        try:
            import cv2

            if path.lower().endswith(_IMAGE_EXTS):
                return self.extract_from_frame(cv2.imread(path))

            cap = cv2.VideoCapture(path)
            total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
            step = max(1, total // max_frames) if total else 1
            last_good: Optional[Dict] = None
            idx = 0
            grabbed = 0
            while cap.isOpened() and grabbed < max_frames:
                ok, frame = cap.read()
                if not ok:
                    break
                if idx % step == 0:
                    kp = self.extract_from_frame(frame)
                    if kp is not None:
                        last_good = kp
                    grabbed += 1
                idx += 1
            cap.release()
            return last_good
        except Exception as exc:  # noqa: BLE001 - fail soft
            logger.warning("Video pose extraction failed: %s", exc)
            return None


_service: Optional[PoseEstimationService] = None
_service_lock = threading.Lock()


def get_pose_service() -> PoseEstimationService:
    global _service
    if _service is None:
        with _service_lock:
            if _service is None:
                _service = PoseEstimationService()
    return _service
