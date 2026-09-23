"""
PDF Report Export API (ENH-004)

Endpoints for generating PDF reports for visitors, analytics,
audit trails, and liveness detection.
"""

import os
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy.orm import Session
from typing import Optional
from datetime import datetime, timedelta, timezone
from pathlib import Path
import json

from db.base import get_db
from core.security import get_current_user
from services import user_service
from services.pdf_export_service import pdf_export_service
from models import models

router = APIRouter(prefix="/reports", tags=["Reports & PDF Export"])


def _get_user(db: Session, user_id: str) -> models.User:
    user = user_service.get_user_by_id(db, user_id)
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    return user


_MAX_REPORT_DAYS = int(os.getenv("MAX_REPORT_DATE_RANGE_DAYS", "90"))


def _parse_dates(start_date: Optional[str], end_date: Optional[str]):
    """Parse date strings to datetime objects and enforce the maximum window.

    Large date ranges (>90 days) run synchronous COUNT/SELECT queries that can
    cause request timeouts.  The cap prevents accidental DoS.  For longer
    ranges, export via CSV endpoints or schedule an async report job.
    """
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=30)
    if start_date:
        try:
            start = datetime.fromisoformat(start_date.replace("Z", "+00:00"))
        except ValueError:
            pass
    if end_date:
        try:
            end = datetime.fromisoformat(end_date.replace("Z", "+00:00"))
        except ValueError:
            pass

    # Clamp to maximum allowed window
    if (end - start).days > _MAX_REPORT_DAYS:
        from fastapi import HTTPException as _HTTPException
        raise _HTTPException(
            status_code=400,
            detail=(
                f"Report date range exceeds the {_MAX_REPORT_DAYS}-day maximum. "
                "Narrow the range or use the CSV export for longer periods."
            ),
        )
    return start, end


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _quality_artifact(path: Path) -> dict:
    return {
        "exists": path.exists(),
        "path": str(path),
        "modified_at": (
            datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat()
            if path.exists()
            else None
        ),
    }


def _read_pytest_nodeids_count(root: Path) -> int:
    cache_file = root / "backend" / ".pytest_cache" / "v" / "cache" / "nodeids"
    if not cache_file.exists():
        return 0
    contents = cache_file.read_text(encoding="utf-8", errors="ignore")
    try:
        parsed = json.loads(contents)
        if isinstance(parsed, list):
            return sum(1 for item in parsed if isinstance(item, str) and "::" in item)
    except (TypeError, ValueError, json.JSONDecodeError):
        pass

    count = 0
    for line in contents.splitlines():
        count += line.count("::")
    return count


def _ci_coverage_enabled(root: Path) -> bool:
    workflow = root / ".github" / "workflows" / "ci-cd.yml"
    if not workflow.exists():
        return False
    contents = workflow.read_text(encoding="utf-8", errors="ignore")
    return "--cov=backend" in contents or "--cov " in contents or "pytest-cov" in contents


def _collect_quality_summary(root: Path) -> dict:
    integration_tests = list((root / "backend" / "tests" / "integration").glob("test_*.py"))
    service_tests = list((root / "backend" / "tests").glob("test_*.py"))
    artifact_paths = {
        "coverage_xml": root / "coverage.xml",
        "coverage_html": root / "htmlcov" / "index.html",
        "bandit_report": root / "bandit-report.json",
        "pylint_report": root / "pylint-report.json",
    }

    return {
        "ci_workflow_present": (root / ".github" / "workflows" / "ci-cd.yml").exists(),
        "coverage_enabled_in_ci": _ci_coverage_enabled(root),
        "pytest_collected_tests": _read_pytest_nodeids_count(root),
        "integration_test_files": len(integration_tests),
        "service_test_files": len(service_tests),
        "backend_readme_present": (root / "backend" / "README.md").exists(),
        "artifacts": {
            name: _quality_artifact(path)
            for name, path in artifact_paths.items()
        },
    }


@router.get("/visitors/pdf")
def export_visitors_pdf(
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user_id: str = Depends(get_current_user),
):
    """Generate visitor activity report as PDF."""
    user = _get_user(db, current_user_id)
    start, end = _parse_dates(start_date, end_date)

    # Get org name
    org = db.query(models.Organization).filter(
        models.Organization.id == user.organization_id
    ).first()
    org_name = org.name if org else "Unknown"

    # Get visitors
    visitors_q = db.query(models.Visitor).filter(
        models.Visitor.organization_id == user.organization_id,
    ).limit(100000).all()

    visitors = [
        {
            "name": v.name or "Unknown",
            "email": v.email or "",
            "status": "active" if v.is_active else "inactive",
            "detection_count": v.detection_count or 0,
            "last_detected_at": str(v.last_detected_at or "Never"),
        }
        for v in visitors_q
    ]

    # Stats
    stats = {
        "total_visitors": len(visitors),
        "active_visitors": sum(1 for v in visitors if v["status"] == "active"),
        "total_detections": sum(v["detection_count"] for v in visitors),
        "identified_rate": 0.8,
    }

    date_range = f"{start.strftime('%Y-%m-%d')} to {end.strftime('%Y-%m-%d')}"
    pdf_bytes = pdf_export_service.generate_visitor_report_pdf(org_name, date_range, visitors, stats)

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": "attachment; filename=visitor_report.pdf"},
    )


@router.get("/analytics/pdf")
def export_analytics_pdf(
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user_id: str = Depends(get_current_user),
):
    """Generate analytics summary report as PDF."""
    user = _get_user(db, current_user_id)
    start, end = _parse_dates(start_date, end_date)

    org = db.query(models.Organization).filter(
        models.Organization.id == user.organization_id
    ).first()
    org_name = org.name if org else "Unknown"

    # Gather stats
    total_logs = db.query(models.VisitorLog).filter(
        models.VisitorLog.organization_id == user.organization_id,
        models.VisitorLog.timestamp >= start,
        models.VisitorLog.timestamp <= end,
    ).count()

    identified = db.query(models.VisitorLog).filter(
        models.VisitorLog.organization_id == user.organization_id,
        models.VisitorLog.timestamp >= start,
        models.VisitorLog.identified == True,
    ).count()

    cameras = db.query(models.Camera).filter(
        models.Camera.organization_id == user.organization_id,
    ).count()

    stats = {
        "total_detections": total_logs,
        "identified": identified,
        "unidentified": total_logs - identified,
        "identification_rate": f"{(identified / max(1, total_logs)) * 100:.1f}%",
        "active_cameras": cameras,
        "total_visitors": db.query(models.Visitor).filter(
            models.Visitor.organization_id == user.organization_id
        ).count(),
        "period": f"{start.strftime('%Y-%m-%d')} to {end.strftime('%Y-%m-%d')}",
    }

    date_range = f"{start.strftime('%Y-%m-%d')} to {end.strftime('%Y-%m-%d')}"
    pdf_bytes = pdf_export_service.generate_analytics_report_pdf(org_name, date_range, stats)

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": "attachment; filename=analytics_report.pdf"},
    )


@router.get("/audit/pdf")
def export_audit_pdf(
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user_id: str = Depends(get_current_user),
):
    """Generate audit trail report as PDF."""
    user = _get_user(db, current_user_id)
    start, end = _parse_dates(start_date, end_date)

    org = db.query(models.Organization).filter(
        models.Organization.id == user.organization_id
    ).first()
    org_name = org.name if org else "Unknown"

    audit_logs_q = db.query(models.AuditLog).filter(
        models.AuditLog.organization_id == user.organization_id,
        models.AuditLog.timestamp >= start,
        models.AuditLog.timestamp <= end,
    ).order_by(models.AuditLog.timestamp.desc()).limit(500).all()

    audit_logs = []
    for a in audit_logs_q:
        user_obj = db.query(models.User).filter(models.User.id == a.user_id).first() if a.user_id else None
        audit_logs.append({
            "timestamp": str(a.timestamp),
            "user_email": user_obj.email if user_obj else "system",
            "action": a.action,
            "entity_type": a.entity_type or "",
            "entity_id": str(a.entity_id or ""),
        })

    date_range = f"{start.strftime('%Y-%m-%d')} to {end.strftime('%Y-%m-%d')}"
    pdf_bytes = pdf_export_service.generate_audit_report_pdf(org_name, date_range, audit_logs)

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": "attachment; filename=audit_report.pdf"},
    )


@router.get("/liveness/pdf")
def export_liveness_pdf(
    days: int = Query(7, ge=1, le=365),
    db: Session = Depends(get_db),
    current_user_id: str = Depends(get_current_user),
):
    """Generate liveness detection report as PDF."""
    user = _get_user(db, current_user_id)

    org = db.query(models.Organization).filter(
        models.Organization.id == user.organization_id
    ).first()
    org_name = org.name if org else "Unknown"

    end = datetime.now(timezone.utc)
    start = end - timedelta(days=days)

    scores = db.query(models.LivenessScore).filter(
        models.LivenessScore.organization_id == user.organization_id,
        models.LivenessScore.created_at >= start,
    ).order_by(models.LivenessScore.created_at.desc()).limit(10000).all()

    total = len(scores)
    live = sum(1 for s in scores if s.is_live)

    stats = {
        "total_detections": total,
        "live_count": live,
        "spoof_count": total - live,
        "live_rate": f"{(live / max(1, total)) * 100:.1f}%",
        "period_days": days,
    }

    detections = [
        {
            "timestamp": str(s.created_at),
            "is_live": s.is_live,
            "score": s.overall_score,
            "method": s.method_used,
            "rejection_reason": s.rejection_reason or "",
        }
        for s in scores[:200]
    ]

    date_range = f"{start.strftime('%Y-%m-%d')} to {end.strftime('%Y-%m-%d')}"
    pdf_bytes = pdf_export_service.generate_liveness_report_pdf(org_name, date_range, stats, detections)

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": "attachment; filename=liveness_report.pdf"},
    )


@router.get("/job-queue/stats")
def get_job_queue_stats(
    current_user_id: str = Depends(get_current_user),
):
    """Get background job queue statistics."""
    from services.job_queue_service import job_queue
    return job_queue.get_stats()


@router.get("/cache/info")
def get_cache_info(
    current_user_id: str = Depends(get_current_user),
):
    """Get Redis cache connection info."""
    from services.redis_service import get_redis_service

    redis_service = get_redis_service()
    return redis_service.get_metrics()


@router.get("/quality/summary")
def get_quality_summary(
    current_user_id: str = Depends(get_current_user),
):
    """Return visibility into test, coverage, and quality-report artifacts."""
    _root = _project_root()
    return _collect_quality_summary(_root)
