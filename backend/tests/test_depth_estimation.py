"""Tests for the real monocular depth service and its use in 3D depth loading.

The DPT model auto-downloads on first use (fast once cached). Fail-soft and
path-type behaviour are tested without any download.
"""

import os
import tempfile

import cv2
import numpy as np
import pytest

from services.depth_estimation_service import (
    DepthEstimationService,
    get_depth_estimation_service,
)


def _write_png(path: str, size: int = 64) -> None:
    img = np.random.randint(0, 255, (size, size, 3), dtype=np.uint8)
    assert cv2.imwrite(path, img)


def test_is_image_path():
    svc = DepthEstimationService()
    assert svc.is_image_path("a/b/face.png")
    assert svc.is_image_path("FACE.JPG")
    assert not svc.is_image_path("capture.npy")
    assert not svc.is_image_path("")


def test_disabled_returns_none_without_download(monkeypatch):
    monkeypatch.setenv("ENABLE_REAL_DEPTH_MODEL", "0")
    svc = DepthEstimationService()
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "face.png")
        _write_png(p)
        assert svc.available() is False
        assert svc.estimate_from_path(p) is None


def test_npy_path_skips_model(monkeypatch):
    # Non-image extension must return None fast without loading the model.
    svc = DepthEstimationService()
    assert svc.estimate_from_path("some/capture.npy") is None


def test_singleton_identity():
    assert get_depth_estimation_service() is get_depth_estimation_service()


def test_real_depth_from_image():
    svc = DepthEstimationService()
    if not svc.available():
        pytest.skip("Depth model not available in this environment")
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "face.png")
        _write_png(p, size=128)
        depth = svc.estimate_from_path(p)
    assert depth is not None
    assert depth.ndim == 2
    assert 0.0 <= float(depth.min()) and float(depth.max()) <= 1.0
