"""Facial emotion backend (ONNX / onnxruntime) via HSEmotion.

Real 8-class facial-expression recognition that runs on onnxruntime, so it works
on Python 3.13/3.14 where DeepFace/TensorFlow has no wheels. Output is mapped to
the pipeline's 7 emotion labels (neutral, happy, sad, angry, fearful, disgusted,
surprised); HSEmotion's extra "contempt" class is folded into "disgusted".

Model (~15 MB) is auto-downloaded by HSEmotion on first use. Override the variant
with HSEMOTION_MODEL_NAME if needed.
"""
from __future__ import annotations

import logging
import os
import threading
from typing import Dict, List, Optional

import cv2
import numpy as np

# HSEmotion (<=0.3.1) does `import urllib` but calls `urllib.request.urlretrieve`
# without importing the submodule. On a fresh Python 3.14 process that submodule
# is not yet registered, so its model download crashes. Importing it here
# registers `urllib.request` on the package for the whole process.
import urllib.request  # noqa: F401  (intentional side-effect import)

logger = logging.getLogger("ai_services.emotion")

try:
    from hsemotion_onnx.facial_emotions import HSEmotionRecognizer

    _HSEMOTION_IMPORTABLE = True
except Exception:  # pragma: no cover - import-time environment guard
    HSEmotionRecognizer = None  # type: ignore[assignment]
    _HSEMOTION_IMPORTABLE = False

# HSEmotion class index -> pipeline label. "Contempt" folds into "disgusted".
_HSEMOTION_TO_LABEL = {
    "anger": "angry",
    "contempt": "disgusted",
    "disgust": "disgusted",
    "fear": "fearful",
    "happiness": "happy",
    "neutral": "neutral",
    "sadness": "sad",
    "surprise": "surprised",
}

_LABELS = ["neutral", "happy", "sad", "angry", "fearful", "disgusted", "surprised"]


class EmotionService:
    """Lazy, thread-safe singleton wrapper around an HSEmotion ONNX recognizer."""

    def __init__(self) -> None:
        self._model = None
        self._lock = threading.Lock()
        self._load_failed = False
        self._model_name = os.getenv("HSEMOTION_MODEL_NAME", "enet_b0_8_best_afew")

    @property
    def available(self) -> bool:
        return _HSEMOTION_IMPORTABLE and not self._load_failed

    def _get_model(self):
        if self._model is not None:
            return self._model
        if not self.available:
            return None
        with self._lock:
            if self._model is not None:
                return self._model
            try:
                self._model = HSEmotionRecognizer(model_name=self._model_name)
                logger.info("HSEmotion ready (model=%s)", self._model_name)
            except Exception as e:
                self._load_failed = True
                logger.warning("HSEmotion failed to initialize, disabling: %s", e)
                return None
        return self._model

    def predict(self, img_bgr) -> Optional[Dict[str, float]]:
        """Return a 7-label probability dict, or None on failure.

        Accepts a file path or a BGR ndarray (a face crop or a full frame).
        """
        model = self._get_model()
        if model is None:
            return None
        try:
            if isinstance(img_bgr, str):
                img_bgr = cv2.imread(img_bgr)
            if img_bgr is None or getattr(img_bgr, "size", 0) == 0:
                return None
            # HSEmotion expects an RGB face image.
            img_rgb = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB)
            _label, scores = model.predict_emotions(img_rgb, logits=False)

            idx_to_class = model.idx_to_class  # {0: 'Anger', ...}
            agg: Dict[str, float] = {label: 0.0 for label in _LABELS}
            for idx, prob in enumerate(np.asarray(scores, dtype=np.float64).flatten()):
                src = str(idx_to_class[idx]).lower()
                dst = _HSEMOTION_TO_LABEL.get(src)
                if dst is not None:
                    agg[dst] += float(prob)

            total = sum(agg.values())
            if total <= 0:
                return None
            return {label: round(agg[label] / total, 4) for label in _LABELS}
        except Exception as e:
            logger.warning("HSEmotion prediction error: %s", e)
            return None


# Module-level singleton, mirroring insightface_service / adaface_service.
emotion_service = EmotionService()
