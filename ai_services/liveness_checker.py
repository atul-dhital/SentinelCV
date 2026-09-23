"""
Lightweight liveness checker for the AI service.

Mirrors the backend's LivenessDetectionService logic (texture LBP +
spectral/DCT/FFT analysis) but without backend schema dependencies.
This avoids an HTTP round-trip to the backend for every frame.

Returns plain dicts so it can be used from the RTSP stream manager
and the /process endpoint with zero coupling to the backend.
"""

import cv2
import numpy as np
from typing import Dict, Any, Optional, Tuple, List
from pathlib import Path
import logging
import os
import sys
from runtime_registry import get_runtime_component

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from shared.liveness_core import LivenessCore

logger = logging.getLogger(__name__)

# Default thresholds — override via environment variables
DEFAULT_CONFIDENCE_THRESHOLD = float(os.getenv("LIVENESS_CONFIDENCE_THRESHOLD", "0.5"))
_ATTACK_PRINT_ENTROPY_MAX   = float(os.getenv("LIVENESS_PRINT_ENTROPY_MAX",   "0.3"))
_ATTACK_REPLAY_FLOW_MAX     = float(os.getenv("LIVENESS_REPLAY_FLOW_MAX",     "1.0"))
_ATTACK_REPLAY_TEXTURE_MIN  = float(os.getenv("LIVENESS_REPLAY_TEXTURE_MIN",  "0.6"))
_ATTACK_MASK_BLUR_MAX       = float(os.getenv("LIVENESS_MASK_BLUR_MAX",       "0.15"))
_ATTACK_MASK_TEXTURE_MIN    = float(os.getenv("LIVENESS_MASK_TEXTURE_MIN",    "0.7"))
_ENSEMBLE_W_TEXTURE         = float(os.getenv("LIVENESS_ENSEMBLE_W_TEXTURE",  "0.3"))
_ENSEMBLE_W_MOTION          = float(os.getenv("LIVENESS_ENSEMBLE_W_MOTION",   "0.4"))
_ENSEMBLE_W_DEEP            = float(os.getenv("LIVENESS_ENSEMBLE_W_DEEP",     "0.3"))


class LivenessChecker:
    """Stateless liveness checker using texture, motion, and spectral analysis."""

    def __init__(self, confidence_threshold: float = DEFAULT_CONFIDENCE_THRESHOLD):
        runtime_config = get_runtime_component("liveness_engine")
        threshold_env = os.getenv("LIVENESS_CONFIDENCE_THRESHOLD")
        self.confidence_threshold = float(threshold_env) if threshold_env else confidence_threshold
        self.ensemble_method = os.getenv("LIVENESS_ENSEMBLE_METHOD", "weighted")
        self.model_name = runtime_config.get("current_model", "Spectral + CNN Ensemble")
        self.model_path = runtime_config.get("current_artifact", "models/liveness_net.onnx")
        self._core = LivenessCore(model_path=self.model_path)
        self.face_cascade = None
        try:
            cascade_path = cv2.data.haarcascades
            self.face_cascade = cv2.CascadeClassifier(
                f"{cascade_path}haarcascade_frontalface_default.xml"
            )
        except Exception as e:
            logger.warning("Failed to load face cascade: %s", e)

    # ── Public API ─────────────────────────────────────────────────────────

    def check(
        self,
        face_img: np.ndarray,
        frames: Optional[List[np.ndarray]] = None,
        methods: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Run liveness detection on a face crop, optionally with motion frames."""
        scores: Dict[str, float] = {}
        details: Dict[str, Any] = {}

        if methods is None:
            methods = ["texture", "deep_learning"]
            if frames and len(frames) > 1:
                methods.append("motion")

        if "texture" in methods:
            try:
                t_score, t_details = self._texture(face_img)
                scores["texture"] = self._normalize_score(t_score)
                details["texture"] = t_details
            except Exception as e:
                logger.error("Texture liveness failed: %s", e)
                scores["texture"] = 0.5

        if "motion" in methods and frames and len(frames) > 1:
            try:
                m_score, m_details = self._motion(frames)
                scores["motion"] = self._normalize_score(m_score)
                details["motion"] = m_details
            except Exception as e:
                logger.error("Motion liveness failed: %s", e)
                scores["motion"] = 0.5

        if "deep_learning" in methods:
            try:
                dl_score, dl_details = self._spectral(face_img)
                scores["deep_learning"] = self._normalize_score(dl_score)
                details["deep_learning"] = dl_details
            except Exception as e:
                logger.error("Spectral liveness failed: %s", e)
                scores["deep_learning"] = 0.5

        if not scores:
            return {
                "is_live": False,
                "score": 0.0,
                "attack_type": "no_detection",
                "details": {"error": "no_methods_available"},
            }

        if self.ensemble_method == "average":
            ensemble_score = sum(scores.values()) / len(scores)
        elif self.ensemble_method == "weighted":
            ensemble_score = (
                scores.get("texture", 0.5) * _ENSEMBLE_W_TEXTURE
                + scores.get("motion", 0.5) * _ENSEMBLE_W_MOTION
                + scores.get("deep_learning", 0.5) * _ENSEMBLE_W_DEEP
            )
        else:
            threshold = self.confidence_threshold
            live_votes = sum(1 for score in scores.values() if score >= threshold)
            ensemble_score = live_votes / len(scores)

        ensemble_score = self._normalize_score(ensemble_score, fallback=0.0)
        is_live = ensemble_score >= self.confidence_threshold

        attack_type = self._detect_attacks(face_img, scores, details) if not is_live else None

        return {
            "is_live": is_live,
            "score": float(ensemble_score),
            "attack_type": attack_type,
            "details": {
                "individual_scores": scores,
                "combined_method": self.ensemble_method,
                **details,
            },
        }

    def _normalize_score(self, score: Any, fallback: float = 0.5) -> float:
        try:
            normalized = float(score)
        except (TypeError, ValueError):
            return fallback
        if not np.isfinite(normalized):
            return fallback
        return max(0.0, min(1.0, normalized))

    # ── Texture (LBP) ─────────────────────────────────────────────────────

    def _texture(self, frame: np.ndarray) -> Tuple[float, Dict[str, Any]]:
        return self._core.texture_score(frame)

    @staticmethod
    def _compute_lbp(gray: np.ndarray) -> np.ndarray:
        height, width = gray.shape
        lbp = np.zeros((height, width), dtype=np.uint8)
        for i in range(1, height - 1):
            for j in range(1, width - 1):
                center = gray[i, j]
                neighbors = [
                    gray[i - 1, j - 1], gray[i - 1, j], gray[i - 1, j + 1],
                    gray[i, j + 1], gray[i + 1, j + 1], gray[i + 1, j],
                    gray[i + 1, j - 1], gray[i, j - 1],
                ]
                lbp_code = 0
                for k, neighbor in enumerate(neighbors):
                    lbp_code |= (1 << k) if neighbor >= center else 0
                lbp[i, j] = lbp_code
        return lbp

    # ── Spectral / Deep-Learning ───────────────────────────────────────────

    def _motion(self, frames: List[np.ndarray], fps: int = 30) -> Tuple[float, Dict[str, Any]]:
        return self._core.motion_score(frames, fps=fps)

    def _spectral(self, frame: np.ndarray) -> Tuple[float, Dict[str, Any]]:
        score, details = self._core.spectral_score(frame)
        details["configured_model"] = self.model_name
        return score, details

    def _to_grayscale_uint8(self, frame: np.ndarray) -> np.ndarray:
        return self._core.to_grayscale_uint8(frame)

    def _detect_blinks(self, gray_frames: List[np.ndarray]) -> int:
        return self._core.detect_blinks(gray_frames)

    def _analyze_frame_quality(self, frame: np.ndarray) -> Dict[str, float]:
        return self._core.analyze_frame_quality(frame)

    def _detect_attacks(
        self,
        frame: np.ndarray,
        scores: Dict[str, float],
        details: Dict[str, Any],
    ) -> Optional[str]:
        texture_details = details.get("texture", {})
        entropy = texture_details.get("entropy_normalized", 0.5)
        if entropy < _ATTACK_PRINT_ENTROPY_MAX:
            return "print_attack"

        motion_details = details.get("motion", {})
        avg_flow = motion_details.get("avg_optical_flow", 0.0)
        if avg_flow < _ATTACK_REPLAY_FLOW_MAX and scores.get("texture", 0.5) > _ATTACK_REPLAY_TEXTURE_MIN:
            return "replay_attack"

        quality = details.get("deep_learning", {}).get("quality_metrics", {})
        blur = quality.get("blur_score", 1.0)
        if blur < _ATTACK_MASK_BLUR_MAX and scores.get("texture", 0.5) > _ATTACK_MASK_TEXTURE_MIN:
            return "mask_attack"

        return "spoof_generic"
