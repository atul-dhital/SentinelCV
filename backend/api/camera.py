from datetime import datetime, timedelta, timezone
"""Live Camera Session API — webcam-based real-time face recognition."""

from fastapi import APIRouter, Depends, HTTPException
from fastapi.concurrency import run_in_threadpool
from sqlalchemy.orm import Session
from db.base import get_db, SessionLocal
from models import models
from schemas import schemas
from services import user_service, visitor_service
from core.security import get_current_user
from core.realtime import realtime_manager
from uuid import UUID
from typing import List, Optional
import datetime
import base64
import os
import time
import httpx
import cv2
import numpy as np
from core.storage import storage

from services.liveness_service import LivenessDetectionService, create_liveness_score
from schemas.schemas import LivenessScoreCreateRequest

router = APIRouter(prefix="/camera", tags=["Live Camera"])

AI_SERVICE_URL = os.getenv("AI_SERVICE_URL", "http://127.0.0.1:8001")
# G5 quality gate: reject live face crops blurrier than this Laplacian-variance
# threshold before matching/logging. 0 disables. Sharp faces are >>200; genuinely
# blurry crops are <30, so the default rejects only clearly unusable frames.
_LIVE_FACE_SHARPNESS_MIN = float(os.getenv("LIVE_FACE_SHARPNESS_MIN", "30"))

# In-memory store for active session metadata (not DB sessions)
_active_sessions: dict = {}
_SESSION_TIMEOUT_SECONDS = 3600  # 1 hour TTL for inactive sessions
liveness_detector = LivenessDetectionService()


def _cleanup_expired_sessions() -> None:
    """Remove sessions that have exceeded TTL. Call periodically."""
    now = time.time()
    expired = [
        sid for sid, data in _active_sessions.items()
        if now - data.get("last_activity", now) > _SESSION_TIMEOUT_SECONDS
    ]
    for sid in expired:
        del _active_sessions[sid]


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


def _should_trigger_alert(
    db: Session,
    organization_id: UUID,
    trigger_type: str,
    visitor_id: Optional[UUID] = None,
    confidence: float = 0.0,
    camera_id: Optional[UUID] = None,
) -> bool:
    """Check if an alert should be triggered based on alert rules.
    
    Args:
        db: Database session
        organization_id: Organization ID
        trigger_type: Type of trigger (known, unknown, liveness_fail, anomaly)
        visitor_id: Visitor ID if applicable
        confidence: Confidence score for the detection
        camera_id: Camera ID where detection occurred
    
    Returns:
        True if alert should be triggered, False otherwise
    """
    # Get alert config for organization
    config = db.query(models.AlertConfig).filter(
        models.AlertConfig.organization_id == organization_id
    ).first()
    
    # If no config or alerts disabled, don't trigger
    if not config or not config.alerts_enabled:
        return False
    
    # If trigger type is not enabled, don't trigger
    if config.enabled_alert_types and trigger_type not in config.enabled_alert_types:
        return False
    
    # Check min confidence threshold
    if confidence < config.min_confidence_threshold:
        return False
    
    # Get matching rules for this trigger type
    rules = db.query(models.AlertRule).filter(
        models.AlertRule.alert_config_id == config.id,
        models.AlertRule.is_active == True,
        models.AlertRule.trigger_type == trigger_type,
    ).order_by(models.AlertRule.order).limit(10000).all()
    
    # If no active rules for this type, don't trigger
    if not rules:
        return False
    
    # Check if any rule matches
    for rule in rules:
        # Check confidence range
        if rule.min_confidence and confidence < rule.min_confidence:
            continue
        if rule.max_confidence and confidence > rule.max_confidence:
            continue
        
        # Check visitor filter
        if rule.include_visitor_ids and visitor_id:
            if str(visitor_id) not in rule.include_visitor_ids:
                continue
        
        # Check camera filter
        if rule.include_camera_ids and camera_id:
            if str(camera_id) not in rule.include_camera_ids:
                continue
        
        # Rule matches, trigger alert
        return True
    
    return False


# ── Start Session ────────────────────────────────────────────────────────────


@router.post("/start-session", response_model=schemas.CameraSessionResponse)
async def start_session(
    req: schemas.StartSessionRequest,
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Start a new live camera session."""
    user = _get_user(db, current_user_id)

    camera_id = None
    if req.camera_id:
        camera = db.query(models.Camera).filter(
            models.Camera.id == req.camera_id,
            models.Camera.organization_id == user.organization_id,
        ).first()
        if not camera:
            raise HTTPException(status_code=404, detail="Camera not found")
        camera_id = camera.id
        camera.status = "online"
        camera.last_seen = datetime.datetime.now(timezone.utc)

    session = models.CameraSession(
        organization_id=user.organization_id,
        user_id=user.id,
        camera_id=camera_id,
        status="active",
        settings=req.settings or {},
    )
    db.add(session)
    db.commit()
    db.refresh(session)

    # Track in-memory frame counter (not the DB session itself)
    # Include last_activity for TTL cleanup
    _active_sessions[str(session.id)] = {
        "frame_count": 0,
        "detection_count": 0,
        "identification_count": 0,
        "last_activity": time.time(),
    }
    # Cleanup expired sessions periodically
    _cleanup_expired_sessions()

    visitor_service.create_audit_log(
        db, user.organization_id, user.id,
        "create", "camera_session", str(session.id),
    )

    if camera_id:
        await realtime_manager.broadcast(
            str(user.organization_id),
            "camera.status_changed",
            _camera_event_payload(camera),
        )

    return session


# ── Process Frame ────────────────────────────────────────────────────────────


@router.post("/process-frame", response_model=schemas.ProcessFrameResponse)
async def process_frame(
    req: schemas.ProcessFrameRequest,
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Process a single webcam frame: detect faces, generate embeddings, match visitors."""
    start_time = time.time()
    ai_processing_time_ms: Optional[float] = None
    ai_roundtrip_time_ms: Optional[float] = None
    identification_timings: List[float] = []
    user = _get_user(db, current_user_id)

    session = db.query(models.CameraSession).filter(
        models.CameraSession.id == req.session_id,
        models.CameraSession.organization_id == user.organization_id,
        models.CameraSession.status == "active",
    ).first()
    if not session:
        raise HTTPException(status_code=404, detail="Active session not found")

    # Increment frame counter and update last activity time
    mem = _active_sessions.get(str(session.id), {})
    frame_num = mem.get("frame_count", 0) + 1
    mem["frame_count"] = frame_num
    mem["last_activity"] = time.time()  # Update activity timestamp for TTL
    _active_sessions[str(session.id)] = mem

    # Call AI service for face detection + embedding
    detections: List[schemas.DetectionResult] = []
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            ai_start_time = time.time()
            ai_resp = await client.post(
                f"{AI_SERVICE_URL}/realtime/frame-full-process",
                json={"frame_data": req.frame_data},
            )
            ai_roundtrip_time_ms = (time.time() - ai_start_time) * 1000
            if ai_resp.status_code != 200:
                # AI service not available — return empty detections
                elapsed = (time.time() - start_time) * 1000
                return schemas.ProcessFrameResponse(
                    detections=[],
                    frame_number=frame_num,
                    processing_time_ms=round(elapsed, 1),
                    ai_roundtrip_time_ms=round(ai_roundtrip_time_ms, 1),
                )
            ai_result = ai_resp.json()
            if ai_result.get("processing_time_ms") is not None:
                ai_processing_time_ms = float(ai_result.get("processing_time_ms") or 0.0)
    except Exception:
        elapsed = (time.time() - start_time) * 1000
        return schemas.ProcessFrameResponse(
            detections=[], frame_number=frame_num, processing_time_ms=round(elapsed, 1)
        )

    faces = ai_result.get("faces", [])
    persons = [
        schemas.PersonBox(
            bbox=p.get("bbox", {}),
            confidence=float(p.get("confidence", 0.0) or 0.0),
        )
        for p in ai_result.get("persons", [])
        if p.get("bbox")
    ]

    def _process_faces_sync() -> List[schemas.DetectionResult]:
        """Per-face liveness, embedding matching, and DB writes.

        Everything here is sync CPU/DB work (deep-learning liveness, pgvector
        search at ~400ms RTT per query against the hosted database, multiple
        commits). It runs in a worker thread via run_in_threadpool so the event
        loop stays responsive — otherwise a webcam polling every 2.5s starves
        every other request, including session creation and health checks.
        """
        results: List[schemas.DetectionResult] = []

        for face in faces:
            bbox = face.get("bbox", {})
            embedding = face.get("embedding")
            face_angle = visitor_service.normalize_face_angle(face.get("face_angle"))
            if not embedding:
                continue

            # G5 quality gate: skip blurry face crops before matching/logging so
            # low-quality frames can't create false matches or garbage logs.
            if _LIVE_FACE_SHARPNESS_MIN > 0:
                _crop_b64 = face.get("face_crop_b64")
                if _crop_b64:
                    try:
                        _crop = cv2.imdecode(
                            np.frombuffer(base64.b64decode(_crop_b64), np.uint8),
                            cv2.IMREAD_GRAYSCALE,
                        )
                        if _crop is not None:
                            _sharpness = float(cv2.Laplacian(_crop, cv2.CV_64F).var())
                            if _sharpness < _LIVE_FACE_SHARPNESS_MIN:
                                mem["low_quality_skipped"] = mem.get("low_quality_skipped", 0) + 1
                                continue
                    except Exception:
                        pass

            # Search for matching visitor using existing service function
            visitor_id = None
            visitor_name = None
            matched_visitor = None
            matched_face_data_id = None
            confidence = 0.0
            identified = False

            identify_start_time = time.time()
            match_result = visitor_service.search_visitor_by_embedding(
                db, user.organization_id, embedding, threshold=0.6, angle=face_angle
            )
            identification_timings.append((time.time() - identify_start_time) * 1000)
            if match_result:
                matched_visitor, conf, face_data_id, _angle_scores = match_result
                visitor_id = str(matched_visitor.id)
                visitor_name = matched_visitor.name
                confidence = conf
                matched_face_data_id = face_data_id
                identified = True

            # Save face crop if available. Degenerate crops (e.g. a downgraded/fallback
            # detector emitting a tiny patch) are useless to display and pollute the
            # gallery, so reject anything below a usable face size instead of storing it.
            MIN_FACE_CROP_PX = 48
            face_image_path = None
            face_crop_b64 = face.get("face_crop_b64")
            if face_crop_b64:
                try:
                    face_bytes = base64.b64decode(face_crop_b64)
                    crop_img = cv2.imdecode(np.frombuffer(face_bytes, np.uint8), cv2.IMREAD_COLOR)
                    if crop_img is None or min(crop_img.shape[:2]) < MIN_FACE_CROP_PX:
                        face_bytes = None  # too small / unreadable — skip persistence
                except Exception:
                    face_bytes = None

                if face_bytes:
                    face_filename = f"rt_{str(session.id)[:8]}_{frame_num}_{int(time.time())}.jpg"
                    relative_path = f"face_images/{face_filename}"
                    try:
                        storage.save_file(relative_path, face_bytes, content_type="image/jpeg")
                        face_image_path = relative_path
                    except Exception:
                        pass

            # Run liveness on the decoded face crop and reject only concrete spoof signals.
            # Single-frame liveness scores are recorded for audit, but dedicated challenge
            # verification handles the stricter pass/fail flow for real-time identity checks.
            liveness_result = None
            if face_crop_b64:
                try:
                    face_bytes = base64.b64decode(face_crop_b64)
                    nparr = np.frombuffer(face_bytes, np.uint8)
                    face_img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
                    if face_img is not None:
                        liveness_result = liveness_detector.ensemble_detection(
                            frame=face_img,
                            methods=["texture", "deep_learning"],
                        )
                        if liveness_result.attack_detected:
                            identified = False
                            visitor_id = None
                            visitor_name = None
                except Exception:
                    liveness_result = None

            # Match the database backend's expected embedding storage format.
            embedding_stored = None
            try:
                embedding_stored = visitor_service.serialize_embedding_for_storage(embedding)
            except Exception:
                pass

            # Detection de-duplication: for a visitor already logged at this
            # camera within the cooldown window, skip the duplicate DB writes and
            # alerts but still return the detection so the live overlay shows it.
            if identified and not visitor_service.should_log_detection(
                user.organization_id, visitor_id, session.camera_id
            ):
                results.append(schemas.DetectionResult(
                    bbox=bbox,
                    confidence=confidence,
                    identified=identified,
                    visitor_id=visitor_id,
                    visitor_name=visitor_name,
                    face_image_path=face_image_path,
                    face_angle=face_angle,
                ))
                continue

            # Create detection log
            det_log = models.DetectionLog(
                session_id=session.id,
                visitor_id=visitor_id,
                confidence=confidence,
                bbox=bbox,
                face_image_path=face_image_path,
                identified=identified,
                embedding_snapshot=embedding_stored,
            )
            db.add(det_log)

            log_status = "identified" if identified else "unidentified"
            visitor_log = models.VisitorLog(
                organization_id=user.organization_id,
                visitor_id=visitor_id,
                face_data_id=str(matched_face_data_id) if matched_face_data_id else None,
                camera_id=session.camera_id,
                face_image_path=face_image_path,
                confidence=confidence,
                identified=identified,
                status=log_status,
                track_id=frame_num,
                source_video="live_camera",
            )
            db.add(visitor_log)
            db.flush()

            if liveness_result is not None:
                try:
                    quality = liveness_result.quality_metrics or {}
                    individual = liveness_result.details.get("individual_scores", {}) if liveness_result.details else {}
                    create_liveness_score(
                        db,
                        str(user.organization_id),
                        str(visitor_log.id),
                        LivenessScoreCreateRequest(
                            visitor_log_id=str(visitor_log.id),
                            is_live=liveness_result.is_live,
                            overall_score=liveness_result.score,
                            rejection_reason=liveness_result.attack_type if liveness_result.attack_detected else None,
                            texture_score=individual.get("texture"),
                            deep_learning_score=individual.get("deep_learning"),
                            attack_indicators={
                                liveness_result.attack_type: 1.0
                            } if liveness_result.attack_detected and liveness_result.attack_type else {},
                            illumination_score=quality.get("illumination_score"),
                            blur_score=quality.get("blur_score"),
                            noise_level=quality.get("noise_level"),
                            method_used=liveness_result.method,
                            model_version="liveness_v1_quality",
                        ),
                    )
                except Exception:
                    pass

            # Create alert for known visitors (if allowed by alert rules)
            if identified:
                # Check if alerts are enabled and if this alert should be triggered
                should_alert = _should_trigger_alert(
                    db,
                    user.organization_id,
                    trigger_type="known",
                    visitor_id=visitor_id,
                    confidence=confidence,
                    camera_id=session.camera_id,
                )

                if should_alert:
                    matched_visitor.last_detected_at = datetime.datetime.now(timezone.utc)
                    matched_visitor.detection_count = (matched_visitor.detection_count or 0) + 1
                    alert = models.VisitorAlert(
                        session_id=session.id,
                        visitor_id=visitor_id,
                        alert_type="known",
                        message=f"Known visitor '{visitor_name}' detected with {confidence:.0%} confidence",
                    )
                    db.add(alert)

                mem["identification_count"] = mem.get("identification_count", 0) + 1

            # Watchlist hit (G2): typed alert if this identified visitor is watchlisted.
            # Runs once per visit because suppressed duplicates `continue` earlier.
            if identified and visitor_id:
                watch = db.query(models.Watchlist).filter(
                    models.Watchlist.organization_id == user.organization_id,
                    models.Watchlist.visitor_id == visitor_id,
                    models.Watchlist.is_active == True,
                ).first()
                if watch is not None:
                    _wl_msg = f"Watchlist hit [{watch.category}/{watch.severity}]: '{visitor_name}'"
                    if watch.reason:
                        _wl_msg += f" — {watch.reason}"
                    db.add(models.VisitorAlert(
                        session_id=session.id,
                        visitor_id=visitor_id,
                        alert_type="watchlist",
                        message=_wl_msg,
                    ))
                    # G3: route the hit to external channels (Slack/webhook).
                    try:
                        from services.webhook_delivery_service import dispatch_event_async
                        dispatch_event_async(user.organization_id, "watchlist.hit", {
                            "visitor_id": visitor_id,
                            "visitor_name": visitor_name,
                            "category": watch.category,
                            "severity": watch.severity,
                            "reason": watch.reason,
                            "camera_id": str(session.camera_id) if session.camera_id else None,
                            "confidence": confidence,
                        })
                    except Exception:
                        pass

            # Create alert for liveness failures
            if liveness_result is not None and liveness_result.attack_detected and identified:
                should_alert = _should_trigger_alert(
                    db,
                    user.organization_id,
                    trigger_type="liveness_fail",
                    visitor_id=visitor_id,
                    confidence=confidence,
                    camera_id=session.camera_id,
                )

                if should_alert:
                    alert = models.VisitorAlert(
                        session_id=session.id,
                        visitor_id=visitor_id,
                        alert_type="liveness_fail",
                        message=f"Liveness check failed for '{visitor_name}'",
                    )
                    db.add(alert)

            mem["detection_count"] = mem.get("detection_count", 0) + 1

            results.append(schemas.DetectionResult(
                bbox=bbox,
                confidence=confidence,
                identified=identified,
                visitor_id=visitor_id,
                visitor_name=visitor_name,
                face_image_path=face_image_path,
                face_angle=face_angle,
            ))

        # Update session counters in DB
        session.total_frames = frame_num
        session.total_detections = mem.get("detection_count", 0)
        session.total_identifications = mem.get("identification_count", 0)

        db.commit()
        mem["last_activity"] = time.time()  # Update activity timestamp
        _active_sessions[str(session.id)] = mem
        return results

    detections = await run_in_threadpool(_process_faces_sync)

    await realtime_manager.broadcast(
        str(user.organization_id),
        "camera.frame_processed",
        {
            "session_id": str(session.id),
            "frame_number": frame_num,
            "detections": len(detections),
            "identified": sum(1 for d in detections if d.identified),
        },
    )

    elapsed = (time.time() - start_time) * 1000
    identification_time_ms = sum(identification_timings) if identification_timings else 0.0
    average_identification_time_ms = (
        identification_time_ms / len(identification_timings)
        if identification_timings
        else 0.0
    )
    return schemas.ProcessFrameResponse(
        detections=detections,
        persons=persons,
        frame_number=frame_num,
        processing_time_ms=round(elapsed, 1),
        ai_processing_time_ms=round(ai_processing_time_ms, 1) if ai_processing_time_ms is not None else None,
        ai_roundtrip_time_ms=round(ai_roundtrip_time_ms, 1) if ai_roundtrip_time_ms is not None else None,
        identification_time_ms=round(identification_time_ms, 1),
        average_identification_time_ms=round(average_identification_time_ms, 1),
    )


# ── End Session ──────────────────────────────────────────────────────────────


@router.post("/end-session/{session_id}", response_model=schemas.EndSessionResponse)
async def end_session(
    session_id: str,
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """End an active camera session."""
    user = _get_user(db, current_user_id)

    session = db.query(models.CameraSession).filter(
        models.CameraSession.id == session_id,
        models.CameraSession.organization_id == user.organization_id,
    ).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    session.status = "ended"
    session.ended_at = datetime.datetime.now(timezone.utc)

    # Sync final counters from memory
    mem = _active_sessions.pop(str(session.id), {})
    session.total_frames = mem.get("frame_count", session.total_frames)
    session.total_detections = mem.get("detection_count", session.total_detections)
    session.total_identifications = mem.get("identification_count", session.total_identifications)

    # Set camera offline if applicable
    camera_status_payload = None
    if session.camera_id:
        camera = db.query(models.Camera).filter(models.Camera.id == session.camera_id).first()
        if camera:
            other_active_sessions = (
                db.query(models.CameraSession)
                .filter(
                    models.CameraSession.camera_id == session.camera_id,
                    models.CameraSession.status == "active",
                    models.CameraSession.id != session.id,
                )
                .count()
            )
            if other_active_sessions == 0 and camera.status != "offline":
                camera.status = "offline"
                camera_status_payload = _camera_event_payload(camera)

    db.commit()
    db.refresh(session)

    visitor_service.create_audit_log(
        db, user.organization_id, user.id,
        "update", "camera_session", str(session.id),
        details={"action": "ended", "total_frames": session.total_frames},
    )

    if camera_status_payload is not None:
        await realtime_manager.broadcast(
            str(user.organization_id),
            "camera.status_changed",
            camera_status_payload,
        )

    return session


# ── Get Session Logs ─────────────────────────────────────────────────────────


@router.get("/session/{session_id}/logs", response_model=List[schemas.DetectionLogResponse])
async def get_session_logs(
    session_id: str,
    skip: int = 0,
    limit: int = 50,
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get detection logs for a session."""
    user = _get_user(db, current_user_id)

    session = db.query(models.CameraSession).filter(
        models.CameraSession.id == session_id,
        models.CameraSession.organization_id == user.organization_id,
    ).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    logs = (
        db.query(models.DetectionLog)
        .filter(models.DetectionLog.session_id == session.id)
        .order_by(models.DetectionLog.timestamp.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )
    return logs


# ── Manual Assign ────────────────────────────────────────────────────────────


@router.post("/manual-assign")
async def manual_assign(
    req: schemas.ManualAssignRequest,
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Manually assign a detection log to a visitor."""
    user = _get_user(db, current_user_id)

    # Verify the detection log belongs to a session in the user's org before fetching
    det_log = (
        db.query(models.DetectionLog)
        .join(models.CameraSession, models.CameraSession.id == models.DetectionLog.session_id)
        .filter(
            models.DetectionLog.id == req.detection_log_id,
            models.CameraSession.organization_id == user.organization_id,
        )
        .first()
    )
    if not det_log:
        raise HTTPException(status_code=404, detail="Detection log not found")

    session = db.query(models.CameraSession).filter(
        models.CameraSession.id == det_log.session_id,
    ).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    visitor = db.query(models.Visitor).filter(
        models.Visitor.id == req.visitor_id,
        models.Visitor.organization_id == user.organization_id,
    ).first()
    if not visitor:
        raise HTTPException(status_code=404, detail="Visitor not found")

    det_log.visitor_id = visitor.id
    det_log.identified = True
    db.commit()

    return {"message": "Detection assigned to visitor", "visitor_name": visitor.name}


# ── Get Active Sessions ──────────────────────────────────────────────────────


@router.get("/sessions", response_model=List[schemas.CameraSessionResponse])
async def list_sessions(
    status: Optional[str] = None,
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List camera sessions for the user's organization."""
    user = _get_user(db, current_user_id)

    query = db.query(models.CameraSession).filter(
        models.CameraSession.organization_id == user.organization_id,
    )
    if status:
        query = query.filter(models.CameraSession.status == status)

    sessions = query.order_by(models.CameraSession.started_at.desc()).limit(50).all()
    return sessions
