from fastapi import APIRouter, Depends, HTTPException, Response
from fastapi.concurrency import run_in_threadpool
from sqlalchemy.orm import Session
from sqlalchemy import func
from db.base import get_db
from models import models
from schemas import schemas
from services import user_service, visitor_service
from core.security import get_current_user
from core.realtime import realtime_manager
from uuid import UUID
from typing import List
from datetime import datetime, timedelta, timezone
import base64
import ipaddress
import os
import socket
import struct
from urllib.parse import urlparse
import httpx

router = APIRouter(prefix="/cameras", tags=["Cameras"])
AI_SERVICE_URL = os.getenv("AI_SERVICE_URL", "http://127.0.0.1:8001")


# ─── RTSP URL validation ─────────────────────────────────────────────────────
#
# OpenCV's ``cv2.VideoCapture`` accepts whatever string is passed to it,
# including ``file://``, ``http://``, raw filesystem paths and other
# unexpected schemes. Any of these would let a tenant-admin point the AI
# worker at internal services or local files. We restrict camera URLs to
# real RTSP streams over public addresses.

_RTSP_ALLOWED_SCHEMES = {"rtsp", "rtsps"}


def _allow_private_rtsp_targets() -> bool:
    """Allow private/loopback hosts only when explicitly opted in (dev/CI)."""
    raw = (os.getenv("ALLOW_PRIVATE_RTSP_TARGETS") or "").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def _validate_rtsp_url(url: str) -> str:
    """Validate that ``url`` is a real RTSP stream over a public address."""
    if not url:
        raise HTTPException(status_code=400, detail="rtsp_url is required")

    parsed = urlparse(url)
    if parsed.scheme.lower() not in _RTSP_ALLOWED_SCHEMES:
        raise HTTPException(
            status_code=400,
            detail="rtsp_url must use rtsp:// or rtsps://",
        )
    host = (parsed.hostname or "").strip()
    if not host:
        raise HTTPException(status_code=400, detail="rtsp_url must include a hostname")

    if _allow_private_rtsp_targets():
        return url

    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror as exc:
        raise HTTPException(
            status_code=400,
            detail=f"Could not resolve rtsp_url hostname '{host}': {exc}",
        )

    for info in infos:
        ip_str = info[4][0]
        try:
            ip_obj = ipaddress.ip_address(ip_str)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid resolved IP '{ip_str}'")
        if (
            ip_obj.is_private
            or ip_obj.is_loopback
            or ip_obj.is_link_local
            or ip_obj.is_multicast
            or ip_obj.is_reserved
            or ip_obj.is_unspecified
        ):
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Refusing to register rtsp_url '{host}' — resolves to non-public "
                    f"address {ip_str}. Set ALLOW_PRIVATE_RTSP_TARGETS=1 to override."
                ),
            )
    return url


def _get_user(db: Session, user_id: str) -> models.User:
    user = user_service.get_user_by_id(db, user_id)
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    return user


def _camera_event_payload(camera: models.Camera) -> dict:
    return {
        "id": str(camera.id),
        "organization_id": str(camera.organization_id),
        "name": camera.name,
        "location": camera.location,
        "rtsp_url": camera.rtsp_url,
        "is_active": camera.is_active,
        "status": camera.status,
        "last_seen": camera.last_seen.isoformat() if camera.last_seen else None,
        "created_at": camera.created_at.isoformat() if camera.created_at else None,
    }


async def _broadcast_camera_event(organization_id: UUID | str, event_type: str, camera: models.Camera) -> None:
    await realtime_manager.broadcast(
        str(organization_id),
        event_type,
        _camera_event_payload(camera),
    )


@router.get("/", response_model=List[schemas.Camera])
def list_cameras(
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List all cameras for the user's organization."""
    user = _get_user(db, current_user_id)
    cameras = db.query(models.Camera).filter(
        models.Camera.organization_id == user.organization_id
    ).order_by(models.Camera.created_at.desc()).limit(10000).all()
    return cameras


# ─── S21: Camera Groups (US-CAM-001 … US-CAM-003) ────────────────────────────


@router.get("/groups", response_model=List[schemas.CameraGroupResponse])
async def list_camera_groups(
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """US-CAM-003: List all camera groups for the organization."""
    user = _get_user(db, current_user_id)
    groups = (
        db.query(models.CameraGroup)
        .filter(models.CameraGroup.organization_id == user.organization_id)
        .order_by(models.CameraGroup.name)
        .limit(10000).all()
    )
    results = []
    for g in groups:
        cam_count = (
            db.query(func.count(models.Camera.id))
            .filter(models.Camera.group_id == g.id)
            .scalar() or 0
        )
        results.append(schemas.CameraGroupResponse(
            id=g.id,
            name=g.name,
            description=g.description,
            color=g.color,
            camera_count=cam_count,
            created_at=g.created_at,
        ))
    return results


@router.post("/groups", response_model=schemas.CameraGroupResponse)
async def create_camera_group(
    group: schemas.CameraGroupCreate,
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """US-CAM-003: Create a camera group. Admin only."""
    user = _get_user(db, current_user_id)
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Only admins can create camera groups")

    db_group = models.CameraGroup(
        organization_id=user.organization_id,
        name=group.name,
        description=group.description,
        color=group.color,
    )
    db.add(db_group)
    db.commit()
    db.refresh(db_group)

    visitor_service.create_audit_log(
        db, user.organization_id, user.id, "create", "camera_group", str(db_group.id),
    )

    return schemas.CameraGroupResponse(
        id=db_group.id,
        name=db_group.name,
        description=db_group.description,
        color=db_group.color,
        camera_count=0,
        created_at=db_group.created_at,
    )


@router.put("/groups/{group_id}", response_model=schemas.CameraGroupResponse)
async def update_camera_group(
    group_id: UUID,
    update_data: schemas.CameraGroupUpdate,
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Update a camera group. Admin only."""
    user = _get_user(db, current_user_id)
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Only admins can update camera groups")

    db_group = db.query(models.CameraGroup).filter(
        models.CameraGroup.id == group_id,
        models.CameraGroup.organization_id == user.organization_id,
    ).first()
    if not db_group:
        raise HTTPException(status_code=404, detail="Camera group not found")

    update_dict = update_data.model_dump(exclude_unset=True)
    for key, value in update_dict.items():
        setattr(db_group, key, value)
    db.commit()
    db.refresh(db_group)

    cam_count = (
        db.query(func.count(models.Camera.id))
        .filter(models.Camera.group_id == db_group.id)
        .scalar() or 0
    )

    return schemas.CameraGroupResponse(
        id=db_group.id,
        name=db_group.name,
        description=db_group.description,
        color=db_group.color,
        camera_count=cam_count,
        created_at=db_group.created_at,
    )


@router.delete("/groups/{group_id}")
async def delete_camera_group(
    group_id: UUID,
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Delete a camera group. Cameras in the group are unassigned. Admin only."""
    user = _get_user(db, current_user_id)
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Only admins can delete camera groups")

    db_group = db.query(models.CameraGroup).filter(
        models.CameraGroup.id == group_id,
        models.CameraGroup.organization_id == user.organization_id,
    ).first()
    if not db_group:
        raise HTTPException(status_code=404, detail="Camera group not found")

    # Unassign cameras from this group
    db.query(models.Camera).filter(models.Camera.group_id == group_id).update(
        {"group_id": None}
    )

    visitor_service.create_audit_log(
        db, user.organization_id, user.id, "delete", "camera_group", str(group_id),
    )
    db.delete(db_group)
    db.commit()
    return {"message": "Camera group deleted"}


@router.get("/health", response_model=List[schemas.CameraHealthResponse])
async def camera_health(
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """US-CAM-002: Camera health monitoring — returns status, uptime, last seen for all cameras."""
    user = _get_user(db, current_user_id)
    cameras = db.query(models.Camera).filter(
        models.Camera.organization_id == user.organization_id,
    ).limit(10000).all()

    results = []
    for cam in cameras:
        # Calculate uptime from camera sessions
        now = datetime.now(timezone.utc)
        day_ago = now - timedelta(hours=24)
        sessions = (
            db.query(models.CameraSession)
            .filter(
                models.CameraSession.camera_id == cam.id,
                models.CameraSession.started_at >= day_ago,
            )
            .limit(10000).all()
        )
        total_seconds = 0
        last_active = None
        for s in sessions:
            end = s.ended_at or now
            total_seconds += (end - s.started_at).total_seconds()
            if last_active is None or s.started_at > last_active:
                last_active = s.ended_at or s.started_at

        uptime_pct = round(min(total_seconds / 86400 * 100, 100), 1)

        results.append(schemas.CameraHealthResponse(
            camera_id=cam.id,
            camera_name=cam.name,
            status=cam.health_status or cam.status or "unknown",
            uptime_percent=uptime_pct,
            last_active=last_active,
            frame_rate=cam.frame_rate,
            error_count=0,
        ))
    return results


@router.get("/{camera_id}", response_model=schemas.Camera)
async def get_camera(
    camera_id: UUID,
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get a single camera by ID."""
    user = _get_user(db, current_user_id)
    camera = db.query(models.Camera).filter(
        models.Camera.id == camera_id,
        models.Camera.organization_id == user.organization_id
    ).first()
    if not camera:
        raise HTTPException(status_code=404, detail="Camera not found")
    return camera


async def _fetch_rtsp_snapshot(camera: models.Camera, db: Session, organization_id) -> bytes:
    """Grab a JPEG snapshot from the camera's RTSP feed via the AI service.

    Updates camera status / last_seen and broadcasts status changes as a side
    effect, mirroring the original stream-frame behaviour.
    """
    previous_status = camera.status
    try:
        async with httpx.AsyncClient(timeout=25.0) as client:
            resp = await client.post(
                f"{AI_SERVICE_URL}/realtime/rtsp-snapshot",
                json={
                    "rtsp_url": camera.rtsp_url,
                    "max_width": 1280,
                    "jpeg_quality": 80,
                },
            )
    except httpx.RequestError as exc:
        if camera.status != "error":
            camera.status = "error"
            db.commit()
            await _broadcast_camera_event(organization_id, "camera.status_changed", camera)
        raise HTTPException(status_code=503, detail=f"AI service unavailable: {exc}")

    if resp.status_code != 200:
        detail = None
        try:
            detail = resp.json().get("detail")
        except Exception:
            detail = resp.text
        if camera.status != "error":
            camera.status = "error"
            db.commit()
            await _broadcast_camera_event(organization_id, "camera.status_changed", camera)
        raise HTTPException(status_code=resp.status_code, detail=detail or "Unable to capture camera feed")

    camera.status = "online"
    camera.last_seen = datetime.now(timezone.utc)
    db.commit()
    if previous_status != "online":
        await _broadcast_camera_event(organization_id, "camera.status_changed", camera)

    return resp.content


def _jpeg_dimensions(data: bytes) -> tuple[int, int]:
    """Read width/height from JPEG SOF markers without decoding the image."""
    try:
        idx = 2  # skip SOI
        while idx + 9 < len(data):
            if data[idx] != 0xFF:
                idx += 1
                continue
            marker = data[idx + 1]
            # SOF0–SOF15 carry dimensions (excluding DHT/JPG/DAC markers C4, C8, CC)
            if 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):
                height, width = struct.unpack(">HH", data[idx + 5 : idx + 9])
                return width, height
            length = struct.unpack(">H", data[idx + 2 : idx + 4])[0]
            idx += 2 + length
    except Exception:
        pass
    return 0, 0


@router.get("/{camera_id}/stream-frame")
async def get_camera_stream_frame(
    camera_id: UUID,
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Return a JPEG snapshot of the current RTSP feed for a camera."""
    user = _get_user(db, current_user_id)
    camera = db.query(models.Camera).filter(
        models.Camera.id == camera_id,
        models.Camera.organization_id == user.organization_id,
    ).first()
    if not camera:
        raise HTTPException(status_code=404, detail="Camera not found")
    if not camera.rtsp_url:
        raise HTTPException(status_code=400, detail="Camera does not have an RTSP URL")

    content = await _fetch_rtsp_snapshot(camera, db, user.organization_id)
    return Response(
        content=content,
        media_type="image/jpeg",
        headers={"Cache-Control": "no-store"},
    )


@router.get("/{camera_id}/stream-frame/analyzed", response_model=schemas.AnalyzedFrameResponse)
async def get_camera_stream_frame_analyzed(
    camera_id: UUID,
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Snapshot the RTSP feed and run face detection + visitor matching on it.

    Read-only counterpart to /camera/process-frame: returns the frame plus
    detection boxes so the dashboard can overlay identified/unidentified faces.
    No detection or visitor logs are written.
    """
    user = _get_user(db, current_user_id)
    camera = db.query(models.Camera).filter(
        models.Camera.id == camera_id,
        models.Camera.organization_id == user.organization_id,
    ).first()
    if not camera:
        raise HTTPException(status_code=404, detail="Camera not found")
    if not camera.rtsp_url:
        raise HTTPException(status_code=400, detail="Camera does not have an RTSP URL")

    content = await _fetch_rtsp_snapshot(camera, db, user.organization_id)
    frame_b64 = base64.b64encode(content).decode("utf-8")
    width, height = _jpeg_dimensions(content)

    detections: List[schemas.DetectionResult] = []
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            ai_resp = await client.post(
                f"{AI_SERVICE_URL}/realtime/frame-full-process",
                json={"frame_data": frame_b64},
            )
        faces = ai_resp.json().get("faces", []) if ai_resp.status_code == 200 else []
    except Exception:
        faces = []

    for face in faces:
        embedding = face.get("embedding")
        if not embedding:
            continue
        face_angle = visitor_service.normalize_face_angle(face.get("face_angle"))

        visitor_id = None
        visitor_name = None
        confidence = 0.0
        identified = False
        # Keep the CPU/DB-heavy embedding search off the event loop
        match_result = await run_in_threadpool(
            visitor_service.search_visitor_by_embedding,
            db, user.organization_id, embedding, threshold=0.6, angle=face_angle,
        )
        if match_result:
            matched_visitor, conf, _face_data_id, _angle_scores = match_result
            visitor_id = str(matched_visitor.id)
            visitor_name = matched_visitor.name
            confidence = conf
            identified = True

        detections.append(schemas.DetectionResult(
            bbox=face.get("bbox", {}),
            confidence=confidence,
            identified=identified,
            visitor_id=visitor_id,
            visitor_name=visitor_name,
            face_angle=face_angle,
        ))

    return schemas.AnalyzedFrameResponse(
        frame_data=frame_b64,
        width=width,
        height=height,
        detections=detections,
    )


@router.post("/", response_model=schemas.Camera)
async def create_camera(
    camera: schemas.CameraCreate,
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Create a new camera. Admin only."""
    user = _get_user(db, current_user_id)
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Only admins can add cameras")

    if camera.rtsp_url:
        _validate_rtsp_url(camera.rtsp_url)

    db_camera = models.Camera(
        organization_id=user.organization_id,
        name=camera.name,
        rtsp_url=camera.rtsp_url,
        location=camera.location,
        is_active=True,
        status="offline",
    )
    db.add(db_camera)
    db.commit()
    db.refresh(db_camera)

    visitor_service.create_audit_log(
        db, user.organization_id, user.id, "create", "camera", str(db_camera.id)
    )
    await _broadcast_camera_event(user.organization_id, "camera.created", db_camera)
    return db_camera


@router.put("/{camera_id}", response_model=schemas.Camera)
async def update_camera(
    camera_id: UUID,
    update_data: schemas.CameraUpdate,
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Update a camera's settings. Admin only."""
    user = _get_user(db, current_user_id)
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Only admins can update cameras")

    camera = db.query(models.Camera).filter(
        models.Camera.id == camera_id,
        models.Camera.organization_id == user.organization_id
    ).first()
    if not camera:
        raise HTTPException(status_code=404, detail="Camera not found")

    previous_status = camera.status
    previous_active = camera.is_active
    update_dict = update_data.model_dump(exclude_unset=True)
    if "rtsp_url" in update_dict and update_dict["rtsp_url"]:
        _validate_rtsp_url(update_dict["rtsp_url"])
    for key, value in update_dict.items():
        setattr(camera, key, value)

    if "is_active" in update_dict and camera.is_active is False:
        camera.status = "offline"

    db.commit()
    db.refresh(camera)

    visitor_service.create_audit_log(
        db, user.organization_id, user.id, "update", "camera", str(camera_id)
    )
    event_type = "camera.updated"
    if previous_status != camera.status or previous_active != camera.is_active:
        event_type = "camera.status_changed"
    await _broadcast_camera_event(user.organization_id, event_type, camera)
    return camera


@router.delete("/{camera_id}")
async def delete_camera(
    camera_id: UUID,
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Delete a camera. Admin only."""
    user = _get_user(db, current_user_id)
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Only admins can delete cameras")

    camera = db.query(models.Camera).filter(
        models.Camera.id == camera_id,
        models.Camera.organization_id == user.organization_id
    ).first()
    if not camera:
        raise HTTPException(status_code=404, detail="Camera not found")

    visitor_service.create_audit_log(
        db, user.organization_id, user.id, "delete", "camera", str(camera_id)
    )
    deleted_payload = _camera_event_payload(camera)
    db.delete(camera)
    db.commit()
    await realtime_manager.broadcast(
        str(user.organization_id),
        "camera.deleted",
        deleted_payload,
    )
    return {"message": "Camera deleted"}


@router.post("/{camera_id}/test")
async def test_camera_connection(
    camera_id: UUID,
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Test camera RTSP connection."""
    user = _get_user(db, current_user_id)
    camera = db.query(models.Camera).filter(
        models.Camera.id == camera_id,
        models.Camera.organization_id == user.organization_id
    ).first()
    if not camera:
        raise HTTPException(status_code=404, detail="Camera not found")

    if not camera.rtsp_url:
        return {"status": "failed", "error": "Missing RTSP URL"}

    previous_status = camera.status
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                f"{AI_SERVICE_URL}/realtime/rtsp-probe",
                json={"rtsp_url": camera.rtsp_url},
            )
        if resp.status_code != 200:
            camera.status = "error"
            db.commit()
            if previous_status != "error":
                await _broadcast_camera_event(user.organization_id, "camera.status_changed", camera)
            return {"status": "failed", "error": "AI service probe failed"}

        result = resp.json()
        if result.get("connected"):
            camera.status = "online"
            camera.last_seen = datetime.now(timezone.utc)
            db.commit()
            if previous_status != "online":
                await _broadcast_camera_event(user.organization_id, "camera.status_changed", camera)
            return {
                "status": "connected",
                "camera_id": str(camera_id),
                "width": result.get("width"),
                "height": result.get("height"),
                "fps": result.get("fps"),
            }

        camera.status = "error"
        db.commit()
        if previous_status != "error":
            await _broadcast_camera_event(user.organization_id, "camera.status_changed", camera)
        return {"status": "failed", "error": result.get("error", "RTSP probe failed")}
    except Exception as exc:
        camera.status = "error"
        db.commit()
        if previous_status != "error":
            await _broadcast_camera_event(user.organization_id, "camera.status_changed", camera)
        return {"status": "failed", "error": f"Probe error: {exc}"}
@router.post("/{camera_id}/assign-group")
async def assign_camera_to_group(
    camera_id: UUID,
    group_id: UUID | None = None,
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Assign a camera to a group (or unassign by passing null). Admin only."""
    user = _get_user(db, current_user_id)
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Only admins can assign cameras to groups")

    camera = db.query(models.Camera).filter(
        models.Camera.id == camera_id,
        models.Camera.organization_id == user.organization_id,
    ).first()
    if not camera:
        raise HTTPException(status_code=404, detail="Camera not found")

    if group_id is not None:
        grp = db.query(models.CameraGroup).filter(
            models.CameraGroup.id == group_id,
            models.CameraGroup.organization_id == user.organization_id,
        ).first()
        if not grp:
            raise HTTPException(status_code=404, detail="Camera group not found")

    camera.group_id = str(group_id) if group_id else None
    db.commit()
    return {"message": "Camera group assignment updated", "camera_id": str(camera_id), "group_id": str(group_id) if group_id else None}
