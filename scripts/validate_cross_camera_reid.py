#!/usr/bin/env python3
"""Validate cross-camera re-ID using the configured database."""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = PROJECT_ROOT / "backend"
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from sqlalchemy import text

from db.base import SessionLocal
from services.reid_service import search_cross_camera_matches
from schemas.schemas import CrossCameraReidRequest


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate cross-camera re-ID metrics")
    parser.add_argument("--organization-id", default="", help="Organization UUID")
    parser.add_argument("--lookback-minutes", type=int, default=120)
    parser.add_argument("--min-camera-count", type=int, default=2)
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument(
        "--output",
        default="data/benchmarks/cross_camera_reid_validation.json",
        help="Output JSON path",
    )
    args = parser.parse_args()

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with SessionLocal() as db:
        organization_id = args.organization_id.strip()
        if not organization_id:
            organization_id = db.execute(text("SELECT id FROM organizations LIMIT 1")).scalar()
        if not organization_id:
            raise SystemExit("No organization found. Provide --organization-id.")

        request = CrossCameraReidRequest(
            lookback_minutes=args.lookback_minutes,
            min_camera_count=args.min_camera_count,
            limit=args.limit,
        )
        result = search_cross_camera_matches(
            db=db,
            organization_id=organization_id,
            request=request,
        )

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "organization_id": str(organization_id),
        "lookback_minutes": args.lookback_minutes,
        "evaluated_logs": result.evaluated_logs,
        "candidate_visitors": result.candidate_visitors,
        "match_count": len(result.matches),
        "notes": "Run against staging data to validate re-ID coverage and transitions.",
    }

    output_path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    print(f"Wrote re-ID validation to {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
