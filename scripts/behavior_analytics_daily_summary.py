#!/usr/bin/env python3
"""Generate a baseline behavior analytics daily summary (stub with safe DB queries)."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict

from sqlalchemy import create_engine, text


def _safe_count(engine, table_name: str) -> Dict[str, object]:
    try:
        with engine.connect() as conn:
            result = conn.execute(text(f"SELECT COUNT(*) FROM {table_name}"))
            count = result.scalar() or 0
        return {"table": table_name, "count": int(count), "status": "ok"}
    except Exception as exc:
        return {"table": table_name, "count": 0, "status": "unavailable", "error": str(exc)}


def main() -> int:
    db_url = os.getenv("DATABASE_URL", "sqlite:///./sentinelcv.db")
    output_path = Path("data/benchmarks/behavior_analytics_daily_summary.json")
    output_path.parent.mkdir(parents=True, exist_ok=True)

    engine = create_engine(db_url)
    try:
        tables = [
            "behavior_events",
            "vision_analytics_events",
            "cross_camera_movement_summaries",
            "visitor_logs",
        ]
        counts = [_safe_count(engine, table) for table in tables]
    finally:
        engine.dispose()

    summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "database_url": db_url,
        "status": "partial" if any(item["status"] != "ok" for item in counts) else "ok",
        "counts": counts,
        "baseline_metrics": [
            "behavior_event_count",
            "anomaly_event_count",
            "top_postures",
            "top_actions",
            "top_gestures",
            "cross_camera_transition_count",
        ],
        "notes": "Baseline daily summary stub; add aggregation by posture, action, anomaly severity.",
    }

    output_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(f"Wrote daily summary stub to {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
