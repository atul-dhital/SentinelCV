"""Smoke-test a SentinelCV secondary person detector adapter endpoint."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import tempfile
from typing import Any

import cv2
import numpy as np
import requests


def _synthetic_person_image(path: Path) -> None:
    frame = np.zeros((480, 640, 3), dtype=np.uint8)
    cv2.rectangle(frame, (270, 120), (370, 430), (225, 225, 225), -1)
    cv2.circle(frame, (320, 85), 38, (190, 190, 190), -1)
    cv2.imwrite(str(path), frame)


def run(args: argparse.Namespace) -> dict[str, Any]:
    image_path = Path(args.image) if args.image else None
    temp_file = None
    if image_path is None:
        temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".jpg")
        temp_file.close()
        image_path = Path(temp_file.name)
        _synthetic_person_image(image_path)

    if not image_path.exists():
        raise FileNotFoundError(f"Image not found: {image_path}")

    with image_path.open("rb") as handle:
        response = requests.post(
            args.url,
            data={
                "model_id": args.model_id,
                "confidence": str(args.confidence),
            },
            files={"file": (image_path.name, handle, "image/jpeg")},
            timeout=args.timeout,
        )
    response.raise_for_status()
    payload = response.json()
    predictions = payload.get("predictions", []) if isinstance(payload, dict) else []
    return {
        "url": args.url,
        "model_id": args.model_id,
        "prediction_count": len(predictions) if isinstance(predictions, list) else None,
        "payload": payload,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Smoke-test person detector adapter /infer endpoint.")
    parser.add_argument("--url", default="http://127.0.0.1:9001/infer")
    parser.add_argument("--model-id", default="rfdetr-nano")
    parser.add_argument("--image", default="", help="Optional image path. Synthetic image is used when omitted.")
    parser.add_argument("--confidence", type=float, default=0.3)
    parser.add_argument("--timeout", type=float, default=10.0)
    args = parser.parse_args()

    print(json.dumps(run(args), indent=2))


if __name__ == "__main__":
    main()
