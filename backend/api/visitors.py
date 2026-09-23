from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Query, Form, Header, Request, BackgroundTasks
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from db.base import get_db, SessionLocal
from models import models
from schemas import schemas
from services import visitor_service, user_service
from services.redis_service import get_redis_service
from services.job_queue_service import job_queue, JobStatus, JobType
from core.security import get_current_user
from core.storage import storage
from uuid import UUID
from typing import List, Optional
import logging
import os
import uuid as uuid_lib
import httpx
import ipaddress
import socket
import csv
import io
import tempfile
import re
from urllib.parse import urlparse

logger = logging.getLogger(__name__)
from core.paths import data_path
from services.visitor_media_service import (
    enroll_existing_image_path,
    enroll_media_for_visitor,
)
from .models_api import _validate_media_strict

_INTERNAL_KEY_RATE_LIMIT = int(os.getenv("INTERNAL_KEY_RATE_LIMIT", "300"))
_INTERNAL_KEY_RATE_WINDOW = int(os.getenv("INTERNAL_KEY_RATE_WINDOW_SECONDS", "60"))

# F4 — biometric READ-event audit logging.
# Every individual visitor lookup or embedding search records who looked at
# whose biometric record. Disable only in non-regulated test environments.
_AUDIT_BIOMETRIC_READS = (os.getenv("AUDIT_BIOMETRIC_READS") or "1").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}


def _mark_face_job_running(job_id: str) -> bool:
    job = job_queue.get_job(job_id)
    if not job or job.status not in {JobStatus.QUEUED, JobStatus.RUNNING}:
        return False
    job.status = JobStatus.RUNNING
    job.started_at = datetime.now(timezone.utc).isoformat()
    with job_queue._lock:
        job_queue._jobs[job.id] = job
    job_queue._persist_job(job)
    return True


async def _process_face_embedding_job(job_id: str) -> None:
    if not _mark_face_job_running(job_id):
        return

    job = job_queue.get_job(job_id)
    if not job:
        return
    payload = job.payload or {}
    relative_path = str(payload.get("relative_path") or "")
    file_path = str(payload.get("file_path") or "")

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(
                f"{AI_SERVICE_URL}/embed-face",
                json={"image_path": file_path},
            )
        if resp.status_code != 200:
            storage.delete_file(relative_path)
            job_queue.fail_job(job_id, "AI service returned an error")
            return

        result = resp.json()
        if result.get("error"):
            storage.delete_file(relative_path)
            job_queue.fail_job(job_id, str(result["error"]))
            return

        embedding = result.get("embedding")
        if not embedding:
            storage.delete_file(relative_path)
            job_queue.fail_job(job_id, "Could not generate face embedding from image")
            return

        db = SessionLocal()
        try:
            visitor_id = UUID(str(payload["visitor_id"]))
            user_id = UUID(str(payload["user_id"]))
            organization_id = UUID(str(payload["organization_id"]))
            normalized_angle = visitor_service.normalize_face_angle(
                payload.get("face_angle") or result.get("face_angle")
            )
            is_primary = visitor_service.get_face_data_count(db, visitor_id) == 0
            face_data = visitor_service.create_face_data(
                db,
                visitor_id,
                embedding,
                image_url=relative_path,
                quality_score=result.get("quality_score", 0.0),
                face_angle=normalized_angle,
                is_primary=is_primary,
            )
            visitor_service.create_audit_log(
                db,
                organization_id,
                user_id,
                "upload_face_async",
                "face_data",
                str(face_data.id),
            )
            job_queue.complete_job(
                job_id,
                {
                    "face_data_id": str(face_data.id),
                    "visitor_id": str(visitor_id),
                    "image_url": relative_path,
                },
            )
        finally:
            db.close()
    except Exception as exc:
        if relative_path:
            storage.delete_file(relative_path)
        logger.exception("Face embedding job failed: %s", job_id)
        job_queue.fail_job(job_id, str(exc))


def _audit_biometric_read(
    db: Session,
    user: models.User,
    action: str,
    entity_type: str,
    entity_id: Optional[str],
    *,
    details: Optional[dict] = None,
) -> None:
    """Record a biometric-record read in the audit log.

    Wraps ``visitor_service.create_audit_log`` so that any failure to write
    the audit row is logged but does not break the read for the user. The
    intended deployment surface is a duplicated append-only sink (S3 Object
    Lock / SIEM) — the local row is the secondary copy.
    """
    if not _AUDIT_BIOMETRIC_READS:
        return
    try:
        visitor_service.create_audit_log(
            db,
            user.organization_id,
            user.id,
            action,
            entity_type,
            entity_id,
            details=details or {},
        )
    except Exception:
        logger.exception(
            "Failed to write biometric read audit (action=%s entity=%s id=%s)",
            action,
            entity_type,
            entity_id,
        )


def _require_internal_key(
    request: Request,
    x_internal_api_key: Optional[str] = Header(None, alias="X-Internal-API-Key"),
) -> None:
    from core.security import verify_internal_key
    if not verify_internal_key(x_internal_api_key):
        raise HTTPException(status_code=401, detail="Invalid or missing internal API key")
    client_ip = (request.headers.get("x-forwarded-for", "").split(",")[0].strip()
                 or (request.client.host if request.client else "unknown"))
    result = get_redis_service().check_rate_limit(
        key=f"internal_key:{client_ip}",
        max_requests=_INTERNAL_KEY_RATE_LIMIT,
        window_seconds=_INTERNAL_KEY_RATE_WINDOW,
    )
    if not result.get("allowed", True):
        raise HTTPException(status_code=429, detail="Rate limit exceeded for internal API key")

router = APIRouter(prefix="/visitors", tags=["Visitors"])

AI_SERVICE_URL = os.getenv("AI_SERVICE_URL", "http://127.0.0.1:8001")


def _get_user(db: Session, user_id: str) -> models.User:
    user = user_service.get_user_by_id(db, user_id)
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    return user


_BULK_IMAGE_FETCH_MAX_BYTES = int(os.getenv("BULK_IMAGE_FETCH_MAX_BYTES", str(10 * 1024 * 1024)))
_BULK_IMAGE_FETCH_TIMEOUT_SECONDS = float(os.getenv("BULK_IMAGE_FETCH_TIMEOUT_SECONDS", "20"))
_BULK_IMAGE_ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}


def _bulk_image_host_allowlist() -> set[str]:
    raw = os.getenv("BULK_IMAGE_FETCH_ALLOWED_HOSTS", "") or ""
    return {item.strip().lower() for item in raw.split(",") if item.strip()}


def _assert_public_ip(host: str) -> None:
    """Reject SSRF targets: loopback, private, link-local, multicast, reserved."""
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror as exc:
        raise ValueError(f"could not resolve host '{host}': {exc}") from exc

    for info in infos:
        ip_str = info[4][0]
        try:
            ip_obj = ipaddress.ip_address(ip_str)
        except ValueError:
            raise ValueError(f"invalid resolved address '{ip_str}'")
        if (
            ip_obj.is_private
            or ip_obj.is_loopback
            or ip_obj.is_link_local
            or ip_obj.is_multicast
            or ip_obj.is_reserved
            or ip_obj.is_unspecified
        ):
            raise ValueError(
                f"refusing to fetch '{host}' — resolves to non-public address {ip_str}"
            )


async def _resolve_bulk_face_image_source(source: str) -> tuple[str, str, bool]:
    cleaned = (source or "").strip()
    if not cleaned:
        raise ValueError("face image source is empty")

    if cleaned.startswith(("http://", "https://")):
        parsed = urlparse(cleaned)
        host = (parsed.hostname or "").strip().lower()
        if not host:
            raise ValueError("URL is missing a hostname")

        allowlist = _bulk_image_host_allowlist()
        if allowlist and host not in allowlist:
            raise ValueError(f"host '{host}' not in BULK_IMAGE_FETCH_ALLOWED_HOSTS")

        # Block SSRF: resolve and verify the address space before connecting.
        _assert_public_ip(host)

        ext = os.path.splitext(parsed.path or "")[1].lower()
        if ext not in _BULK_IMAGE_ALLOWED_EXTENSIONS:
            ext = ".jpg"

        timeout = httpx.Timeout(_BULK_IMAGE_FETCH_TIMEOUT_SECONDS)
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=False) as client:
            try:
                response = await client.get(cleaned)
            except httpx.HTTPError as exc:
                raise ValueError(f"failed to download image: {exc}") from exc

        if response.status_code != 200:
            raise ValueError(f"failed to download image ({response.status_code})")

        content_type = (response.headers.get("content-type") or "").lower()
        if content_type and not content_type.startswith("image/"):
            raise ValueError("remote file is not an image")

        body = response.content
        if len(body) > _BULK_IMAGE_FETCH_MAX_BYTES:
            raise ValueError(
                f"image exceeds maximum size of {_BULK_IMAGE_FETCH_MAX_BYTES} bytes"
            )

        temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=ext)
        try:
            temp_file.write(body)
            temp_file.flush()
        finally:
            temp_file.close()
        return temp_file.name, cleaned, True

    local_candidate = cleaned[7:] if cleaned.startswith("file://") else cleaned
    candidates = [
        os.path.normpath(local_candidate),
        os.path.normpath(data_path(local_candidate.replace("\\", "/"))),
    ]
    for candidate in candidates:
        if os.path.exists(candidate):
            return candidate, cleaned, False

    raise ValueError("local image path not found")


def _ensure_face_capacity(db: Session, visitor_id: UUID) -> None:
    current_count = visitor_service.get_face_data_count(db, visitor_id)
    if current_count >= visitor_service.MAX_FACE_DATA_PER_VISITOR:
        raise HTTPException(
            status_code=400,
            detail=(
                "Visitor already has the maximum number of face images "
                f"({visitor_service.MAX_FACE_DATA_PER_VISITOR})."
            ),
        )


@router.get("/", response_model=schemas.PaginatedResponse)
async def list_visitors(
    search: Optional[str] = None,
    page: int = 1,
    limit: int = 20,
    after_cursor: Optional[str] = None,
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List all visitors with pagination and search.

    Supports cursor-based pagination via ``after_cursor=<ISO-timestamp>``
    to avoid offset scans on large tables.
    """
    user = _get_user(db, current_user_id)

    cursor_dt = None
    if after_cursor:
        try:
            from datetime import datetime as _dt
            cursor_dt = _dt.fromisoformat(after_cursor.replace("Z", "+00:00"))
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid after_cursor; use ISO 8601")

    if cursor_dt is not None:
        # Filter visitors created before the cursor timestamp
        skip = 0
        page = 1
        visitors, total = visitor_service.get_visitors_by_org(
            db, user.organization_id, skip, limit, search,
            created_before=cursor_dt,
        )
    else:
        skip = (page - 1) * limit
        visitors, total = visitor_service.get_visitors_by_org(
            db, user.organization_id, skip, limit, search
        )
    _audit_biometric_read(
        db,
        user,
        action="visitor.list",
        entity_type="visitor",
        entity_id=None,
        details={"page": page, "limit": limit, "search": search, "result_count": total},
    )
    face_summary = visitor_service.get_face_summary_for_visitors(
        db, [v.id for v in visitors]
    )
    pages = (total + limit - 1) // limit
    items = []
    for visitor in visitors:
        item = schemas.Visitor.model_validate(visitor)
        summary = face_summary.get(str(visitor.id), {})
        item.primary_face_image_url = summary.get("primary_face_image_url")
        item.face_count = int(summary.get("face_count", 0) or 0)
        items.append(item)

    # Emit cursor based on the last visitor's created_at
    next_cursor = None
    if visitors and after_cursor is not None:
        last_ts = visitors[-1].created_at
        if last_ts:
            from datetime import timezone as _tz
            if last_ts.tzinfo is None:
                last_ts = last_ts.replace(tzinfo=_tz.utc)
            next_cursor = last_ts.isoformat()

    return schemas.PaginatedResponse(
        items=items,
        total=total,
        page=page,
        limit=limit,
        pages=pages,
        next_cursor=next_cursor,
    )


@router.get("/export")
async def export_visitors(
    search: Optional[str] = None,
    is_active: Optional[bool] = None,
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Export visitors as CSV (admin only)."""
    user = _get_user(db, current_user_id)
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Only admins can export visitors")

    query = db.query(models.Visitor).filter(models.Visitor.organization_id == user.organization_id)
    if is_active is not None:
        query = query.filter(models.Visitor.is_active == is_active)
    if search:
        search_filter = f"%{search}%"
        query = query.filter(
            (models.Visitor.name.ilike(search_filter))
            | (models.Visitor.email.ilike(search_filter))
            | (models.Visitor.phone.ilike(search_filter))
        )

    visitors = query.order_by(models.Visitor.created_at.desc()).limit(100000).all()  # Cap export at 100k visitors
    face_summary = visitor_service.get_face_summary_for_visitors(db, [item.id for item in visitors])

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "id",
        "name",
        "email",
        "phone",
        "description",
        "notes",
        "is_known",
        "is_active",
        "detection_count",
        "custom_threshold",
        "auto_learn",
        "primary_face_image_url",
        "face_count",
        "created_at",
        "updated_at",
    ])

    for item in visitors:
        summary = face_summary.get(str(item.id), {})
        writer.writerow([
            str(item.id),
            item.name or "",
            item.email or "",
            item.phone or "",
            item.description or "",
            item.notes or "",
            bool(item.is_known),
            bool(item.is_active),
            int(item.detection_count or 0),
            item.custom_threshold if item.custom_threshold is not None else "",
            bool(item.auto_learn),
            summary.get("primary_face_image_url") or "",
            int(summary.get("face_count", 0) or 0),
            item.created_at.isoformat() if item.created_at else "",
            item.updated_at.isoformat() if item.updated_at else "",
        ])

    visitor_service.create_audit_log(
        db,
        user.organization_id,
        user.id,
        "export_visitors",
        "visitor",
        None,
        details={
            "search": search,
            "is_active": is_active,
            "export_count": len(visitors),
        },
    )

    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=visitors.csv"},
    )


@router.get("/{visitor_id}", response_model=schemas.VisitorDetail)
async def get_visitor(
    visitor_id: UUID,
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get a single visitor by ID with face data."""
    user = _get_user(db, current_user_id)
    visitor = visitor_service.get_visitor(db, visitor_id)
    if not visitor or visitor.organization_id != user.organization_id:
        raise HTTPException(status_code=404, detail="Visitor not found")

    face_data = visitor_service.get_face_data_for_visitor(db, visitor_id)
    log_count = db.query(models.VisitorLog).filter(
        models.VisitorLog.visitor_id == visitor_id
    ).count()

    result = schemas.VisitorDetail.model_validate(visitor)
    face_summary = visitor_service.get_face_summary_for_visitor(db, visitor_id)
    result.primary_face_image_url = face_summary.get("primary_face_image_url")
    result.face_count = int(face_summary.get("face_count", 0) or 0)
    result.face_data = [schemas.FaceData.model_validate(f) for f in face_data]
    result.log_count = log_count
    _audit_biometric_read(
        db,
        user,
        action="visitor.get",
        entity_type="visitor",
        entity_id=str(visitor_id),
        details={"face_count": result.face_count},
    )
    return result


@router.post("/", response_model=schemas.Visitor)
async def create_visitor(
    visitor: schemas.VisitorCreate,
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Create a new visitor record."""
    user = _get_user(db, current_user_id)
    # Enforce org isolation
    visitor.organization_id = user.organization_id
    result = visitor_service.create_visitor(db, visitor)

    visitor_service.create_audit_log(
        db, user.organization_id, user.id, "create", "visitor", str(result.id)
    )
    return result


@router.put("/{visitor_id}", response_model=schemas.Visitor)
async def update_visitor(
    visitor_id: UUID,
    update_data: schemas.VisitorUpdate,
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Update a visitor's details."""
    user = _get_user(db, current_user_id)
    # Admin-only for updates? Spec says Staff is read-only for visitors.
    if user.role == "staff":
        raise HTTPException(status_code=403, detail="Staff cannot modify visitors")

    visitor = visitor_service.get_visitor(db, visitor_id)
    if not visitor or visitor.organization_id != user.organization_id:
        raise HTTPException(status_code=404, detail="Visitor not found")

    result = visitor_service.update_visitor(db, visitor, update_data)
    visitor_service.create_audit_log(
        db, user.organization_id, user.id, "update", "visitor", str(visitor_id)
    )
    return result


@router.delete("/{visitor_id}")
async def delete_visitor(
    visitor_id: UUID,
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Delete a visitor and all related data."""
    user = _get_user(db, current_user_id)
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Only admins can delete visitors")

    visitor = visitor_service.get_visitor(db, visitor_id)
    if not visitor or visitor.organization_id != user.organization_id:
        raise HTTPException(status_code=404, detail="Visitor not found")

    visitor_service.create_audit_log(
        db, user.organization_id, user.id, "delete", "visitor", str(visitor_id)
    )
    visitor_service.delete_visitor(db, visitor)
    return {"message": "Visitor deleted"}


# --- Face Data Endpoints ---


@router.post("/{visitor_id}/face-data", response_model=schemas.FaceData)
async def upload_face_data(
    visitor_id: UUID,
    data: schemas.FaceDataCreate,
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Upload face embedding data for a visitor (JSON embedding array)."""
    user = _get_user(db, current_user_id)
    visitor = visitor_service.get_visitor(db, visitor_id)
    if not visitor or visitor.organization_id != user.organization_id:
        raise HTTPException(status_code=404, detail="Visitor not found")

    _ensure_face_capacity(db, visitor_id)

    return visitor_service.create_face_data(
        db,
        visitor_id,
        data.embedding,
        image_url=data.image_url,
        quality_score=data.quality_score,
        face_angle=data.face_angle,
        is_primary=data.is_primary,
    )


@router.post("/{visitor_id}/face-upload", response_model=schemas.FaceData)
async def upload_face_image(
    visitor_id: UUID,
    file: UploadFile = File(...),
    face_angle: Optional[str] = Form(None),
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Upload a face image for a visitor. The image is validated, saved, and
    an embedding is generated automatically via the AI service."""
    user = _get_user(db, current_user_id)
    visitor = visitor_service.get_visitor(db, visitor_id)
    if not visitor or visitor.organization_id != user.organization_id:
        raise HTTPException(status_code=404, detail="Visitor not found")

    _ensure_face_capacity(db, visitor_id)

    normalized_angle = visitor_service.normalize_face_angle(face_angle)
    if face_angle and normalized_angle is None:
        raise HTTPException(status_code=400, detail="Invalid face_angle value")

    file_ext = os.path.splitext(file.filename or "face.jpg")[1] or ".jpg"
    file_id = str(uuid_lib.uuid4())
    filename = f"{file_id}{file_ext}"

    contents = await file.read()
    relative_path = f"face_images/{filename}"
    file_path = str(
        storage.save_file(
            relative_path,
            contents,
            content_type=file.content_type or "application/octet-stream",
        )
    )

    # US-FUT-022: Strict media validation before processing
    validation_result = _validate_media_strict(file_path)
    if not validation_result.valid and not validation_result.is_corrupt:
        storage.delete_file(relative_path)
        raise HTTPException(
            status_code=400,
            detail=f"Media validation failed: {'; '.join(validation_result.issues)}",
        )

    # Call AI service to validate face and generate embedding
    embedding = None
    quality_score = 0.0
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(
                f"{AI_SERVICE_URL}/embed-face",
                json={"image_path": file_path},
            )
        if resp.status_code == 200:
            result = resp.json()
            if result.get("error"):
                storage.delete_file(relative_path)
                raise HTTPException(
                    status_code=400,
                    detail=result["error"],
                )
            embedding = result.get("embedding")
            quality_score = result.get("quality_score", 0.0)
            if normalized_angle is None:
                normalized_angle = visitor_service.normalize_face_angle(
                    result.get("face_angle")
                )
        else:
            storage.delete_file(relative_path)
            raise HTTPException(status_code=502, detail="AI service returned an error")
    except httpx.RequestError:
        storage.delete_file(relative_path)
        raise HTTPException(
            status_code=503,
            detail="AI service is not available. Please ensure the AI service is running.",
        )

    if not embedding:
        storage.delete_file(relative_path)
        raise HTTPException(status_code=400, detail="Could not generate face embedding from image")

    image_url = relative_path
    try:
        face_data = visitor_service.create_face_data(
            db,
            visitor_id,
            embedding,
            image_url=image_url,
            quality_score=quality_score,
            face_angle=normalized_angle,
            is_primary=len(visitor_service.get_face_data_for_visitor(db, visitor_id)) == 0,
        )

        visitor_service.create_audit_log(
            db, user.organization_id, user.id, "upload_face",
            "face_data", str(face_data.id),
        )
    except Exception:
        storage.delete_file(relative_path)
        raise
    return face_data


@router.post("/{visitor_id}/face-upload/jobs", status_code=202)
async def queue_face_image_upload(
    visitor_id: UUID,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    face_angle: Optional[str] = Form(None),
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Queue face enrollment so upload requests do not block on AI embedding."""
    user = _get_user(db, current_user_id)
    visitor = visitor_service.get_visitor(db, visitor_id)
    if not visitor or visitor.organization_id != user.organization_id:
        raise HTTPException(status_code=404, detail="Visitor not found")

    _ensure_face_capacity(db, visitor_id)

    normalized_angle = visitor_service.normalize_face_angle(face_angle)
    if face_angle and normalized_angle is None:
        raise HTTPException(status_code=400, detail="Invalid face_angle value")

    file_ext = os.path.splitext(file.filename or "face.jpg")[1] or ".jpg"
    file_id = str(uuid_lib.uuid4())
    filename = f"{file_id}{file_ext}"
    contents = await file.read()
    relative_path = f"face_images/{filename}"
    file_path = str(
        storage.save_file(
            relative_path,
            contents,
            content_type=file.content_type or "application/octet-stream",
        )
    )

    validation_result = _validate_media_strict(file_path)
    if not validation_result.valid and not validation_result.is_corrupt:
        storage.delete_file(relative_path)
        raise HTTPException(
            status_code=400,
            detail=f"Media validation failed: {'; '.join(validation_result.issues)}",
        )

    job = job_queue.enqueue(
        JobType.FACE_EMBEDDING,
        {
            "visitor_id": str(visitor_id),
            "organization_id": str(user.organization_id),
            "user_id": str(user.id),
            "relative_path": relative_path,
            "file_path": file_path,
            "face_angle": normalized_angle,
        },
        organization_id=str(user.organization_id),
        user_id=str(user.id),
    )
    background_tasks.add_task(_process_face_embedding_job, job.id)

    return {
        "job_id": job.id,
        "status": job.status,
        "message": "Face enrollment queued. Poll /api/v1/visitors/face-upload/jobs/{job_id}.",
        "image_url": relative_path,
    }


@router.get("/face-upload/jobs/{job_id}")
async def get_face_upload_job(
    job_id: str,
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    user = _get_user(db, current_user_id)
    job = job_queue.get_job_status(job_id)
    if not job or job.get("job_type") != JobType.FACE_EMBEDDING:
        raise HTTPException(status_code=404, detail="Face upload job not found")
    if job.get("organization_id") != str(user.organization_id):
        raise HTTPException(status_code=404, detail="Face upload job not found")
    return job


@router.post("/{visitor_id}/register-face", response_model=schemas.FaceData)
async def register_face(
    visitor_id: UUID,
    file: UploadFile = File(...),
    face_angle: Optional[str] = Form(None),
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Register a face image for a visitor (alias for face-upload).
    Saves the image into the known/ subdirectory and generates an embedding.
    """
    user = _get_user(db, current_user_id)
    visitor = visitor_service.get_visitor(db, visitor_id)
    if not visitor or visitor.organization_id != user.organization_id:
        raise HTTPException(status_code=404, detail="Visitor not found")

    _ensure_face_capacity(db, visitor_id)

    normalized_angle = visitor_service.normalize_face_angle(face_angle)
    if face_angle and normalized_angle is None:
        raise HTTPException(status_code=400, detail="Invalid face_angle value")

    file_ext = os.path.splitext(file.filename or "face.jpg")[1] or ".jpg"
    visitor_name = (visitor.name or "unknown").replace(" ", "_")
    file_id = str(uuid_lib.uuid4())[:8]
    filename = f"{file_id}_{visitor_name}{file_ext}"
    relative_path = f"face_images/known/{filename}"

    contents = await file.read()
    file_path = str(
        storage.save_file(
            relative_path,
            contents,
            content_type=file.content_type or "application/octet-stream",
        )
    )

    # US-FUT-022: Strict media validation before processing
    validation_result = _validate_media_strict(file_path)
    if not validation_result.valid and not validation_result.is_corrupt:
        storage.delete_file(relative_path)
        raise HTTPException(
            status_code=400,
            detail=f"Media validation failed: {'; '.join(validation_result.issues)}",
        )

    # Call AI service
    embedding = None
    quality_score = 0.0
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(
                f"{AI_SERVICE_URL}/embed-face",
                json={"image_path": file_path},
            )
        if resp.status_code == 200:
            result = resp.json()
            if result.get("error"):
                storage.delete_file(relative_path)
                raise HTTPException(status_code=400, detail=result["error"])
            embedding = result.get("embedding")
            quality_score = result.get("quality_score", 0.0)
            if normalized_angle is None:
                normalized_angle = visitor_service.normalize_face_angle(
                    result.get("face_angle")
                )
        else:
            storage.delete_file(relative_path)
            raise HTTPException(status_code=502, detail="AI service returned an error")
    except httpx.RequestError:
        storage.delete_file(relative_path)
        raise HTTPException(
            status_code=503,
            detail="AI service is not available. Please ensure the AI service is running.",
        )

    if not embedding:
        storage.delete_file(relative_path)
        raise HTTPException(status_code=400, detail="Could not generate face embedding from image")

    image_url = relative_path
    try:
        face_data = visitor_service.create_face_data(
            db,
            visitor_id,
            embedding,
            image_url=image_url,
            quality_score=quality_score,
            face_angle=normalized_angle,
            is_primary=len(visitor_service.get_face_data_for_visitor(db, visitor_id)) == 0,
        )

        visitor_service.create_audit_log(
            db, user.organization_id, user.id, "register_face",
            "face_data", str(face_data.id),
        )
    except Exception:
        storage.delete_file(relative_path)
        raise
    return face_data


_ALLOWED_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp"}
_ALLOWED_VIDEO_EXTS = {".mp4", ".avi", ".mov", ".mkv", ".webm"}
_MAX_IMAGE_BYTES = 10 * 1024 * 1024   # 10 MB per image
_MAX_VIDEO_BYTES = 200 * 1024 * 1024  # 200 MB for video


@router.post("/{visitor_id}/media", response_model=schemas.VisitorMediaUploadResult)
async def upload_visitor_media(
    visitor_id: UUID,
    images: Optional[List[UploadFile]] = File(None),
    video: Optional[UploadFile] = File(None),
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Upload images and/or a video for a visitor and generate face embeddings."""
    user = _get_user(db, current_user_id)
    visitor = visitor_service.get_visitor(db, visitor_id)
    if not visitor or visitor.organization_id != user.organization_id:
        raise HTTPException(status_code=404, detail="Visitor not found")

    if not images and not video:
        raise HTTPException(
            status_code=400,
            detail="Provide at least one image or a video file",
        )

    # Validate image types and sizes before saving anything
    for file in images or []:
        ext = os.path.splitext(file.filename or "face.jpg")[1].lower() or ".jpg"
        if ext not in _ALLOWED_IMAGE_EXTS:
            raise HTTPException(
                status_code=400,
                detail=f"Unsupported image format '{ext}'. Allowed: jpg, jpeg, png, webp",
            )
        content = await file.read()
        if len(content) > _MAX_IMAGE_BYTES:
            raise HTTPException(
                status_code=400,
                detail=f"Image '{file.filename}' exceeds 10 MB limit",
            )
        await file.seek(0)

    if video:
        video_ext = os.path.splitext(video.filename or "enrollment.webm")[1].lower() or ".webm"
        if video_ext not in _ALLOWED_VIDEO_EXTS:
            raise HTTPException(
                status_code=400,
                detail=f"Unsupported video format '{video_ext}'. Allowed: mp4, avi, mov, mkv, webm",
            )
        content = await video.read()
        if len(content) > _MAX_VIDEO_BYTES:
            raise HTTPException(
                status_code=400,
                detail="Video exceeds 200 MB limit",
            )
        await video.seek(0)

    saved_images: List[tuple[str, str]] = []
    saved_relative_paths: List[str] = []

    for file in images or []:
        ext = os.path.splitext(file.filename or "face.jpg")[1].lower() or ".jpg"
        filename = f"{uuid_lib.uuid4().hex}{ext}"
        relative_path = f"face_images/known/{visitor_id}/{filename}"
        content = await file.read()
        full_path = storage.save_file(
            relative_path,
            content,
            content_type=file.content_type or "application/octet-stream",
        )
        saved_images.append((str(full_path), relative_path))
        saved_relative_paths.append(relative_path)

    video_path = None
    video_url = None
    if video:
        video_ext = os.path.splitext(video.filename or "enrollment.webm")[1].lower() or ".webm"
        video_filename = f"{uuid_lib.uuid4().hex}{video_ext}"
        video_url = f"raw_videos/visitor-enrollments/{visitor_id}/{video_filename}"
        video_content = await video.read()
        video_path = str(
            storage.save_file(
                video_url,
                video_content,
                content_type=video.content_type or "application/octet-stream",
            )
        )

    result = enroll_media_for_visitor(
        db,
        visitor,
        image_paths=saved_images,
        video_path=video_path,
        video_url=video_url,
        max_faces=visitor_service.MAX_FACE_DATA_PER_VISITOR,
    )

    if result.images_added == 0 and result.video_frames_added == 0:
        # Clean up all saved files — nothing was enrolled
        for relative_path in saved_relative_paths:
            storage.delete_file(relative_path)
        if video_url:
            storage.delete_file(video_url)
        reason = result.warnings[0] if result.warnings else "No face could be detected in the uploaded media"
        raise HTTPException(status_code=400, detail=reason)

    visitor_service.create_audit_log(
        db,
        user.organization_id,
        user.id,
        "upload_visitor_media",
        "visitor",
        str(visitor.id),
        details={
            "images_added": result.images_added,
            "video_frames_added": result.video_frames_added,
            "video_url": result.video_url,
            "warnings": result.warnings[:10],
        },
    )

    return schemas.VisitorMediaUploadResult(
        visitor_id=visitor.id,
        images_added=result.images_added,
        video_frames_added=result.video_frames_added,
        video_url=result.video_url,
        warnings=result.warnings[:10],
        message=(
            "Media processed successfully"
            if not result.warnings
            else "Media processed with warnings"
        ),
    )


@router.post("/{visitor_id}/train")
async def train_visitor(
    visitor_id: UUID,
    augment: bool = False,
    random_erasing: bool = Query(False),
    geometric_transforms: bool = Query(False),
    color_jitter: bool = Query(False),
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Re-generate embeddings for all face images of a visitor.
    If augment is True, generates synthetic variants to improve robustness.
    
    US-FUT-020/021/027: Supports optional augmentation techniques:
    - random_erasing: Random erasing augmentation
    - geometric_transforms: Geometric transformation augmentation
    - color_jitter: Color jittering augmentation
    """
    user = _get_user(db, current_user_id)
    visitor = visitor_service.get_visitor(db, visitor_id)
    if not visitor or visitor.organization_id != user.organization_id:
        raise HTTPException(status_code=404, detail="Visitor not found")

    face_records = visitor_service.get_face_data_for_visitor(db, visitor_id)
    if not face_records:
        raise HTTPException(status_code=400, detail="No face data found for this visitor")

    retrained = 0
    augmented = 0
    errors = []
    
    augmentation_types = []
    if random_erasing:
        augmentation_types.append("random_erasing")
    if geometric_transforms:
        augmentation_types.append("geometric")
    if color_jitter:
        augmentation_types.append("color_jitter")
    
    for face in face_records:
        if not face.image_url:
            continue
        # Resolve image path
        try:
            image_path = str(storage.ensure_local_file(face.image_url))
        except FileNotFoundError:
            errors.append(f"Image not found: {face.image_url}")
            continue
        except RuntimeError as exc:
            errors.append(f"Could not access image {face.image_url}: {exc}")
            continue

        # Optional Augmentation (US-FUT-020/021/027)
        if augment and face.is_primary:
            aug_params = {
                "image_path": image_path,
                "num_variants": 3,
            }
            if augmentation_types:
                aug_params["augmentation_types"] = augmentation_types
            
            try:
                async with httpx.AsyncClient(timeout=30.0) as client:
                    aug_resp = await client.post(
                        f"{AI_SERVICE_URL}/augment-face",
                        json=aug_params,
                    )
                    if aug_resp.status_code == 200:
                        aug_result = aug_resp.json()
                        for aug_path in aug_result.get("augmented_paths", []):
                            emb_resp = await client.post(
                                f"{AI_SERVICE_URL}/embed-face",
                                json={"image_path": aug_path},
                            )
                            if emb_resp.status_code == 200:
                                emb_res = emb_resp.json()
                                if emb_res.get("embedding"):
                                    image_url = os.path.relpath(aug_path, "data").replace("\\", "/")
                                    with open(aug_path, "rb") as handle:
                                        storage.save_file(
                                            image_url,
                                            handle.read(),
                                            content_type="image/jpeg",
                                        )
                                    try:
                                        visitor_service.create_face_data(
                                            db, visitor_id, emb_res["embedding"],
                                            image_url=image_url,
                                            quality_score=emb_res.get("quality_score", 0.0),
                                            face_angle=emb_res.get("face_angle"),
                                            is_primary=False
                                        )
                                        augmented += 1
                                    except Exception:
                                        storage.delete_file(image_url)
                                        raise
            except Exception as e:
                logger.warning("Augmentation failed: %s", e)

        # Standard Retraining
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                resp = await client.post(
                    f"{AI_SERVICE_URL}/embed-face",
                    json={"image_path": image_path},
                )
            if resp.status_code == 200:
                result = resp.json()
                if result.get("embedding"):
                    face.embedding = visitor_service.serialize_embedding_for_storage(result["embedding"])
                    face.quality_score = result.get("quality_score", face.quality_score)
                    updated_angle = visitor_service.normalize_face_angle(result.get("face_angle"))
                    if updated_angle:
                        face.face_angle = updated_angle
                    retrained += 1
                elif result.get("error"):
                    errors.append(f"{face.image_url}: {result['error']}")
        except httpx.RequestError:
            raise HTTPException(
                status_code=503,
                detail="AI service is not available.",
            )

    db.commit()

    visitor_service.create_audit_log(
        db, user.organization_id, user.id, "train",
        "visitor", str(visitor_id),
        details={"retrained": retrained, "augmented": augmented, "errors": errors[:10]},
    )

    return {
        "message": f"Retrained {retrained} and added {augmented} augmented images",
        "retrained": retrained,
        "augmented": augmented,
        "errors": errors[:10],
    }


@router.get("/{visitor_id}/face-data", response_model=List[schemas.FaceData])
async def list_face_data(
    visitor_id: UUID,
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List all face data for a visitor."""
    user = _get_user(db, current_user_id)
    visitor = visitor_service.get_visitor(db, visitor_id)
    if not visitor or visitor.organization_id != user.organization_id:
        raise HTTPException(status_code=404, detail="Visitor not found")

    face_records = visitor_service.get_face_data_for_visitor(db, visitor_id)
    _audit_biometric_read(
        db,
        user,
        action="face_data.list",
        entity_type="visitor",
        entity_id=str(visitor_id),
        details={"face_count": len(face_records)},
    )
    return face_records


@router.delete("/{visitor_id}/face-data/{face_data_id}")
async def delete_face_data(
    visitor_id: UUID,
    face_data_id: UUID,
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Delete a specific face data entry."""
    user = _get_user(db, current_user_id)
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Only admins can delete face data")

    if not visitor_service.delete_face_data(db, face_data_id):
        raise HTTPException(status_code=404, detail="Face data not found")
    return {"message": "Face data deleted"}


@router.post("/{visitor_id}/face-data/{face_data_id}/primary", response_model=schemas.FaceData)
async def set_primary_face_data(
    visitor_id: UUID,
    face_data_id: UUID,
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Mark a face image as the primary reference for a visitor."""
    user = _get_user(db, current_user_id)
    visitor = visitor_service.get_visitor(db, visitor_id)
    if not visitor or visitor.organization_id != user.organization_id:
        raise HTTPException(status_code=404, detail="Visitor not found")

    face = visitor_service.set_primary_face_data(db, visitor_id, face_data_id)
    if not face:
        raise HTTPException(status_code=404, detail="Face data not found")

    visitor_service.create_audit_log(
        db,
        user.organization_id,
        user.id,
        "set_primary_face",
        "face_data",
        str(face.id),
        details={"visitor_id": str(visitor_id)},
    )
    return face


# --- Embedding Search (used by AI service) ---


@router.post("/search", response_model=schemas.EmbeddingSearchResult)
async def search_by_embedding(
    search: schemas.EmbeddingSearchRequest,
    db: Session = Depends(get_db),
    _: None = Depends(_require_internal_key),
):
    """Search for a visitor by face embedding vector (cosine similarity).
    This endpoint is used by the AI service internally and requires X-Internal-API-Key."""
    result = visitor_service.search_visitor_by_embedding(
        db, search.organization_id, search.embedding, search.threshold, search.angle
    )
    if result:
        visitor, confidence, face_data_id, angle_scores = result
        # Audit only HITS — every frame produces a search call so logging
        # misses would saturate the audit table without adding signal.
        if _AUDIT_BIOMETRIC_READS:
            try:
                visitor_service.create_audit_log(
                    db,
                    search.organization_id,
                    None,  # no human user — internal AI service call
                    "visitor.embedding_match",
                    "visitor",
                    str(visitor.id),
                    details={
                        "confidence": float(confidence),
                        "angle": search.angle,
                        "search_backend": (angle_scores or {}).get("search_backend"),
                    },
                )
            except Exception:
                logger.exception("Failed to audit embedding match")
        return schemas.EmbeddingSearchResult(
            visitor=schemas.Visitor.model_validate(visitor),
            confidence=confidence,
            matched=True,
            face_data_id=face_data_id,
            angle_scores=angle_scores,
        )
    return schemas.EmbeddingSearchResult(matched=False)


@router.post("/bulk-import", response_model=schemas.BulkImportResult)
async def bulk_import_visitors(
    file: UploadFile = File(...),
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Bulk import visitors from a CSV file.
    Expected CSV columns: name, email, phone, description, notes, is_known,
    and optionally photo_url/image_url/image_path for face enrollment.
    """
    user = _get_user(db, current_user_id)
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Only admins can bulk import visitors")

    contents = await file.read()
    try:
        text = contents.decode("utf-8")
    except UnicodeDecodeError:
        text = contents.decode("latin-1")

    reader = csv.DictReader(io.StringIO(text))
    rows = list(reader)
    total = len(rows)
    created = 0
    face_enrolled = 0
    errors = []

    for i, row in enumerate(rows, start=2):  # start=2 because row 1 is headers
        name = row.get("name", "").strip()
        if not name:
            errors.append(schemas.BulkImportError(row=i, error="name is required"))
            continue

        try:
            visitor_create = schemas.VisitorCreate(
                organization_id=user.organization_id,
                name=name,
                email=row.get("email", "").strip() or None,
                phone=row.get("phone", "").strip() or None,
                description=row.get("description", "").strip() or None,
                notes=row.get("notes", "").strip() or None,
                is_known=row.get("is_known", "true").strip().lower() in ("true", "1", "yes"),
            )
            created_visitor = visitor_service.create_visitor(db, visitor_create)
            created += 1

            image_source = (
                row.get("photo_url")
                or row.get("image_url")
                or row.get("image_path")
                or row.get("photo")
                or row.get("image")
                or ""
            ).strip()

            if image_source:
                resolved_path = ""
                source_label = image_source
                cleanup_temp_file = False
                try:
                    resolved_path, source_label, cleanup_temp_file = await _resolve_bulk_face_image_source(image_source)
                    enroll_existing_image_path(
                        db,
                        created_visitor,
                        resolved_path,
                        image_url=source_label,
                        is_primary=True,
                    )
                    face_enrolled += 1
                except Exception as face_error:
                    errors.append(
                        schemas.BulkImportError(
                            row=i,
                            error=f"created visitor but face enrollment failed: {face_error}",
                        )
                    )
                finally:
                    if cleanup_temp_file and resolved_path and os.path.exists(resolved_path):
                        try:
                            os.remove(resolved_path)
                        except OSError:
                            pass
        except Exception as e:
            errors.append(schemas.BulkImportError(row=i, error=str(e)))

    visitor_service.create_audit_log(
        db, user.organization_id, user.id, "bulk_import",
        "visitor", None,
        details={"created": created, "total": total, "face_enrolled": face_enrolled},
    )

    return schemas.BulkImportResult(
        total=total,
        created=created,
        face_enrolled=face_enrolled,
        errors=errors[:20],  # Limit error messages
    )
