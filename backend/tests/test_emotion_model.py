"""Tests for the real (trained) FER emotion service.

The model auto-downloads on first use; these tests run real inference and are
fast once cached. Fail-soft behaviour (disabled -> None) is tested without any
download.
"""

import numpy as np
import pytest

from services.emotion_model_service import (
    EmotionModelService,
    get_emotion_model_service,
    _LABEL_MAP,
)

VALID_EMOTIONS = {"happy", "sad", "angry", "surprised", "neutral", "fear", "disgust"}


def test_disabled_service_returns_none_without_download(monkeypatch):
    monkeypatch.setenv("ENABLE_REAL_EMOTION_MODEL", "0")
    svc = EmotionModelService()
    assert svc.available() is False
    img = np.random.randint(0, 255, (64, 64, 3), dtype=np.uint8)
    assert svc.detect(img) is None


def test_label_map_targets_are_valid_emotion_labels():
    assert set(_LABEL_MAP.values()).issubset(VALID_EMOTIONS)


def test_singleton_identity():
    assert get_emotion_model_service() is get_emotion_model_service()


def test_real_inference_returns_mapped_emotion():
    svc = EmotionModelService()
    if not svc.available():
        pytest.skip("FER model not available in this environment")
    img = np.random.randint(0, 255, (224, 224, 3), dtype=np.uint8)
    result = svc.detect(img)
    assert result is not None
    assert result["emotion"] in VALID_EMOTIONS
    assert 0.0 <= result["confidence"] <= 1.0
    assert result["method"].startswith("trained:")
    assert set(result["scores"]).issubset(VALID_EMOTIONS)
