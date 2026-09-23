"""Real monocular depth estimation service.

Wraps a pretrained DPT/MiDaS depth model (`Intel/dpt-swinv2-tiny-256`) behind a
lazy, fail-soft interface. This lets the 3D-face pipeline derive a *real*
estimated depth map from an ordinary RGB image when no depth-sensor capture
(.npy) is available — replacing the previous seeded-synthetic depth.

Design mirrors emotion_model_service: lazy load, env-gated
(`ENABLE_REAL_DEPTH_MODEL=0` forces fallback), fail-soft to None.
"""

from __future__ import annotations

import logging
import os
import threading
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)

_MODEL_NAME = os.getenv("DEPTH_MODEL_NAME", "Intel/dpt-swinv2-tiny-256")
_IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".bmp", ".webp")


class DepthEstimationService:
    """Lazy, fail-soft wrapper around a pretrained monocular-depth pipeline."""

    def __init__(self) -> None:
        self.enabled = os.getenv("ENABLE_REAL_DEPTH_MODEL", "1") == "1"
        self._pipe = None
        self._load_attempted = False
        self._lock = threading.Lock()

    def _ensure_loaded(self) -> bool:
        if self._pipe is not None:
            return True
        if not self.enabled or self._load_attempted:
            return self._pipe is not None
        with self._lock:
            if self._pipe is not None:
                return True
            if self._load_attempted:
                return False
            self._load_attempted = True
            try:
                from transformers import pipeline  # heavy import, kept local

                logger.info("Loading monocular depth model: %s", _MODEL_NAME)
                self._pipe = pipeline("depth-estimation", model=_MODEL_NAME)
                logger.info("Depth model loaded")
                return True
            except Exception as exc:  # noqa: BLE001 - fail soft
                logger.warning("Depth model unavailable, will use synthetic: %s", exc)
                self.enabled = False
                self._pipe = None
                return False

    def available(self) -> bool:
        return self._ensure_loaded()

    @staticmethod
    def is_image_path(path: str) -> bool:
        return bool(path) and path.lower().endswith(_IMAGE_EXTS)

    def estimate_from_path(self, image_path: str) -> Optional[np.ndarray]:
        """Return a normalized [0,1] float64 depth map for an RGB image, or None."""
        if not self.is_image_path(image_path) or not os.path.exists(image_path):
            return None
        if not self._ensure_loaded():
            return None
        try:
            from PIL import Image

            with Image.open(image_path) as im:
                rgb = im.convert("RGB")
                out = self._pipe(rgb)
            depth = np.asarray(out["depth"], dtype=np.float64)
            dmin, dmax = float(depth.min()), float(depth.max())
            if dmax > dmin:
                depth = (depth - dmin) / (dmax - dmin)
            return depth
        except Exception as exc:  # noqa: BLE001 - fail soft
            logger.warning("Depth estimation failed, falling back to synthetic: %s", exc)
            return None


_service: Optional[DepthEstimationService] = None
_service_lock = threading.Lock()


def get_depth_estimation_service() -> DepthEstimationService:
    global _service
    if _service is None:
        with _service_lock:
            if _service is None:
                _service = DepthEstimationService()
    return _service
