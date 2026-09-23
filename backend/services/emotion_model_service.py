"""Real (trained) facial-emotion recognition service.

Wraps a pretrained FER classifier (`trpakov/vit-face-expression`, a ViT fine-tuned
on facial-expression data) behind a lazy, fail-soft interface. This replaces the
deterministic embedding heuristic with genuine trained-model inference for the
image-upload path of the emotion endpoint.

Design:
- Lazy load: the ~300 MB model is only fetched/loaded on first actual use, not at
  import, so mounting the router stays cheap.
- Gated: set `ENABLE_REAL_EMOTION_MODEL=0` to force the heuristic fallback.
- Fail-soft: any load/inference error disables the service and the caller falls
  back to the heuristic — never a hard failure.
"""

from __future__ import annotations

import logging
import os
import threading
from typing import Dict, List, Optional

import numpy as np

logger = logging.getLogger(__name__)

# FER model label -> system EmotionLabel value (see api/advanced_recognition.py)
_LABEL_MAP = {
    "angry": "angry",
    "anger": "angry",
    "disgust": "disgust",
    "fear": "fear",
    "happy": "happy",
    "happiness": "happy",
    "neutral": "neutral",
    "sad": "sad",
    "sadness": "sad",
    "surprise": "surprised",
    "surprised": "surprised",
}

_MODEL_NAME = os.getenv("EMOTION_MODEL_NAME", "trpakov/vit-face-expression")
METHOD_TAG = f"trained:{_MODEL_NAME}"


class EmotionModelService:
    """Lazy, fail-soft wrapper around a pretrained FER pipeline."""

    def __init__(self) -> None:
        self.enabled = os.getenv("ENABLE_REAL_EMOTION_MODEL", "1") == "1"
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

                logger.info("Loading FER emotion model: %s", _MODEL_NAME)
                self._pipe = pipeline("image-classification", model=_MODEL_NAME)
                logger.info("FER emotion model loaded")
                return True
            except Exception as exc:  # noqa: BLE001 - fail soft to heuristic
                logger.warning("FER emotion model unavailable, will use heuristic: %s", exc)
                self.enabled = False
                self._pipe = None
                return False

    def available(self) -> bool:
        return self._ensure_loaded()

    def detect(self, image_bgr: np.ndarray) -> Optional[Dict]:
        """Run trained FER on a BGR image.

        Returns {"emotion", "confidence", "scores", "method"} or None if the
        model is unavailable / inference fails (caller falls back to heuristic).
        """
        if image_bgr is None or not self._ensure_loaded():
            return None
        try:
            from PIL import Image

            rgb = image_bgr[:, :, ::-1]  # BGR -> RGB
            pil = Image.fromarray(np.ascontiguousarray(rgb))
            raw: List[Dict] = self._pipe(pil)  # [{label, score}, ...]

            scores: Dict[str, float] = {}
            for item in raw:
                mapped = _LABEL_MAP.get(str(item["label"]).lower())
                if mapped is None:
                    continue
                scores[mapped] = scores.get(mapped, 0.0) + float(item["score"])

            if not scores:
                return None

            top = max(scores.items(), key=lambda kv: kv[1])
            return {
                "emotion": top[0],
                "confidence": round(float(top[1]), 4),
                "scores": {k: round(v, 4) for k, v in scores.items()},
                "method": METHOD_TAG,
            }
        except Exception as exc:  # noqa: BLE001 - fail soft to heuristic
            logger.warning("FER inference failed, falling back to heuristic: %s", exc)
            return None


_service: Optional[EmotionModelService] = None
_service_lock = threading.Lock()


def get_emotion_model_service() -> EmotionModelService:
    global _service
    if _service is None:
        with _service_lock:
            if _service is None:
                _service = EmotionModelService()
    return _service
