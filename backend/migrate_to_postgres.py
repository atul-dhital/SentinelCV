"""
Database Migration Script for SentinelCV.

Migrates data from SQLite (dev) to PostgreSQL + pgvector (production).

Usage:
    # 1. Start PostgreSQL with pgvector (via docker-compose)
    docker compose up -d db

    # 2. Create schema using Alembic (or let SQLAlchemy auto-create)
    DATABASE_URL=postgresql://postgres:postgres@localhost:5432/visitor_db \
        python -c "from db.base import engine, Base; from models.models import *; Base.metadata.create_all(bind=engine)"

    # 3. Enable pgvector extension
    psql -U postgres -d visitor_db -c "CREATE EXTENSION IF NOT EXISTS vector;"

    # 4. Run migration (add --dry-run to validate without writing)
    python migrate_to_postgres.py [path/to/sentinelcv.db] [--dry-run]

Dry-run mode reads all rows and decrypts embeddings but commits nothing.
On any unrecoverable error, all changes since the last per-table commit
are rolled back before the script exits.
"""

import os
import sys
import json
import sqlite3
import ast
import traceback
from typing import List, Optional


def _decrypt_embedding_for_migration(encrypted: str) -> str:
    """Decrypt a v1: Fernet embedding string using HKDF key derivation.
    Tries the configured EMBEDDING_KEY_SECRET first, then the dev-fallback key."""
    import base64
    from cryptography.hazmat.primitives.kdf.hkdf import HKDF
    from cryptography.hazmat.primitives import hashes
    from cryptography.fernet import Fernet, InvalidToken

    _HKDF_INFO = b"sentinelcv-embedding-encryption-v1"
    _HKDF_SALT = b"sentinelcv|embedding|v1"

    def _make_fernet(secret: str) -> Fernet:
        key = base64.urlsafe_b64encode(
            HKDF(algorithm=hashes.SHA256(), length=32,
                 salt=_HKDF_SALT, info=_HKDF_INFO).derive(secret.encode())
        )
        return Fernet(key)

    payload = encrypted[len("v1:"):]
    secrets_to_try = [
        os.getenv("EMBEDDING_KEY_SECRET", ""),
        "sentinelcv-dev-embedding-key-not-for-production",
    ]
    for secret in secrets_to_try:
        if not secret:
            continue
        try:
            return _make_fernet(secret).decrypt(payload.encode()).decode()
        except (InvalidToken, Exception):
            continue
    raise ValueError(f"Could not decrypt embedding with any known key")


def get_sqlite_connection(db_path: str = "sentinelcv.db"):
    """Connect to SQLite database."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def get_postgres_connection():
    """Connect to PostgreSQL database."""
    import psycopg2
    from dotenv import load_dotenv
    load_dotenv()

    DATABASE_URL = os.getenv("DATABASE_URL")
    if not DATABASE_URL:
        raise RuntimeError(
            "DATABASE_URL environment variable must be set before running this migration script."
        )
    return psycopg2.connect(DATABASE_URL)


def _sqlite_table_exists(conn, table_name: str) -> bool:
    cur = conn.cursor()
    cur.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
        (table_name,),
    )
    return cur.fetchone() is not None


def _get_sqlite_columns(conn, table_name: str) -> List[str]:
    cur = conn.cursor()
    cur.execute(f"PRAGMA table_info({table_name})")
    return [row[1] for row in cur.fetchall()]


def _get_pg_columns(pg_conn, table_name: str) -> dict:
    """Return {column_name: (data_type, udt_name)} for a Postgres table.

    Used to make the migrator tolerant of schema drift between the SQLite
    snapshot's columns and the current (alembic-managed) Postgres schema.
    """
    cur = pg_conn.cursor()
    cur.execute(
        "SELECT column_name, data_type, udt_name FROM information_schema.columns "
        "WHERE table_schema='public' AND table_name=%s",
        (table_name,),
    )
    info = {r[0]: (r[1], r[2]) for r in cur.fetchall()}
    cur.close()
    return info


def _safe_json(value) -> str:
    """Ensure value is a JSON string suitable for JSONB columns."""
    if value is None:
        return "{}"
    if isinstance(value, str):
        try:
            json.loads(value)
            return value
        except (json.JSONDecodeError, ValueError):
            return json.dumps(value)
    return json.dumps(value)


def _migrate_generic(
    sqlite_conn,
    pg_conn,
    table_name: str,
    columns: List[str],
    *,
    jsonb_columns: Optional[List[str]] = None,
    vector_columns: Optional[List[str]] = None,
    bool_columns: Optional[List[str]] = None,
    on_conflict: str = "DO NOTHING",
    dry_run: bool = False,
    skip_errors: Optional[List[str]] = None,
):
    """Generic table migration helper.

    Reads all rows from the SQLite table and inserts them into the
    corresponding PostgreSQL table.  Handles JSONB serialisation,
    vector casting, and SQLite integer→boolean coercion automatically.

    dry_run=True validates all rows (including decryption) but commits nothing.
    Row-level errors are appended to skip_errors and execution continues.
    """
    jsonb_columns = jsonb_columns or []
    vector_columns = vector_columns or []
    bool_columns = bool_columns or []
    _errors = skip_errors if skip_errors is not None else []

    if not _sqlite_table_exists(sqlite_conn, table_name):
        print(f"  {table_name}: table not found in SQLite, skipping")
        return

    existing_cols = _get_sqlite_columns(sqlite_conn, table_name)
    pg_info = _get_pg_columns(pg_conn, table_name)
    if not pg_info:
        print(f"  {table_name}: table not found in PostgreSQL, skipping")
        return
    # Only migrate columns that exist in BOTH the SQLite snapshot and the live
    # PG schema — silently drop columns that were removed/renamed by migrations.
    usable_cols = [c for c in columns if c in existing_cols and c in pg_info]
    dropped = [c for c in columns if c in existing_cols and c not in pg_info]
    if dropped:
        print(f"    note: dropping columns absent from PG schema: {dropped}")
    if not usable_cols:
        print(f"  {table_name}: no matching columns found, skipping")
        return
    # Derive type handling from the live PG schema (augments the explicit lists),
    # so int->bool, json/jsonb, and pgvector casts are correct even if the
    # hardcoded lists drifted from the current schema.
    bool_columns = list(set(bool_columns) | {c for c in usable_cols if pg_info[c][0] == "boolean"})
    jsonb_columns = list(set(jsonb_columns) | {c for c in usable_cols if pg_info[c][0] in ("json", "jsonb")})
    vector_columns = list(set(vector_columns) | {c for c in usable_cols if pg_info[c][1] == "vector"})

    prefix = "[DRY-RUN] " if dry_run else ""
    print(f"  {prefix}Migrating {table_name}...")
    cur = sqlite_conn.cursor()
    # Quote identifiers — some tables have reserved-word columns (e.g. "order").
    _sel_cols = ", ".join(f'"{c}"' for c in usable_cols)
    cur.execute(f'SELECT {_sel_cols} FROM "{table_name}"')
    rows = cur.fetchall()

    pg_cur = pg_conn.cursor() if not dry_run else None
    migrated = 0
    for row in rows:
        values = []
        pg_cols = []
        placeholders = []
        for i, col in enumerate(usable_cols):
            val = row[i]
            pg_cols.append(col)
            if col in vector_columns:
                if val and isinstance(val, str):
                    # Decrypt Fernet-encrypted embedding stored in SQLite
                    raw = val
                    try:
                        import json as _json
                        outer = _json.loads(raw)
                        if isinstance(outer, str):
                            raw = outer  # strip JSON-string wrapper
                    except Exception:
                        pass
                    if raw.startswith("v1:"):
                        try:
                            raw = _decrypt_embedding_for_migration(raw)
                        except Exception as _dec_exc:
                            _errors.append(f"{table_name}: decrypt failed: {_dec_exc}")
                    try:
                        val = _json.loads(raw)
                    except (ValueError, SyntaxError):
                        try:
                            val = ast.literal_eval(raw)
                        except Exception:
                            val = None
                if val and isinstance(val, (list, tuple)):
                    placeholders.append("%s::vector")
                    values.append(json.dumps(list(val)))
                else:
                    placeholders.append("%s")
                    values.append(None)
            elif col in bool_columns:
                placeholders.append("%s")
                values.append(bool(val) if val is not None else None)
            elif col in jsonb_columns:
                placeholders.append("%s::jsonb")
                values.append(_safe_json(val))
            else:
                placeholders.append("%s")
                values.append(val)

        if dry_run:
            migrated += 1
            continue

        _ins_cols = ", ".join(f'"{c}"' for c in pg_cols)
        sql = (
            f'INSERT INTO "{table_name}" ({_ins_cols}) '
            f"VALUES ({', '.join(placeholders)}) "
            f"ON CONFLICT (id) {on_conflict}"
        )
        try:
            # Per-row savepoint so one bad row doesn't discard the whole table's
            # already-inserted rows (a plain rollback() would wipe everything
            # since the last per-table commit).
            pg_cur.execute("SAVEPOINT _row")
            pg_cur.execute(sql, values)
            pg_cur.execute("RELEASE SAVEPOINT _row")
            migrated += 1
        except Exception as exc:
            pg_cur.execute("ROLLBACK TO SAVEPOINT _row")
            msg = f"{table_name}: row skipped: {exc}"
            _errors.append(msg)
            print(f"    WARN: {msg}")
            continue

    if not dry_run:
        pg_conn.commit()
    print(f"    -> {prefix}{migrated}/{len(rows)} rows {'validated' if dry_run else 'migrated'}")


def run_migration(sqlite_db: str = "sentinelcv.db", dry_run: bool = False):
    """Run complete migration from SQLite to PostgreSQL.

    dry_run=True validates all data (decryption, type coercion) without
    writing anything to PostgreSQL. Use it to catch problems before the
    real run.
    """
    mode = "DRY-RUN VALIDATION" if dry_run else "MIGRATION"
    print(f"Starting {mode} from {sqlite_db} to PostgreSQL...\n")

    if not os.path.exists(sqlite_db):
        print(f"Error: SQLite database {sqlite_db} not found!")
        return False

    skip_errors: List[str] = []

    try:
        sqlite_conn = get_sqlite_connection(sqlite_db)
        pg_conn = get_postgres_connection()

        # Enable pgvector extension
        pg_cur = pg_conn.cursor()
        if not dry_run:
            pg_cur.execute("CREATE EXTENSION IF NOT EXISTS vector;")
            pg_conn.commit()
            print("pgvector extension enabled\n")
        else:
            print("pgvector check skipped in dry-run mode\n")

        # ── Core tables (order matters for FK constraints) ──────────────
        _migrate_generic(sqlite_conn, pg_conn, "organizations", [
            "id", "name", "api_key", "face_confidence_threshold",
            "log_retention_days", "notification_email",
            "notification_unidentified", "settings", "created_at",
        ], jsonb_columns=["settings"], dry_run=dry_run, skip_errors=skip_errors)

        _migrate_generic(sqlite_conn, pg_conn, "users", [
            "id", "organization_id", "email", "full_name", "password_hash",
            "role", "is_active", "created_at",
        ], dry_run=dry_run, skip_errors=skip_errors)

        _migrate_generic(sqlite_conn, pg_conn, "camera_groups", [
            "id", "organization_id", "name", "description", "color", "created_at",
        ], dry_run=dry_run, skip_errors=skip_errors)

        _migrate_generic(sqlite_conn, pg_conn, "visitors", [
            "id", "organization_id", "name", "email", "phone", "description",
            "notes", "visitor_metadata", "is_known", "is_active",
            "created_at", "updated_at", "last_detected_at",
            "detection_count", "custom_threshold", "auto_learn",
        ], jsonb_columns=["visitor_metadata"], dry_run=dry_run, skip_errors=skip_errors)

        _migrate_generic(sqlite_conn, pg_conn, "face_data", [
            "id", "visitor_id", "embedding", "image_url", "quality_score",
            "is_primary", "created_at",
        ], vector_columns=["embedding"], dry_run=dry_run, skip_errors=skip_errors)

        _migrate_generic(sqlite_conn, pg_conn, "cameras", [
            "id", "organization_id", "name", "rtsp_url", "location",
            "is_active", "status", "last_seen", "created_at",
            "group_id", "frame_rate", "health_status",
        ], dry_run=dry_run, skip_errors=skip_errors)

        _migrate_generic(sqlite_conn, pg_conn, "visitor_logs", [
            "id", "organization_id", "visitor_id", "camera_id",
            "face_data_id", "timestamp", "video_snippet_path",
            "face_image_path", "confidence", "identified", "status",
            "track_id", "source_video",
        ], dry_run=dry_run, skip_errors=skip_errors)

        _migrate_generic(sqlite_conn, pg_conn, "liveness_scores", [
            "id", "organization_id", "visitor_log_id",
            "is_live", "overall_score", "rejection_reason",
            "texture_score", "motion_score", "deep_learning_score",
            "video_required", "video_duration_frames",
            "has_sufficient_motion", "blink_count",
            "attack_indicators", "face_size", "illumination_score",
            "blur_score", "noise_level",
            "challenge_type", "challenge_passed", "challenge_attempts",
            "method_used", "model_version", "processing_time_ms",
            "created_at", "updated_at",
        ], jsonb_columns=["attack_indicators"], dry_run=dry_run, skip_errors=skip_errors)

        _migrate_generic(sqlite_conn, pg_conn, "liveness_challenges", [
            "id", "organization_id", "visitor_log_id",
            "challenge_type", "status", "instruction", "timeout_seconds",
            "verified", "confidence", "details", "attempts",
            "created_at", "verified_at",
        ], jsonb_columns=["details"], dry_run=dry_run, skip_errors=skip_errors)

        _migrate_generic(sqlite_conn, pg_conn, "audit_logs", [
            "id", "organization_id", "user_id", "action",
            "entity_type", "entity_id", "details",
            "before_values", "after_values", "timestamp",
        ], jsonb_columns=["details", "before_values", "after_values"], dry_run=dry_run, skip_errors=skip_errors)

        _migrate_generic(sqlite_conn, pg_conn, "password_reset_tokens", [
            "id", "user_id", "token", "expires_at", "used", "created_at",
        ], dry_run=dry_run, skip_errors=skip_errors)

        _migrate_generic(sqlite_conn, pg_conn, "video_processing_jobs", [
            "id", "organization_id", "file_id", "file_path",
            "status", "message", "people_detected",
            "people_identified", "created_at", "updated_at",
        ], dry_run=dry_run, skip_errors=skip_errors)

        _migrate_generic(sqlite_conn, pg_conn, "camera_sessions", [
            "id", "organization_id", "user_id", "camera_id",
            "status", "started_at", "ended_at",
            "total_frames", "total_detections", "total_identifications",
            "settings",
        ], jsonb_columns=["settings"], dry_run=dry_run, skip_errors=skip_errors)

        _migrate_generic(sqlite_conn, pg_conn, "detection_logs", [
            "id", "session_id", "visitor_id", "timestamp",
            "confidence", "bbox", "face_image_path", "identified",
            "embedding_snapshot",
        ], jsonb_columns=["bbox"], vector_columns=["embedding_snapshot"], dry_run=dry_run, skip_errors=skip_errors)

        _migrate_generic(sqlite_conn, pg_conn, "visitor_alerts", [
            "id", "session_id", "visitor_id", "alert_type",
            "message", "timestamp", "acknowledged",
        ], dry_run=dry_run, skip_errors=skip_errors)

        # ── Extension tables ────────────────────────────────────────────
        _migrate_generic(sqlite_conn, pg_conn, "webhooks", [
            "id", "organization_id", "url", "secret", "events",
            "is_active", "created_at",
        ], jsonb_columns=["events"], dry_run=dry_run, skip_errors=skip_errors)

        _migrate_generic(sqlite_conn, pg_conn, "webhook_logs", [
            "id", "webhook_id", "event", "payload",
            "response_status", "response_body", "success", "created_at",
        ], jsonb_columns=["payload"], dry_run=dry_run, skip_errors=skip_errors)

        _migrate_generic(sqlite_conn, pg_conn, "api_keys", [
            "id", "organization_id", "name", "key_hash", "key_prefix",
            "permissions", "is_active", "last_used_at", "expires_at",
            "created_at",
        ], jsonb_columns=["permissions"], dry_run=dry_run, skip_errors=skip_errors)

        _migrate_generic(sqlite_conn, pg_conn, "notifications", [
            "id", "organization_id", "user_id", "title", "message",
            "notification_type", "is_read", "link", "created_at",
        ], dry_run=dry_run, skip_errors=skip_errors)

        _migrate_generic(sqlite_conn, pg_conn, "data_retention_policies", [
            "id", "organization_id", "data_type",
            "retention_days", "auto_delete_enabled", "last_cleanup_at", "created_at",
        ], dry_run=dry_run, skip_errors=skip_errors)

        _migrate_generic(sqlite_conn, pg_conn, "future_enhancements", [
            "id", "organization_id", "story_id", "category",
            "title", "description", "status", "priority",
            "config", "metrics", "roadmap_phase", "enabled",
            "created_at", "updated_at",
        ], jsonb_columns=["config", "metrics"], dry_run=dry_run, skip_errors=skip_errors)

        _migrate_generic(sqlite_conn, pg_conn, "rate_limit_rules", [
            "id", "organization_id", "endpoint_pattern",
            "max_requests", "window_seconds", "current_count",
            "window_start", "is_active", "created_at",
        ], dry_run=dry_run, skip_errors=skip_errors)

        _migrate_generic(sqlite_conn, pg_conn, "carbon_metrics", [
            "id", "organization_id", "period_start", "period_end",
            "gpu_hours", "cpu_hours", "estimated_kwh", "estimated_co2_kg",
            "training_runs", "inference_count", "optimization_notes",
            "created_at",
        ], dry_run=dry_run, skip_errors=skip_errors)

        _migrate_generic(sqlite_conn, pg_conn, "training_jobs", [
            "id", "organization_id", "status", "config",
            "accuracy", "precision", "recall", "f1_score",
            "metrics_history", "started_at", "completed_at",
            "created_at", "started_by",
        ], jsonb_columns=["config", "metrics_history"], dry_run=dry_run, skip_errors=skip_errors)

        _migrate_generic(sqlite_conn, pg_conn, "hpo_jobs", [
            "id", "organization_id", "status", "n_trials",
            "best_params", "best_value", "trial_results",
            "created_at", "completed_at", "started_by",
        ], jsonb_columns=["best_params", "trial_results"], dry_run=dry_run, skip_errors=skip_errors)

        _migrate_generic(sqlite_conn, pg_conn, "ensembles", [
            "id", "organization_id", "name", "model_ids",
            "weights", "accuracy", "created_at", "created_by",
        ], jsonb_columns=["model_ids", "weights"], dry_run=dry_run, skip_errors=skip_errors)

        _migrate_generic(sqlite_conn, pg_conn, "active_learning_jobs", [
            "id", "organization_id", "strategy", "status",
            "n_samples", "selected_samples", "created_at", "created_by",
        ], jsonb_columns=["selected_samples"], dry_run=dry_run, skip_errors=skip_errors)

        _migrate_generic(sqlite_conn, pg_conn, "alert_configs", [
            "id", "organization_id", "alerts_enabled",
            "email_alerts_enabled", "webhook_alerts_enabled",
            "min_confidence_threshold", "alert_duplicate_window_seconds",
            "enabled_alert_types", "default_action",
            "created_at", "updated_at",
        ], jsonb_columns=["enabled_alert_types"], dry_run=dry_run, skip_errors=skip_errors)

        _migrate_generic(sqlite_conn, pg_conn, "alert_rules", [
            "id", "organization_id", "alert_config_id",
            "name", "description", "is_active", "priority", "order",
            "trigger_type", "min_confidence", "max_confidence",
            "include_visitor_ids", "include_camera_ids",
            "time_range_start", "time_range_end", "days_of_week",
            "action", "webhook_id", "notification_template",
            "max_alerts_per_hour", "created_at", "updated_at",
        ], jsonb_columns=["include_visitor_ids", "include_camera_ids", "days_of_week"], dry_run=dry_run, skip_errors=skip_errors)

        sqlite_conn.close()
        pg_conn.close()

        print("\n" + "=" * 60)
        if dry_run:
            print("DRY-RUN VALIDATION completed — nothing written to PostgreSQL.")
        else:
            print("Migration completed successfully!")
        print("=" * 60)

        if skip_errors:
            print(f"\n  {len(skip_errors)} row(s) skipped:")
            for err in skip_errors:
                print(f"    - {err}")
        else:
            print("\n  No row-level errors.")

        if not dry_run:
            print("\nTo switch to PostgreSQL, update your .env file:")
            print('  DATABASE_URL=postgresql://postgres:postgres@localhost:5432/visitor_db')
            print("\nOr start the full stack via docker-compose:")
            print("  docker compose up -d")

        return True

    except Exception as e:
        print(f"\n{'Dry-run' if dry_run else 'Migration'} failed: {e}")
        traceback.print_exc()
        try:
            pg_conn.rollback()
            pg_conn.close()
        except Exception:
            pass
        try:
            sqlite_conn.close()
        except Exception:
            pass
        return False


if __name__ == "__main__":
    args = sys.argv[1:]
    dry_run_flag = "--dry-run" in args
    args = [a for a in args if a != "--dry-run"]
    db_file = args[0] if args else "sentinelcv.db"
    success = run_migration(db_file, dry_run=dry_run_flag)
    sys.exit(0 if success else 1)
