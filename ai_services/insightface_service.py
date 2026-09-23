"""InsightFace ArcFace backend (ONNX / onnxruntime).

Primary face-embedding backend. Unlike DeepFace (TensorFlow), InsightFace runs
on onnxruntime, so it works on current Python runtimes (3.13/3.14) where no
TensorFlow wheel exists. Produces real 512-d L2-normalized ArcFace embeddings,
the same contract the rest of the pipeline already assumes.

Model pack (`buffalo_l`, ~280 MB) is auto-downloaded by InsightFace on first use
into ~/.insightface/models. Override the pack with INSIGHTFACE_MODEL_PACK and the
execution provider with INSIGHTFACE_PROVIDERS (comma-separated) if needed.
"""
from __future__ import annotations

import logging
import os
import threading
from typing import Any, Dict, List, Optional

import cv2
import numpy as np

from onnx_providers import runtime_providers

logger = logging.getLogger("ai_services.insightface")

try:  # heavy import guarded so a missing dep never breaks the engine
    from insightface.app import FaceAnalysis

    _INSIGHTFACE_IMPORTABLE = True
except Exception:  # pragma: no cover - import-time environment guard
    FaceAnalysis = None  # type: ignore[assignment]
    _INSIGHTFACE_IMPORTABLE = False


class InsightFaceService:
    """Lazy, thread-safe singleton wrapper around an InsightFace FaceAnalysis app."""

    def __init__(self) -> None:
        self._app = None
        self._lock = threading.Lock()
        self._load_failed = False
        self._pack = os.getenv("INSIGHTFACE_MODEL_PACK", "buffalo_l")
        providers_env = os.getenv("INSIGHTFACE_PROVIDERS", "").strip()
        if providers_env:
            self._providers = [p.strip() for p in providers_env.split(",") if p.strip()]
        else:
            # Auto-detect: use CUDA when an onnxruntime-gpu build is installed
            # (else CPU). GPU drops a full-frame ArcFace call from ~1s to ~30-50ms.
            # Install: pip install onnxruntime-gpu  (and remove onnxruntime).
            self._providers = ["CPUExecutionProvider"]
            try:
                import onnxruntime as _ort

                self._providers = runtime_providers(_ort, logger)
            except Exception:
                pass
        # Only load the models embedding/detection actually need. The full buffalo_l
        # pack also runs 3D landmarks, 2D landmarks, and gender/age on EVERY app.get(),
        # which adds ~4-5s/call on CPU for no benefit here (det_10g still supplies the
        # 5 keypoints we use). Restricting modules cuts a full-frame call ~5.4s -> ~1s.
        modules_env = os.getenv("INSIGHTFACE_MODULES", "detection,recognition").strip()
        self._allowed_modules = [m.strip() for m in modules_env.split(",") if m.strip()] or None
        try:
            self._det_size = int(os.getenv("INSIGHTFACE_DET_SIZE", "640"))
        except ValueError:
            self._det_size = 640

    @property
    def available(self) -> bool:
        """True if the backend can be used (importable and not previously failed)."""
        return _INSIGHTFACE_IMPORTABLE and not self._load_failed

    def _get_app(self):
        if self._app is not None:
            return self._app
        if not self.available:
            return None
        with self._lock:
            if self._app is not None:
                return self._app
            try:
                app = FaceAnalysis(
                    name=self._pack,
                    providers=self._providers,
                    allowed_modules=self._allowed_modules,
                )
                # ctx_id selects the onnxruntime execution device for insightface's
                # internal sessions: 0 = first GPU, -1 = CPU. This is independent of
                # the `providers` list above (that only controls which providers
                # onnxruntime is *allowed* to use) -- ctx_id=-1 forces CPU even when
                # CUDAExecutionProvider is available, silently discarding the GPU
                # detection above. A full-frame ArcFace call drops from ~1s (CPU) to
                # ~30-50ms (GPU) once this actually engages CUDA.
                ctx_id = 0 if "CUDAExecutionProvider" in self._providers else -1
                app.prepare(ctx_id=ctx_id, det_size=(self._det_size, self._det_size))
                self._app = app
                logger.info(
                    "InsightFace ready (pack=%s, providers=%s, ctx_id=%s)",
                    self._pack,
                    self._providers,
                    ctx_id,
                )
            except Exception as e:  # download/build/runtime failure -> stay unavailable
                self._load_failed = True
                logger.warning("InsightFace failed to initialize, disabling: %s", e)
                return None
        return self._app

    def extract_embedding(self, img_bgr) -> Optional[List[float]]:
        """Return a 512-d L2-normalized ArcFace embedding, or None on failure.

        Accepts a file path or a BGR ndarray. Runs detection first; if no face is
        detected (e.g. the input is an already-tight crop), it falls back to
        embedding the resized 112x112 image directly through the recognition model.
        """
        app = self._get_app()
        if app is None:
            return None
        try:
            if isinstance(img_bgr, str):
                img_bgr = cv2.imread(img_bgr)
            if img_bgr is None or getattr(img_bgr, "size", 0) == 0:
                return None

            faces = app.get(img_bgr)
            if faces:
                largest = max(
                    faces,
                    key=lambda f: (f.bbox[2] - f.bbox[0]) * (f.bbox[3] - f.bbox[1]),
                )
                emb = np.asarray(largest.normed_embedding, dtype=np.float32)
                return emb.tolist()

            # No detection: treat input as a pre-aligned crop.
            rec = app.models.get("recognition")
            if rec is None:
                return None
            crop = cv2.resize(img_bgr, (112, 112))
            feat = np.asarray(rec.get_feat(crop), dtype=np.float32).flatten()
            norm = float(np.linalg.norm(feat))
            if norm < 1e-8:
                return None
            return (feat / norm).tolist()
        except Exception as e:
            logger.warning("InsightFace embedding error: %s", e)
            return None

    def detect_faces(self, img_bgr) -> List[Dict[str, Any]]:
        """Detect faces with RetinaFace (the detector already loaded for recognition).

        Returns dicts shaped like DeepFace.extract_faces so callers can use it
        interchangeably: {"face", "facial_area": {x,y,w,h,landmarks}, "confidence"}.
        `confidence` is the real RetinaFace det_score — not a hardcoded placeholder —
        and `landmarks` (5 kps) enable downstream face alignment. Largest face first.
        """
        app = self._get_app()
        if app is None:
            return []
        try:
            if isinstance(img_bgr, str):
                img_bgr = cv2.imread(img_bgr)
            if img_bgr is None or getattr(img_bgr, "size", 0) == 0:
                return []
            h, w = img_bgr.shape[:2]
            out: List[Dict[str, Any]] = []
            for f in app.get(img_bgr):
                x1, y1, x2, y2 = (int(v) for v in f.bbox)
                x1, y1 = max(0, x1), max(0, y1)
                x2, y2 = min(w, x2), min(h, y2)
                if x2 <= x1 or y2 <= y1:
                    continue
                crop = img_bgr[y1:y2, x1:x2]
                if crop.size == 0:
                    continue
                landmarks = f.kps.tolist() if getattr(f, "kps", None) is not None else []
                out.append({
                    "face": crop,
                    "facial_area": {
                        "x": x1, "y": y1, "w": x2 - x1, "h": y2 - y1,
                        "landmarks": landmarks,
                    },
                    "confidence": float(getattr(f, "det_score", 0.0)),
                })
            out.sort(key=lambda d: d["facial_area"]["w"] * d["facial_area"]["h"], reverse=True)
            return out
        except Exception as e:
            logger.warning("InsightFace detect error: %s", e)
            return []


# Module-level singleton, mirroring adaface_service's usage pattern.
insightface_service = InsightFaceService()
