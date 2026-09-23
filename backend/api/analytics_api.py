from datetime import datetime, timedelta, timezone
"""S18: Advanced Analytics & Insights — accuracy dashboard, patterns, health, reports."""

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from sqlalchemy import func, extract
from db.base import get_db, engine
from models import models
from schemas import schemas
from services import user_service
from core.security import get_current_user
from core.paths import BACKEND_DIR, DATA_DIR
from typing import Optional, Dict, List, Any
from collections import Counter
import datetime
import csv
import io
import json
import os
import requests
import time
from pathlib import Path

router = APIRouter(prefix="/analytics", tags=["Analytics"])

AI_SERVICE_URL = os.getenv("AI_SERVICE_URL", "http://127.0.0.1:8001").replace("://localhost", "://127.0.0.1")
SYSTEM_HEALTH_CACHE_TTL_SECONDS = 15
_system_health_cache: dict[str, tuple[float, schemas.SystemHealthMetrics]] = {}


def _get_user(db: Session, user_id: str) -> models.User:
    user = user_service.get_user_by_id(db, user_id)
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    return user


def _get_database_size_mb() -> float:
    """Resolve the active SQLite database path correctly and return its size."""
    if engine.url.get_backend_name() != "sqlite":
        return 0.0

    database_path = engine.url.database
    if not database_path:
        return 0.0

    path = Path(database_path)
    if not path.is_absolute():
        path = (Path(BACKEND_DIR) / path).resolve()

    if not path.exists():
        return 0.0
    return path.stat().st_size / (1024 * 1024)


def _normalize_timestamp(value: Optional[datetime.datetime]) -> Optional[datetime.datetime]:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


@router.get("/accuracy-dashboard", response_model=schemas.AccuracyDashboard)
async def get_accuracy_dashboard(
    days: int = 30,
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """US-AN-001: Get recognition accuracy dashboard with trends."""
    user = _get_user(db, current_user_id)
    org_id = user.organization_id
    cutoff = datetime.datetime.now(timezone.utc) - datetime.timedelta(days=days)

    # Use database-side aggregation instead of loading all rows
    total = db.query(func.count(models.VisitorLog.id)).filter(
        models.VisitorLog.organization_id == org_id,
        models.VisitorLog.timestamp >= cutoff,
    ).scalar() or 0

    logs = db.query(models.VisitorLog).filter(
        models.VisitorLog.organization_id == org_id,
        models.VisitorLog.timestamp >= cutoff,
    ).limit(10000).all()  # Cap at 10k rows to prevent memory spike
    identified = sum(1 for l in logs if l.identified)
    overall_accuracy = identified / total if total > 0 else 0.0

    # Daily accuracy breakdown
    daily = {}
    for log in logs:
        day = log.timestamp.strftime("%Y-%m-%d")
        if day not in daily:
            daily[day] = {"date": day, "total": 0, "identified": 0}
        daily[day]["total"] += 1
        if log.identified:
            daily[day]["identified"] += 1

    daily_accuracy = []
    for day_data in sorted(daily.values(), key=lambda x: x["date"]):
        day_data["accuracy"] = round(
            day_data["identified"] / day_data["total"] if day_data["total"] > 0 else 0, 4
        )
        daily_accuracy.append(day_data)

    # Confidence distribution
    conf_dist = {"0.0-0.3": 0, "0.3-0.5": 0, "0.5-0.7": 0, "0.7-0.8": 0, "0.8-0.9": 0, "0.9-1.0": 0}
    for log in logs:
        c = log.confidence
        if c < 0.3:
            conf_dist["0.0-0.3"] += 1
        elif c < 0.5:
            conf_dist["0.3-0.5"] += 1
        elif c < 0.7:
            conf_dist["0.5-0.7"] += 1
        elif c < 0.8:
            conf_dist["0.7-0.8"] += 1
        elif c < 0.9:
            conf_dist["0.8-0.9"] += 1
        else:
            conf_dist["0.9-1.0"] += 1

    # Top misidentified (logs that were reviewed/reassigned)
    reviewed_logs = db.query(models.VisitorLog).filter(
        models.VisitorLog.organization_id == org_id,
        models.VisitorLog.status == "reviewed",
        models.VisitorLog.timestamp >= cutoff,
    ).limit(10).all()
    top_misidentified = [
        {"log_id": str(l.id), "confidence": l.confidence, "visitor_id": str(l.visitor_id) if l.visitor_id else None}
        for l in reviewed_logs
    ]

    return schemas.AccuracyDashboard(
        overall_accuracy=round(overall_accuracy, 4),
        daily_accuracy=daily_accuracy,
        confidence_distribution=conf_dist,
        top_misidentified=top_misidentified,
    )


@router.get("/visitor-patterns", response_model=schemas.VisitorPatternAnalysis)
async def get_visitor_patterns(
    days: int = 30,
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """US-AN-002: Analyze visitor traffic patterns."""
    user = _get_user(db, current_user_id)
    org_id = user.organization_id
    cutoff = datetime.datetime.now(timezone.utc) - datetime.timedelta(days=days)

    # Load logs with limit to prevent memory exhaustion
    logs = db.query(models.VisitorLog).filter(
        models.VisitorLog.organization_id == org_id,
        models.VisitorLog.timestamp >= cutoff,
    ).limit(50000).all()  # Cap at 50k rows for analysis

    # Peak hours
    hour_counts = {}
    for log in logs:
        h = log.timestamp.hour
        hour_counts[h] = hour_counts.get(h, 0) + 1
    peak_hours = [{"hour": h, "count": c} for h, c in sorted(hour_counts.items())]

    # Daily trends
    daily = {}
    for log in logs:
        day = log.timestamp.strftime("%Y-%m-%d")
        if day not in daily:
            daily[day] = {"date": day, "total": 0, "identified": 0, "unidentified": 0}
        daily[day]["total"] += 1
        if log.identified:
            daily[day]["identified"] += 1
        else:
            daily[day]["unidentified"] += 1
    daily_trends = sorted(daily.values(), key=lambda x: x["date"])

    # Frequent visitors
    visitor_counts = {}
    for log in logs:
        if log.visitor_id:
            vid = str(log.visitor_id)
            visitor_counts[vid] = visitor_counts.get(vid, 0) + 1

    top_visitor_ids = [vid for vid, _ in sorted(visitor_counts.items(), key=lambda x: -x[1])[:10]]
    visitors_by_id = {
        str(v.id): v
        for v in db.query(models.Visitor).filter(models.Visitor.id.in_(top_visitor_ids)).limit(100).all()
    }
    frequent = [
        {
            "visitor_id": vid,
            "name": visitors_by_id[vid].name if vid in visitors_by_id else "Unknown",
            "count": visitor_counts[vid],
        }
        for vid in top_visitor_ids
    ]

    avg_daily = len(logs) / max(days, 1)

    return schemas.VisitorPatternAnalysis(
        peak_hours=peak_hours,
        daily_trends=daily_trends,
        frequent_visitors=frequent,
        avg_daily_visitors=round(avg_daily, 2),
    )


@router.get("/emotion-analytics", response_model=schemas.EmotionAnalyticsSummary)
async def get_emotion_analytics(
    lookback_days: int = Query(7, ge=1, le=365),
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """US-FUT-035/US-FUT-004: Aggregate emotion analytics across the org."""
    user = _get_user(db, current_user_id)
    cutoff = datetime.datetime.now(timezone.utc) - datetime.timedelta(days=lookback_days)

    events = (
        db.query(models.BehaviorEvent)
        .filter(models.BehaviorEvent.organization_id == user.organization_id)
        .filter(models.BehaviorEvent.source == "emotion_detection")
        .filter(models.BehaviorEvent.created_at >= cutoff)
        .order_by(models.BehaviorEvent.created_at.asc())
        .limit(50000)  # Cap at 50k events to prevent memory bloat
        .all()
    )

    emotion_counts: Dict[str, int] = {}
    valences: List[float] = []
    arousals: List[float] = []
    timeline: Dict[str, Dict[str, Any]] = {}

    for event in events:
        details = event.details or {}
        dominant = details.get("dominant_emotion") or event.action or "neutral"
        emotion_counts[dominant] = emotion_counts.get(dominant, 0) + 1
        valence = details.get("valence")
        arousal = details.get("arousal")
        if isinstance(valence, (int, float)):
            valences.append(float(valence))
        if isinstance(arousal, (int, float)):
            arousals.append(float(arousal))

        created_at = _normalize_timestamp(event.created_at)
        if created_at is None:
            continue
        day_key = created_at.strftime("%Y-%m-%d")
        day_bucket = timeline.setdefault(
            day_key,
            {
                "date": day_key,
                "total_events": 0,
                "emotion_counts": {},
                "valences": [],
                "arousals": [],
            },
        )
        day_bucket["total_events"] += 1
        day_bucket["emotion_counts"][dominant] = day_bucket["emotion_counts"].get(dominant, 0) + 1
        if isinstance(valence, (int, float)):
            day_bucket["valences"].append(float(valence))
        if isinstance(arousal, (int, float)):
            day_bucket["arousals"].append(float(arousal))

    total_events = sum(emotion_counts.values())
    emotion_distribution = {
        key: round(count / total_events, 4) if total_events else 0.0
        for key, count in emotion_counts.items()
    }

    dominant_emotion = max(emotion_counts, key=emotion_counts.get) if emotion_counts else "unknown"

    timeline_points: List[schemas.EmotionAnalyticsTimelinePoint] = []
    for day_key in sorted(timeline.keys()):
        bucket = timeline[day_key]
        day_counts = bucket["emotion_counts"]
        day_dominant = max(day_counts, key=day_counts.get) if day_counts else "unknown"
        day_valences = bucket["valences"]
        day_arousals = bucket["arousals"]
        timeline_points.append(
            schemas.EmotionAnalyticsTimelinePoint(
                date=day_key,
                total_events=bucket["total_events"],
                dominant_emotion=day_dominant,
                avg_valence=round(sum(day_valences) / len(day_valences), 4) if day_valences else 0.0,
                avg_arousal=round(sum(day_arousals) / len(day_arousals), 4) if day_arousals else 0.0,
            )
        )

    return schemas.EmotionAnalyticsSummary(
        lookback_days=lookback_days,
        since=cutoff.isoformat(),
        total_events=total_events,
        dominant_emotion=dominant_emotion,
        avg_valence=round(sum(valences) / len(valences), 4) if valences else 0.0,
        avg_arousal=round(sum(arousals) / len(arousals), 4) if arousals else 0.0,
        emotion_distribution=emotion_distribution,
        emotion_counts=emotion_counts,
        timeline=timeline_points,
        generated_at=datetime.datetime.now(timezone.utc).isoformat(),
    )


@router.get("/visitor-flow", response_model=schemas.VisitorFlowAnalytics)
async def get_visitor_flow(
    lookback_hours: int = Query(24, ge=1, le=720),
    camera_id: Optional[str] = Query(None),
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """US-FUT-039: Visitor flow analytics with dwell time and heatmap grid."""
    user = _get_user(db, current_user_id)
    since = datetime.datetime.now(timezone.utc) - datetime.timedelta(hours=lookback_hours)

    log_query = db.query(models.VisitorLog).filter(
        models.VisitorLog.organization_id == user.organization_id,
        models.VisitorLog.timestamp >= since,
    )
    if camera_id:
        log_query = log_query.filter(models.VisitorLog.camera_id == camera_id)
    logs = log_query.limit(100000).all()  # Cap at 100k to allow hourly analysis without memory bloat

    total_events = len(logs)
    unique_visitors = len({str(log.visitor_id) for log in logs if log.visitor_id})
    identified = sum(1 for log in logs if log.identified)

    hourly_counts: Counter = Counter()
    for log in logs:
        created = _normalize_timestamp(log.timestamp)
        if created is None:
            continue
        bucket = created.replace(minute=0, second=0, microsecond=0).isoformat()
        hourly_counts[bucket] += 1

    hourly_timeline = [
        schemas.VisitorFlowHourlyPoint(hour=hour, visitor_events=count)
        for hour, count in sorted(hourly_counts.items())
    ]

    camera_counts: Counter = Counter()
    for log in logs:
        cam_id = str(log.camera_id) if log.camera_id else "unknown"
        camera_counts[cam_id] += 1

    cameras = {
        str(camera.id): camera.name
        for camera in db.query(models.Camera)
        .filter(models.Camera.organization_id == user.organization_id)
        .limit(500)  # Reasonable limit for org cameras
        .all()
    }

    peak_camera = camera_counts.most_common(1)
    camera_density = [
        schemas.VisitorFlowCameraDensityItem(
            camera_id=cam_id,
            camera_name=cameras.get(cam_id, "Unknown Camera"),
            events=count,
            share=round(count / max(1, total_events), 4),
        )
        for cam_id, count in camera_counts.most_common()
    ]

    dwell_samples: List[float] = []
    visitor_events: Dict[str, List[datetime.datetime]] = {}
    for log in logs:
        if not log.visitor_id:
            continue
        ts = _normalize_timestamp(log.timestamp)
        if ts is None:
            continue
        visitor_events.setdefault(str(log.visitor_id), []).append(ts)
    for events in visitor_events.values():
        if len(events) < 2:
            continue
        events.sort()
        for earlier, later in zip(events[:-1], events[1:]):
            diff = (later - earlier).total_seconds()
            if 0 < diff < 3600:
                dwell_samples.append(diff)

    if dwell_samples:
        dwell_samples.sort()
        median_dwell = dwell_samples[len(dwell_samples) // 2]
        avg_dwell = sum(dwell_samples) / len(dwell_samples)
    else:
        median_dwell = 0.0
        avg_dwell = 0.0

    grid: List[List[int]] = [[0 for _ in range(10)] for _ in range(10)]
    peak_value = 0
    for log in logs:
        cam_id = str(log.camera_id) if log.camera_id else "unknown"
        ts = _normalize_timestamp(log.timestamp)
        hour = ts.hour if ts else 0
        row = hash(cam_id) % 10
        col = hour % 10
        grid[row][col] += 1
        peak_value = max(peak_value, grid[row][col])

    normalized_grid = [
        [round(cell / peak_value, 4) if peak_value > 0 else 0.0 for cell in row]
        for row in grid
    ]

    return schemas.VisitorFlowAnalytics(
        lookback_hours=lookback_hours,
        since=since.isoformat(),
        totals=schemas.VisitorFlowTotals(
            total_events=total_events,
            unique_visitors=unique_visitors,
            identified_events=identified,
            identified_rate=round(identified / total_events, 4) if total_events else 0.0,
        ),
        hourly_timeline=hourly_timeline,
        camera_density=camera_density,
        peak_camera=schemas.VisitorFlowPeakCamera(
            camera_id=peak_camera[0][0] if peak_camera else None,
            camera_name=cameras.get(peak_camera[0][0], "Unknown") if peak_camera else None,
            events=peak_camera[0][1] if peak_camera else 0,
        ),
        dwell_time=schemas.VisitorFlowDwellTime(
            median_seconds=round(median_dwell, 2),
            average_seconds=round(avg_dwell, 2),
            sample_count=len(dwell_samples),
        ),
        heatmap=schemas.VisitorFlowHeatmap(
            grid_size=[10, 10],
            raw_grid=grid,
            normalized_grid=normalized_grid,
            peak_cell_events=peak_value,
        ),
        generated_at=datetime.datetime.now(timezone.utc).isoformat(),
    )


@router.get("/system-health", response_model=schemas.SystemHealthMetrics)
def get_system_health(
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """US-AN-003: Get system health metrics."""
    user = _get_user(db, current_user_id)
    org_id = user.organization_id
    cache_key = str(org_id)

    cached = _system_health_cache.get(cache_key)
    now_monotonic = time.monotonic()
    if cached and (now_monotonic - cached[0]) < SYSTEM_HEALTH_CACHE_TTL_SECONDS:
        return cached[1]

    # Check AI service status and which face-recognition backend it has loaded
    ai_status = "offline"
    recognition_backend: Optional[str] = None
    recognition_degraded: Optional[bool] = None
    try:
        resp = requests.get(f"{AI_SERVICE_URL}/health", timeout=1.5)
        if resp.status_code == 200:
            ai_status = "online"
            recognition = (resp.json() or {}).get("recognition", {})
            backends = recognition.get("backends", {})
            if backends.get("insightface_arcface"):
                recognition_backend = "arcface"
            elif backends.get("adaface"):
                recognition_backend = "adaface"
            elif backends.get("vit"):
                recognition_backend = "vit"
            elif backends.get("deepface"):
                recognition_backend = "deepface"
            else:
                recognition_backend = "fallback"
            recognition_degraded = not bool(recognition.get("real_recognition"))
    except Exception:
        ai_status = "offline"

    # Today's processing
    today = datetime.datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    today_logs = db.query(func.count(models.VisitorLog.id)).filter(
        models.VisitorLog.organization_id == org_id,
        models.VisitorLog.timestamp >= today,
    ).scalar() or 0

    # Error rate (jobs with errors / total jobs)
    total_jobs = db.query(func.count(models.VideoProcessingJob.id)).filter(
        models.VideoProcessingJob.organization_id == org_id,
    ).scalar() or 0
    error_jobs = db.query(func.count(models.VideoProcessingJob.id)).filter(
        models.VideoProcessingJob.organization_id == org_id,
        models.VideoProcessingJob.status == "error",
    ).scalar() or 0
    error_rate = error_jobs / total_jobs if total_jobs > 0 else 0.0

    # Storage usage
    storage_mb = 0.0
    if os.path.exists(DATA_DIR):
        for dirpath, dirnames, filenames in os.walk(DATA_DIR):
            for f in filenames:
                fp = os.path.join(dirpath, f)
                storage_mb += os.path.getsize(fp)
    storage_mb = storage_mb / (1024 * 1024)

    db_size_mb = _get_database_size_mb()

    metrics = schemas.SystemHealthMetrics(
        ai_service_status=ai_status,
        avg_processing_time_ms=0.0,  # Would need timing instrumentation
        total_processed_today=today_logs,
        error_rate=round(error_rate, 4),
        storage_used_mb=round(storage_mb, 2),
        database_size_mb=round(db_size_mb, 2),
        recognition_backend=recognition_backend,
        recognition_degraded=recognition_degraded,
    )
    _system_health_cache[cache_key] = (now_monotonic, metrics)
    return metrics


@router.post("/reports")
async def generate_report(
    request: schemas.ReportRequest,
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """US-AN-004: Generate comprehensive reports (JSON or CSV)."""
    user = _get_user(db, current_user_id)
    org_id = user.organization_id

    # Determine date range
    now = datetime.datetime.now(timezone.utc)
    if request.date_from:
        date_from = datetime.datetime.fromisoformat(request.date_from)
    elif request.period == "daily":
        date_from = now - datetime.timedelta(days=1)
    elif request.period == "monthly":
        date_from = now - datetime.timedelta(days=30)
    else:  # weekly
        date_from = now - datetime.timedelta(days=7)

    date_to = datetime.datetime.fromisoformat(request.date_to) if request.date_to else now

    # Use database-side count for efficiency
    total = db.query(func.count(models.VisitorLog.id)).filter(
        models.VisitorLog.organization_id == org_id,
        models.VisitorLog.timestamp >= date_from,
        models.VisitorLog.timestamp <= date_to,
    ).scalar() or 0

    logs = db.query(models.VisitorLog).filter(
        models.VisitorLog.organization_id == org_id,
        models.VisitorLog.timestamp >= date_from,
        models.VisitorLog.timestamp <= date_to,
    ).limit(500000).all()  # Cap at 500k rows for reports
    identified = sum(1 for l in logs if l.identified)
    unidentified = total - identified
    avg_conf = sum(l.confidence for l in logs) / total if total > 0 else 0

    # Use database-side aggregation instead of loading all visitors
    total_visitors = db.query(func.count(models.Visitor.id)).filter(
        models.Visitor.organization_id == org_id
    ).scalar() or 0
    known_visitors = db.query(func.count(models.Visitor.id)).filter(
        models.Visitor.organization_id == org_id,
        models.Visitor.is_known == True,
    ).scalar() or 0

    report_data = {
        "report_type": request.report_type,
        "period": request.period,
        "date_from": date_from.isoformat(),
        "date_to": date_to.isoformat(),
        "generated_at": now.isoformat(),
        "summary": {
            "total_events": total,
            "identified": identified,
            "unidentified": unidentified,
            "accuracy": round(identified / total if total > 0 else 0, 4),
            "avg_confidence": round(avg_conf, 4),
            "total_visitors": total_visitors,
            "known_visitors": known_visitors,
        },
        "daily_breakdown": [],
    }

    # Daily breakdown
    daily = {}
    for log in logs:
        day = log.timestamp.strftime("%Y-%m-%d")
        if day not in daily:
            daily[day] = {"date": day, "total": 0, "identified": 0, "unidentified": 0}
        daily[day]["total"] += 1
        if log.identified:
            daily[day]["identified"] += 1
        else:
            daily[day]["unidentified"] += 1
    report_data["daily_breakdown"] = sorted(daily.values(), key=lambda x: x["date"])

    if request.format == "csv":
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["Date", "Total Events", "Identified", "Unidentified", "Accuracy"])
        for day_data in report_data["daily_breakdown"]:
            acc = day_data["identified"] / day_data["total"] if day_data["total"] > 0 else 0
            writer.writerow([
                day_data["date"], day_data["total"],
                day_data["identified"], day_data["unidentified"],
                f"{acc:.2%}",
            ])
        output.seek(0)
        return StreamingResponse(
            iter([output.getvalue()]),
            media_type="text/csv",
            headers={"Content-Disposition": f"attachment; filename=report_{request.period}.csv"},
        )

    return report_data


@router.get("/realtime-tracking", response_model=schemas.RealtimeTrackingResponse)
async def get_realtime_tracking(
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """UTA: Get real-time active user sessions for tracking."""
    user = _get_user(db, current_user_id)
    org_id = user.organization_id

    active_sessions = db.query(models.UserSession).filter(
        models.UserSession.organization_id == org_id,
        models.UserSession.status == "active",
    ).limit(10000).all()  # Cap active sessions loaded into memory

    session_responses = [
        schemas.UserSessionResponse.model_validate(session)
        for session in active_sessions
    ]

    return schemas.RealtimeTrackingResponse(
        active_sessions=session_responses,
        total_active=len(active_sessions),
        generated_at=datetime.datetime.now(timezone.utc).isoformat(),
    )
