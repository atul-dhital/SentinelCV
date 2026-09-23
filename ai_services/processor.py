from __future__ import annotations

from collections import defaultdict
from threading import Lock
import asyncio
import logging
import socket
from urllib.parse import urlparse
import os
import base64
import time
from dotenv import load_dotenv

# Load environment variables from .env if present
load_dotenv()
import cv2
import requests
import numpy as np
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Response
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any, Tuple
from uuid import UUID
import uvicorn
from runtime_registry import get_runtime_component, load_runtime_registry
from edge_export import edge_export_service, EXPORT_DIR

# Global state for cleanup
_rtsp_manager_for_cleanup: Optional[RTSPStreamManager] = None

# How long to wait on an unresponsive camera before giving up. Set on the
# capture object and, for older OpenCV builds that ignore those properties,
# passed to FFmpeg directly. Must be exported before the first capture is
# created — FFmpeg reads it at open time.
RTSP_TIMEOUT_MS = int(os.getenv("RTSP_TIMEOUT_MS", "5000"))
# FFmpeg renamed the RTSP socket timeout from `stimeout` to `timeout` in 5.0;
# send both so the bound holds whichever build OpenCV ships with. Value is
# microseconds.
os.environ.setdefault(
    "OPENCV_FFMPEG_CAPTURE_OPTIONS",
    "|".join(
        [
            "rtsp_transport;tcp",
            f"timeout;{RTSP_TIMEOUT_MS * 1000}",
            f"stimeout;{RTSP_TIMEOUT_MS * 1000}",
        ]
    ),
)

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan context manager for app startup and shutdown."""
    # Startup: pre-load + warm the heavy models so the FIRST camera frame is not
    # slow. Without this, buffalo_l (~280MB ONNX) + YOLO weights load lazily on
    # the first identification request, producing a multi-second stall every boot.
    # Skippable via AI_PREWARM=0 (e.g. fast restarts in tests).
    if os.getenv("AI_PREWARM", "1").strip().lower() not in ("0", "false", "no", "off"):
        import asyncio

        def _prewarm():
            try:
                get_face_engine()._warmup()   # loads buffalo_l + warms ArcFace
                get_tracker()                 # loads YOLO weights
                logger.info("AI models pre-warmed at startup")
            except Exception as exc:
                logger.warning("Model prewarm skipped: %s", exc)

        await asyncio.to_thread(_prewarm)     # off the event loop; non-fatal
    yield
    # Shutdown: cleanup
    global _rtsp_manager_for_cleanup
    if _rtsp_manager_for_cleanup:
        _rtsp_manager_for_cleanup.stop_all()

app = FastAPI(title="SentinelCV AI Service", lifespan=lifespan)
APP_STARTED_AT = time.time()
_metrics_lock = Lock()
_ai_metrics = {
    "requests_total": 0,
    "errors_total": 0,
    "latency_total_seconds": 0.0,
    "path_counts": defaultdict(int),
}
logger = logging.getLogger(__name__)

# Configuration
API_BASE_URL = os.getenv("API_BASE_URL", "http://127.0.0.1:8000/api/v1")
INTERNAL_SERVICE_KEY = os.getenv("INTERNAL_SERVICE_KEY", "")
_INTERNAL_HEADERS = {"X-Internal-API-Key": INTERNAL_SERVICE_KEY} if INTERNAL_SERVICE_KEY else {}
AI_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(AI_DIR)
DEFAULT_SHARED_DATA_DIR = os.path.join(PROJECT_ROOT, "backend", "data")
DATA_DIR = os.getenv("DATA_DIR", DEFAULT_SHARED_DATA_DIR)
FACE_IMAGE_DIR = os.getenv("FACE_IMAGE_DIR", os.path.join(DATA_DIR, "face_images"))

# Tunable thresholds — override via environment variables
FACE_SEARCH_THRESHOLD = float(os.getenv("FACE_SEARCH_THRESHOLD", "0.6"))
FACE_QUALITY_MIN = float(os.getenv("FACE_QUALITY_MIN", "0.15"))
LIVENESS_SCORE_MIN = float(os.getenv("LIVENESS_SCORE_MIN", "0.5"))


def resolve_input_path(path_value: str) -> str:
    if os.path.isabs(path_value) and os.path.exists(path_value):
        return path_value

    normalized_input = path_value.replace("\\", "/")
    data_relative = (
        normalized_input[5:]
        if normalized_input.startswith("data/")
        else normalized_input
    )

    candidates = [
        path_value,
        os.path.join(os.getcwd(), path_value),
        os.path.join(DATA_DIR, path_value),
        os.path.join(DATA_DIR, data_relative),
        os.path.join(PROJECT_ROOT, path_value),
    ]

    normalized = []
    for candidate in candidates:
        fixed = os.path.normpath(candidate)
        if fixed not in normalized:
            normalized.append(fixed)

    for candidate in normalized:
        if os.path.exists(candidate):
            return candidate

    return os.path.normpath(path_value)


def _validate_relative_output_path(output_path: str) -> str:
    normalized = os.path.normpath(output_path)
    drive, _ = os.path.splitdrive(normalized)
    if drive or os.path.isabs(normalized):
        raise ValueError("output_path must be a relative path")

    parts = [part for part in normalized.replace("\\", "/").split("/") if part]
    if any(part == ".." for part in parts):
        raise ValueError("output_path cannot traverse outside export directory")

    if normalized in {".", ""}:
        raise ValueError("output_path must include a file name")

    return normalized


def _normalize_input_shape(input_shape: List[int]) -> Tuple[int, ...]:
    if not input_shape:
        raise ValueError("input_shape must not be empty")

    normalized: List[int] = []
    for dim in input_shape:
        if not isinstance(dim, int) or dim <= 0:
            raise ValueError("input_shape must contain positive integers")
        normalized.append(dim)

    return tuple(normalized)


def _load_torch_model(model_path: str) -> Any:
    try:
        import torch
    except ImportError as exc:
        raise ValueError("PyTorch not installed in AI service") from exc

    try:
        model = torch.load(model_path, map_location="cpu", weights_only=True)
    except Exception as weights_only_exc:
        try:
            model = torch.jit.load(model_path, map_location="cpu")
        except Exception as jit_exc:
            raise ValueError(
                f"Failed to load model with weights_only=True ({weights_only_exc}); "
                f"TorchScript fallback also failed ({jit_exc}). "
                "Pickle-based torch.load is disabled by default for security; "
                "re-export the model as a state_dict or TorchScript module."
            ) from weights_only_exc

    if isinstance(model, dict):
        candidate = model.get("model") or model.get("module")
        if candidate is not None:
            model = candidate

    if not isinstance(model, torch.nn.Module):
        raise ValueError("Loaded model is not a torch.nn.Module")

    if hasattr(model, "eval"):
        model.eval()

    return model


def _wrap_edge_result(result: Dict[str, Any]) -> Dict[str, Any]:
    if "success" in result:
        return result
    if "error" in result:
        return {"success": False, **result}
    return {"success": True, **result}


def _escape_prometheus_label(value: str) -> str:
    return value.replace("\\", "\\\\").replace("\n", "\\n").replace('"', '\\"')


@app.middleware("http")
async def capture_metrics(request, call_next):
    started_at = time.time()
    try:
        response = await call_next(request)
    except Exception:
        process_time = time.time() - started_at
        with _metrics_lock:
            _ai_metrics["requests_total"] += 1
            _ai_metrics["errors_total"] += 1
            _ai_metrics["latency_total_seconds"] += process_time
            _ai_metrics["path_counts"][request.url.path] += 1
        raise

    process_time = time.time() - started_at
    with _metrics_lock:
        _ai_metrics["requests_total"] += 1
        if response.status_code >= 500:
            _ai_metrics["errors_total"] += 1
        _ai_metrics["latency_total_seconds"] += process_time
        _ai_metrics["path_counts"][request.url.path] += 1
    return response

# Lazy-initialized RTSP stream manager (needs face_engine)
_rtsp_manager: Optional[RTSPStreamManager] = None
_liveness_checker: Optional[LivenessChecker] = None
_multi_angle_matcher: Optional[MultiAngleFaceMatcher] = None
_augmenter: Optional[AdvancedAugmentation] = None
_xai_manager: Optional[ExplainabilityManager] = None
_pose_estimator: Optional[PoseEstimator] = None
_action_inference: Optional[ActionInferenceEngine] = None
_liveness_signature: Optional[tuple] = None
_pose_signature: Optional[tuple] = None
_action_signature: Optional[tuple] = None

# Per-component locks to prevent double-init under concurrent requests
_liveness_lock = Lock()
_multi_angle_lock = Lock()
_augmenter_lock = Lock()
_xai_lock = Lock()
_pose_lock = Lock()
_action_lock = Lock()


def get_liveness_checker() -> LivenessChecker:
    global _liveness_checker, _liveness_signature
    liveness_config = get_runtime_component("liveness_engine")
    signature = (
        liveness_config.get("current_model"),
        liveness_config.get("current_artifact"),
    )
    with _liveness_lock:
        if _liveness_checker is None or signature != _liveness_signature:
            from liveness_checker import LivenessChecker
            _liveness_checker = LivenessChecker()
            _liveness_signature = signature
        return _liveness_checker


def get_multi_angle_matcher() -> MultiAngleFaceMatcher:
    global _multi_angle_matcher
    with _multi_angle_lock:
        if _multi_angle_matcher is None:
            from multi_angle_recognition import MultiAngleFaceMatcher
            _multi_angle_matcher = MultiAngleFaceMatcher()
        return _multi_angle_matcher


def get_augmenter() -> AdvancedAugmentation:
    global _augmenter
    with _augmenter_lock:
        if _augmenter is None:
            from advanced_augmentation import AdvancedAugmentation
            _augmenter = AdvancedAugmentation()
        return _augmenter


def get_xai_manager() -> ExplainabilityManager:
    global _xai_manager
    with _xai_lock:
        if _xai_manager is None:
            from explainability import ExplainabilityManager
            _xai_manager = ExplainabilityManager()
        return _xai_manager


def get_pose_estimator() -> PoseEstimator:
    global _pose_estimator, _pose_signature
    pose_config = get_runtime_component("pose_estimation")
    signature = (
        pose_config.get("current_model"),
        pose_config.get("current_artifact"),
    )
    with _pose_lock:
        if _pose_estimator is None or signature != _pose_signature:
            from pose_estimator import PoseEstimator
            _pose_estimator = PoseEstimator()
            _pose_signature = signature
        return _pose_estimator


def get_action_inference() -> ActionInferenceEngine:
    global _action_inference, _action_signature
    action_config = get_runtime_component("action_gesture_inference")
    signature = (
        action_config.get("current_model"),
        action_config.get("current_artifact"),
    )
    with _action_lock:
        if _action_inference is None or signature != _action_signature:
            from action_inference import ActionInferenceEngine
            _action_inference = ActionInferenceEngine()
            _action_signature = signature
        return _action_inference


def get_rtsp_manager() -> RTSPStreamManager:
    global _rtsp_manager, _rtsp_manager_for_cleanup
    if _rtsp_manager is None:
        from rtsp_manager import RTSPStreamManager
        _rtsp_manager = RTSPStreamManager(
            face_engine=get_face_engine(),
            api_base_url=API_BASE_URL,
        )
        _rtsp_manager_for_cleanup = _rtsp_manager
    return _rtsp_manager


class VideoProcessRequest(BaseModel):
    organization_id: UUID
    video_path: str


class ProcessResult(BaseModel):
    status: str
    message: str
    people_detected: int = 0
    people_identified: int = 0


class EmbedFaceRequest(BaseModel):
    image_path: str


class EmbedFaceResult(BaseModel):
    embedding: Optional[list] = None
    quality_score: float = 0.0
    face_count: int = 0
    face_angle: Optional[str] = None
    error: Optional[str] = None


class FaceRecognitionDiagnostics(BaseModel):
    current_model: str
    detector_backend: str
    embedding_mode: str
    vit_available: bool
    vit_loaded: bool
    vit_model_type: Optional[str] = None
    vit_device: Optional[str] = None
    runtime_component: Dict[str, Any]


def _extract_landmarks(face_data: Dict[str, Any]) -> Dict[str, Tuple[float, float]]:
    facial_area = face_data.get("facial_area") or {}
    if not isinstance(facial_area, dict):
        return {}

    landmarks: Dict[str, Tuple[float, float]] = {}
    for key in ("left_eye", "right_eye", "nose", "mouth_left", "mouth_right"):
        point = facial_area.get(key)
        if isinstance(point, (list, tuple)) and len(point) >= 2:
            landmarks[key] = (float(point[0]), float(point[1]))
    return landmarks


def _classify_face_angle(face_data: Dict[str, Any]) -> Optional[str]:
    landmarks = _extract_landmarks(face_data)
    left_eye = landmarks.get("left_eye")
    right_eye = landmarks.get("right_eye")
    nose = landmarks.get("nose")

    if left_eye and right_eye and nose:
        center_x = (left_eye[0] + right_eye[0]) / 2.0
        interocular = max(abs(right_eye[0] - left_eye[0]), 1e-6)
        offset_ratio = (nose[0] - center_x) / interocular
        abs_offset = abs(offset_ratio)
        if abs_offset < 0.1:
            return "frontal"
        if abs_offset < 0.25:
            return "45_right" if offset_ratio > 0 else "45_left"
        return "profile"

    facial_area = face_data.get("facial_area") or {}
    try:
        width = float(facial_area.get("w", 0.0))
        height = float(facial_area.get("h", 0.0))
        if height > 0 and (width / height) > 1.3:
            return "profile"
    except Exception:
        pass

    return None


# Lazy-load heavy models
_tracker: Optional[PersonTracker] = None
_face_engine: Optional[FaceEngine] = None
_tracker_signature: Optional[tuple] = None
_face_signature: Optional[tuple] = None


def get_tracker():
    global _tracker, _tracker_signature
    detector_config = get_runtime_component("person_detector")
    tracker_config = get_runtime_component("person_tracker")
    signature = (
        detector_config.get("current_model"),
        detector_config.get("current_artifact"),
        tracker_config.get("current_model"),
    )
    if _tracker is None or signature != _tracker_signature:
        from tracker import PersonTracker
        _tracker = PersonTracker()
        _tracker_signature = signature
    return _tracker


def get_face_engine():
    global _face_engine, _face_signature
    recognition_config = get_runtime_component("face_recognition")
    detector_config = get_runtime_component("face_detector")
    signature = (
        recognition_config.get("current_model"),
        detector_config.get("current_model"),
    )
    if _face_engine is None or signature != _face_signature:
        from face_engine import FaceEngine
        _face_engine = FaceEngine()
        _face_signature = signature
    return _face_engine


def _models_initialized() -> bool:
    detector = get_runtime_component("person_detector")
    artifact = str(detector.get("current_artifact") or "").strip()
    if not artifact:
        return True

    candidates = [
        artifact,
        os.path.join(AI_DIR, artifact),
        os.path.join(DATA_DIR, artifact),
        os.path.join(PROJECT_ROOT, artifact),
        os.path.join(PROJECT_ROOT, "backend", "data", artifact),
        os.path.join(PROJECT_ROOT, "models", os.path.basename(artifact)),
    ]
    return any(os.path.exists(os.path.normpath(candidate)) for candidate in candidates)


@app.get("/health")
async def health():
    detector = get_runtime_component("person_detector")
    recognition = get_runtime_component("face_recognition")
    liveness = get_runtime_component("liveness_engine")
    pose = get_runtime_component("pose_estimation")
    action = get_runtime_component("action_gesture_inference")
    try:
        from face_engine import recognition_backend_status
        recognition_status = recognition_backend_status()
    except Exception as exc:  # never let health crash on a status probe
        recognition_status = {"real_recognition": False, "degraded": True, "error": str(exc)}
    return {
        "status": "ok",
        "service": "ai",
        "models_loaded": _models_initialized(),
        # True real face recognition only when a real ArcFace backend is loadable;
        # otherwise the engine degrades to a weak pixel fallback (or refuses, in strict mode).
        "recognition": recognition_status,
        "runtime_registry": load_runtime_registry(),
        "active_models": {
            "person_detector": detector.get("current_model"),
            "face_recognition": recognition.get("current_model"),
            "liveness_engine": liveness.get("current_model"),
            "pose_estimation": pose.get("current_model"),
            "action_gesture_inference": action.get("current_model"),
        },
    }


@app.get("/diagnostics/face-recognition", response_model=FaceRecognitionDiagnostics)
async def face_recognition_diagnostics():
    recognition = get_runtime_component("face_recognition")
    detector = get_runtime_component("face_detector")
    model_name = str(recognition.get("current_model") or "ArcFace")
    model_norm = model_name.lower()
    if "ensemble" in model_norm:
        embedding_mode = "ensemble"
    elif "vit" in model_norm or "transformer" in model_norm:
        embedding_mode = "vit"
    else:
        embedding_mode = "arcface"

    vit_available = False
    vit_loaded = False
    vit_model_type = None
    vit_device = None

    if embedding_mode in {"vit", "ensemble"}:
        try:
            from vit_engine import get_vit_service
            vit_available = True
            vit_service = get_vit_service()
            vit_loaded = vit_service.load_model()
            vit_model_type = vit_service.model_type
            vit_device = str(vit_service.device)
        except Exception:
            vit_available = False

    return FaceRecognitionDiagnostics(
        current_model=model_name,
        detector_backend=str(detector.get("current_model") or "opencv"),
        embedding_mode=embedding_mode,
        vit_available=vit_available,
        vit_loaded=vit_loaded,
        vit_model_type=vit_model_type,
        vit_device=vit_device,
        runtime_component=recognition,
    )


@app.get("/metrics")
async def metrics():
    with _metrics_lock:
        requests_total = int(_ai_metrics["requests_total"])
        errors_total = int(_ai_metrics["errors_total"])
        latency_total_seconds = float(_ai_metrics["latency_total_seconds"])
        path_counts = dict(_ai_metrics["path_counts"])

    average_latency = latency_total_seconds / requests_total if requests_total else 0.0
    detector = get_runtime_component("person_detector")
    recognition = get_runtime_component("face_recognition")
    liveness = get_runtime_component("liveness_engine")
    pose = get_runtime_component("pose_estimation")
    action = get_runtime_component("action_gesture_inference")

    lines = [
        "# HELP sentinelcv_ai_requests_total Total HTTP requests handled by the AI service.",
        "# TYPE sentinelcv_ai_requests_total counter",
        f"sentinelcv_ai_requests_total {requests_total}",
        "# HELP sentinelcv_ai_errors_total Total AI service requests that resulted in a server error.",
        "# TYPE sentinelcv_ai_errors_total counter",
        f"sentinelcv_ai_errors_total {errors_total}",
        "# HELP sentinelcv_ai_request_latency_average_seconds Average AI service request latency in seconds.",
        "# TYPE sentinelcv_ai_request_latency_average_seconds gauge",
        f"sentinelcv_ai_request_latency_average_seconds {average_latency:.6f}",
        "# HELP sentinelcv_ai_uptime_seconds AI service process uptime in seconds.",
        "# TYPE sentinelcv_ai_uptime_seconds gauge",
        f"sentinelcv_ai_uptime_seconds {time.time() - APP_STARTED_AT:.2f}",
        "# HELP sentinelcv_ai_runtime_registry_loaded Whether the shared runtime registry is readable.",
        "# TYPE sentinelcv_ai_runtime_registry_loaded gauge",
        f"sentinelcv_ai_runtime_registry_loaded {1 if load_runtime_registry() else 0}",
        "# HELP sentinelcv_ai_component_loaded Indicator that the AI runtime component is configured.",
        "# TYPE sentinelcv_ai_component_loaded gauge",
        f'sentinelcv_ai_component_loaded{{component="person_detector",model="{_escape_prometheus_label(detector.get("current_model") or "unknown")}"}} 1',
        f'sentinelcv_ai_component_loaded{{component="face_recognition",model="{_escape_prometheus_label(recognition.get("current_model") or "unknown")}"}} 1',
        f'sentinelcv_ai_component_loaded{{component="liveness_engine",model="{_escape_prometheus_label(liveness.get("current_model") or "unknown")}"}} 1',
        f'sentinelcv_ai_component_loaded{{component="pose_estimation",model="{_escape_prometheus_label(pose.get("current_model") or "unknown")}"}} 1',
        f'sentinelcv_ai_component_loaded{{component="action_gesture_inference",model="{_escape_prometheus_label(action.get("current_model") or "unknown")}"}} 1',
        "# HELP sentinelcv_ai_path_requests_total Requests grouped by path.",
        "# TYPE sentinelcv_ai_path_requests_total counter",
    ]
    for path, count in sorted(path_counts.items()):
        lines.append(f'sentinelcv_ai_path_requests_total{{path="{_escape_prometheus_label(path)}"}} {count}')

    return Response(content="\n".join(lines) + "\n", media_type="text/plain; version=0.0.4")


@app.post("/process", response_model=ProcessResult)
async def process_video(req: VideoProcessRequest):
    """
    Process an uploaded video:
    1. Track people using YOLO11/YOLOv8
    2. Extract face embeddings using DeepFace/ArcFace
    3. Search backend for matching visitors
    4. Log results via the backend API
    """
    org_id = str(req.organization_id)
    video_path = req.video_path

    video_path = resolve_input_path(video_path)
    if not os.path.exists(video_path):
        print(f"[AI] Error: Video file not found at {video_path}")
        return ProcessResult(status="error", message=f"Video not found: {video_path}")

    tracker = get_tracker()
    face_engine = get_face_engine()

    print(f"[AI] Processing video: {video_path} for org {org_id}")
    try:
        detections = tracker.track_video(video_path)
    except Exception as e:
        print(f"[AI] Tracking failed: {e}")
        return ProcessResult(
            status="error",
            message=f"Video tracking failed: {str(e)[:200]}",
        )

    # Group detections by track ID
    tracked_people = {}
    for det in detections:
        track_id = int(det["id"])
        if track_id not in tracked_people:
            tracked_people[track_id] = []
        if det["frame"] is not None:
            tracked_people[track_id].append(det)

    people_detected = len(tracked_people)
    people_identified = 0

    os.makedirs(FACE_IMAGE_DIR, exist_ok=True)

    for track_id, dets in tracked_people.items():
        print(f"[AI] Processing Track ID: {track_id}")

        best_embedding = None
        best_face_img = None

        for det in dets:
            faces = face_engine.extract_face(det["frame"])
            if faces:
                face_img = faces[0]["face"]
                # Convert float [0,1] face to uint8 for saving
                if face_img.dtype != np.uint8:
                    face_img_save = (face_img * 255).astype(np.uint8)
                else:
                    face_img_save = face_img

                embedding = face_engine.get_embedding(face_img)
                if embedding is not None:
                    best_embedding = embedding
                    best_face_img = face_img_save
                    break

        if best_embedding is None or best_face_img is None:
            continue

        # Save the face image
        face_filename = f"track_{track_id}_{int(time.time())}.jpg"
        face_path = os.path.join(FACE_IMAGE_DIR, face_filename)
        # Ensure best_face_img is not None for cv2.imwrite
        if best_face_img is not None:
            cv2.imwrite(face_path, best_face_img)
        else:
            continue

        # Search for matching visitor in the backend
        visitor_id = None
        face_data_id = None
        confidence = 0.0
        status = "unidentified"
        angle_scores = {}

        try:
            from multi_angle_recognition import FaceAngle
            # Derive angle from facial_area returned by extract_face
            _face_meta = faces[0] if faces else {}
            _area = _face_meta.get("facial_area", {})
            if _area:
                _x, _y, _w, _h = _area.get("x", 0), _area.get("y", 0), _area.get("w", 64), _area.get("h", 64)
                _bbox = (_x, _y, _x + _w, _y + _h)
                _landmarks = np.array(_area.get("landmarks", [])) if _area.get("landmarks") else None
                angle = get_multi_angle_matcher().detect_angle(_bbox, _landmarks)
            else:
                angle = FaceAngle.FRONTAL
            
            embedding_list = best_embedding.tolist() if hasattr(best_embedding, "tolist") else best_embedding
            search_resp = requests.post(
                f"{API_BASE_URL}/visitors/search",
                json={
                    "organization_id": org_id,
                    "embedding": embedding_list,
                    "threshold": FACE_SEARCH_THRESHOLD,
                    "angle": angle.value
                },
                headers=_INTERNAL_HEADERS,
                timeout=30,
            )
            if search_resp.status_code == 200:
                result = search_resp.json()
                matched_visitor = result.get("visitor")
                if result.get("matched") and matched_visitor:
                    visitor_id = matched_visitor["id"]
                    confidence = result["confidence"]
                    face_data_id = result.get("face_data_id")
                    angle_scores = result.get("angle_scores", {})
                    status = "identified"
                    people_identified += 1
        except Exception as e:
            print(f"[AI] Search failed: {e}")

        # Liveness check — reject spoofed faces before logging
        try:
            if best_face_img is not None:
                motion_frames = [d.get("frame") for d in dets if d.get("frame") is not None][:10]
                liveness = get_liveness_checker().check(
                    best_face_img,
                    frames=motion_frames if motion_frames else None,
                )
                if not liveness.get("is_live", True):
                    print(
                        f"[AI] Liveness FAILED for track {track_id} "
                        f"(score={liveness.get('score', 0):.2f}, "
                        f"attack={liveness.get('attack_type')})"
                    )
                    # Undo identification
                    if status == "identified":
                        people_identified -= 1
                    visitor_id = None
                    face_data_id = None
                    confidence = 0.0
                    status = "spoof_rejected"
        except Exception as e:
            print(f"[AI] Liveness check error for track {track_id}: {e}")
            # Treat liveness check failure as a spoof rejection to avoid false positives
            if status == "identified":
                people_identified -= 1
            visitor_id = None
            face_data_id = None
            confidence = 0.0
            status = "liveness_error"

        # Log the detection event
        log_payload = {
            "organization_id": org_id,
            "video_snippet_path": video_path,
            "face_image_path": f"face_images/{face_filename}",
            "confidence": confidence if confidence > 0 else 0.0,
            "status": status,
            "identified": status == "identified",
        }
        if visitor_id:
            log_payload["visitor_id"] = visitor_id
        if face_data_id:
            log_payload["face_data_id"] = face_data_id

        try:
            log_resp = requests.post(
                f"{API_BASE_URL}/logs",
                json=log_payload,
                headers=_INTERNAL_HEADERS,
                timeout=10,
            )
            print(f"[AI] Logged track {track_id}: {log_resp.status_code}")
        except Exception as e:
            print(f"[AI] Log failed: {e}")

    return ProcessResult(
        status="completed",
        message=f"Processed {people_detected} people, identified {people_identified}",
        people_detected=people_detected,
        people_identified=people_identified,
    )


@app.post("/embed-face", response_model=EmbedFaceResult)
async def embed_face(req: EmbedFaceRequest):
    """
    Accept an image path, detect faces, validate quality, and return embedding.
    Used by the backend when a user uploads a face photo for a visitor.
    """
    image_path = req.image_path
    if not os.path.exists(image_path):
        return EmbedFaceResult(error="Image file not found on server")

    face_engine = get_face_engine()

    # Read the image
    img = cv2.imread(image_path)
    if img is None:
        return EmbedFaceResult(error="Failed to read image file")

    # Extract faces
    faces = face_engine.extract_face(img)
    face_count = len(faces)

    if face_count == 0:
        return EmbedFaceResult(
            face_count=0,
            error="No face detected in the image",
        )

    if face_count > 1:
        return EmbedFaceResult(
            face_count=face_count,
            error=f"Multiple faces detected ({face_count}). Please upload an image with a single face.",
        )

    # Quality check — compute Laplacian variance as blur metric
    face_data = faces[0]
    face_img = face_data.get("face")
    face_angle = _classify_face_angle(face_data)

    # Convert float [0,1] face to uint8 if needed
    if face_img is not None and face_img.dtype != np.uint8:
        face_img_uint8 = (face_img * 255).astype(np.uint8)
    else:
        face_img_uint8 = face_img

    quality_score = 0.0
    if face_img_uint8 is not None:
        gray = cv2.cvtColor(face_img_uint8, cv2.COLOR_BGR2GRAY) if len(face_img_uint8.shape) == 3 else face_img_uint8
        laplacian_var = cv2.Laplacian(gray, cv2.CV_64F).var()
        # Normalize: <50 is blurry, >200 is sharp — map to 0..1
        quality_score = min(1.0, max(0.0, laplacian_var / 200.0))

    if quality_score < FACE_QUALITY_MIN:
        return EmbedFaceResult(
            face_count=1,
            quality_score=round(quality_score, 4),
            error="Image is too blurry. Please upload a clearer photo.",
        )

    # Generate embedding
    embedding = face_engine.get_embedding(face_img)
    if embedding is None:
        return EmbedFaceResult(
            face_count=1,
            quality_score=round(quality_score, 4),
            error="Failed to generate face embedding",
        )

    return EmbedFaceResult(
        embedding=embedding,
        quality_score=round(quality_score, 4),
        face_count=1,
        face_angle=face_angle,
    )


# ─── Realtime / Live Camera Endpoints ────────────────────────────────────────


class RealtimeDetectRequest(BaseModel):
    frame_data: str  # base64-encoded JPEG


class DetectedFace(BaseModel):
    bbox: Dict[str, Any]
    face_crop_b64: Optional[str] = None
    confidence: float = 0.0


class RealtimeDetectResult(BaseModel):
    faces: List[DetectedFace]


class RealtimeEmbedRequest(BaseModel):
    face_crop_b64: str  # base64-encoded face crop


class RealtimeEmbedResult(BaseModel):
    embedding: Optional[List[float]] = None
    error: Optional[str] = None


class FrameFullProcessRequest(BaseModel):
    frame_data: str  # base64-encoded JPEG


class ProcessedFace(BaseModel):
    bbox: Dict[str, Any]
    embedding: Optional[List[float]] = None
    face_crop_b64: Optional[str] = None
    confidence: float = 0.0
    face_angle: Optional[str] = None


class PersonBox(BaseModel):
    bbox: Dict[str, Any]
    confidence: float = 0.0


class FrameFullProcessResult(BaseModel):
    faces: List[ProcessedFace]
    persons: List[PersonBox] = Field(default_factory=list)
    processing_time_ms: float = 0.0


class PoseEstimateRequest(BaseModel):
    frame_data: str


class PoseEstimateResult(BaseModel):
    status: str
    available: bool
    model: str
    posture: str = "unknown"
    keypoint_count: int = 0
    average_visibility: float = 0.0
    processing_time_ms: float = 0.0
    message: Optional[str] = None


class ActionInferRequest(BaseModel):
    frame_data: str
    track_id: Optional[str] = None


class ActionInferResult(BaseModel):
    status: str
    available: bool
    model: str
    action: str = "unknown"
    gesture: str = "none"
    confidence: float = 0.0
    posture: str = "unknown"
    keypoint_count: int = 0
    processing_time_ms: float = 0.0
    message: Optional[str] = None
    flags: Dict[str, Any] = Field(default_factory=dict)


class RtspProbeRequest(BaseModel):
    rtsp_url: str


class RtspProbeResult(BaseModel):
    connected: bool
    width: int = 0
    height: int = 0
    fps: float = 0.0
    error: Optional[str] = None


class RtspSnapshotRequest(BaseModel):
    rtsp_url: str
    max_width: int = 1280
    jpeg_quality: int = 80


class RtspProcessRequest(BaseModel):
    organization_id: UUID
    rtsp_url: str
    camera_id: Optional[str] = None
    max_frames: int = 300
    frame_stride: int = 5
    max_faces_per_frame: int = 2
    threshold: float = 0.6


class RtspProcessResult(BaseModel):
    status: str
    processed_frames: int = 0
    faces_detected: int = 0
    faces_identified: int = 0
    logs_created: int = 0
    message: Optional[str] = None


class EdgeExportOnnxRequest(BaseModel):
    model_path: str
    input_shape: List[int] = Field(default_factory=lambda: [1, 3, 224, 224])
    output_path: Optional[str] = None
    model_name: Optional[str] = None
    opset_version: int = 13


class EdgeExportOptimizeRequest(BaseModel):
    onnx_path: str
    output_path: Optional[str] = None


class EdgeExportQuantizeRequest(BaseModel):
    model_path: str
    quantization_type: str = "dynamic"
    output_path: Optional[str] = None


class EdgeExportBenchmarkRequest(BaseModel):
    model_path: str
    num_iterations: int = 100
    input_shape: List[int] = Field(default_factory=lambda: [1, 3, 224, 224])


def _decode_frame(frame_data: str) -> Optional[np.ndarray]:
    """Decode a base64-encoded JPEG into a numpy array (BGR)."""
    try:
        # Strip data URI prefix if present
        if "," in frame_data:
            frame_data = frame_data.split(",", 1)[1]
        img_bytes = base64.b64decode(frame_data)
        nparr = np.frombuffer(img_bytes, np.uint8)
        img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        return img
    except Exception as e:
        print(f"[AI] Failed to decode frame: {e}")
        return None


# A host with no route costs a full RTSP_TIMEOUT_MS of SYN retries on every
# attempt. One dashboard tile per camera polling every few seconds then keeps a
# thread blocked per camera indefinitely and writes one warning per poll. Once a
# host has failed, fail its next attempts instantly and re-probe only once per
# TTL, so a camera that comes back is still picked up within that window.
RTSP_UNREACHABLE_TTL_S = float(os.getenv("RTSP_UNREACHABLE_TTL_S", "30"))
_rtsp_unreachable: Dict[Tuple[str, int], float] = {}
_rtsp_unreachable_lock = Lock()


def _rtsp_host_reachable(rtsp_url: str) -> bool:
    """Return True if the stream's host accepts a TCP connection quickly.

    Non-RTSP sources (files, device indices, HTTP) skip the check.
    """
    try:
        parsed = urlparse(rtsp_url)
    except Exception:
        return True
    if parsed.scheme not in ("rtsp", "rtsps"):
        return True
    host = parsed.hostname
    if not host:
        return True
    port = parsed.port or (322 if parsed.scheme == "rtsps" else 554)

    endpoint = (host, port)
    with _rtsp_unreachable_lock:
        retry_at = _rtsp_unreachable.get(endpoint)
        if retry_at is not None and time.monotonic() < retry_at:
            return False

    try:
        with socket.create_connection(endpoint, timeout=RTSP_TIMEOUT_MS / 1000):
            with _rtsp_unreachable_lock:
                _rtsp_unreachable.pop(endpoint, None)
            return True
    except OSError as exc:
        with _rtsp_unreachable_lock:
            _rtsp_unreachable[endpoint] = time.monotonic() + RTSP_UNREACHABLE_TTL_S
        logger.warning(
            "RTSP host %s:%s unreachable: %s (skipping retries for %.0fs)",
            host,
            port,
            exc,
            RTSP_UNREACHABLE_TTL_S,
        )
        return False


def _open_rtsp(rtsp_url: str) -> cv2.VideoCapture:
    """Open an RTSP stream with a bounded connect/read timeout.

    Without these, OpenCV falls back to FFmpeg's 30s stream timeout per
    attempt. A dashboard polling an unreachable camera every couple of
    seconds then stacks blocked calls faster than they drain.
    """
    # FFmpeg's timeouts govern socket I/O, not the TCP connect, so an
    # unreachable host still costs ~30s of SYN retries before OpenCV reports
    # anything. Check reachability ourselves first and fail fast.
    if not _rtsp_host_reachable(rtsp_url):
        return cv2.VideoCapture()  # not opened; callers handle isOpened() == False

    # Construct empty, then set the timeouts, then open — passing the URL to
    # the constructor opens the stream immediately and the properties would
    # arrive too late to bound that first connect.
    cap = cv2.VideoCapture()
    for prop in ("CAP_PROP_OPEN_TIMEOUT_MSEC", "CAP_PROP_READ_TIMEOUT_MSEC"):
        prop_id = getattr(cv2, prop, None)
        if prop_id is not None:
            cap.set(prop_id, RTSP_TIMEOUT_MS)
    cap.open(rtsp_url, cv2.CAP_FFMPEG)
    return cap


def _capture_rtsp_snapshot(rtsp_url: str, max_width: int = 1280, jpeg_quality: int = 80) -> bytes:
    """Capture a single JPEG snapshot from an RTSP stream."""
    cap = _open_rtsp(rtsp_url)
    if not cap.isOpened():
        cap.release()
        raise ValueError("Unable to open RTSP stream")

    try:
        frame = None
        for _ in range(5):
            ok, candidate = cap.read()
            if ok and candidate is not None:
                frame = candidate
                break

        if frame is None:
            raise ValueError("Unable to read a frame from the RTSP stream")

        height, width = frame.shape[:2]
        if max_width and width > max_width:
            scale = max_width / float(width)
            frame = cv2.resize(frame, (max_width, int(height * scale)))

        quality = int(max(30, min(95, jpeg_quality)))
        ok, buf = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), quality])
        if not ok:
            raise ValueError("Failed to encode RTSP snapshot")
        return buf.tobytes()
    finally:
        cap.release()


@app.post("/realtime/detect", response_model=RealtimeDetectResult)
async def realtime_detect(req: RealtimeDetectRequest):
    """Detect faces in a single frame. Returns bounding boxes and face crops."""
    img = _decode_frame(req.frame_data)
    if img is None:
        return RealtimeDetectResult(faces=[])

    face_engine = get_face_engine()
    faces = face_engine.extract_face(img)

    results: List[DetectedFace] = []
    for face_data in faces:
        facial_area = face_data.get("facial_area", {})
        bbox = {
            "x1": int(facial_area.get("x", 0)),
            "y1": int(facial_area.get("y", 0)),
            "x2": int(facial_area.get("x", 0) + facial_area.get("w", 0)),
            "y2": int(facial_area.get("y", 0) + facial_area.get("h", 0)),
        }
        conf = float(face_data.get("confidence", 0.0) or 0.0)

        # Encode face crop as base64
        face_crop_b64 = None
        face_img = face_data.get("face")
        if face_img is not None:
            if face_img.dtype != np.uint8:
                face_img_uint8 = (face_img * 255).astype(np.uint8)
            else:
                face_img_uint8 = face_img
            _, buf = cv2.imencode(".jpg", face_img_uint8)
            face_crop_b64 = base64.b64encode(buf).decode("utf-8")

        results.append(DetectedFace(bbox=bbox, face_crop_b64=face_crop_b64, confidence=conf))

    return RealtimeDetectResult(faces=results)


@app.post("/realtime/embed", response_model=RealtimeEmbedResult)
async def realtime_embed(req: RealtimeEmbedRequest):
    """Generate face embedding from a base64-encoded face crop."""
    try:
        img_bytes = base64.b64decode(req.face_crop_b64)
        nparr = np.frombuffer(img_bytes, np.uint8)
        face_img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        if face_img is None:
            return RealtimeEmbedResult(error="Failed to decode face image")
    except Exception as e:
        return RealtimeEmbedResult(error=str(e))

    face_engine = get_face_engine()
    embedding = face_engine.get_embedding_from_crop(face_img)
    if embedding is None:
        return RealtimeEmbedResult(error="Failed to generate embedding")

    return RealtimeEmbedResult(embedding=embedding)


@app.post("/realtime/frame-full-process", response_model=FrameFullProcessResult)
async def realtime_frame_full_process(req: FrameFullProcessRequest):
    """
    Full pipeline for a single frame:
    1. Decode base64 frame
    2. Detect faces
    3. Generate embeddings for each face
    Returns faces with bboxes, embeddings, and base64 face crops.
    """
    start_time = time.time()
    img = _decode_frame(req.frame_data)
    if img is None:
        elapsed = (time.time() - start_time) * 1000
        return FrameFullProcessResult(faces=[], processing_time_ms=round(elapsed, 1))

    # Downscale before detection to cut latency on high-res frames. Remember the
    # inverse factor so every returned bbox maps back to original-frame coords
    # (the frontend overlays them on the full-res frame). inv_scale==1.0 -> no-op.
    inv_scale = 1.0
    try:
        _max_w = int(os.getenv("REALTIME_MAX_WIDTH", "960"))
    except ValueError:
        _max_w = 960
    if _max_w > 0:
        _oh, _ow = img.shape[:2]
        if _ow > _max_w:
            _s = _max_w / float(_ow)
            img = cv2.resize(img, (_max_w, int(round(_oh * _s))))
            inv_scale = 1.0 / _s

    # Person/body detection (white box stage). Best-effort: if YOLO is
    # unavailable the live pipeline still returns faces.
    persons: List[PersonBox] = []
    try:
        for person in get_tracker().detect_persons(img):
            persons.append(PersonBox(
                bbox={
                    "x1": int(person["x1"] * inv_scale),
                    "y1": int(person["y1"] * inv_scale),
                    "x2": int(person["x2"] * inv_scale),
                    "y2": int(person["y2"] * inv_scale),
                },
                confidence=person["confidence"],
            ))
    except Exception as exc:
        print(f"[AI] Person detection skipped: {exc}")

    face_engine = get_face_engine()
    detected_faces = face_engine.extract_face(img)

    results: List[ProcessedFace] = []
    for face_data in detected_faces:
        facial_area = face_data.get("facial_area", {})
        bbox = {
            "x1": int(facial_area.get("x", 0) * inv_scale),
            "y1": int(facial_area.get("y", 0) * inv_scale),
            "x2": int((facial_area.get("x", 0) + facial_area.get("w", 0)) * inv_scale),
            "y2": int((facial_area.get("y", 0) + facial_area.get("h", 0)) * inv_scale),
        }
        conf = float(face_data.get("confidence", 0.0) or 0.0)
        face_angle = _classify_face_angle(face_data)

        face_img = face_data.get("face")
        embedding = None
        face_crop_b64 = None

        if face_img is not None:
            # Convert to uint8 if needed
            if face_img.dtype != np.uint8:
                face_img_uint8 = (face_img * 255).astype(np.uint8)
            else:
                face_img_uint8 = face_img

            # Encode crop as base64
            _, buf = cv2.imencode(".jpg", face_img_uint8)
            face_crop_b64 = base64.b64encode(buf).decode("utf-8")

            # Generate embedding from the crop
            embedding = face_engine.get_embedding_from_crop(face_img_uint8)

        results.append(ProcessedFace(
            bbox=bbox,
            embedding=embedding,
            face_crop_b64=face_crop_b64,
            confidence=conf,
            face_angle=face_angle,
        ))

    elapsed = (time.time() - start_time) * 1000
    return FrameFullProcessResult(
        faces=results,
        persons=persons,
        processing_time_ms=round(elapsed, 1),
    )


@app.post("/realtime/pose-estimate", response_model=PoseEstimateResult)
async def realtime_pose_estimate(req: PoseEstimateRequest):
    img = _decode_frame(req.frame_data)
    pose_config = get_runtime_component("pose_estimation")
    pose_engine = get_pose_estimator()

    if img is None:
        return PoseEstimateResult(
            status="error",
            available=pose_engine.available,
            model=pose_config.get("current_model", "unknown"),
            message="Failed to decode frame",
        )

    result = pose_engine.estimate(img)
    return PoseEstimateResult(
        status=result.get("status", "ok"),
        available=bool(result.get("available", False)),
        model=pose_config.get("current_model", "unknown"),
        posture=result.get("posture", "unknown"),
        keypoint_count=int(result.get("keypoint_count", 0) or 0),
        average_visibility=float(result.get("average_visibility", 0.0) or 0.0),
        processing_time_ms=float(result.get("processing_time_ms", 0.0) or 0.0),
        message=result.get("message"),
    )


@app.post("/realtime/action-infer", response_model=ActionInferResult)
async def realtime_action_infer(req: ActionInferRequest):
    img = _decode_frame(req.frame_data)
    action_config = get_runtime_component("action_gesture_inference")
    action_engine = get_action_inference()

    if img is None:
        return ActionInferResult(
            status="error",
            available=action_engine.available,
            model=action_config.get("current_model", "unknown"),
            message="Failed to decode frame",
        )

    result = action_engine.infer(img, track_id=req.track_id)
    pose_info = result.get("pose", {}) if isinstance(result.get("pose"), dict) else {}
    return ActionInferResult(
        status=result.get("status", "ok"),
        available=bool(result.get("available", False)),
        model=action_config.get("current_model", "unknown"),
        action=result.get("action", "unknown"),
        gesture=result.get("gesture", "none"),
        confidence=float(result.get("confidence", 0.0) or 0.0),
        posture=pose_info.get("posture", "unknown"),
        keypoint_count=int(pose_info.get("keypoint_count", 0) or 0),
        processing_time_ms=float(result.get("processing_time_ms", 0.0) or 0.0),
        message=result.get("message"),
        flags=result.get("flags", {}),
    )


@app.post("/realtime/rtsp-probe", response_model=RtspProbeResult)
async def realtime_rtsp_probe(req: RtspProbeRequest):
    def _probe():
        cap = _open_rtsp(req.rtsp_url)
        if not cap.isOpened():
            cap.release()
            return None
        try:
            ok, frame = cap.read()
            return (
                ok,
                frame,
                int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0),
                int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0),
                float(cap.get(cv2.CAP_PROP_FPS) or 0.0),
            )
        finally:
            cap.release()

    probed = await asyncio.to_thread(_probe)
    if probed is None:
        return RtspProbeResult(connected=False, error="Unable to open RTSP stream")
    ok, frame, width, height, fps = probed

    if not ok or frame is None:
        return RtspProbeResult(
            connected=False,
            width=width,
            height=height,
            fps=fps,
            error="Stream opened but no frames were received",
        )

    return RtspProbeResult(connected=True, width=width, height=height, fps=fps)


@app.post("/realtime/rtsp-snapshot")
async def realtime_rtsp_snapshot(req: RtspSnapshotRequest):
    try:
        # Off the event loop: cv2 blocks, and an unreachable camera would
        # otherwise stall every other request this service is serving.
        snapshot = await asyncio.to_thread(
            _capture_rtsp_snapshot,
            req.rtsp_url,
            req.max_width,
            req.jpeg_quality,
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    return Response(
        content=snapshot,
        media_type="image/jpeg",
        headers={"Cache-Control": "no-store"},
    )


@app.post("/realtime/rtsp-process", response_model=RtspProcessResult)
def realtime_rtsp_process(req: RtspProcessRequest):
    # Sync on purpose: the whole body is blocking cv2 + inference work with no
    # awaits, so FastAPI runs it in its threadpool instead of on the loop.
    face_engine = get_face_engine()
    org_id = str(req.organization_id)

    cap = _open_rtsp(req.rtsp_url)
    if not cap.isOpened():
        cap.release()
        return RtspProcessResult(status="error", message="Unable to open RTSP stream")

    os.makedirs(FACE_IMAGE_DIR, exist_ok=True)

    frame_idx = 0
    processed_frames = 0
    faces_detected = 0
    faces_identified = 0
    logs_created = 0

    try:
        while frame_idx < max(1, req.max_frames):
            ok, frame = cap.read()
            if not ok or frame is None:
                break

            frame_idx += 1
            if req.frame_stride > 1 and (frame_idx % req.frame_stride) != 0:
                continue

            processed_frames += 1
            detected_faces = face_engine.extract_face(frame)
            if not detected_faces:
                continue

            for face_data in detected_faces[: max(1, req.max_faces_per_frame)]:
                face_img = face_data.get("face")
                if face_img is None:
                    continue

                embedding = face_engine.get_embedding_from_crop(face_img)
                if embedding is None:
                    continue

                faces_detected += 1
                visitor_id = None
                face_data_id = None
                confidence = 0.0
                status = "unidentified"

                try:
                    embedding_list = embedding.tolist() if hasattr(embedding, "tolist") else embedding
                    search_resp = requests.post(
                        f"{API_BASE_URL}/visitors/search",
                        json={
                            "organization_id": org_id,
                            "embedding": embedding_list,
                            "threshold": req.threshold,
                        },
                        headers=_INTERNAL_HEADERS,
                        timeout=15,
                    )
                    if search_resp.status_code == 200:
                        result = search_resp.json()
                        matched_visitor = result.get("visitor")
                        if result.get("matched") and matched_visitor:
                            visitor_id = matched_visitor["id"]
                            confidence = float(result.get("confidence") or 0.0)
                            face_data_id = result.get("face_data_id")
                            status = "identified"
                            faces_identified += 1
                except Exception as exc:
                    print(f"[AI] RTSP search failed: {exc}")

                if face_img.dtype != np.uint8:
                    face_img_save = (face_img * 255).astype(np.uint8)
                else:
                    face_img_save = face_img

                # Liveness check — reject spoofed faces
                try:
                    liveness = get_liveness_checker().check(face_img_save)
                    if not liveness.get("is_live", True):
                        print(
                            f"[AI] RTSP liveness FAILED frame {frame_idx} "
                            f"(score={liveness.get('score', 0):.2f}, "
                            f"attack={liveness.get('attack_type')})"
                        )
                        if status == "identified":
                            faces_identified -= 1
                        visitor_id = None
                        face_data_id = None
                        confidence = 0.0
                        status = "spoof_rejected"
                except Exception as exc:
                    print(f"[AI] RTSP liveness error frame {frame_idx}: {exc}")

                filename = f"rtsp_{int(time.time())}_{frame_idx}.jpg"
                file_path = os.path.join(FACE_IMAGE_DIR, filename)
                cv2.imwrite(file_path, face_img_save)

                payload = {
                    "organization_id": org_id,
                    "camera_id": req.camera_id,
                    "face_image_path": f"face_images/{filename}",
                    "video_snippet_path": req.rtsp_url,
                    "source_video": "rtsp_live",
                    "track_id": frame_idx,
                    "confidence": confidence,
                    "status": status,
                    "identified": status == "identified",
                }
                if visitor_id:
                    payload["visitor_id"] = visitor_id
                if face_data_id:
                    payload["face_data_id"] = face_data_id

                try:
                    log_resp = requests.post(
                        f"{API_BASE_URL}/logs",
                        json=payload,
                        headers=_INTERNAL_HEADERS,
                        timeout=10,
                    )
                    if log_resp.status_code in (200, 201):
                        logs_created += 1
                except Exception as exc:
                    print(f"[AI] RTSP log failed: {exc}")
    finally:
        cap.release()

    return RtspProcessResult(
        status="completed",
        processed_frames=processed_frames,
        faces_detected=faces_detected,
        faces_identified=faces_identified,
        logs_created=logs_created,
        message="RTSP stream processing finished",
    )


# ─── Continuous RTSP Stream Management Endpoints ─────────────────────────────


class StartStreamRequest(BaseModel):
    organization_id: UUID
    rtsp_url: str
    camera_id: Optional[str] = None
    frame_stride: int = 5
    max_faces_per_frame: int = 4
    threshold: float = 0.6
    target_fps: float = 5.0


class StopStreamRequest(BaseModel):
    stream_id: str


@app.post("/streams/start")
async def start_stream(req: StartStreamRequest):
    """
    Start a continuous RTSP stream for a camera.
    The stream runs in the background, continuously processing frames,
    detecting faces, matching visitors, and creating logs.
    """
    manager = get_rtsp_manager()

    # Use camera_id as stream_id if provided, otherwise generate one
    stream_id = req.camera_id or f"stream_{str(req.organization_id)[:8]}_{int(time.time())}"

    from rtsp_manager import StreamConfig
    config = StreamConfig(
        rtsp_url=req.rtsp_url,
        organization_id=str(req.organization_id),
        camera_id=req.camera_id,
        frame_stride=req.frame_stride,
        max_faces_per_frame=req.max_faces_per_frame,
        threshold=req.threshold,
        target_fps=req.target_fps,
    )

    info = manager.start_stream(stream_id, config)
    return {"status": "started", "stream": info}


@app.post("/streams/stop")
async def stop_stream(req: StopStreamRequest):
    """Stop a running RTSP stream."""
    manager = get_rtsp_manager()
    info = manager.stop_stream(req.stream_id)
    if info is None:
        return {"status": "error", "message": f"Stream {req.stream_id} not found"}
    return {"status": "stopped", "stream": info}


@app.get("/streams/{stream_id}")
async def get_stream_status(stream_id: str):
    """Get the status and stats of a specific RTSP stream."""
    manager = get_rtsp_manager()
    info = manager.get_stream_status(stream_id)
    if info is None:
        return {"status": "error", "message": f"Stream {stream_id} not found"}
    return info


@app.get("/streams")
async def list_streams():
    """List all RTSP streams and their statuses."""
    manager = get_rtsp_manager()
    return {"streams": manager.list_streams()}


@app.post("/streams/stop-all")
async def stop_all_streams():
     """Stop all running RTSP streams."""
     manager = get_rtsp_manager()
     manager.stop_all()
     return {"status": "all_stopped", "streams": manager.list_streams()}


class AugmentFaceRequest(BaseModel):
    image_path: str
    num_variants: int = 5
    techniques: List[str] = ["rotate", "flip", "jitter", "erase"]


class AugmentFaceResult(BaseModel):
    augmented_paths: List[str] = []
    error: Optional[str] = None


class XAIRequest(BaseModel):
    image_path: str


class XAIExplanation(BaseModel):
    heatmap_path: Optional[str] = None
    feature_importance: Dict[str, float] = {}
    decision_factors: List[Dict[str, Any]] = []
    error: Optional[str] = None


@app.post("/xai/explain", response_model=XAIExplanation)
async def explain_face(req: XAIRequest):
    """
    US-FUT-015: Explainable AI endpoint.
    Generates a heatmap and importance metrics for a given face image.
    """
    image_path = req.image_path
    if not os.path.exists(image_path):
        return XAIExplanation(error=f"Image not found: {image_path}")

    img = cv2.imread(image_path)
    if img is None:
        return XAIExplanation(error="Failed to read image")

    xai = get_xai_manager()
    
    # 1. Generate Heatmap
    heatmap_img = xai.generate_heatmap(img)
    base_dir = os.path.dirname(image_path)
    base_name = os.path.splitext(os.path.basename(image_path))[0]
    heatmap_filename = f"{base_name}_xai_heatmap.jpg"
    heatmap_path = os.path.join(base_dir, heatmap_filename)
    cv2.imwrite(heatmap_path, heatmap_img)
    
    # 2. Get feature importance and decision factors from active XAI backend
    importance = xai.get_feature_importance()
    factors = xai.explain_decision(0.85, 0.6)
    
    return XAIExplanation(
        heatmap_path=f"face_images/{heatmap_filename}",
        feature_importance=importance,
        decision_factors=factors
    )


@app.post("/augment-face", response_model=AugmentFaceResult)
async def augment_face(req: AugmentFaceRequest):
    """
    Generate augmented variants of a face image.
    Used for improving training diversity.
    """
    image_path = req.image_path
    if not os.path.exists(image_path):
        return AugmentFaceResult(error=f"Image not found: {image_path}")

    img = cv2.imread(image_path)
    if img is None:
        return AugmentFaceResult(error="Failed to read image")

    augmenter = get_augmenter()
    augmented_paths = []
    
    base_dir = os.path.dirname(image_path)
    base_name = os.path.splitext(os.path.basename(image_path))[0]
    ext = os.path.splitext(image_path)[1]

    for i in range(req.num_variants):
        aug_img = augmenter.apply_augmentation_pipeline(img, req.techniques)
        aug_filename = f"{base_name}_aug_{i}{ext}"
        aug_path = os.path.join(base_dir, aug_filename)
        cv2.imwrite(aug_path, aug_img)
        augmented_paths.append(aug_path)

    return AugmentFaceResult(augmented_paths=augmented_paths)


@app.post("/edge/export/onnx")
async def edge_export_onnx(req: EdgeExportOnnxRequest) -> Dict[str, Any]:
    model_path = resolve_input_path(req.model_path)
    if not os.path.exists(model_path):
        raise HTTPException(status_code=404, detail=f"Model not found: {model_path}")

    try:
        model = _load_torch_model(model_path)
        input_shape = _normalize_input_shape(req.input_shape)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    model_stem = os.path.splitext(os.path.basename(model_path))[0]
    output_path = req.output_path or f"{model_stem}.onnx"
    try:
        output_path = _validate_relative_output_path(output_path)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    result = edge_export_service.export_to_onnx(
        model=model,
        input_shape=input_shape,
        output_path=output_path,
        model_name=req.model_name or model_stem,
        opset_version=req.opset_version,
    )
    if not result.get("success", True):
        logger.warning("Edge export failed: %s", result.get("error"))
    return _wrap_edge_result(result)


@app.post("/edge/export/optimize")
async def edge_export_optimize(req: EdgeExportOptimizeRequest) -> Dict[str, Any]:
    onnx_path = resolve_input_path(req.onnx_path)
    if not os.path.exists(onnx_path):
        raise HTTPException(status_code=404, detail=f"ONNX file not found: {onnx_path}")

    output_path = req.output_path or f"{os.path.splitext(os.path.basename(onnx_path))[0]}_opt.onnx"
    try:
        output_path = _validate_relative_output_path(output_path)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    result = edge_export_service.optimize_onnx(onnx_path, output_path)
    if not result.get("success", True):
        logger.warning("ONNX optimize failed: %s", result.get("error"))
    return _wrap_edge_result(result)


@app.post("/edge/export/quantize")
async def edge_export_quantize(req: EdgeExportQuantizeRequest) -> Dict[str, Any]:
    model_path = resolve_input_path(req.model_path)
    if not os.path.exists(model_path):
        raise HTTPException(status_code=404, detail=f"Model not found: {model_path}")

    if req.output_path:
        try:
            output_rel = _validate_relative_output_path(req.output_path)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        output_path = os.path.join(EXPORT_DIR, output_rel)
    else:
        base, ext = os.path.splitext(os.path.basename(model_path))
        output_path = os.path.join(EXPORT_DIR, f"{base}_quantized{ext or '.onnx'}")

    result = edge_export_service.quantize_model(
        model_path,
        quantization_type=req.quantization_type,
        output_path=output_path,
    )
    if not result.get("success", True):
        logger.warning("Quantization failed: %s", result.get("error"))
    return _wrap_edge_result(result)


@app.post("/edge/export/benchmark")
async def edge_export_benchmark(req: EdgeExportBenchmarkRequest) -> Dict[str, Any]:
    model_path = resolve_input_path(req.model_path)
    if not os.path.exists(model_path):
        raise HTTPException(status_code=404, detail=f"Model not found: {model_path}")

    try:
        input_shape = _normalize_input_shape(req.input_shape)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    result = edge_export_service.benchmark_edge_model(
        model_path,
        num_iterations=req.num_iterations,
        input_shape=input_shape,
    )
    return _wrap_edge_result(result)


@app.get("/edge/export/info")
async def edge_export_info(model_path: str) -> Dict[str, Any]:
    resolved_path = resolve_input_path(model_path)
    if not os.path.exists(resolved_path):
        raise HTTPException(status_code=404, detail=f"Model not found: {resolved_path}")
    result = edge_export_service.get_model_info(resolved_path)
    return _wrap_edge_result(result)


@app.get("/edge/export/exports")
async def edge_export_exports() -> Dict[str, Any]:
    return {"success": True, "models": edge_export_service.list_exported_models()}


if __name__ == "__main__":
    reload_enabled = os.getenv("AI_SERVICE_RELOAD", "false").lower() in {"1", "true", "yes", "on"}
    uvicorn.run("processor:app", host="0.0.0.0", port=8001, reload=reload_enabled)
