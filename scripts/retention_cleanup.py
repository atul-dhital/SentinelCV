#!/usr/bin/env python3
"""Run data retention cleanup for configured organizations."""

from __future__ import annotations

import argparse
import datetime as dt
import os
import sys
from pathlib import Path
from typing import Dict, List, Optional

PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = PROJECT_ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from sqlalchemy import func
from db.base import SessionLocal
from models import models
from core.paths import data_path
from services import visitor_service


def _load_env_file(path: Optional[str]) -> None:
    if not path:
        return
    env_path = Path(path)
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        key = key.strip()
        value = value.strip()
        if key and key not in os.environ:
            os.environ[key] = value


def _cleanup_for_org(
    db,
    organization_id: str,
    dry_run: bool,
) -> List[Dict[str, object]]:
    policies = (
        db.query(models.DataRetentionPolicy)
        .filter(
            models.DataRetentionPolicy.organization_id == organization_id,
            models.DataRetentionPolicy.auto_delete == True,
        )
        .all()
    )

    results: List[Dict[str, object]] = []
    now = dt.datetime.now(dt.timezone.utc)

    for policy in policies:
        cutoff = now - dt.timedelta(days=policy.retention_days)
        deleted = 0

        if policy.entity_type == "audit_logs":
            query = db.query(models.AuditLog).filter(
                models.AuditLog.organization_id == organization_id,
                models.AuditLog.timestamp < cutoff,
            )
            deleted = query.count() if dry_run else query.delete(synchronize_session=False)

        elif policy.entity_type == "face_data":
            face_ids = (
                db.query(models.FaceData.id)
                .join(models.Visitor)
                .filter(
                    models.Visitor.organization_id == organization_id,
                    models.FaceData.created_at < cutoff,
                )
                .all()
            )
            if dry_run:
                deleted = len(face_ids)
            else:
                for (face_id,) in face_ids:
                    face = db.query(models.FaceData).filter(models.FaceData.id == face_id).first()
                    if face and face.image_url:
                        path = data_path(face.image_url)
                        if os.path.exists(path):
                            os.remove(path)
                    if face:
                        db.delete(face)
                        deleted += 1

        elif policy.entity_type == "visitor_logs":
            query = db.query(func.count(models.VisitorLog.id)).filter(
                models.VisitorLog.organization_id == organization_id,
                models.VisitorLog.timestamp < cutoff,
            )
            _count = query.scalar() or 0
            deleted = 0

        results.append(
            {
                "entity_type": policy.entity_type,
                "records_deleted": deleted,
                "cutoff_date": cutoff.isoformat(),
            }
        )

        if not dry_run:
            policy.last_cleanup_at = now

    if not dry_run and results:
        visitor_service.create_audit_log(
            db,
            organization_id,
            None,
            "retention_cleanup_automation",
            "system",
            None,
            details={"results": results},
        )

    return results


def main() -> int:
    parser = argparse.ArgumentParser(description="Run retention cleanup policies")
    parser.add_argument("--env-file", default=".env.staging", help="Env file to load")
    parser.add_argument("--org-id", default="", help="Optional organization id")
    parser.add_argument("--dry-run", action="store_true", help="Report counts without deleting")
    args = parser.parse_args()

    _load_env_file(args.env_file)

    db = SessionLocal()
    try:
        if args.org_id:
            org_ids = [args.org_id]
        else:
            org_ids = [str(org_id) for (org_id,) in db.query(models.Organization.id).all()]

        summary: Dict[str, List[Dict[str, object]]] = {}
        for org_id in org_ids:
            summary[org_id] = _cleanup_for_org(db, org_id, args.dry_run)

        if not args.dry_run:
            db.commit()
        else:
            db.rollback()

        for org_id, results in summary.items():
            print(f"Organization {org_id}")
            for item in results:
                print(f"  {item['entity_type']}: deleted {item['records_deleted']} (cutoff {item['cutoff_date']})")

    finally:
        db.close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
