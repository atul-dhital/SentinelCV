"""
Continuous RTSP Stream Manager for SentinelCV AI Service.

Manages persistent RTSP camera streams that run as background tasks,
continuously reading frames, detecting faces, matching visitors, and
pushing results to the backend API.

Supports multiple concurrent camera streams with start/stop lifecycle.
"""

import os
import cv2
import logging
import time
import asyncio
import base64
import threading
import numpy as np
import requests
from typing import Optional, Dict, Any
from dataclasses import dataclass, field
from enum import Enum

from liveness_checker import LivenessChecker
from multi_angle_recognition import MultiAngleFaceMatcher, FaceAngle, MultiAngleEmbedding


logger = logging.getLogger("sentinelcv.rtsp")
INTERNAL_SERVICE_KEY = os.getenv("INTERNAL_SERVICE_KEY", "")
_INTERNAL_HEADERS = {"X-Internal-API-Key": INTERNAL_SERVICE_KEY} if INTERNAL_SERVICE_KEY else {}


class StreamStatus(str, Enum):
    STARTING = "starting"
    RUNNING = "running"
    STOPPING = "stopping"
    STOPPED = "stopped"
    ERROR = "error"


@dataclass
class StreamStats:
    frames_read: int = 0
    frames_processed: int = 0
    faces_detected: int = 0
    faces_identified: int = 0
    logs_created: int = 0
    errors: int = 0
    started_at: float = 0.0
    last_frame_at: float = 0.0
    fps: float = 0.0


@dataclass
class StreamConfig:
    rtsp_url: str
    organization_id: str
    camera_id: Optional[str] = None
    frame_stride: int = 5          # Process every Nth frame
    max_faces_per_frame: int = 4
    threshold: float = 0.6
    reconnect_delay: float = 5.0   # Seconds between reconnection attempts
    max_reconnects: int = 10
    target_fps: float = 5.0        # Target processing FPS (throttle)


class RTSPStreamWorker:
    """
    A single RTSP stream worker that runs in a background thread.
    Reads frames from an RTSP URL, processes them for face detection,
    and sends results to the backend API.
    """

    def __init__(
        self,
        stream_id: str,
        config: StreamConfig,
        face_engine,
        api_base_url: str,
    ):
        self.stream_id = stream_id
        self.config = config
        self.face_engine = face_engine
        self.api_base_url = api_base_url

        self.status = StreamStatus.STOPPED
        self.stats = StreamStats()
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._cap: Optional[cv2.VideoCapture] = None
        self._error_message: Optional[str] = None
        self._face_image_dir = os.getenv("FACE_IMAGE_DIR", "/app/data/face_images")
        self._liveness = LivenessChecker()
        self._multi_angle = MultiAngleFaceMatcher()

    def start(self):
        """Start the stream worker in a background thread."""
        if self.status == StreamStatus.RUNNING:
            return
        self._stop_event.clear()
        self.status = StreamStatus.STARTING
        self.stats = StreamStats(started_at=time.time())
        self._error_message = None
        self._thread = threading.Thread(
            target=self._run_loop,
            name=f"rtsp-{self.stream_id}",
            daemon=True,
        )
        self._thread.start()

    def stop(self):
        """Signal the worker to stop gracefully."""
        self.status = StreamStatus.STOPPING
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=10)
        self.status = StreamStatus.STOPPED

    def get_info(self) -> Dict[str, Any]:
        """Return current status and stats."""
        elapsed = time.time() - self.stats.started_at if self.stats.started_at else 0
        return {
            "stream_id": self.stream_id,
            "camera_id": self.config.camera_id,
            "rtsp_url": self.config.rtsp_url,
            "status": self.status.value,
            "error": self._error_message,
            "stats": {
                "frames_read": self.stats.frames_read,
                "frames_processed": self.stats.frames_processed,
                "faces_detected": self.stats.faces_detected,
                "faces_identified": self.stats.faces_identified,
                "logs_created": self.stats.logs_created,
                "errors": self.stats.errors,
                "uptime_seconds": round(elapsed, 1),
                "fps": round(self.stats.fps, 2),
            },
        }

    def _run_loop(self):
        """Main processing loop running in background thread."""
        reconnect_count = 0
        # Reset the reconnect budget after the stream has been live for this
        # many seconds. Previously the counter was only zeroed on the initial
        # connect, so 10 transient blips spread across hours would
        # permanently mark a stream as ERROR.
        reconnect_budget_reset_seconds = 60.0
        last_successful_open_at = 0.0

        while not self._stop_event.is_set():
            # Connect / reconnect
            try:
                self._cap = cv2.VideoCapture(self.config.rtsp_url)
                if not self._cap.isOpened():
                    raise ConnectionError(f"Cannot open RTSP: {self.config.rtsp_url}")
                self.status = StreamStatus.RUNNING
                reconnect_count = 0
                last_successful_open_at = time.time()
                logger.info(
                    "Stream %s connected to %s",
                    self.stream_id,
                    self.config.rtsp_url,
                )
            except Exception as e:
                reconnect_count += 1
                self._error_message = str(e)
                logger.warning(
                    "Stream %s connection failed (%d/%d): %s",
                    self.stream_id,
                    reconnect_count,
                    self.config.max_reconnects,
                    e,
                )
                if reconnect_count >= self.config.max_reconnects:
                    self.status = StreamStatus.ERROR
                    self._error_message = f"Max reconnects exceeded: {e}"
                    return
                self._stop_event.wait(self.config.reconnect_delay)
                continue

            # Frame reading loop
            frame_interval = 1.0 / max(0.1, self.config.target_fps)
            frame_idx = 0

            try:
                while not self._stop_event.is_set():
                    loop_start = time.time()

                    ok, frame = self._cap.read()
                    if not ok or frame is None:
                        logger.info(
                            "Stream %s lost frame, will attempt reconnect",
                            self.stream_id,
                        )
                        break

                    self.stats.frames_read += 1
                    frame_idx += 1

                    # Reset the reconnect budget once the stream is healthy.
                    if (
                        reconnect_count > 0
                        and last_successful_open_at
                        and (time.time() - last_successful_open_at) > reconnect_budget_reset_seconds
                    ):
                        reconnect_count = 0

                    # Skip frames based on stride
                    if self.config.frame_stride > 1 and (frame_idx % self.config.frame_stride) != 0:
                        continue

                    self.stats.last_frame_at = time.time()
                    self._process_frame(frame, frame_idx)
                    self.stats.frames_processed += 1

                    # Calculate FPS
                    elapsed = time.time() - self.stats.started_at
                    if elapsed > 0:
                        self.stats.fps = self.stats.frames_processed / elapsed

                    # Throttle to target FPS
                    processing_time = time.time() - loop_start
                    sleep_time = frame_interval - processing_time
                    if sleep_time > 0:
                        self._stop_event.wait(sleep_time)

            except Exception as e:
                self._error_message = str(e)
                self.stats.errors += 1
                logger.exception("Stream %s error: %s", self.stream_id, e)
            finally:
                if self._cap:
                    self._cap.release()
                    self._cap = None

            # If not stopped intentionally, try to reconnect
            if not self._stop_event.is_set():
                reconnect_count += 1
                if reconnect_count >= self.config.max_reconnects:
                    self.status = StreamStatus.ERROR
                    self._error_message = "Max reconnects exceeded after stream loss"
                    return
                logger.info(
                    "Stream %s reconnecting in %.1fs...",
                    self.stream_id,
                    self.config.reconnect_delay,
                )
                self._stop_event.wait(self.config.reconnect_delay)

        self.status = StreamStatus.STOPPED

    def _process_frame(self, frame: np.ndarray, frame_idx: int):
        """Detect faces in a frame, match visitors, create logs."""
        try:
            detected_faces = self.face_engine.extract_face(frame)
            if not detected_faces:
                return

            os.makedirs(self._face_image_dir, exist_ok=True)

            for face_data in detected_faces[: self.config.max_faces_per_frame]:
                face_img = face_data.get("face")
                if face_img is None:
                    continue

                # Convert to uint8 if needed
                if face_img.dtype != np.uint8:
                    face_img_uint8 = (face_img * 255).astype(np.uint8)
                else:
                    face_img_uint8 = face_img

                embedding = self.face_engine.get_embedding_from_crop(face_img_uint8)
                if embedding is None:
                    continue

                self.stats.faces_detected += 1

                # Search for matching visitor
                visitor_id = None
                face_data_id = None
                confidence = 0.0
                status = "unidentified"
                
                # Determine angle
                angle = FaceAngle.FRONTAL
                if "facial_area" in face_data:
                    fa = face_data["facial_area"]
                    bbox = (fa["x"], fa["y"], fa["x"] + fa["w"], fa["y"] + fa["h"])
                    angle = self._multi_angle.detect_angle(bbox)

                try:
                    search_resp = requests.post(
                        f"{self.api_base_url}/visitors/search",
                        json={
                            "organization_id": self.config.organization_id,
                            "embedding": embedding,
                            "threshold": self.config.threshold,
                            "angle": angle.value
                        },
                        headers=_INTERNAL_HEADERS,
                        timeout=15,
                    )
                    if search_resp.status_code == 200:
                        result = search_resp.json()
                        if result.get("matched"):
                            visitor_id = result["visitor"]["id"]
                            confidence = float(result.get("confidence") or 0.0)
                            face_data_id = result.get("face_data_id")
                            status = "identified"
                            self.stats.faces_identified += 1
                except Exception as exc:
                    self.stats.errors += 1
                    logger.warning(
                        "Search failed for stream %s: %s", self.stream_id, exc
                    )

                # Liveness check — reject spoofs before logging
                liveness_passed = True
                try:
                    liveness_result = self._liveness.check(face_img_uint8)
                    liveness_passed = liveness_result.get("is_live", True)
                    if not liveness_passed:
                        # Spoof detected: clear identification
                        visitor_id = None
                        face_data_id = None
                        confidence = 0.0
                        status = "spoof_rejected"
                        logger.warning(
                            "Liveness FAILED for stream %s (score=%.2f, attack=%s)",
                            self.stream_id,
                            liveness_result.get("score", 0),
                            liveness_result.get("attack_type"),
                        )
                except Exception as exc:
                    # Liveness failure should not block logging
                    logger.warning(
                        "Liveness check error for stream %s: %s", self.stream_id, exc
                    )

                # Save face crop
                filename = f"rtsp_{self.stream_id[:8]}_{frame_idx}_{int(time.time())}.jpg"
                file_path = os.path.join(self._face_image_dir, filename)
                cv2.imwrite(file_path, face_img_uint8)

                # Encode face crop as base64 for WebSocket push
                _, buf = cv2.imencode(".jpg", face_img_uint8)
                face_crop_b64 = base64.b64encode(buf).decode("utf-8")

                # Create log via backend API
                payload = {
                    "organization_id": self.config.organization_id,
                    "camera_id": self.config.camera_id,
                    "face_image_path": f"face_images/{filename}",
                    "video_snippet_path": self.config.rtsp_url,
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
                        f"{self.api_base_url}/logs",
                        json=payload,
                        headers=_INTERNAL_HEADERS,
                        timeout=10,
                    )
                    if log_resp.status_code in (200, 201):
                        self.stats.logs_created += 1
                except Exception as exc:
                    self.stats.errors += 1
                    logger.warning(
                        "Log creation failed for stream %s: %s", self.stream_id, exc
                    )

        except Exception as e:
            self.stats.errors += 1
            logger.exception(
                "Frame processing error in stream %s: %s", self.stream_id, e
            )


class RTSPStreamManager:
    """
    Manages multiple concurrent RTSP stream workers.
    Provides start/stop/status APIs for each stream.
    """

    def __init__(self, face_engine, api_base_url: str):
        self.face_engine = face_engine
        self.api_base_url = api_base_url
        self._streams: Dict[str, RTSPStreamWorker] = {}

    def start_stream(self, stream_id: str, config: StreamConfig) -> Dict[str, Any]:
        """Start a new RTSP stream or restart an existing one."""
        # Stop existing stream with same ID if running
        if stream_id in self._streams:
            existing = self._streams[stream_id]
            if existing.status == StreamStatus.RUNNING:
                existing.stop()

        worker = RTSPStreamWorker(
            stream_id=stream_id,
            config=config,
            face_engine=self.face_engine,
            api_base_url=self.api_base_url,
        )
        self._streams[stream_id] = worker
        worker.start()
        # Give it a moment to connect
        time.sleep(0.5)
        return worker.get_info()

    def stop_stream(self, stream_id: str) -> Optional[Dict[str, Any]]:
        """Stop a running RTSP stream."""
        worker = self._streams.get(stream_id)
        if not worker:
            return None
        worker.stop()
        return worker.get_info()

    def get_stream_status(self, stream_id: str) -> Optional[Dict[str, Any]]:
        """Get status and stats for a specific stream."""
        worker = self._streams.get(stream_id)
        if not worker:
            return None
        return worker.get_info()

    def list_streams(self) -> list:
        """List all streams and their statuses."""
        return [w.get_info() for w in self._streams.values()]

    def stop_all(self):
        """Stop all running streams."""
        for worker in self._streams.values():
            if worker.status in (StreamStatus.RUNNING, StreamStatus.STARTING):
                worker.stop()
