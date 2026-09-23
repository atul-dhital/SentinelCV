import cv2
from ultralytics import YOLO
import logging
import os
import time
import json
import numpy as np
import requests
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from runtime_registry import get_runtime_component

try:
    import supervision as sv
except ImportError:  # pragma: no cover - dependency may be absent in old local envs
    sv = None


logger = logging.getLogger("sentinelcv.person_tracker")

AI_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(AI_DIR)
DATA_DIR = os.getenv("DATA_DIR", os.path.join(PROJECT_ROOT, "backend", "data"))


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


class PersonTracker:
    def __init__(self, model_path: Optional[str] = None, model_name: Optional[str] = None):
        """Initialize YOLO-based person tracker (YOLOv8/YOLO11 compatible)."""
        detector_config = get_runtime_component("person_detector")
        tracker_config = get_runtime_component("person_tracker")
        self.model_name = model_name or detector_config.get("current_model", "YOLOv8n")
        requested_path = model_path or detector_config.get("current_artifact", "yolov8n.pt")
        resolved_path, resolved_name = self._resolve_model_path(requested_path)
        if resolved_name:
            self.model_name = resolved_name
        self.model_path = resolved_path
        self.tracker_backend = tracker_config.get("current_model", "ByteTrack")
        self.model = YOLO(self.model_path)
        self.device = self._resolve_device()
        self._fallback_notice_emitted = False
        self._secondary_warning_emitted = False
        self._secondary_cooldown_until = 0.0
        self._detect_frame_count = 0

        self.detector_mode = str(
            os.getenv(
                "PERSON_DETECTOR_MODE",
                detector_config.get("mode") or detector_config.get("detector_mode") or "yolo_only",
            )
        ).strip().lower()
        self.secondary_model = str(
            os.getenv(
                "PERSON_SECONDARY_MODEL",
                detector_config.get("secondary_model") or "rfdetr-nano",
            )
        ).strip()
        self.secondary_inference_url = str(
            os.getenv(
                "PERSON_SECONDARY_INFERENCE_URL",
                detector_config.get("secondary_inference_url") or "",
            )
        ).strip()
        self.secondary_image_field = str(os.getenv("PERSON_SECONDARY_IMAGE_FIELD", "file")).strip() or "file"
        self.secondary_timeout_seconds = _env_float("PERSON_SECONDARY_TIMEOUT_SECONDS", 0.6)
        self.secondary_cooldown_seconds = _env_float("PERSON_SECONDARY_COOLDOWN_SECONDS", 30.0)
        self.secondary_every_n_frames = max(0, _env_int("PERSON_SECONDARY_EVERY_N_FRAMES", 10))
        self.secondary_trigger_confidence = _env_float("PERSON_SECONDARY_TRIGGER_CONFIDENCE", 0.65)
        self.fusion_iou_threshold = _env_float("PERSON_FUSION_IOU_THRESHOLD", 0.5)
        self.distillation_capture_enabled = _env_bool("PERSON_DISTILLATION_CAPTURE", False)
        self.distillation_dir = Path(
            os.getenv(
                "PERSON_DISTILLATION_DIR",
                os.path.join(DATA_DIR, "person_detector_distillation"),
            )
        )
        self.distillation_source = os.getenv("PERSON_DISTILLATION_SOURCE", "live")
        self.distillation_max_per_run = max(0, _env_int("PERSON_DISTILLATION_MAX_PER_RUN", 200))
        self.distillation_min_interval_seconds = max(
            0.0,
            _env_float("PERSON_DISTILLATION_MIN_INTERVAL_SECONDS", 2.0),
        )
        self._distillation_captured_count = 0
        self._distillation_last_capture_at = 0.0

    @staticmethod
    def _resolve_device() -> str:
        """Pick the YOLO inference device. Env YOLO_DEVICE wins (e.g. "0", "cpu");
        otherwise use CUDA GPU 0 when a CUDA torch build sees a GPU, else CPU."""
        env_device = os.getenv("YOLO_DEVICE", "").strip()
        if env_device:
            return env_device
        try:
            import torch

            if torch.cuda.is_available():
                return "0"
        except Exception:
            pass
        return "cpu"

    def _resolve_model_path(self, requested_path: str) -> Tuple[str, Optional[str]]:
        ai_dir = os.path.dirname(os.path.abspath(__file__))
        candidates = []
        if requested_path:
            candidates.extend([
                requested_path,
                os.path.join(ai_dir, requested_path),
            ])

        fallback_names = ["yolo26n.pt", "yolo11n.pt", "yolov8n.pt"]
        project_root = os.path.dirname(ai_dir)
        models_dir = os.path.join(project_root, "models")

        for name in fallback_names:
            candidates.extend([
                name,
                os.path.join(ai_dir, name),
                os.path.join(models_dir, name),
            ])

        if requested_path:
            candidates.extend([
                os.path.join(DATA_DIR, requested_path),
                os.path.join(project_root, "backend", "data", requested_path),
                os.path.join(models_dir, os.path.basename(requested_path)),
            ])

        for candidate in candidates:
            if candidate and os.path.exists(candidate):
                return candidate, self._infer_model_name(candidate)

        return requested_path, None

    @staticmethod
    def _infer_model_name(path_value: str) -> Optional[str]:
        filename = os.path.basename(path_value).lower()
        if "yolo26" in filename:
            return "YOLO26n"
        if "yolo11" in filename:
            return "YOLO11n"
        if "yolov8" in filename:
            return "YOLOv8n"
        return None

    @staticmethod
    def _compute_iou(box_a, box_b):
        """Compute IoU between two XYXY boxes."""
        ax1, ay1, ax2, ay2 = box_a
        bx1, by1, bx2, by2 = box_b

        inter_x1 = max(ax1, bx1)
        inter_y1 = max(ay1, by1)
        inter_x2 = min(ax2, bx2)
        inter_y2 = min(ay2, by2)

        inter_w = max(0, inter_x2 - inter_x1)
        inter_h = max(0, inter_y2 - inter_y1)
        inter_area = inter_w * inter_h

        area_a = max(0, ax2 - ax1) * max(0, ay2 - ay1)
        area_b = max(0, bx2 - bx1) * max(0, by2 - by1)
        union = area_a + area_b - inter_area
        if union <= 0:
            return 0.0
        return inter_area / union

    def _assign_fallback_ids(self, boxes, previous_tracks, next_track_id, iou_threshold=0.3):
        """Assign stable-ish IDs when the tracking backend is unavailable."""
        current_tracks = {}
        assigned_ids = []
        used_previous_ids = set()

        for box in boxes:
            best_track_id = None
            best_iou = iou_threshold

            for track_id, prev_box in previous_tracks.items():
                if track_id in used_previous_ids:
                    continue
                iou = self._compute_iou(box, prev_box)
                if iou > best_iou:
                    best_iou = iou
                    best_track_id = track_id

            if best_track_id is None:
                best_track_id = next_track_id
                next_track_id += 1

            used_previous_ids.add(best_track_id)
            current_tracks[best_track_id] = box
            assigned_ids.append(best_track_id)

        return assigned_ids, current_tracks, next_track_id

    @staticmethod
    def _detections_from_result(result, conf_threshold: float = 0.3):
        """Return filtered boxes/confs/tracker IDs from an Ultralytics result."""
        if sv is not None:
            detections = sv.Detections.from_ultralytics(result)
            if len(detections) == 0:
                return np.empty((0, 4), dtype=int), np.empty((0,), dtype=float), None
            if detections.confidence is not None:
                detections = detections[detections.confidence >= conf_threshold]
            if len(detections) == 0:
                return np.empty((0, 4), dtype=int), np.empty((0,), dtype=float), None
            boxes = detections.xyxy.astype(int)
            confs = (
                detections.confidence.astype(float)
                if detections.confidence is not None
                else np.ones((len(detections),), dtype=float)
            )
            ids = detections.tracker_id.astype(int) if detections.tracker_id is not None else None
            return boxes, confs, ids

        boxes_data = result.boxes
        if boxes_data is None or len(boxes_data) == 0:
            return np.empty((0, 4), dtype=int), np.empty((0,), dtype=float), None

        boxes = boxes_data.xyxy.cpu().numpy().astype(int)
        confs = boxes_data.conf.cpu().numpy()
        keep = confs >= conf_threshold
        boxes = boxes[keep]
        confs = confs[keep]
        ids = None
        if boxes_data.id is not None:
            ids = boxes_data.id.cpu().numpy().astype(int)[keep]
        return boxes, confs, ids

    def _secondary_enabled(self) -> bool:
        if self.detector_mode not in {"fallback_fusion", "fusion_fallback"}:
            return False
        if not self.secondary_inference_url:
            return False
        return time.time() >= self._secondary_cooldown_until

    def _should_run_secondary(self, yolo_persons: List[Dict[str, Any]], frame_index: Optional[int] = None) -> bool:
        if not self._secondary_enabled():
            return False
        if not yolo_persons:
            return True

        best_confidence = max(float(person.get("confidence") or 0.0) for person in yolo_persons)
        if best_confidence < self.secondary_trigger_confidence:
            return True

        if self.secondary_every_n_frames > 0:
            idx = frame_index if frame_index is not None else self._detect_frame_count
            return idx > 0 and idx % self.secondary_every_n_frames == 0

        return False

    @staticmethod
    def _person_dict_from_box(box, confidence: float, source: str) -> Dict[str, Any]:
        x1, y1, x2, y2 = [int(value) for value in box]
        return {
            "x1": x1,
            "y1": y1,
            "x2": x2,
            "y2": y2,
            "confidence": float(confidence),
            "source": source,
        }

    @staticmethod
    def _prediction_is_person(prediction: Dict[str, Any]) -> bool:
        label = next(
            (
                prediction.get(key)
                for key in ("class", "class_name", "label", "name")
                if prediction.get(key) is not None
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
        class_id = prediction.get("class_id")
        try:
            return int(class_id) == 0
        except (TypeError, ValueError):
            return False

    @staticmethod
    def _prediction_confidence(prediction: Dict[str, Any]) -> float:
        raw = prediction.get("confidence", prediction.get("score", prediction.get("probability", 0.0)))
        try:
            return float(raw)
        except (TypeError, ValueError):
            return 0.0

    @staticmethod
    def _prediction_box_xyxy(prediction: Dict[str, Any]) -> Optional[Tuple[int, int, int, int]]:
        xyxy = prediction.get("xyxy") or prediction.get("box_xyxy")
        if isinstance(xyxy, (list, tuple)) and len(xyxy) == 4:
            return tuple(int(round(float(value))) for value in xyxy)

        box = prediction.get("bbox") or prediction.get("box")
        if isinstance(box, dict):
            if all(key in box for key in ("x1", "y1", "x2", "y2")):
                return (
                    int(round(float(box["x1"]))),
                    int(round(float(box["y1"]))),
                    int(round(float(box["x2"]))),
                    int(round(float(box["y2"]))),
                )
            if all(key in box for key in ("x", "y", "width", "height")):
                x = float(box["x"])
                y = float(box["y"])
                width = float(box["width"])
                height = float(box["height"])
                return (
                    int(round(x - width / 2.0)),
                    int(round(y - height / 2.0)),
                    int(round(x + width / 2.0)),
                    int(round(y + height / 2.0)),
                )
        elif isinstance(box, (list, tuple)) and len(box) == 4:
            return tuple(int(round(float(value))) for value in box)

        if all(key in prediction for key in ("x", "y", "width", "height")):
            x = float(prediction["x"])
            y = float(prediction["y"])
            width = float(prediction["width"])
            height = float(prediction["height"])
            return (
                int(round(x - width / 2.0)),
                int(round(y - height / 2.0)),
                int(round(x + width / 2.0)),
                int(round(y + height / 2.0)),
            )

        return None

    @staticmethod
    def _extract_prediction_list(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
        candidates = [
            payload.get("predictions"),
            payload.get("detections"),
            (payload.get("result") or {}).get("predictions") if isinstance(payload.get("result"), dict) else None,
            (payload.get("outputs") or {}).get("predictions") if isinstance(payload.get("outputs"), dict) else None,
        ]
        for candidate in candidates:
            if isinstance(candidate, list):
                return [item for item in candidate if isinstance(item, dict)]
        return []

    def _parse_secondary_payload(
        self,
        payload: Dict[str, Any],
        conf_threshold: float,
    ) -> List[Dict[str, Any]]:
        people = []
        for prediction in self._extract_prediction_list(payload):
            if not self._prediction_is_person(prediction):
                continue
            confidence = self._prediction_confidence(prediction)
            if confidence < conf_threshold:
                continue
            box = self._prediction_box_xyxy(prediction)
            if box is None:
                continue
            people.append(self._person_dict_from_box(box, confidence, self.secondary_model))
        return people

    def _run_secondary_detector(self, frame, conf_threshold: float) -> List[Dict[str, Any]]:
        ok, encoded = cv2.imencode(".jpg", frame)
        if not ok:
            return []

        params = {"model_id": self.secondary_model}
        api_key = os.getenv("ROBOFLOW_API_KEY", "").strip()
        if api_key:
            params["api_key"] = api_key

        data = {
            "model_id": self.secondary_model,
            "confidence": str(conf_threshold),
            "classes": "person",
        }
        files = {
            self.secondary_image_field: (
                "frame.jpg",
                encoded.tobytes(),
                "image/jpeg",
            )
        }

        try:
            response = requests.post(
                self.secondary_inference_url,
                params=params,
                data=data,
                files=files,
                timeout=self.secondary_timeout_seconds,
            )
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, dict):
                return []
            return self._parse_secondary_payload(payload, conf_threshold)
        except Exception as exc:
            self._secondary_cooldown_until = time.time() + self.secondary_cooldown_seconds
            if not self._secondary_warning_emitted:
                logger.warning(
                    "Secondary person detector unavailable; YOLO-only mode until cooldown expires: %s",
                    exc,
                )
                self._secondary_warning_emitted = True
            return []

    def _merge_persons(
        self,
        primary: List[Dict[str, Any]],
        secondary: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        merged = [dict(person) for person in primary]
        for candidate in sorted(secondary, key=lambda item: float(item.get("confidence") or 0.0), reverse=True):
            candidate_box = [candidate["x1"], candidate["y1"], candidate["x2"], candidate["y2"]]
            best_index = None
            best_iou = self.fusion_iou_threshold
            for index, existing in enumerate(merged):
                existing_box = [existing["x1"], existing["y1"], existing["x2"], existing["y2"]]
                iou = self._compute_iou(candidate_box, existing_box)
                if iou > best_iou:
                    best_index = index
                    best_iou = iou

            if best_index is None:
                merged.append(dict(candidate))
                continue

            existing = merged[best_index]
            if float(candidate.get("confidence") or 0.0) > float(existing.get("confidence") or 0.0):
                updated = dict(candidate)
            else:
                updated = dict(existing)
            updated["source"] = f"{existing.get('source', 'yolo')}+{candidate.get('source', self.secondary_model)}"
            updated["fusion_iou"] = float(best_iou)
            merged[best_index] = updated
        return merged

    @staticmethod
    def _persons_to_arrays(persons: List[Dict[str, Any]]):
        boxes = np.array(
            [[person["x1"], person["y1"], person["x2"], person["y2"]] for person in persons],
            dtype=int,
        )
        confs = np.array([float(person.get("confidence") or 0.0) for person in persons], dtype=float)
        return boxes, confs

    @staticmethod
    def _clamp_person_box(person: Dict[str, Any], width: int, height: int) -> Optional[Tuple[int, int, int, int]]:
        x1 = max(0, min(width - 1, int(person.get("x1", 0))))
        y1 = max(0, min(height - 1, int(person.get("y1", 0))))
        x2 = max(0, min(width - 1, int(person.get("x2", 0))))
        y2 = max(0, min(height - 1, int(person.get("y2", 0))))
        if x2 <= x1 or y2 <= y1:
            return None
        return x1, y1, x2, y2

    @staticmethod
    def _yolo_label_line(box: Tuple[int, int, int, int], width: int, height: int) -> str:
        x1, y1, x2, y2 = box
        x_center = ((x1 + x2) / 2.0) / width
        y_center = ((y1 + y2) / 2.0) / height
        box_width = (x2 - x1) / width
        box_height = (y2 - y1) / height
        return f"0 {x_center:.6f} {y_center:.6f} {box_width:.6f} {box_height:.6f}"

    def _write_distillation_yaml(self) -> None:
        data_yaml = self.distillation_dir / "data.yaml"
        if data_yaml.exists():
            return
        data_yaml.write_text(
            "\n".join([
                f"path: {self.distillation_dir.as_posix()}",
                "train: images",
                "val: images",
                "names:",
                "  0: person",
                "",
            ]),
            encoding="utf-8",
        )

    def _capture_distillation_frame(
        self,
        frame,
        primary: List[Dict[str, Any]],
        secondary: List[Dict[str, Any]],
        fused: List[Dict[str, Any]],
        reason: str,
        frame_index: Optional[int] = None,
    ) -> None:
        if not self.distillation_capture_enabled:
            return
        if self.distillation_max_per_run and self._distillation_captured_count >= self.distillation_max_per_run:
            return
        now = time.time()
        if (now - self._distillation_last_capture_at) < self.distillation_min_interval_seconds:
            return
        if frame is None or not fused:
            return

        height, width = frame.shape[:2]
        labels = []
        for person in fused:
            box = self._clamp_person_box(person, width, height)
            if box is None:
                continue
            labels.append(self._yolo_label_line(box, width, height))
        if not labels:
            return

        images_dir = self.distillation_dir / "images"
        labels_dir = self.distillation_dir / "labels"
        review_dir = self.distillation_dir / "review"
        images_dir.mkdir(parents=True, exist_ok=True)
        labels_dir.mkdir(parents=True, exist_ok=True)
        review_dir.mkdir(parents=True, exist_ok=True)
        self._write_distillation_yaml()

        stamp = time.strftime("%Y%m%d_%H%M%S", time.localtime(now))
        frame_suffix = frame_index if frame_index is not None else self._detect_frame_count
        stem = f"person_{stamp}_{int((now % 1) * 1000):03d}_{frame_suffix:06d}"
        image_path = images_dir / f"{stem}.jpg"
        label_path = labels_dir / f"{stem}.txt"
        review_path = review_dir / f"{stem}.json"

        if not cv2.imwrite(str(image_path), frame):
            return
        label_path.write_text("\n".join(labels) + "\n", encoding="utf-8")

        metadata = {
            "image": str(image_path.relative_to(self.distillation_dir).as_posix()),
            "label": str(label_path.relative_to(self.distillation_dir).as_posix()),
            "source": self.distillation_source,
            "reason": reason,
            "frame_index": frame_index,
            "primary_model": self.model_name,
            "secondary_model": self.secondary_model,
            "primary_count": len(primary),
            "secondary_count": len(secondary),
            "fused_count": len(fused),
            "primary": primary,
            "secondary": secondary,
            "fused": fused,
            "captured_at": now,
        }
        review_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
        with (self.distillation_dir / "manifest.jsonl").open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(metadata, separators=(",", ":")) + "\n")

        self._distillation_captured_count += 1
        self._distillation_last_capture_at = now

    def detect_persons(self, frame, conf_threshold: float = 0.3):
        """Detect people in a single frame (no tracking).

        Returns a list of {"x1","y1","x2","y2","confidence"} person boxes.
        Used by the live webcam pipeline to draw a body/"human detected" box
        around each person before face detection runs.
        """
        results = self.model.predict(
            frame,
            classes=[0],
            conf=conf_threshold,
            verbose=False,
            device=self.device,
        )
        boxes, confs, _ = self._detections_from_result(results[0], conf_threshold)
        persons: List[Dict[str, Any]] = []
        for box, conf in zip(boxes, confs):
            persons.append(self._person_dict_from_box(box.tolist(), float(conf), self.model_name))

        self._detect_frame_count += 1
        if self._should_run_secondary(persons):
            secondary_persons = self._run_secondary_detector(frame, conf_threshold)
            if secondary_persons:
                original_persons = [dict(person) for person in persons]
                persons = self._merge_persons(persons, secondary_persons)
                reason = "yolo_missed" if not original_persons else "model_disagreement"
                self._capture_distillation_frame(
                    frame,
                    original_persons,
                    secondary_persons,
                    persons,
                    reason=reason,
                )

        return persons

    def track_video(self, video_path, output_dir="data/processed_snippets", sample_rate=10, conf_threshold: float = 0.3):
        """
        Track people in the video using YOLOv8 + built-in BoT-SORT/ByteTrack.
        
        Args:
            video_path: Path to video file
            output_dir: Directory for saving processed snippets
            sample_rate: Save one frame per N frames per person for face extraction
            conf_threshold: Person detection confidence threshold
            
        Returns:
            List of detection dicts with track IDs, bounding boxes, and sampled frames.
        """
        os.makedirs(output_dir, exist_ok=True)

        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            print(f"Error: Could not open video {video_path}")
            return []

        fps = cap.get(cv2.CAP_PROP_FPS)
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        print(f"Processing video: {video_path} ({total_frames} frames at {fps:.1f} FPS)")

        frame_count = 0
        person_detections = []
        track_frame_counts = {}  # Track how many frames we've seen per person
        tracker_backend_available = True
        fallback_tracks = {}
        next_fallback_track_id = 1

        while cap.isOpened():
            ret, frame = cap.read()
            if not ret:
                break

            # Run YOLOv8 tracking with persistence for consistent IDs.
            # If ByteTrack/BoT-SORT deps are missing, gracefully fall back to
            # per-frame detection plus lightweight IoU-based ID assignment.
            if tracker_backend_available:
                try:
                    results = self.model.track(
                        frame,
                        persist=True,
                        classes=[0],
                        conf=conf_threshold,
                        verbose=False,
                        device=self.device,
                    )
                except Exception as exc:
                    tracker_backend_available = False
                    if not self._fallback_notice_emitted:
                        print(
                            "Tracking backend unavailable, falling back to detection-only mode: "
                            f"{exc}"
                        )
                        self._fallback_notice_emitted = True
                    results = self.model.predict(
                        frame,
                        classes=[0],
                        conf=conf_threshold,
                        verbose=False,
                        device=self.device,
                    )
            else:
                results = self.model.predict(
                    frame,
                    classes=[0],
                    conf=conf_threshold,
                    verbose=False,
                    device=self.device,
                )

            boxes, confs, tracker_ids = self._detections_from_result(results[0], conf_threshold)
            if len(boxes) == 0 and self._should_run_secondary([], frame_count):
                secondary_persons = self._run_secondary_detector(frame, conf_threshold)
                if secondary_persons:
                    self._capture_distillation_frame(
                        frame,
                        [],
                        secondary_persons,
                        secondary_persons,
                        reason="video_yolo_missed",
                        frame_index=frame_count,
                    )
                    boxes, confs = self._persons_to_arrays(secondary_persons)
                    tracker_ids = None

            if len(boxes) > 0:
                if tracker_backend_available and tracker_ids is not None:
                    ids = tracker_ids
                else:
                    ids, fallback_tracks, next_fallback_track_id = self._assign_fallback_ids(
                        boxes,
                        fallback_tracks,
                        next_fallback_track_id,
                    )

                for box, track_id, conf in zip(boxes, ids, confs):
                    track_id = int(track_id)
                    if track_id not in track_frame_counts:
                        track_frame_counts[track_id] = 0
                    track_frame_counts[track_id] += 1

                    # Sample frames for face extraction
                    should_sample = track_frame_counts[track_id] % sample_rate == 0

                    # Extract person crop for face detection
                    x1, y1, x2, y2 = box
                    person_crop = frame[
                        max(0, y1):min(frame.shape[0], y2),
                        max(0, x1):min(frame.shape[1], x2),
                    ].copy() if should_sample else None

                    person_detections.append({
                        "id": track_id,
                        "box": box.tolist(),
                        "frame_idx": frame_count,
                        "confidence": float(conf),
                        "frame": frame.copy() if should_sample else None,
                        "person_crop": person_crop,
                    })
            elif not tracker_backend_available:
                fallback_tracks = {}

            frame_count += 1
            if frame_count % 100 == 0:
                print(f"  Processed {frame_count}/{total_frames} frames...")

        cap.release()
        print(f"Tracking complete: {len(person_detections)} detections, "
              f"{len(track_frame_counts)} unique people tracked")
        return person_detections


if __name__ == "__main__":
    tracker = PersonTracker()
    # Example: tracker.track_video("data/raw_videos/sample.mp4")
