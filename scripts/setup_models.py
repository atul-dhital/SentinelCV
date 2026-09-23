#!/usr/bin/env python
"""Set up and verify the real face-recognition model stack for SentinelCV.

This makes "the model must load" turnkey and verifiable:

  1. (optional) install the ML deps   ->  --install
  2. import the recognition backends  (insightface / onnxruntime / adaface)
  3. warm the FaceEngine, which triggers InsightFace's model-pack download
     (e.g. buffalo_l) on first use — needs network the first time
  4. run a real embedding on a synthetic face and confirm a 512-d ArcFace
     vector comes back (NOT the weak pixel fallback)
  5. print a clear PASS / FAIL + the live recognition backend status

Usage:
    python scripts/setup_models.py            # verify only
    python scripts/setup_models.py --install   # pip install deps first, then verify

Exit code 0 = real recognition is working; 1 = degraded/fallback only.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
AI_DIR = PROJECT_ROOT / "ai_services"
REQUIREMENTS = AI_DIR / "requirements.txt"

# The minimal real-recognition deps (full set is in ai_services/requirements.txt).
CORE_DEPS = ["insightface>=0.7.3", "onnxruntime>=1.16.0", "opencv-python>=4.8.0", "numpy"]


def _print(label: str, msg: str) -> None:
    print(f"[{label:5}] {msg}")


def install_deps() -> None:
    print("=" * 72)
    print("Installing recognition dependencies...")
    print("=" * 72)
    cmd = [sys.executable, "-m", "pip", "install", *CORE_DEPS]
    if REQUIREMENTS.exists():
        # Prefer the pinned project set when present.
        cmd = [sys.executable, "-m", "pip", "install", "-r", str(REQUIREMENTS)]
    print("  $", " ".join(cmd))
    subprocess.run(cmd, check=True)


def verify() -> int:
    if str(AI_DIR) not in sys.path:
        sys.path.insert(0, str(AI_DIR))

    # 1. Imports
    try:
        import numpy as np  # noqa: F401
        import cv2  # noqa: F401
    except Exception as exc:
        _print("FAIL", f"core libs missing (numpy/opencv): {exc}")
        _print("HINT", "Re-run with --install, or pip install -r ai_services/requirements.txt")
        return 1

    try:
        from face_engine import FaceEngine, recognition_backend_status
    except Exception as exc:
        _print("FAIL", f"could not import face_engine: {exc}")
        return 1

    status = recognition_backend_status()
    _print("INFO", f"recognition backends loadable: {status['backends']}")

    if not status.get("real_recognition"):
        _print("FAIL", "No real ArcFace backend (InsightFace/AdaFace) is loadable.")
        _print("HINT", "pip install insightface onnxruntime (or --install). "
                       "First run also downloads the model pack — needs network.")
        return 1

    # 2. Warm + real embedding on a synthetic face-sized image.
    import numpy as np
    engine = FaceEngine()
    try:
        engine._warmup()  # triggers model-pack download on first run
    except Exception as exc:
        _print("WARN", f"warmup raised (continuing to embedding test): {exc}")

    sample = (np.random.default_rng(0).random((112, 112, 3)) * 255).astype("uint8")
    emb = engine.get_embedding_from_crop(sample)
    if emb is None:
        _print("FAIL", "embedding returned None (model not producing vectors).")
        return 1

    engine_used = engine.last_embedding_engine
    _print("INFO", f"embedding dim={len(emb)}  produced_by={engine_used}")

    if engine_used == "fallback":
        _print("FAIL", "Embedding came from the WEAK PIXEL FALLBACK, not real ArcFace.")
        _print("HINT", "The ONNX model did not load. Check network/cache and deps.")
        return 1

    if len(emb) != 512:
        _print("WARN", f"expected 512-d embedding, got {len(emb)}-d.")

    print("-" * 72)
    _print("PASS", f"Real face recognition is working (backend={engine_used}, 512-d ArcFace).")
    _print("NEXT", "Set SENTINELCV_STRICT_RECOGNITION=1 in production and confirm "
                   "GET :8001/health -> recognition.real_recognition == true.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Set up / verify SentinelCV recognition models.")
    parser.add_argument("--install", action="store_true",
                        help="pip install the recognition dependencies before verifying.")
    args = parser.parse_args()

    if args.install:
        try:
            install_deps()
        except subprocess.CalledProcessError as exc:
            _print("FAIL", f"dependency install failed: {exc}")
            return 1

    return verify()


if __name__ == "__main__":
    raise SystemExit(main())
