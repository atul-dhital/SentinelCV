#!/usr/bin/env python3
"""SentinelCV database monitoring for local staging.

Usage:
  python scripts/db_monitoring.py --env-file .env.staging
  python scripts/db_monitoring.py --database-url postgresql://user:pass@localhost:5432/db
  python scripts/db_monitoring.py --json
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import psycopg2
from psycopg2.extras import RealDictCursor


def _load_env_file(path: str) -> None:
    if not path or not os.path.exists(path):
        return
    with open(path, "r", encoding="utf-8") as handle:
        for line in handle:
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or "=" not in stripped:
                continue
            key, value = stripped.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip())


def _get_database_url(cli_value: Optional[str]) -> str:
    db_url = cli_value or os.getenv("DATABASE_URL", "")
    if not db_url:
        raise ValueError("DATABASE_URL is required (set env var or pass --database-url)")
    if not db_url.startswith("postgresql://"):
        raise ValueError("DATABASE_URL must start with postgresql://")
    return db_url


def _connect(database_url: str):
    return psycopg2.connect(database_url)


def _fetch_one(cursor: RealDictCursor, query: str, params: tuple[Any, ...] | None = None) -> Dict[str, Any]:
    cursor.execute(query, params or ())
    row = cursor.fetchone()
    return dict(row) if row else {}


def _fetch_all(cursor: RealDictCursor, query: str, params: tuple[Any, ...] | None = None) -> List[Dict[str, Any]]:
    cursor.execute(query, params or ())
    return [dict(row) for row in cursor.fetchall()]


def _pg_stat_statements_enabled(cursor: RealDictCursor) -> bool:
    row = _fetch_one(cursor, "SELECT extname FROM pg_extension WHERE extname = 'pg_stat_statements'")
    return row.get("extname") == "pg_stat_statements"


def _collect_connection_stats(cursor: RealDictCursor) -> Dict[str, Any]:
    return _fetch_one(
        cursor,
        """
        SELECT
            COUNT(*) AS total_connections,
            COUNT(*) FILTER (WHERE state = 'active') AS active_connections,
            COUNT(*) FILTER (WHERE state = 'idle') AS idle_connections,
            COUNT(*) FILTER (WHERE state = 'idle in transaction') AS idle_in_transaction
        FROM pg_stat_activity
        WHERE datname = current_database();
        """,
    )


def _collect_cache_stats(cursor: RealDictCursor) -> Dict[str, Any]:
    row = _fetch_one(
        cursor,
        """
        SELECT
            blks_hit,
            blks_read,
            CASE
                WHEN (blks_hit + blks_read) = 0 THEN 0
                ELSE ROUND((blks_hit::numeric / (blks_hit + blks_read)) * 100, 2)
            END AS cache_hit_ratio
        FROM pg_stat_database
        WHERE datname = current_database();
        """,
    )
    return row


def _collect_db_size(cursor: RealDictCursor) -> Dict[str, Any]:
    return _fetch_one(
        cursor,
        "SELECT pg_database_size(current_database()) AS database_size_bytes;",
    )


def _collect_db_settings(cursor: RealDictCursor) -> Dict[str, Any]:
    settings = {}
    max_connections = _fetch_one(cursor, "SHOW max_connections;")
    if max_connections:
        try:
            settings["max_connections"] = int(list(max_connections.values())[0])
        except (ValueError, TypeError, IndexError):
            settings["max_connections"] = None
    return settings


def _collect_slow_queries(cursor: RealDictCursor, limit: int) -> List[Dict[str, Any]]:
    return _fetch_all(
        cursor,
        """
        SELECT
            query,
            calls,
            total_time,
            mean_time,
            rows
        FROM pg_stat_statements
        WHERE query NOT LIKE '%pg_stat_statements%'
        ORDER BY mean_time DESC
        LIMIT %s;
        """,
        (limit,),
    )


def _collect_index_usage(cursor: RealDictCursor, limit: int) -> List[Dict[str, Any]]:
    return _fetch_all(
        cursor,
        """
        SELECT
            relname AS table_name,
            indexrelname AS index_name,
            idx_scan,
            idx_tup_read,
            idx_tup_fetch
        FROM pg_stat_user_indexes
        ORDER BY idx_scan DESC
        LIMIT %s;
        """,
        (limit,),
    )


def _collect_seq_scan_tables(cursor: RealDictCursor, limit: int) -> List[Dict[str, Any]]:
    return _fetch_all(
        cursor,
        """
        SELECT
            relname AS table_name,
            seq_scan,
            seq_tup_read,
            idx_scan,
            n_live_tup
        FROM pg_stat_user_tables
        ORDER BY seq_scan DESC
        LIMIT %s;
        """,
        (limit,),
    )


def _build_index_recommendations(
    seq_scans: List[Dict[str, Any]],
    min_seq_scans: int,
    min_rows: int,
    ratio_threshold: float,
) -> List[Dict[str, Any]]:
    recommendations = []
    for item in seq_scans:
        seq_scan = int(item.get("seq_scan", 0) or 0)
        idx_scan = int(item.get("idx_scan", 0) or 0)
        live_rows = int(item.get("n_live_tup", 0) or 0)

        if seq_scan < min_seq_scans or live_rows < min_rows:
            continue

        if idx_scan == 0 or seq_scan > idx_scan * ratio_threshold:
            recommendations.append(
                {
                    "table": item.get("table_name"),
                    "seq_scan": seq_scan,
                    "idx_scan": idx_scan,
                    "rows": live_rows,
                    "reason": "High sequential scan ratio; review filters and add indexes on WHERE columns.",
                }
            )

    return recommendations


def _compute_connection_utilization(
    connections: Dict[str, Any],
    max_connections: Optional[int],
) -> Optional[float]:
    if not max_connections:
        return None
    total = int(connections.get("total_connections", 0) or 0)
    if max_connections <= 0:
        return None
    return round(total / max_connections, 4)


def _format_report(report: Dict[str, Any]) -> str:
    lines: List[str] = []
    lines.append("Database Monitoring Summary")
    lines.append("=" * 72)

    connections = report.get("connections", {})
    lines.append("Connections:")
    lines.append(f"  total: {connections.get('total_connections', 0)}")
    lines.append(f"  active: {connections.get('active_connections', 0)}")
    lines.append(f"  idle: {connections.get('idle_connections', 0)}")
    lines.append(f"  idle in transaction: {connections.get('idle_in_transaction', 0)}")
    utilization = report.get("connection_utilization")
    if utilization is not None:
        lines.append(f"  utilization: {utilization * 100:.2f}%")

    cache = report.get("cache", {})
    lines.append("Cache:")
    lines.append(f"  hit ratio: {cache.get('cache_hit_ratio', 0)}%")

    db_size = report.get("database", {})
    size_bytes = db_size.get("database_size_bytes", 0)
    size_mb = round(size_bytes / (1024 * 1024), 2) if size_bytes else 0
    lines.append("Database:")
    lines.append(f"  size: {size_mb} MB")

    if report.get("pg_stat_statements_enabled"):
        lines.append("Slow queries:")
        for item in report.get("slow_queries", []):
            query = (item.get("query") or "").replace("\n", " ")[:120]
            lines.append(
                f"  mean={item.get('mean_time', 0):.2f}ms calls={item.get('calls', 0)} rows={item.get('rows', 0)} | {query}"
            )
    else:
        lines.append("Slow queries:")
        lines.append("  pg_stat_statements not enabled")

    lines.append("Index usage (top):")
    for item in report.get("index_usage", []):
        lines.append(
            f"  {item.get('table_name')} | {item.get('index_name')} | idx_scan={item.get('idx_scan', 0)}"
        )

    lines.append("Sequential scan hotspots:")
    for item in report.get("seq_scans", []):
        lines.append(
            f"  {item.get('table_name')} | seq_scan={item.get('seq_scan', 0)} rows={item.get('seq_tup_read', 0)}"
        )

    if report.get("index_recommendations"):
        lines.append("Index recommendations:")
        for item in report.get("index_recommendations", []):
            lines.append(
                f"  {item.get('table')} | seq_scan={item.get('seq_scan')} idx_scan={item.get('idx_scan')} rows={item.get('rows')}"
            )
            lines.append(f"    - {item.get('reason')}")

    if report.get("warnings"):
        lines.append("Warnings:")
        for warning in report.get("warnings", []):
            lines.append(f"  - {warning}")

    return "\n".join(lines)


def _write_index_report(
    report_path: Path,
    report: Dict[str, Any],
    seq_scan_min: int,
    seq_scan_ratio: float,
    min_rows: int,
) -> None:
    report_path.parent.mkdir(parents=True, exist_ok=True)

    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ")
    recommendations = report.get("index_recommendations", [])

    lines: List[str] = []
    lines.append("# DB Index Suggestions")
    lines.append("")
    lines.append(f"Generated: {generated_at}")
    lines.append("")
    lines.append("## Thresholds")
    lines.append(f"- Minimum sequential scans: {seq_scan_min}")
    lines.append(f"- Seq scan to index scan ratio: {seq_scan_ratio}")
    lines.append(f"- Minimum live rows: {min_rows}")
    lines.append("")

    if not recommendations:
        lines.append("## Suggestions")
        lines.append("No index suggestions detected for the current thresholds.")
        report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return

    lines.append("## Suggestions")
    lines.append("")
    lines.append("| Table | Seq Scans | Index Scans | Live Rows | Recommendation |")
    lines.append("| --- | ---: | ---: | ---: | --- |")
    for item in recommendations:
        lines.append(
            "| {table} | {seq_scan} | {idx_scan} | {rows} | {reason} |".format(
                table=item.get("table"),
                seq_scan=item.get("seq_scan"),
                idx_scan=item.get("idx_scan"),
                rows=item.get("rows"),
                reason=item.get("reason"),
            )
        )

    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="SentinelCV DB monitoring")
    parser.add_argument("--database-url", help="PostgreSQL connection URL")
    parser.add_argument("--env-file", default=".env.staging", help="Optional env file")
    parser.add_argument("--json", action="store_true", help="Output JSON instead of text")
    parser.add_argument("--limit", type=int, default=10, help="Limit for top queries/indexes")
    parser.add_argument("--slow-ms", type=float, default=250.0, help="Slow query threshold in milliseconds")
    parser.add_argument("--seq-scan-min", type=int, default=100, help="Minimum sequential scans for index recommendation")
    parser.add_argument("--seq-scan-ratio", type=float, default=5.0, help="Seq scan to idx scan ratio threshold")
    parser.add_argument("--min-rows", type=int, default=1000, help="Minimum row count for index recommendation")
    parser.add_argument(
        "--report-file",
        default="doc/DB_INDEX_SUGGESTIONS.md",
        help="Path to write index suggestion report",
    )
    args = parser.parse_args()

    try:
        _load_env_file(args.env_file)
        database_url = _get_database_url(args.database_url)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    report: Dict[str, Any] = {
        "pg_stat_statements_enabled": False,
        "connections": {},
        "connection_utilization": None,
        "settings": {},
        "cache": {},
        "database": {},
        "slow_queries": [],
        "index_usage": [],
        "seq_scans": [],
        "index_recommendations": [],
        "warnings": [],
    }

    try:
        with _connect(database_url) as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                report["pg_stat_statements_enabled"] = _pg_stat_statements_enabled(cursor)
                if not report["pg_stat_statements_enabled"]:
                    report["warnings"].append("pg_stat_statements is not enabled; slow query insights limited")
                report["connections"] = _collect_connection_stats(cursor)
                report["cache"] = _collect_cache_stats(cursor)
                report["database"] = _collect_db_size(cursor)
                report["settings"] = _collect_db_settings(cursor)
                report["index_usage"] = _collect_index_usage(cursor, args.limit)
                report["seq_scans"] = _collect_seq_scan_tables(cursor, args.limit)
                if report["pg_stat_statements_enabled"]:
                    report["slow_queries"] = _collect_slow_queries(cursor, args.limit)

                report["connection_utilization"] = _compute_connection_utilization(
                    report["connections"],
                    report.get("settings", {}).get("max_connections"),
                )
                report["index_recommendations"] = _build_index_recommendations(
                    report["seq_scans"],
                    args.seq_scan_min,
                    args.min_rows,
                    args.seq_scan_ratio,
                )

                utilization = report["connection_utilization"]
                if utilization is not None and utilization >= 0.8:
                    report["warnings"].append(
                        f"High connection utilization: {utilization * 100:.1f}%"
                    )

                if report["pg_stat_statements_enabled"]:
                    slow_threshold = args.slow_ms
                    for entry in report["slow_queries"]:
                        mean_time = float(entry.get("mean_time", 0.0) or 0.0)
                        if mean_time >= slow_threshold:
                            query = (entry.get("query") or "").replace("\n", " ")[:120]
                            report["warnings"].append(
                                f"Slow query (mean {mean_time:.1f}ms): {query}"
                            )
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    report_path = Path(args.report_file)
    if not report_path.is_absolute():
        report_path = (Path(__file__).resolve().parents[1] / report_path).resolve()

    _write_index_report(
        report_path,
        report,
        args.seq_scan_min,
        args.seq_scan_ratio,
        args.min_rows,
    )

    if args.json:
        print(json.dumps(report, indent=2))
        return 0

    print(_format_report(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
