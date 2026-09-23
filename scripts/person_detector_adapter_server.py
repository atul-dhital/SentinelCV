"""HTTP adapter for SentinelCV secondary person detector.

Exposes the /infer contract consumed by ai_services/tracker.py. It supports:
- inference: Roboflow Inference get_model(...) when package is available
- inference_sdk: calls a Roboflow-compatible HTTP API through InferenceHTTPClient
- ultralytics: local YOLO smoke/backend fallback

The adapter is intentionally optional. If RF-DETR dependencies are unavailable,
SentinelCV still runs YOLO-only.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional

import cv2
from fastapi import FastAPI, File, Form, HTTPException, UploadFile


app = FastAPI(title="SentinelCV Person Detector Adapter")
_MODEL_CACHE: Dict[str, Any] = {}


def _backend() -> str:
    return os.getenv("PERSON_ADAPTER_BACKEND", "inference").strip().lower()


def _model_id(default: str = "rfdetr-nano") -> str:
    return os.getenv("PERSON_SECONDARY_MODEL", default).strip() or default


def _prediction(
    x1: float,
    y1: float,
    x2: float,
    y2: float,
    confidence: float,
    class_name: str = "person",
) -> Dict[str, Any]:
    width = max(0.0, float(x2) - float(x1))
    height = max(0.0, float(y2) - float(y1))
    return {
        "class": class_name,
        "class_name": class_name,
        "confidence": float(confidence),
        "x": float(x1) + width / 2.0,
        "y": float(y1) + height / 2.0,
        "width": width,
        "height": height,
        "bbox": {
            "x1": float(x1),
            "y1": float(y1),
            "x2": float(x2),
            "y2": float(y2),
        },
    }


def _is_person(raw: Dict[str, Any]) -> bool:
    label = next(
        (
            raw.get(key)
            for key in ("class", "class_name", "label", "name")
            if raw.get(key) is not None
        ),
        None,
    )
    if isinstance(label, str):
        return label.strip().lower() in {"person", "people", "human"}
    try:
        if label is not None and int(label) == 0:
            return True
    except (TypeError, ValueError):
        pass
    try:
        return int(raw.get("class_id")) == 0
    except (TypeError, ValueError):
        return False


def _normalize_predictions(raw_predictions: List[Dict[str, Any]], confidence: float) -> List[Dict[str, Any]]:
    normalized: List[Dict[str, Any]] = []
    for item in raw_predictions:
        if not isinstance(item, dict) or not _is_person(item):
            continue
        conf = float(item.get("confidence", item.get("score", item.get("probability", 0.0))) or 0.0)
        if conf < confidence:
            continue

        if all(key in item for key in ("x", "y", "width", "height")):
            x = float(item["x"])
            y = float(item["y"])
            width = float(item["width"])
            height = float(item["height"])
            normalized.append(_prediction(x - width / 2.0, y - height / 2.0, x + width / 2.0, y + height / 2.0, conf))
            continue

        box = item.get("bbox") or item.get("box")
        if isinstance(box, dict) and all(key in box for key in ("x1", "y1", "x2", "y2")):
            normalized.append(_prediction(box["x1"], box["y1"], box["x2"], box["y2"], conf))
            continue

        xyxy = item.get("xyxy") or item.get("box_xyxy")
        if isinstance(xyxy, (list, tuple)) and len(xyxy) == 4:
            normalized.append(_prediction(xyxy[0], xyxy[1], xyxy[2], xyxy[3], conf))
    return normalized


def _result_to_predictions(result: Any, confidence: float) -> List[Dict[str, Any]]:
    if isinstance(result, list) and result:
        if all(isinstance(item, dict) for item in result):
            return _normalize_predictions(result, confidence)
        return _result_to_predictions(result[0], confidence)

    if isinstance(result, dict):
        for key in ("predictions", "detections"):
            value = result.get(key)
            if isinstance(value, list):
                return _normalize_predictions(value, confidence)
        nested = result.get("result") or result.get("outputs")
        if isinstance(nested, dict):
            return _result_to_predictions(nested, confidence)

    json_method = getattr(result, "json", None)
    if callable(json_method):
        return _result_to_predictions(json_method(), confidence)

    dict_method = getattr(result, "dict", None)
    if callable(dict_method):
        return _result_to_predictions(dict_method(), confidence)

    predictions = getattr(result, "predictions", None)
    if predictions is not None:
        return _result_to_predictions(predictions, confidence)

    return []


def _infer_with_ultralytics(image_path: str, model_id: str, confidence: float) -> List[Dict[str, Any]]:
    try:
        from ultralytics import YOLO
    except Exception as exc:
        raise RuntimeError("ultralytics backend requires package 'ultralytics'") from exc

    model = _MODEL_CACHE.get(model_id)
    if model is None:
        model = YOLO(model_id)
        _MODEL_CACHE[model_id] = model

    image = cv2.imread(image_path)
    if image is None:
        raise RuntimeError("Could not read uploaded image")
    results = model.predict(image, classes=[0], conf=confidence, verbose=False)
    boxes = results[0].boxes
    if boxes is None or len(boxes) == 0:
        return []
    xyxy = boxes.xyxy.cpu().numpy()
    confs = boxes.conf.cpu().numpy()
    return [
        _prediction(box[0], box[1], box[2], box[3], conf)
        for box, conf in zip(xyxy, confs)
        if float(conf) >= confidence
    ]


def _infer_with_inference(image_path: str, model_id: str, confidence: float) -> List[Dict[str, Any]]:
    try:
        from inference import get_model  # type: ignore
    except Exception as exc:
        raise RuntimeError("RF-DETR backend requires package 'inference' in this Python env") from exc

    model = _MODEL_CACHE.get(model_id)
    if model is None:
        api_key = os.getenv("ROBOFLOW_API_KEY") or None
        try:
            model = get_model(model_id=model_id, api_key=api_key)
        except TypeError:
            model = get_model(model_id)
        _MODEL_CACHE[model_id] = model

    try:
        result = model.infer(image_path, confidence=confidence)
    except TypeError:
        result = model.infer(image_path)
    return _result_to_predictions(result, confidence)


def _infer_with_sdk(image_path: str, model_id: str, confidence: float) -> List[Dict[str, Any]]:
    try:
        from inference_sdk import InferenceHTTPClient  # type: ignore
    except Exception as exc:
        raise RuntimeError("SDK backend requires package 'inference-sdk' in this Python env") from exc

    api_url = os.getenv("ROBOFLOW_INFERENCE_API_URL", "https://serverless.roboflow.com")
    api_key = os.getenv("ROBOFLOW_API_KEY", "")
    cache_key = f"sdk:{api_url}:{api_key}"
    client = _MODEL_CACHE.get(cache_key)
    if client is None:
        client = InferenceHTTPClient(api_url=api_url, api_key=api_key)
        _MODEL_CACHE[cache_key] = client
    result = client.infer(image_path, model_id=model_id)
    return _result_to_predictions(result, confidence)


@app.get("/health")
async def health() -> Dict[str, Any]:
    return {
        "status": "ok",
        "backend": _backend(),
        "model_id": _model_id(),
    }


@app.post("/infer")
async def infer(
    file: UploadFile = File(...),
    model_id: Optional[str] = Form(default=None),
    confidence: float = Form(default=0.3),
) -> Dict[str, Any]:
    model = (model_id or _model_id()).strip()
    suffix = Path(file.filename or "frame.jpg").suffix or ".jpg"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(await file.read())
        image_path = tmp.name

    try:
        backend = _backend()
        if backend == "ultralytics":
            predictions = _infer_with_ultralytics(image_path, model, confidence)
        elif backend in {"sdk", "inference_sdk", "roboflow_http"}:
            predictions = _infer_with_sdk(image_path, model, confidence)
        elif backend == "inference":
            predictions = _infer_with_inference(image_path, model, confidence)
        else:
            raise HTTPException(status_code=400, detail=f"Unsupported PERSON_ADAPTER_BACKEND={backend}")
        return {
            "model_id": model,
            "backend": backend,
            "predictions": predictions,
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    finally:
        try:
            os.remove(image_path)
        except OSError:
            pass


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host=os.getenv("PERSON_ADAPTER_HOST", "127.0.0.1"), port=int(os.getenv("PERSON_ADAPTER_PORT", "9001")))
