"""
Compatibility shim for the MediaPipe legacy Solutions API.

MediaPipe wheels for Python 3.13+ (0.10.30+) ship only the Tasks API and no
longer expose ``mediapipe.solutions``. This module rebuilds the two legacy
entry points the codebase uses (``solutions.face_mesh.FaceMesh`` and
``solutions.pose.Pose``) on top of ``mediapipe.tasks.python.vision`` so call
sites keep working unchanged.

Usage: after ``import mediapipe``, call ``ensure_legacy_solutions()`` once.
It is a no-op when the wheel still provides the legacy API.

Model bundles are stored in ``models/mediapipe/`` at the project root and
downloaded on first use if missing.
"""

from __future__ import annotations

import logging
import threading
import urllib.request
from pathlib import Path
from typing import Any, List, Optional

import numpy as np

logger = logging.getLogger(__name__)

try:
    import mediapipe as mp
    from mediapipe.tasks import python as _tasks_python
    from mediapipe.tasks.python import vision as _vision

    _TASKS_AVAILABLE = True
except Exception:  # pragma: no cover - mediapipe absent entirely
    mp = None
    _tasks_python = None
    _vision = None
    _TASKS_AVAILABLE = False

_MODEL_DIR = Path(__file__).resolve().parents[1] / "models" / "mediapipe"
_MODEL_URLS = {
    "face_landmarker.task": (
        "https://storage.googleapis.com/mediapipe-models/face_landmarker/"
        "face_landmarker/float16/1/face_landmarker.task"
    ),
    "pose_landmarker_full.task": (
        "https://storage.googleapis.com/mediapipe-models/pose_landmarker/"
        "pose_landmarker_full/float16/1/pose_landmarker_full.task"
    ),
}
_DOWNLOAD_LOCK = threading.Lock()


def _model_path(name: str) -> str:
    path = _MODEL_DIR / name
    if not path.exists():
        with _DOWNLOAD_LOCK:
            if not path.exists():
                _MODEL_DIR.mkdir(parents=True, exist_ok=True)
                url = _MODEL_URLS[name]
                logger.info("Downloading MediaPipe model %s from %s", name, url)
                tmp = path.with_suffix(".tmp")
                urllib.request.urlretrieve(url, tmp)
                tmp.replace(path)
    return str(path)


class _Landmark:
    __slots__ = ("x", "y", "z", "visibility")

    def __init__(self, x: float, y: float, z: float, visibility: float = 0.0):
        self.x = x
        self.y = y
        self.z = z
        self.visibility = visibility


class _LandmarkList:
    """Mimics the legacy NormalizedLandmarkList: iterable ``.landmark`` plus indexing."""

    def __init__(self, landmarks: List[_Landmark]):
        self.landmark = landmarks

    def __getitem__(self, idx: int) -> _Landmark:
        return self.landmark[idx]

    def __len__(self) -> int:
        return len(self.landmark)

    def __bool__(self) -> bool:
        return bool(self.landmark)


class _FaceMeshResult:
    __slots__ = ("multi_face_landmarks",)

    def __init__(self, multi_face_landmarks: Optional[List[_LandmarkList]]):
        self.multi_face_landmarks = multi_face_landmarks


class _PoseResult:
    __slots__ = ("pose_landmarks",)

    def __init__(self, pose_landmarks: Optional[_LandmarkList]):
        self.pose_landmarks = pose_landmarks


def _to_mp_image(rgb_frame: np.ndarray) -> "mp.Image":
    frame = np.ascontiguousarray(rgb_frame)
    if frame.dtype != np.uint8:
        frame = frame.astype(np.uint8)
    return mp.Image(image_format=mp.ImageFormat.SRGB, data=frame)


class FaceMesh:
    """Drop-in replacement for ``mp.solutions.face_mesh.FaceMesh`` (IMAGE mode)."""

    def __init__(
        self,
        static_image_mode: bool = False,
        max_num_faces: int = 1,
        refine_landmarks: bool = True,
        min_detection_confidence: float = 0.5,
        min_tracking_confidence: float = 0.5,
    ):
        options = _vision.FaceLandmarkerOptions(
            base_options=_tasks_python.BaseOptions(
                model_asset_path=_model_path("face_landmarker.task")
            ),
            running_mode=_vision.RunningMode.IMAGE,
            num_faces=max_num_faces,
            min_face_detection_confidence=min_detection_confidence,
            min_tracking_confidence=min_tracking_confidence,
        )
        self._landmarker = _vision.FaceLandmarker.create_from_options(options)
        self._lock = threading.Lock()

    def process(self, rgb_frame: np.ndarray) -> _FaceMeshResult:
        image = _to_mp_image(rgb_frame)
        with self._lock:
            result = self._landmarker.detect(image)
        if not result.face_landmarks:
            return _FaceMeshResult(None)
        faces = [
            _LandmarkList([_Landmark(lm.x, lm.y, lm.z) for lm in face])
            for face in result.face_landmarks
        ]
        return _FaceMeshResult(faces)

    def close(self) -> None:
        self._landmarker.close()


class Pose:
    """Drop-in replacement for ``mp.solutions.pose.Pose`` (IMAGE mode)."""

    def __init__(
        self,
        static_image_mode: bool = False,
        model_complexity: int = 1,
        smooth_landmarks: bool = True,
        min_detection_confidence: float = 0.5,
        min_tracking_confidence: float = 0.5,
    ):
        options = _vision.PoseLandmarkerOptions(
            base_options=_tasks_python.BaseOptions(
                model_asset_path=_model_path("pose_landmarker_full.task")
            ),
            running_mode=_vision.RunningMode.IMAGE,
            num_poses=1,
            min_pose_detection_confidence=min_detection_confidence,
            min_tracking_confidence=min_tracking_confidence,
        )
        self._landmarker = _vision.PoseLandmarker.create_from_options(options)
        self._lock = threading.Lock()

    def process(self, rgb_frame: np.ndarray) -> _PoseResult:
        image = _to_mp_image(rgb_frame)
        with self._lock:
            result = self._landmarker.detect(image)
        if not result.pose_landmarks:
            return _PoseResult(None)
        first = result.pose_landmarks[0]
        landmarks = [
            _Landmark(lm.x, lm.y, lm.z, getattr(lm, "visibility", 0.0) or 0.0)
            for lm in first
        ]
        return _PoseResult(_LandmarkList(landmarks))

    def close(self) -> None:
        self._landmarker.close()


class _FaceMeshModule:
    FaceMesh = FaceMesh


class _PoseModule:
    Pose = Pose


class _SolutionsShim:
    face_mesh = _FaceMeshModule
    pose = _PoseModule


def ensure_legacy_solutions() -> bool:
    """Attach a ``solutions`` namespace to the mediapipe module if missing.

    Returns True when ``mediapipe.solutions`` is usable (native or shimmed).
    """
    if mp is None:
        return False
    if hasattr(mp, "solutions"):
        return True
    if not _TASKS_AVAILABLE:
        return False
    mp.solutions = _SolutionsShim()
    logger.info("MediaPipe legacy Solutions API shimmed via Tasks API (mediapipe_compat)")
    return True
