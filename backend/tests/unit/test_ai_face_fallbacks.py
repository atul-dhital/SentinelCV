"""Regression tests for face detection fallbacks used by live camera flows."""

from pathlib import Path
import sys

import numpy as np


def _find_repo_root(start: Path) -> Path:
    for parent in [start] + list(start.parents):
        if (parent / "ai_services").exists():
            return parent
    return start.parents[0]


ROOT = _find_repo_root(Path(__file__).resolve())
AI_SERVICES_DIR = ROOT / "ai_services"
if str(AI_SERVICES_DIR) not in sys.path:
    sys.path.insert(0, str(AI_SERVICES_DIR))

import face_engine  # noqa: E402
from api import liveness as liveness_api  # noqa: E402


class _FakeCascade:
    def __init__(self, detections):
        self._detections = detections

    def empty(self):
        return False

    def detectMultiScale(self, *args, **kwargs):
        return self._detections


def test_face_engine_fallback_returns_no_face_for_blank_frame(monkeypatch):
    monkeypatch.setattr(face_engine, "_DEEPFACE_AVAILABLE", False)
    engine = face_engine.FaceEngine()
    engine._fallback_face_cascade = _FakeCascade([])

    blank = np.zeros((120, 160, 3), dtype=np.uint8)

    assert engine.extract_face(blank) == []


def test_face_engine_fallback_returns_detected_crop(monkeypatch):
    monkeypatch.setattr(face_engine, "_DEEPFACE_AVAILABLE", False)
    engine = face_engine.FaceEngine()
    engine._fallback_face_cascade = _FakeCascade([(10, 20, 40, 50)])

    frame = np.full((120, 160, 3), 180, dtype=np.uint8)
    faces = engine.extract_face(frame)

    assert len(faces) == 1
    assert faces[0]["facial_area"] == {"x": 10, "y": 20, "w": 40, "h": 50}
    assert faces[0]["face"].shape[:2] == (50, 40)


def test_extract_face_frame_ignores_suspicious_full_frame_detection(monkeypatch):
    frame = np.full((120, 160, 3), 100, dtype=np.uint8)

    class _FakeResponse:
        status_code = 200

        def json(self):
            return {
                "faces": [
                    {
                        "bbox": {"x1": 0, "y1": 0, "x2": 160, "y2": 120},
                        "confidence": 0.0,
                    }
                ]
            }

    class _FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def post(self, url, json):
            return _FakeResponse()

    monkeypatch.setattr(liveness_api.httpx, "Client", _FakeClient)

    assert liveness_api._extract_face_frame(frame) is None
