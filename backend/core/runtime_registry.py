import json
import os
from datetime import datetime, timezone
from typing import Any, Dict, List

from core.paths import DATA_DIR, data_path


def runtime_registry_path() -> str:
    return data_path("runtime_model_registry.json")


def benchmark_results_path() -> str:
    return data_path("benchmark_results.json")


def benchmark_history_path() -> str:
    return data_path("benchmark_history.json")


def _default_components() -> List[Dict[str, Any]]:
    detector_artifact = os.getenv("PERSON_DETECTOR_ARTIFACT", "yolov8n.pt")
    detector_model = os.getenv("PERSON_DETECTOR_MODEL", "YOLOv8n")
    tracker_backend = os.getenv("TRACKER_BACKEND", "ByteTrack")
    face_detector = os.getenv("FACE_DETECTOR_BACKEND", "opencv")
    face_model = os.getenv("FACE_RECOGNITION_MODEL", "ArcFace")
    liveness_model = os.getenv("LIVENESS_MODEL_NAME", "Spectral + CNN Ensemble")
    liveness_artifact = os.getenv("LIVENESS_MODEL_PATH", "models/liveness_net.onnx")
    pose_model = os.getenv("POSE_MODEL_NAME", "MediaPipe Pose")
    pose_artifact = os.getenv("POSE_MODEL_PATH", "mediapipe.pose")
    action_model = os.getenv("ACTION_MODEL_NAME", "Heuristic Action Inference v1")
    action_artifact = os.getenv("ACTION_MODEL_PATH", "heuristic.action.v1")

    return [
        {
            "component": "person_detector",
            "display_name": "Person detector",
            "current_model": detector_model,
            "current_artifact": detector_artifact,
            "target_model": "YOLO26n",
            "target_artifact": "yolo26n.pt",
            "framework": "Ultralytics / PyTorch",
            "runtime": "ai-service",
            "status": "active",
            "notes": "Current live detector in the AI service. Promote YOLO11 after benchmark validation.",
        },
        {
            "component": "person_tracker",
            "display_name": "Person tracker",
            "current_model": tracker_backend,
            "current_artifact": None,
            "target_model": "ByteTrack",
            "target_artifact": None,
            "framework": "Ultralytics tracking stack",
            "runtime": "ai-service",
            "status": "active",
            "notes": "Tracking backend for persistent person IDs.",
        },
        {
            "component": "face_detector",
            "display_name": "Face detector backend",
            "current_model": face_detector,
            "current_artifact": None,
            "target_model": "retinaface",
            "target_artifact": None,
            "framework": "DeepFace detector backend",
            "runtime": "ai-service",
            "status": "active",
            "notes": "Face extraction backend used before embedding generation.",
        },
        {
            "component": "face_recognition",
            "display_name": "Face recognition model",
            "current_model": face_model,
            "current_artifact": None,
            "target_model": "AdaFace",
            "target_artifact": "models/adaface.onnx",
            "framework": "ArcFace-compatible embedding model",
            "runtime": "ai-service",
            "status": "active",
            "notes": "Current identification model. Benchmark AdaFace before promotion.",
        },
        {
            "component": "liveness_engine",
            "display_name": "Liveness engine",
            "current_model": liveness_model,
            "current_artifact": liveness_artifact,
            "target_model": "CNN + spectral ensemble",
            "target_artifact": "models/liveness_net_v2.onnx",
            "framework": "OpenCV / ONNX / heuristics",
            "runtime": "backend + ai-service",
            "status": "active",
            "notes": "Shared liveness and anti-spoofing baseline across services.",
        },
        {
            "component": "pose_estimation",
            "display_name": "Pose estimation",
            "current_model": pose_model,
            "current_artifact": pose_artifact,
            "target_model": "YOLO26s-pose",
            "target_artifact": "models/yolo26s-pose.pt",
            "framework": "MediaPipe / OpenCV",
            "runtime": "ai-service",
            "status": "pilot",
            "notes": "Initial body-keypoint extraction path for posture and action analytics.",
        },
        {
            "component": "action_gesture_inference",
            "display_name": "Action and gesture inference",
            "current_model": action_model,
            "current_artifact": action_artifact,
            "target_model": "Pose sequence temporal model",
            "target_artifact": "models/action_temporal_v1.onnx",
            "framework": "Heuristic temporal inference",
            "runtime": "ai-service",
            "status": "pilot",
            "notes": "First-class action/gesture module; candidate for temporal model upgrade.",
        },
    ]


def default_runtime_registry() -> Dict[str, Any]:
    return {
        "version": "1.0.0",
        "source": "shared-runtime-registry",
        "last_updated_at": None,
        "data_dir": DATA_DIR,
        "components": _default_components(),
    }


def _merge_components(
    defaults: List[Dict[str, Any]], persisted: List[Dict[str, Any]] | None,
) -> List[Dict[str, Any]]:
    merged = {item["component"]: dict(item) for item in defaults}
    for item in persisted or []:
        component = item.get("component")
        if not component:
            continue
        base = merged.get(component, {"component": component})
        merged[component] = {**base, **item}
    return list(merged.values())


def load_runtime_registry() -> Dict[str, Any]:
    registry = default_runtime_registry()

    path = runtime_registry_path()
    if not os.path.exists(path):
        return registry

    try:
        with open(path, "r", encoding="utf-8") as handle:
            persisted = json.load(handle)
    except Exception:
        return registry

    registry["version"] = persisted.get("version", registry["version"])
    registry["source"] = persisted.get("source", registry["source"])
    registry["last_updated_at"] = persisted.get("last_updated_at")
    registry["components"] = _merge_components(
        registry["components"], persisted.get("components"),
    )
    return registry


def save_runtime_registry(payload: Dict[str, Any]) -> Dict[str, Any]:
    registry = default_runtime_registry()
    registry["version"] = payload.get("version", registry["version"])
    registry["source"] = "shared-runtime-registry"
    registry["last_updated_at"] = datetime.now(timezone.utc).isoformat()
    registry["components"] = _merge_components(
        registry["components"], payload.get("components"),
    )

    os.makedirs(DATA_DIR, exist_ok=True)
    with open(runtime_registry_path(), "w", encoding="utf-8") as handle:
        json.dump(registry, handle, indent=2)
    return registry


def get_runtime_component(component: str) -> Dict[str, Any] | None:
    registry = load_runtime_registry()
    return next(
        (item for item in registry["components"] if item.get("component") == component),
        None,
    )
