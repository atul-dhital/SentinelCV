import json
import os
from typing import Any, Dict, List


AI_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(AI_DIR)
DATA_DIR = os.getenv("DATA_DIR", os.path.join(PROJECT_ROOT, "backend", "data"))
RUNTIME_REGISTRY_PATH = os.getenv(
    "RUNTIME_REGISTRY_PATH",
    os.path.join(DATA_DIR, "runtime_model_registry.json"),
)


def _resolve_person_detector_defaults() -> tuple[str, str]:
    model_env = os.getenv("PERSON_DETECTOR_MODEL")
    artifact_env = os.getenv("PERSON_DETECTOR_ARTIFACT")
    if model_env or artifact_env:
        return model_env or "YOLO26n", artifact_env or "yolo26n.pt"

    ai_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.dirname(ai_dir)
    models_dir = os.path.join(project_root, "models")
    
    yolo26_paths = [
        os.path.join(ai_dir, "yolo26n.pt"),
        os.path.join(models_dir, "yolo26n.pt"),
    ]
    for path in yolo26_paths:
        if os.path.exists(path):
            return "YOLO26n", "yolo26n.pt"

    yolo11_paths = [
        os.path.join(ai_dir, "yolo11n.pt"),
        os.path.join(models_dir, "yolo11n.pt"),
    ]
    for path in yolo11_paths:
        if os.path.exists(path):
            return "YOLO11n", "yolo11n.pt"
    
    yolov8_paths = [
        os.path.join(ai_dir, "yolov8n.pt"),
        os.path.join(models_dir, "yolov8n.pt"),
    ]
    for path in yolov8_paths:
        if os.path.exists(path):
            return "YOLOv8n", "yolov8n.pt"

    return "YOLOv8n", "yolov8n.pt"


def _default_components() -> List[Dict[str, Any]]:
    person_model, person_artifact = _resolve_person_detector_defaults()
    return [
        {
            "component": "person_detector",
            "current_model": person_model,
            "current_artifact": person_artifact,
            "target_model": "YOLO26n",
            "target_artifact": "yolo26n.pt",
        },
        {
            "component": "person_tracker",
            "current_model": os.getenv("TRACKER_BACKEND", "ByteTrack"),
            "target_model": "ByteTrack",
            "target_artifact": None,
        },
        {
            "component": "face_detector",
            "current_model": os.getenv("FACE_DETECTOR_BACKEND", "opencv"),
            "target_model": "retinaface",
            "target_artifact": None,
        },
        {
            "component": "face_recognition",
            "current_model": os.getenv("FACE_RECOGNITION_MODEL", "ArcFace"),
            "target_model": "AdaFace",
            "target_artifact": "models/adaface.onnx",
        },
        {
            "component": "liveness_engine",
            "current_model": os.getenv("LIVENESS_MODEL_NAME", "Spectral + CNN Ensemble"),
            "current_artifact": os.getenv("LIVENESS_MODEL_PATH", "models/liveness_net.onnx"),
            "target_model": "CNN + spectral ensemble",
            "target_artifact": "models/liveness_net_v2.onnx",
        },
        {
            "component": "pose_estimation",
            "current_model": os.getenv("POSE_MODEL_NAME", "MediaPipe Pose"),
            "current_artifact": os.getenv("POSE_MODEL_PATH", "mediapipe.pose"),
            "target_model": "YOLO26s-pose",
            "target_artifact": "models/yolo26s-pose.pt",
        },
        {
            "component": "action_gesture_inference",
            "current_model": os.getenv("ACTION_MODEL_NAME", "Heuristic Action Inference v1"),
            "current_artifact": os.getenv("ACTION_MODEL_PATH", "heuristic.action.v1"),
            "target_model": "Pose sequence temporal model",
            "target_artifact": "models/action_temporal_v1.onnx",
        },
    ]


def load_runtime_registry() -> Dict[str, Any]:
    registry = {"components": _default_components()}
    if not os.path.exists(RUNTIME_REGISTRY_PATH):
        return registry

    try:
        with open(RUNTIME_REGISTRY_PATH, "r", encoding="utf-8") as handle:
            persisted = json.load(handle)
    except Exception:
        return registry

    merged = {item["component"]: dict(item) for item in registry["components"]}
    for item in persisted.get("components", []):
        component = item.get("component")
        if not component:
            continue
        base = merged.get(component, {"component": component})
        merged[component] = {**base, **item}

    registry["components"] = list(merged.values())
    return registry


def get_runtime_component(component: str) -> Dict[str, Any]:
    registry = load_runtime_registry()
    return next(
        (item for item in registry["components"] if item.get("component") == component),
        {"component": component},
    )
