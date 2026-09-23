"""
Carbon & Sustainability Metrics API

Computes real carbon footprint estimates from actual system telemetry:
  - API request volume  → CPU compute carbon
  - Video processing jobs → GPU compute carbon
  - Active camera streams → Streaming energy carbon
  - Database query load  → Storage I/O carbon
  - Redis cache hit rate  → Cache efficiency savings

Emission factors from IPCC AR6 / Our World In Data (global avg grid: 436 gCO2e/kWh).
All values are estimates — configure GRID_CARBON_INTENSITY_GRAMS to adjust for
your datacenter's actual energy mix.
"""

from __future__ import annotations

import os
import time
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from core.security import get_current_user
from db.base import get_db
from models import models
from services import user_service
from services.redis_service import get_redis_service

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/carbon", tags=["Carbon & Sustainability"])

# ── Emission constants ────────────────────────────────────────────────────────
# grams CO2e per kWh  (configurable for local grid)
_GRID_INTENSITY = float(os.getenv("GRID_CARBON_INTENSITY_GRAMS", "436"))

# Server power draw estimates (Watts)
_CPU_WATTS_PER_REQUEST = 0.003       # 3 mW amortized per API request
_GPU_WATTS_VIDEO_PROCESS = 150.0     # typical GPU watt draw during inference
_CAMERA_STREAM_WATTS = 2.5           # per active camera stream (network + decode)
_DB_QUERY_WATTS = 0.001              # per query I/O amortized
_IDLE_SERVER_WATTS = 80.0            # idle baseline per service instance


def _kwh_to_grams(watt_hours: float) -> float:
    return watt_hours / 1000.0 * _GRID_INTENSITY


def _grams_to_kg(grams: float) -> float:
    return grams / 1000.0


def _get_user(db: Session, user_id: str) -> models.User:
    user = user_service.get_user_by_id(db, user_id)
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    return user


# ── Response schemas ──────────────────────────────────────────────────────────

class CarbonBreakdownItem(BaseModel):
    source: str
    description: str
    energy_kwh: float = Field(..., description="Estimated energy in kWh")
    carbon_grams: float = Field(..., description="Estimated CO2e grams")
    carbon_kg: float = Field(..., description="Estimated CO2e kg")


class CarbonSavings(BaseModel):
    cache_avoided_requests: int
    cache_saved_carbon_grams: float
    edge_avoided_cloud_carbon_grams: float
    total_saved_grams: float
    total_saved_kg: float


class CarbonMetricsResponse(BaseModel):
    organization_id: str
    period_start: datetime
    period_end: datetime
    period_hours: float
    total_carbon_grams: float
    total_carbon_kg: float
    carbon_per_visitor_grams: float
    breakdown: List[CarbonBreakdownItem]
    savings: CarbonSavings
    grid_intensity_grams_per_kwh: float
    efficiency_score: float = Field(
        ...,
        description="0-100 score: higher = more efficient (cache hit rate, edge offload, low idle ratio)"
    )
    recommendations: List[str]


class CarbonTrendPoint(BaseModel):
    timestamp: datetime
    carbon_grams: float
    visitor_count: int


class CarbonTrendResponse(BaseModel):
    organization_id: str
    points: List[CarbonTrendPoint]
    avg_carbon_per_hour_grams: float
    trend: str  # "improving" | "stable" | "degrading"


# ── Helpers ───────────────────────────────────────────────────────────────────

def _collect_telemetry(
    db: Session,
    organization_id: Any,
    since: datetime,
    until: datetime,
) -> Dict[str, Any]:
    """Gather real DB telemetry for the period."""
    hours = max(0.001, (until - since).total_seconds() / 3600)

    visitor_log_count = (
        db.query(models.VisitorLog)
        .filter(
            models.VisitorLog.organization_id == organization_id,
            models.VisitorLog.timestamp >= since,
            models.VisitorLog.timestamp <= until,
        )
        .count()
    )

    video_job_count = (
        db.query(models.VideoProcessingJob)
        .filter(
            models.VideoProcessingJob.organization_id == organization_id,
            models.VideoProcessingJob.created_at >= since,
            models.VideoProcessingJob.created_at <= until,
        )
        .count()
        if hasattr(models, "VideoProcessingJob")
        else 0
    )

    active_camera_count = (
        db.query(models.Camera)
        .filter(
            models.Camera.organization_id == organization_id,
            models.Camera.is_active.is_(True),
        )
        .count()
    )

    edge_device_count = (
        db.query(models.EdgeDevice)
        .filter(
            models.EdgeDevice.organization_id == organization_id,
            models.EdgeDevice.status == "online",
        )
        .count()
        if hasattr(models, "EdgeDevice")
        else 0
    )

    redis_svc = get_redis_service()
    redis_metrics: Dict[str, Any] = {}
    try:
        redis_metrics = redis_svc.get_metrics()
    except Exception:
        pass

    cache_hits = int(redis_metrics.get("cache_hits", 0))
    cache_misses = int(redis_metrics.get("cache_misses", 0))
    total_cache = cache_hits + cache_misses
    cache_hit_rate = cache_hits / total_cache if total_cache > 0 else 0.5

    # Estimate total API requests from visitor log density (each detection = ~3 API calls)
    estimated_api_requests = visitor_log_count * 3 + video_job_count * 20

    return {
        "hours": hours,
        "visitor_log_count": visitor_log_count,
        "video_job_count": video_job_count,
        "active_camera_count": active_camera_count,
        "edge_device_count": edge_device_count,
        "cache_hit_rate": cache_hit_rate,
        "cache_hits": cache_hits,
        "cache_misses": cache_misses,
        "estimated_api_requests": estimated_api_requests,
    }


def _compute_carbon(telemetry: Dict[str, Any]) -> CarbonMetricsResponse:
    hours = telemetry["hours"]
    visitor_count = telemetry["visitor_log_count"]
    api_requests = telemetry["estimated_api_requests"]
    video_jobs = telemetry["video_job_count"]
    camera_count = telemetry["active_camera_count"]
    edge_count = telemetry["edge_device_count"]
    cache_hit_rate = telemetry["cache_hit_rate"]
    cache_hits = telemetry["cache_hits"]

    # ── Compute per-source energy ─────────────────────────────────────────────
    # 1. API compute
    api_wh = api_requests * _CPU_WATTS_PER_REQUEST
    api_carbon = _kwh_to_grams(api_wh)

    # 2. Video processing (avg 2 min GPU per job)
    video_wh = video_jobs * (_GPU_WATTS_VIDEO_PROCESS * (2 / 60))
    video_carbon = _kwh_to_grams(video_wh)

    # 3. Camera streaming
    stream_wh = camera_count * _CAMERA_STREAM_WATTS * hours
    stream_carbon = _kwh_to_grams(stream_wh)

    # 4. Database I/O (each visitor log = ~5 queries)
    db_queries = visitor_count * 5 + api_requests
    db_wh = db_queries * _DB_QUERY_WATTS
    db_carbon = _kwh_to_grams(db_wh)

    # 5. Idle baseline (2 services: backend + ai-service)
    idle_wh = _IDLE_SERVER_WATTS * 2 * hours
    idle_carbon = _kwh_to_grams(idle_wh)

    total_grams = api_carbon + video_carbon + stream_carbon + db_carbon + idle_carbon

    # ── Savings ──────────────────────────────────────────────────────────────
    # Cache hits avoided DB roundtrips
    cache_saved_grams = cache_hits * _DB_QUERY_WATTS * _GRID_INTENSITY / 1000.0
    # Edge devices avoid cloud video processing (rough 30% offload)
    edge_saved_grams = edge_count * _GPU_WATTS_VIDEO_PROCESS * hours * 0.3 * _GRID_INTENSITY / 1000.0
    total_saved = cache_saved_grams + edge_saved_grams

    # ── Efficiency score ─────────────────────────────────────────────────────
    # Factors: cache hit rate (40%), edge offload ratio (30%), idle ratio (30%)
    idle_ratio = idle_wh / max(1e-9, idle_wh + api_wh + video_wh + stream_wh + db_wh)
    efficiency = (
        cache_hit_rate * 0.4
        + min(1.0, edge_count * 0.1) * 0.3
        + (1.0 - min(1.0, idle_ratio)) * 0.3
    ) * 100.0

    # ── Recommendations ───────────────────────────────────────────────────────
    recs: List[str] = []
    if cache_hit_rate < 0.5:
        recs.append("Increase Redis TTL to improve cache hit rate and reduce redundant DB queries")
    if camera_count > 4 and edge_count == 0:
        recs.append("Deploy edge devices to offload camera stream processing from cloud GPU")
    if video_jobs > 20 and hours < 8:
        recs.append("Batch video processing jobs during off-peak hours to reduce peak GPU load")
    if idle_ratio > 0.6:
        recs.append("Enable auto-scaling to reduce idle server time during low-traffic windows")
    if _GRID_INTENSITY > 500:
        recs.append("Consider migrating to a datacenter powered by renewable energy (current grid: high carbon)")
    if not recs:
        recs.append("System efficiency is good. Continue monitoring cache hit rate and edge utilization.")

    carbon_per_visitor = total_grams / max(1, visitor_count)

    breakdown = [
        CarbonBreakdownItem(
            source="api_compute",
            description=f"API request processing ({api_requests:,} est. requests)",
            energy_kwh=round(api_wh / 1000, 6),
            carbon_grams=round(api_carbon, 4),
            carbon_kg=round(_grams_to_kg(api_carbon), 6),
        ),
        CarbonBreakdownItem(
            source="video_processing",
            description=f"GPU video inference ({video_jobs} jobs)",
            energy_kwh=round(video_wh / 1000, 6),
            carbon_grams=round(video_carbon, 4),
            carbon_kg=round(_grams_to_kg(video_carbon), 6),
        ),
        CarbonBreakdownItem(
            source="camera_streaming",
            description=f"Camera streams ({camera_count} active, {hours:.1f}h)",
            energy_kwh=round(stream_wh / 1000, 6),
            carbon_grams=round(stream_carbon, 4),
            carbon_kg=round(_grams_to_kg(stream_carbon), 6),
        ),
        CarbonBreakdownItem(
            source="database_io",
            description=f"Database I/O ({db_queries:,} est. queries)",
            energy_kwh=round(db_wh / 1000, 6),
            carbon_grams=round(db_carbon, 4),
            carbon_kg=round(_grams_to_kg(db_carbon), 6),
        ),
        CarbonBreakdownItem(
            source="idle_baseline",
            description=f"Server idle baseline (2 instances, {hours:.1f}h)",
            energy_kwh=round(idle_wh / 1000, 6),
            carbon_grams=round(idle_carbon, 4),
            carbon_kg=round(_grams_to_kg(idle_carbon), 6),
        ),
    ]

    return CarbonMetricsResponse(
        organization_id=str(telemetry.get("organization_id", "")),
        period_start=telemetry["period_start"],
        period_end=telemetry["period_end"],
        period_hours=round(hours, 2),
        total_carbon_grams=round(total_grams, 4),
        total_carbon_kg=round(_grams_to_kg(total_grams), 6),
        carbon_per_visitor_grams=round(carbon_per_visitor, 4),
        breakdown=breakdown,
        savings=CarbonSavings(
            cache_avoided_requests=cache_hits,
            cache_saved_carbon_grams=round(cache_saved_grams, 4),
            edge_avoided_cloud_carbon_grams=round(edge_saved_grams, 4),
            total_saved_grams=round(total_saved, 4),
            total_saved_kg=round(_grams_to_kg(total_saved), 6),
        ),
        grid_intensity_grams_per_kwh=_GRID_INTENSITY,
        efficiency_score=round(efficiency, 1),
        recommendations=recs,
    )


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/metrics", response_model=CarbonMetricsResponse)
def get_carbon_metrics(
    hours: int = 24,
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Return carbon footprint estimates for the organization derived from real
    system telemetry (visitor logs, video jobs, active cameras, cache metrics).

    Query params:
      - hours: lookback window (default 24, max 720)
    """
    hours = max(1, min(hours, 720))
    user = _get_user(db, current_user_id)
    until = datetime.now(timezone.utc)
    since = until - timedelta(hours=hours)

    telemetry = _collect_telemetry(db, user.organization_id, since, until)
    telemetry["organization_id"] = user.organization_id
    telemetry["period_start"] = since
    telemetry["period_end"] = until

    return _compute_carbon(telemetry)


@router.get("/trend", response_model=CarbonTrendResponse)
def get_carbon_trend(
    hours: int = 48,
    buckets: int = 12,
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Return hourly/bucketed carbon trend for the organization over the past N hours.
    Useful for charts: carbon over time vs visitor count.
    """
    hours = max(2, min(hours, 720))
    buckets = max(2, min(buckets, 48))
    user = _get_user(db, current_user_id)
    until = datetime.now(timezone.utc)
    since = until - timedelta(hours=hours)
    bucket_size = timedelta(hours=hours / buckets)

    points: List[CarbonTrendPoint] = []
    total_carbon = 0.0

    for i in range(buckets):
        b_start = since + bucket_size * i
        b_end = b_start + bucket_size
        tel = _collect_telemetry(db, user.organization_id, b_start, b_end)
        tel["organization_id"] = user.organization_id
        tel["period_start"] = b_start
        tel["period_end"] = b_end
        metrics = _compute_carbon(tel)
        total_carbon += metrics.total_carbon_grams
        points.append(CarbonTrendPoint(
            timestamp=b_end,
            carbon_grams=round(metrics.total_carbon_grams, 4),
            visitor_count=tel["visitor_log_count"],
        ))

    avg_per_hour = total_carbon / max(1, hours)

    # Determine trend: compare first half vs second half
    mid = buckets // 2
    first_half = sum(p.carbon_grams for p in points[:mid])
    second_half = sum(p.carbon_grams for p in points[mid:])
    if second_half < first_half * 0.95:
        trend = "improving"
    elif second_half > first_half * 1.05:
        trend = "degrading"
    else:
        trend = "stable"

    return CarbonTrendResponse(
        organization_id=str(user.organization_id),
        points=points,
        avg_carbon_per_hour_grams=round(avg_per_hour, 4),
        trend=trend,
    )


@router.get("/config")
def get_carbon_config(
    current_user_id: str = Depends(get_current_user),
):
    """Return current emission factor configuration."""
    _get_user  # auth check; no DB needed
    return {
        "grid_intensity_grams_per_kwh": _GRID_INTENSITY,
        "emission_factors": {
            "cpu_watts_per_request": _CPU_WATTS_PER_REQUEST,
            "gpu_watts_video_process": _GPU_WATTS_VIDEO_PROCESS,
            "camera_stream_watts": _CAMERA_STREAM_WATTS,
            "db_query_watts": _DB_QUERY_WATTS,
            "idle_server_watts": _IDLE_SERVER_WATTS,
        },
        "configurable_via_env": {
            "GRID_CARBON_INTENSITY_GRAMS": "gCO2e per kWh for your datacenter grid",
        },
        "data_sources": [
            "visitor_logs (DB count)",
            "video_processing_jobs (DB count)",
            "cameras (DB count)",
            "edge_devices (DB count)",
            "redis_cache_metrics (Redis INFO)",
        ],
    }
