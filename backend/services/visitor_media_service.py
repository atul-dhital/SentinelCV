from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import os
import uuid as uuid_lib
from typing import List, Optional, Sequence, Tuple

import requests

try:
    import cv2  # type: ignore
except Exception:  # pragma: no cover - optional dependency fallback
    cv2 = None

from core.storage import storage
from models import models
from services import visitor_service

AI_SERVICE_URL = os.getenv("AI_SERVICE_URL", "http://127.0.0.1:8001")


@dataclass
class VisitorMediaEnrollmentResult:
    images_added: int = 0
    video_frames_added: int = 0
    video_url: Optional[str] = None
    warnings: List[str] = field(default_factory=list)
    face_image_urls: List[str] = field(default_factory=list)


def _call_embed_face(image_path: str) -> Tuple[List[float], float, Optional[str]]:
    response = requests.post(
        f"{AI_SERVICE_URL}/embed-face",
        json={"image_path": image_path},
        timeout=60,
    )
    if response.status_code != 200:
        raise RuntimeError(f"AI service returned status {response.status_code}")

    result = response.json()
    if result.get("error"):
        raise ValueError(result["error"])

    embedding = result.get("embedding")
    if not embedding:
        raise ValueError("Could not generate face embedding")

    return embedding, float(result.get("quality_score", 0.0)), result.get("face_angle")


def enroll_existing_image_path(
    db,
    visitor: models.Visitor,
    image_path: str,
    image_url: Optional[str] = None,
    is_primary: bool = False,
):
    """Create face data from an image that already exists on disk."""
    embedding, quality_score, face_angle = _call_embed_face(image_path)
    return visitor_service.create_face_data(
        db,
        visitor.id,
        embedding,
        image_url=image_url,
        quality_score=quality_score,
        face_angle=face_angle,
        is_primary=is_primary,
    )


def update_visitor_media_metadata(
    db,
    visitor: models.Visitor,
    video_url: Optional[str] = None,
):
    """Record uploaded media references in the visitor metadata JSON."""
    if not video_url:
        return visitor

    metadata = dict(visitor.visitor_metadata or {})
    enrollment_media = dict(metadata.get("enrollment_media") or {})
    video_urls = list(enrollment_media.get("video_urls") or [])

    if video_url not in video_urls:
        video_urls.append(video_url)

    enrollment_media["video_urls"] = video_urls
    enrollment_media["latest_video_url"] = video_url
    enrollment_media["updated_at"] = datetime.now(timezone.utc).isoformat()
    metadata["enrollment_media"] = enrollment_media
    visitor.visitor_metadata = metadata
    db.commit()
    db.refresh(visitor)
    return visitor


def _sample_video_frames(video_path: str, max_frames: int = 5):
    if cv2 is None:
        raise RuntimeError("OpenCV is not available")

    capture = cv2.VideoCapture(video_path)
    if not capture.isOpened():
        raise ValueError("Could not open the uploaded video")

    total_frames = int(capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    if total_frames > 0:
        target_frames = min(max_frames, total_frames)
        step = max(1, total_frames // target_frames)
    else:
        target_frames = max_frames
        step = 12

    sampled_frames = []
    index = 0
    try:
        while True:
            success, frame = capture.read()
            if not success:
                break

            if index % step == 0:
                sampled_frames.append((index, frame))
                if len(sampled_frames) >= target_frames:
                    break
            index += 1
    finally:
        capture.release()

    return sampled_frames


def _save_frame_for_visitor(
    visitor_id,
    frame,
    frame_index: int,
) -> Tuple[str, str]:
    if cv2 is None:
        raise RuntimeError("OpenCV is not available")

    filename = f"video_frame_{uuid_lib.uuid4().hex[:12]}_{frame_index}.jpg"
    relative_path = f"face_images/known/{visitor_id}/video_frames/{filename}"
    success, encoded = cv2.imencode(".jpg", frame)
    if not success:
        raise RuntimeError("Failed to write extracted frame")
    full_path = storage.save_file(
        relative_path,
        encoded.tobytes(),
        content_type="image/jpeg",
    )
    return str(full_path), relative_path


def enroll_media_for_visitor(
    db,
    visitor: models.Visitor,
    image_paths: Optional[Sequence[Tuple[str, str]]] = None,
    video_path: Optional[str] = None,
    video_url: Optional[str] = None,
    max_faces: Optional[int] = None,
) -> VisitorMediaEnrollmentResult:
    """Create face data for uploaded images and optional video frames."""
    result = VisitorMediaEnrollmentResult(video_url=video_url)
    image_paths = list(image_paths or [])
    existing_faces = visitor_service.get_face_data_for_visitor(db, visitor.id)
    remaining = None
    if max_faces is not None:
        remaining = max(0, max_faces - len(existing_faces))
    created_faces: List[models.FaceData] = []

    for image_path, image_url in image_paths:
        if remaining is not None and remaining <= 0:
            result.warnings.append("Face data limit reached. Skipped remaining images.")
            break
        if not os.path.exists(image_path):
            result.warnings.append(f"Missing image: {image_url}")
            continue

        try:
            face = enroll_existing_image_path(
                db,
                visitor,
                image_path,
                image_url=image_url,
                is_primary=False,
            )
            created_faces.append(face)
            result.images_added += 1
            result.face_image_urls.append(image_url)
            if remaining is not None:
                remaining -= 1
        except Exception as exc:
            result.warnings.append(f"{os.path.basename(image_url)}: {exc}")

    if video_path:
        if not os.path.exists(video_path):
            result.warnings.append("Uploaded video file was not found on disk")
        else:
            update_visitor_media_metadata(db, visitor, video_url=video_url)
            try:
                frames = _sample_video_frames(video_path)
            except Exception as exc:
                result.warnings.append(str(exc))
                frames = []

            for frame_index, frame in frames:
                if remaining is not None and remaining <= 0:
                    result.warnings.append("Face data limit reached. Skipped remaining video frames.")
                    break
                try:
                    frame_path, frame_url = _save_frame_for_visitor(visitor.id, frame, frame_index)
                    face = enroll_existing_image_path(
                        db,
                        visitor,
                        frame_path,
                        image_url=frame_url,
                        is_primary=False,
                    )
                    created_faces.append(face)
                    result.video_frames_added += 1
                    result.face_image_urls.append(frame_url)
                    if remaining is not None:
                        remaining -= 1
                except Exception as exc:
                    result.warnings.append(f"Frame {frame_index}: {exc}")

    if not existing_faces and created_faces:
        best_face = max(created_faces, key=lambda face: face.quality_score or 0.0)
        for face in created_faces:
            face.is_primary = face.id == best_face.id
        db.commit()

    return result

