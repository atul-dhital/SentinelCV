#!/usr/bin/env python3
"""
Download ML model weights for production deployment.

Downloads and verifies required model files:
- AdaFace ONNX model (face recognition)
- YOLO models (person/face detection) — usually auto-downloaded by ultralytics
- Liveness ONNX model (anti-spoofing) — optional

Usage:
    python scripts/download_models.py [--all] [--adaface] [--liveness] [--check]
"""

import argparse
import hashlib
import logging
import os
import sys
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

# Model registry: name -> (url, destination, sha256_prefix)
# NOTE: Replace placeholder URLs with actual model hosting URLs
MODEL_REGISTRY = {
    "adaface": {
        "description": "AdaFace IR-101 face recognition (ONNX, ~250MB)",
        "dest": "models/adaface.onnx",
        "url": os.getenv(
            "ADAFACE_MODEL_URL",
            "https://github.com/mk-minchul/AdaFace/releases/download/pretrained/adaface_ir101_webface12m.onnx",
        ),
        "sha256_prefix": None,  # Set after first download for verification
    },
    "liveness": {
        "description": "Liveness anti-spoofing CNN (ONNX, ~15MB)",
        "dest": "models/liveness_net.onnx",
        "url": os.getenv("LIVENESS_MODEL_URL", ""),
        "sha256_prefix": None,
    },
}

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def file_sha256(path: Path) -> str:
    """Compute SHA-256 hex digest of a file."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def download_file(url: str, dest: Path) -> bool:
    """Download a file with progress indication."""
    if not url:
        logger.warning("No URL configured for %s — skipping", dest.name)
        return False

    dest.parent.mkdir(parents=True, exist_ok=True)

    try:
        import requests
    except ImportError:
        logger.error("'requests' package required. Install with: pip install requests")
        return False

    logger.info("Downloading %s ...", url.split("/")[-1])
    logger.info("  -> %s", dest)

    try:
        resp = requests.get(url, stream=True, timeout=300)
        resp.raise_for_status()

        total = int(resp.headers.get("content-length", 0))
        downloaded = 0

        with open(dest, "wb") as f:
            for chunk in resp.iter_content(chunk_size=1 << 20):
                f.write(chunk)
                downloaded += len(chunk)
                if total > 0:
                    pct = downloaded * 100 // total
                    mb = downloaded / (1 << 20)
                    print(f"\r  Progress: {pct}% ({mb:.1f} MB)", end="", flush=True)

        print()  # newline after progress
        logger.info("Download complete: %s (%.1f MB)", dest.name, dest.stat().st_size / (1 << 20))
        return True

    except Exception as e:
        logger.error("Download failed: %s", e)
        if dest.exists():
            dest.unlink()
        return False


def check_model(name: str, info: dict) -> bool:
    """Check if a model file exists and is valid."""
    dest = PROJECT_ROOT / info["dest"]
    if not dest.exists():
        logger.warning("[MISSING] %s: %s", name, info["description"])
        logger.warning("  Expected at: %s", dest)
        return False

    size_mb = dest.stat().st_size / (1 << 20)
    sha_prefix = file_sha256(dest)[:12]

    expected = info.get("sha256_prefix")
    if expected and not sha_prefix.startswith(expected):
        logger.warning("[CORRUPTED] %s: hash mismatch (got %s...)", name, sha_prefix)
        return False

    logger.info("[OK] %s: %.1f MB (sha256: %s...)", name, size_mb, sha_prefix)
    return True


def main():
    parser = argparse.ArgumentParser(description="Download ML model weights")
    parser.add_argument("--all", action="store_true", help="Download all models")
    parser.add_argument("--adaface", action="store_true", help="Download AdaFace model")
    parser.add_argument("--liveness", action="store_true", help="Download liveness model")
    parser.add_argument("--check", action="store_true", help="Check model status only")
    args = parser.parse_args()

    os.chdir(PROJECT_ROOT)

    if args.check or not any([args.all, args.adaface, args.liveness]):
        logger.info("=== Model Status Check ===")
        all_ok = True
        for name, info in MODEL_REGISTRY.items():
            if not check_model(name, info):
                all_ok = False

        # Also check YOLO models
        yolo_paths = ["models/yolov8n.pt", "models/yolo11n.pt"]
        for yp in yolo_paths:
            p = PROJECT_ROOT / yp
            if p.exists():
                logger.info("[OK] %s: %.1f MB", p.name, p.stat().st_size / (1 << 20))
            else:
                logger.warning("[MISSING] %s (auto-downloads on first use via ultralytics)", p.name)

        if all_ok:
            logger.info("\nAll required models are present.")
        else:
            logger.info("\nSome models are missing. Run with --all to download them.")
            logger.info("  python scripts/download_models.py --all")

        return 0 if all_ok else 1

    targets = []
    if args.all or args.adaface:
        targets.append("adaface")
    if args.all or args.liveness:
        targets.append("liveness")

    success = True
    for name in targets:
        info = MODEL_REGISTRY[name]
        dest = PROJECT_ROOT / info["dest"]

        if dest.exists():
            logger.info("[SKIP] %s already exists (%.1f MB)", name, dest.stat().st_size / (1 << 20))
            continue

        if not download_file(info["url"], dest):
            success = False

    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
