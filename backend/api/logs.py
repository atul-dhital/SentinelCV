from datetime import datetime, timedelta, timezone
import os
import logging
import math
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from db.base import get_db
from models import models
from schemas import schemas
from services import visitor_service, user_service
from services.redis_service import get_redis_service
from services.visitor_media_service import enroll_existing_image_path
from core.security import get_current_user
from core.storage import storage
from core.realtime import realtime_manager
from uuid import UUID
from typing import Any, Dict, List, Optional, Sequence
import csv
import io
import requests

_INTERNAL_KEY_RATE_LIMIT = int(os.getenv("INTERNAL_KEY_RATE_LIMIT", "300"))
_INTERNAL_KEY_RATE_WINDOW = int(os.getenv("INTERNAL_KEY_RATE_WINDOW_SECONDS", "60"))


def _require_internal_key(
    request: Request,
    x_internal_api_key: Optional[str] = Header(None, alias="X-Internal-API-Key"),
) -> None:
    # Constant-time comparison via core.security to prevent timing oracle attacks.
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

router = APIRouter(prefix="/logs", tags=["Visitor Logs"])
logger = logging.getLogger(__name__)
AI_SERVICE_URL = os.getenv("AI_SERVICE_URL", "http://127.0.0.1:8001").replace("://localhost", "://127.0.0.1")


def _cosine_similarity(vec_a: Sequence[float], vec_b: Sequence[float]) -> float:
    dimensions = min(len(vec_a), len(vec_b))
    if dimensions <= 0:
        return 0.0

    a_values = [float(value) for value in vec_a[:dimensions]]
    b_values = [float(value) for value in vec_b[:dimensions]]

    dot = sum(a * b for a, b in zip(a_values, b_values))
    norm_a = math.sqrt(sum(a * a for a in a_values))
    norm_b = math.sqrt(sum(b * b for b in b_values))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0

    return max(-1.0, min(1.0, dot / (norm_a * norm_b)))


def _embed_image_via_ai(face_image_path: str) -> Optional[List[float]]:
    if not face_image_path or str(face_image_path).startswith("http"):
        return None

    if os.path.isabs(str(face_image_path)):
        absolute_path = face_image_path
        if not os.path.exists(absolute_path):
            return None
    else:
        try:
            absolute_path = str(storage.ensure_local_file(face_image_path))
        except (FileNotFoundError, RuntimeError):
            return None

    try:
        response = requests.post(
            f"{AI_SERVICE_URL}/embed-face",
            json={"image_path": absolute_path},
            timeout=20,
        )
    except Exception as exc:
        logger.warning("AI embedding request failed for %s: %s", absolute_path, exc)
        return None

    if response.status_code != 200:
        return None

    try:
        payload = response.json()
    except ValueError:
        return None

    raw_embedding = payload.get("embedding")
    if not isinstance(raw_embedding, list) or not raw_embedding:
        return None

    try:
        return [float(value) for value in raw_embedding]
    except (TypeError, ValueError):
        return None


def _load_detection_embedding_map(
    db: Session,
    organization_id: UUID,
    face_paths: List[str],
) -> Dict[str, List[float]]:
    if not face_paths:
        return {}

    rows = (
        db.query(models.DetectionLog.face_image_path, models.DetectionLog.embedding_snapshot)
        .join(models.CameraSession, models.DetectionLog.session_id == models.CameraSession.id)
        .filter(
            models.CameraSession.organization_id == organization_id,
            models.DetectionLog.face_image_path.in_(face_paths),
            models.DetectionLog.embedding_snapshot.isnot(None),
        )
        .order_by(models.DetectionLog.timestamp.desc())
        .limit(10000).all()
    )

    mapping: Dict[str, List[float]] = {}
    for face_path, raw_embedding in rows:
        if not face_path or face_path in mapping:
            continue

        parsed = visitor_service.parse_embedding_payload(raw_embedding)
        if parsed:
            mapping[face_path] = parsed

    return mapping


def _resolve_log_embedding(
    log: models.VisitorLog,
    embedding_map: Dict[str, List[float]],
    ai_cache: Dict[str, Optional[List[float]]],
) -> Optional[List[float]]:
    if not log.face_image_path:
        return None

    face_path = str(log.face_image_path)
    existing = embedding_map.get(face_path)
    if existing:
        return existing

    if face_path in ai_cache:
        return ai_cache[face_path]

    ai_embedding = _embed_image_via_ai(face_path)
    ai_cache[face_path] = ai_embedding
    if ai_embedding:
        embedding_map[face_path] = ai_embedding

    return ai_embedding


def _propagate_assignment_to_similar_logs(
    db: Session,
    organization_id: UUID,
    source_log: models.VisitorLog,
    visitor_id: UUID,
    similarity_threshold: float,
    lookback_days: int,
    max_candidates: int,
) -> int:
    if not source_log.face_image_path:
        return 0

    since = datetime.utcnow() - timedelta(days=lookback_days)
    candidates = (
        db.query(models.VisitorLog)
        .filter(
            models.VisitorLog.organization_id == organization_id,
            models.VisitorLog.id != source_log.id,
            models.VisitorLog.visitor_id.is_(None),
            models.VisitorLog.face_image_path.isnot(None),
            models.VisitorLog.status.in_(["unidentified", "detected"]),
            models.VisitorLog.timestamp >= since,
        )
        .order_by(models.VisitorLog.timestamp.desc())
        .limit(max_candidates)
        .all()
    )

    if not candidates:
        return 0

    face_paths = [str(source_log.face_image_path)] + [str(log.face_image_path) for log in candidates if log.face_image_path]
    embedding_map = _load_detection_embedding_map(db, organization_id, face_paths)
    ai_cache: Dict[str, Optional[List[float]]] = {}

    source_embedding = _resolve_log_embedding(source_log, embedding_map, ai_cache)
    if not source_embedding:
        return 0

    assigned_count = 0
    for candidate in candidates:
        candidate_embedding = _resolve_log_embedding(candidate, embedding_map, ai_cache)
        if not candidate_embedding:
            continue

        similarity = _cosine_similarity(source_embedding, candidate_embedding)
        if similarity < similarity_threshold:
            continue

        candidate.visitor_id = visitor_id
        candidate.identified = True
        candidate.status = "reviewed"
        assigned_count += 1

    if assigned_count:
        db.commit()

    return assigned_count


def _get_user(db: Session, user_id: str) -> models.User:
    user = user_service.get_user_by_id(db, user_id)
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    return user


def _build_log_response(
    log: models.VisitorLog,
    visitor_map: dict[str, models.Visitor],
    face_summary: dict[str, dict],
) -> schemas.VisitorLog:
    """Attach visitor metadata and thumbnails to a log response."""
    item = schemas.VisitorLog.model_validate(log)
    visitor = visitor_map.get(str(log.visitor_id)) if log.visitor_id else None

    if visitor:
        summary = face_summary.get(str(visitor.id), {})
        item.visitor_name = visitor.name or "Unidentified"
        item.visitor_known = visitor.is_known
        item.visitor_image_url = summary.get("primary_face_image_url") or log.face_image_path
    else:
        if log.visitor_id:
            item.visitor_name = f"Visitor {str(log.visitor_id)[:8]}"
        else:
            item.visitor_name = "Unidentified"
        item.visitor_known = False
        item.visitor_image_url = log.face_image_path

    if not item.visitor_image_url and log.face_image_path:
        item.visitor_image_url = log.face_image_path

    return item


@router.get("/", response_model=schemas.PaginatedResponse)
def list_logs(
    status: Optional[str] = None,
    camera_id: Optional[UUID] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    search: Optional[str] = None,
    page: int = 1,
    limit: int = 20,
    after_cursor: Optional[str] = None,
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List visitor detection logs.

    Supports two pagination modes:
    - Offset (default): ?page=N&limit=N
    - Cursor (efficient for large tables): ?after_cursor=<ISO-timestamp>&limit=N
      Returns the next page's cursor in ``next_cursor`` of the response.
    """
    user = _get_user(db, current_user_id)

    # Cursor mode: filter by timestamp rather than OFFSET to avoid O(N) scans.
    cursor_dt: Optional[datetime] = None
    if after_cursor:
        try:
            cursor_dt = datetime.fromisoformat(after_cursor.replace("Z", "+00:00"))
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid after_cursor format; use ISO 8601")

    if cursor_dt is not None:
        # Override date_to with cursor so the service returns rows before the cursor.
        date_to = cursor_dt.isoformat()
        skip = 0
        page = 1
    else:
        skip = (page - 1) * limit

    logs, total = visitor_service.get_logs(
        db, user.organization_id,
        status=status, camera_id=camera_id,
        date_from=date_from, date_to=date_to,
        search=search,
        skip=skip, limit=limit,
    )
    visitor_ids = [log.visitor_id for log in logs if log.visitor_id]
    visitors = (
        db.query(models.Visitor)
        .filter(
            models.Visitor.organization_id == user.organization_id,
            models.Visitor.id.in_(visitor_ids) if visitor_ids else True,
        )
        .limit(100000).all()
        if visitor_ids
        else []
    )
    visitor_map = {str(visitor.id): visitor for visitor in visitors}
    face_summary = visitor_service.get_face_summary_for_visitors(db, visitor_ids)
    pages = (total + limit - 1) // limit

    # Emit next_cursor = timestamp of the last returned log (for cursor mode)
    next_cursor: Optional[str] = None
    if logs and (after_cursor is not None or cursor_dt is not None):
        last_ts = logs[-1].timestamp
        if last_ts:
            tz = timezone.utc
            if last_ts.tzinfo is None:
                last_ts = last_ts.replace(tzinfo=tz)
            next_cursor = last_ts.isoformat()

    return schemas.PaginatedResponse(
        items=[_build_log_response(log, visitor_map, face_summary) for log in logs],
        total=total,
        page=page,
        limit=limit,
        pages=pages,
        next_cursor=next_cursor,
    )


@router.get("/unidentified", response_model=schemas.PaginatedResponse)
async def list_unidentified_logs(
    page: int = 1,
    limit: int = 20,
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get logs that need manual review (unidentified/detected)."""
    user = _get_user(db, current_user_id)
    skip = (page - 1) * limit
    logs, total = visitor_service.get_unidentified_logs(
        db, user.organization_id, skip=skip, limit=limit,
    )
    visitor_ids = [log.visitor_id for log in logs if log.visitor_id]
    visitors = (
        db.query(models.Visitor)
        .filter(
            models.Visitor.organization_id == user.organization_id,
            models.Visitor.id.in_(visitor_ids) if visitor_ids else True,
        )
        .limit(100000).all()
        if visitor_ids
        else []
    )
    visitor_map = {str(visitor.id): visitor for visitor in visitors}
    face_summary = visitor_service.get_face_summary_for_visitors(db, visitor_ids)
    pages = (total + limit - 1) // limit
    return schemas.PaginatedResponse(
        items=[_build_log_response(log, visitor_map, face_summary) for log in logs],
        total=total,
        page=page,
        limit=limit,
        pages=pages,
    )


@router.get("/export")
async def export_logs(
    format: Optional[str] = "csv",
    status: Optional[str] = None,
    camera_id: Optional[UUID] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    search: Optional[str] = None,
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Export logs as CSV or Excel file. Use ?format=csv or ?format=excel."""
    user = _get_user(db, current_user_id)
    visitor_service.create_audit_log(
        db, user.organization_id, user.id, "export_logs", "visitor_log", None,
        details={"format": format, "status": status, "camera_id": str(camera_id) if camera_id else None},
    )
    logs, _ = visitor_service.get_logs(
        db, user.organization_id,
        status=status, camera_id=camera_id,
        date_from=date_from, date_to=date_to,
        search=search,
        skip=0, limit=10000,
    )

    headers_row = [
        "ID", "Timestamp", "Status", "Confidence", "Identified",
        "Visitor ID", "Camera ID", "Face Image", "Source Video",
    ]
    rows = []
    for log in logs:
        rows.append([
            str(log.id),
            str(log.timestamp),
            log.status,
            log.confidence,
            log.identified,
            str(log.visitor_id) if log.visitor_id else "",
            str(log.camera_id) if log.camera_id else "",
            log.face_image_path or "",
            log.source_video or "",
        ])

    if format == "excel":
        try:
            from openpyxl import Workbook
            wb = Workbook()
            ws = wb.active
            ws.title = "Visitor Logs"
            ws.append(headers_row)
            for row in rows:
                ws.append(row)

            output = io.BytesIO()
            wb.save(output)
            output.seek(0)

            return StreamingResponse(
                output,
                media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                headers={"Content-Disposition": "attachment; filename=visitor_logs.xlsx"},
            )
        except ImportError:
            raise HTTPException(
                status_code=500,
                detail="Excel export requires openpyxl. Install it with: pip install openpyxl",
            )
    else:
        # Default CSV export
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(headers_row)
        for row in rows:
            writer.writerow(row)

        output.seek(0)
        return StreamingResponse(
            iter([output.getvalue()]),
            media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=visitor_logs.csv"},
        )


_DASHBOARD_STATS_TTL = int(os.getenv("DASHBOARD_STATS_CACHE_TTL_SECONDS", "15"))


@router.get("/stats/dashboard", response_model=schemas.DashboardStats)
def get_dashboard_stats(
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get dashboard statistics for the user's organization.

    Results are cached in Redis for DASHBOARD_STATS_CACHE_TTL_SECONDS
    (default 15s) so repeated dashboard refreshes do not trigger full-table
    COUNT scans on every request.
    """
    import json as _json
    from services.redis_service import get_redis_service

    user = _get_user(db, current_user_id)
    org_id_str = str(user.organization_id)
    cache_key = f"sentinelcv:stats:{org_id_str}"

    redis_svc = get_redis_service()
    cached = redis_svc.cache_get(cache_key)
    if cached:
        try:
            return _json.loads(cached)
        except Exception:
            pass  # stale/corrupt cache — recompute

    stats = visitor_service.get_dashboard_stats(db, user.organization_id)
    try:
        redis_svc.cache_set(cache_key, _json.dumps(stats), ttl=_DASHBOARD_STATS_TTL)
    except Exception:
        pass  # Redis unavailable — still return live stats

    return stats


@router.get("/{log_id}", response_model=schemas.VisitorLog)
async def get_log(
    log_id: UUID,
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get a single log entry by ID."""
    user = _get_user(db, current_user_id)
    log = visitor_service.get_log(db, log_id)
    if not log or log.organization_id != user.organization_id:
        raise HTTPException(status_code=404, detail="Log not found")
    visitor_map = {}
    face_summary = {}
    if log.visitor_id:
        visitor = (
            db.query(models.Visitor)
            .filter(
                models.Visitor.organization_id == user.organization_id,
                models.Visitor.id == log.visitor_id,
            )
            .first()
        )
        if visitor:
            visitor_map[str(visitor.id)] = visitor
            face_summary = visitor_service.get_face_summary_for_visitors(db, [visitor.id])
    return _build_log_response(log, visitor_map, face_summary)


@router.post("/", response_model=schemas.VisitorLog, dependencies=[Depends(_require_internal_key)])
async def create_log(
    log: schemas.VisitorLogCreate,
    db: Session = Depends(get_db),
):
    """Create a new visitor log entry. Internal AI service only — requires X-Internal-API-Key header."""
    from services.alert_email_service import maybe_send_alert_email

    created = visitor_service.log_visitor_event(db, log)
    await realtime_manager.broadcast(
        str(created.organization_id),
        "log.created",
        {
            "id": str(created.id),
            "status": created.status,
            "identified": created.identified,
            "visitor_id": str(created.visitor_id) if created.visitor_id else None,
            "camera_id": str(created.camera_id) if created.camera_id else None,
            "timestamp": created.timestamp.isoformat() if created.timestamp else None,
        },
    )

    # Fire alert email if org rules match — non-blocking, all exceptions caught inside.
    camera_name = "Unknown Camera"
    if created.camera_id:
        cam = db.query(models.Camera).filter(models.Camera.id == created.camera_id).first()
        if cam:
            camera_name = cam.name or camera_name

    visitor_name: Optional[str] = None
    if created.visitor_id:
        vis = visitor_service.get_visitor(db, created.visitor_id)
        if vis:
            visitor_name = vis.name

    maybe_send_alert_email(
        db=db,
        organization_id=created.organization_id,
        log_id=str(created.id),
        camera_name=camera_name,
        visitor_name=visitor_name,
        confidence=float(created.confidence or 0),
        identified=bool(created.identified),
    )

    # Invalidate the dashboard stats cache for this org so the next request
    # reflects the newly created log immediately rather than serving stale data.
    try:
        from services.redis_service import get_redis_service as _get_redis
        _get_redis().cache_delete(f"sentinelcv:stats:{created.organization_id}")
    except Exception:
        pass  # Redis unavailable — stats will expire naturally

    return created


@router.post("/{log_id}/assign", response_model=schemas.VisitorLog)
async def assign_log_to_visitor(
    log_id: UUID,
    assignment: schemas.LogAssignRequest,
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Manually assign an unidentified log to a known visitor."""
    user = _get_user(db, current_user_id)
    log = visitor_service.get_log(db, log_id)
    if not log or log.organization_id != user.organization_id:
        raise HTTPException(status_code=404, detail="Log not found")

    visitor = visitor_service.get_visitor(db, assignment.visitor_id)
    if not visitor or visitor.organization_id != user.organization_id:
        raise HTTPException(status_code=404, detail="Visitor not found")

    result = visitor_service.assign_log_to_visitor(db, log, assignment.visitor_id)
    propagated_count = 0
    propagation_error = None

    if assignment.propagate_similar:
        try:
            propagated_count = _propagate_assignment_to_similar_logs(
                db=db,
                organization_id=user.organization_id,
                source_log=result,
                visitor_id=assignment.visitor_id,
                similarity_threshold=float(assignment.similarity_threshold),
                lookback_days=int(assignment.lookback_days),
                max_candidates=int(assignment.max_candidates),
            )
        except Exception as exc:
            propagation_error = str(exc)
            logger.exception("Failed to propagate assignment for log %s", log_id)

    visitor_service.create_audit_log(
        db, user.organization_id, user.id, "assign_log",
        "visitor_log", str(log_id),
        details={
            "visitor_id": str(assignment.visitor_id),
            "propagate_similar": assignment.propagate_similar,
            "similarity_threshold": assignment.similarity_threshold,
            "lookback_days": assignment.lookback_days,
            "max_candidates": assignment.max_candidates,
            "propagated_count": propagated_count,
            "propagation_error": propagation_error,
        },
    )
    return result


@router.post("/{log_id}/create-visitor", response_model=schemas.Visitor)
async def create_visitor_from_log(
    log_id: UUID,
    data: schemas.LogCreateVisitorRequest,
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Create a new visitor from an unidentified log entry and assign it."""
    user = _get_user(db, current_user_id)
    log = visitor_service.get_log(db, log_id)
    if not log or log.organization_id != user.organization_id:
        raise HTTPException(status_code=404, detail="Log not found")

    # Create new visitor
    visitor_create = schemas.VisitorCreate(
        organization_id=user.organization_id,
        name=data.name,
        email=data.email,
        phone=data.phone,
        notes=data.notes,
        is_known=True,
    )
    new_visitor = visitor_service.create_visitor(db, visitor_create)

    # Assign log to new visitor
    visitor_service.assign_log_to_visitor(db, log, new_visitor.id)

    # If the log already has a captured face image, enroll it immediately so
    # the new visitor can show up with a thumbnail and recognition template.
    if log.face_image_path and not str(log.face_image_path).startswith("http"):
        if os.path.isabs(str(log.face_image_path)):
            face_path = str(log.face_image_path)
        else:
            try:
                face_path = str(storage.ensure_local_file(str(log.face_image_path)))
            except (FileNotFoundError, RuntimeError):
                face_path = None
        if face_path and os.path.exists(face_path):
            try:
                enroll_existing_image_path(
                    db,
                    new_visitor,
                    face_path,
                    image_url=log.face_image_path,
                    is_primary=True,
                )
            except Exception as exc:
                print(f"[Backend] Failed to enroll log face image for visitor {new_visitor.id}: {exc}")

    visitor_service.create_audit_log(
        db, user.organization_id, user.id, "create_visitor_from_log",
        "visitor", str(new_visitor.id),
        details={"log_id": str(log_id)},
    )
    return new_visitor


@router.post("/{log_id}/confirm", response_model=schemas.VisitorLog)
async def confirm_identification(
    log_id: UUID,
    data: schemas.LogConfirmRequest,
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Confirm or reject an AI identification. Sets status to 'reviewed'."""
    user = _get_user(db, current_user_id)
    log = visitor_service.get_log(db, log_id)
    if not log or log.organization_id != user.organization_id:
        raise HTTPException(status_code=404, detail="Log not found")

    if data.confirmed:
        log.status = "reviewed"
        log.identified = True
        if data.visitor_id:
            log.visitor_id = data.visitor_id
    else:
        # Reject: mark as unidentified and clear visitor assignment
        log.status = "unidentified"
        log.identified = False
        log.visitor_id = None

    db.commit()
    db.refresh(log)

    visitor_service.create_audit_log(
        db, user.organization_id, user.id,
        "confirm_identification" if data.confirmed else "reject_identification",
        "visitor_log", str(log_id),
    )
    return log
