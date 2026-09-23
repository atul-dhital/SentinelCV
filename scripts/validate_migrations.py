#!/usr/bin/env python3
"""Validate that database migrations have been applied correctly.

Connects to the configured database and checks that expected tables,
columns, and indices exist. Designed to run in CI or manually after
applying migrations.

Usage:
    python scripts/validate_migrations.py
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from sqlalchemy import create_engine, inspect, text
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./sentinelcv.db")
IS_SQLITE = DATABASE_URL.startswith("sqlite")

# Tables that must exist for the application to function
REQUIRED_TABLES = [
    "organizations",
    "users",
    "visitors",
    "face_data",
    "cameras",
    "visitor_logs",
    "audit_logs",
    "refresh_token_sessions",
    "edge_devices",
    "liveness_scores",
    "liveness_challenges",
    "notifications",
    "webhooks",
    "camera_groups",
    "future_enhancements",
]

# Critical columns that must exist on specific tables
REQUIRED_COLUMNS = {
    "face_data": ["id", "visitor_id", "embedding", "image_url", "quality_score", "face_angle", "is_primary"],
    "visitors": ["id", "organization_id", "name", "is_known", "is_active", "detection_count"],
    "visitor_logs": ["id", "organization_id", "visitor_id", "camera_id", "confidence", "timestamp"],
    "users": ["id", "organization_id", "email", "password_hash", "role", "is_active"],
    "liveness_scores": ["id", "organization_id", "is_live", "overall_score", "texture_score", "motion_score"],
    "liveness_challenges": ["id", "organization_id", "challenge_type", "status", "verified"],
}

# Indices expected on PostgreSQL (SQLite doesn't support the same index inspection)
EXPECTED_PG_INDICES = [
    ("face_data", "ix_face_data_visitor_id"),
    ("face_data", "ix_face_data_is_primary"),
    ("face_data", "ix_face_data_quality_score"),
    ("visitor_logs", "ix_visitor_logs_visitor_timestamp"),
    ("visitor_logs", "ix_visitor_logs_org_timestamp"),
    ("visitors", "ix_visitors_org_is_known"),
    ("visitors", "ix_visitors_org_is_active"),
    ("liveness_scores", "ix_liveness_scores_org_created"),
]


def validate() -> bool:
    connect_args = {}
    if IS_SQLITE:
        connect_args["check_same_thread"] = False

    engine = create_engine(DATABASE_URL, connect_args=connect_args)
    inspector = inspect(engine)
    passed = True

    # Check tables
    existing_tables = set(inspector.get_table_names())
    print(f"\n{'='*60}")
    print(f"Migration Validation Report")
    print(f"Database: {'SQLite' if IS_SQLITE else 'PostgreSQL'}")
    print(f"{'='*60}\n")

    print("--- Table Check ---")
    for table in REQUIRED_TABLES:
        if table in existing_tables:
            print(f"  [PASS] {table}")
        else:
            print(f"  [FAIL] {table} — MISSING")
            passed = False

    # Check columns
    print("\n--- Column Check ---")
    for table, columns in REQUIRED_COLUMNS.items():
        if table not in existing_tables:
            print(f"  [SKIP] {table} — table missing")
            continue
        existing_columns = {col["name"] for col in inspector.get_columns(table)}
        for column in columns:
            if column in existing_columns:
                print(f"  [PASS] {table}.{column}")
            else:
                print(f"  [FAIL] {table}.{column} — MISSING")
                passed = False

    # Check indices (PostgreSQL only)
    if not IS_SQLITE:
        print("\n--- Index Check (PostgreSQL) ---")

        # Check pgvector extension
        with engine.connect() as conn:
            ext_result = conn.execute(
                text("SELECT 1 FROM pg_extension WHERE extname = 'vector' LIMIT 1")
            ).scalar()
            if ext_result:
                print("  [PASS] pgvector extension installed")
            else:
                print("  [FAIL] pgvector extension NOT installed")
                passed = False

        for table, index_name in EXPECTED_PG_INDICES:
            if table not in existing_tables:
                print(f"  [SKIP] {index_name} — {table} missing")
                continue
            indices = inspector.get_indexes(table)
            index_names = {idx["name"] for idx in indices}
            if index_name in index_names:
                print(f"  [PASS] {index_name}")
            else:
                print(f"  [FAIL] {index_name} — MISSING")
                passed = False

        # Check pgvector ANN index on face_data.embedding
        if "face_data" in existing_tables:
            with engine.connect() as conn:
                hnsw = conn.execute(
                    text(
                        "SELECT 1 FROM pg_indexes WHERE tablename = 'face_data' "
                        "AND indexname LIKE '%embedding%' LIMIT 1"
                    )
                ).scalar()
                if hnsw:
                    print("  [PASS] face_data embedding vector index")
                else:
                    print("  [WARN] face_data embedding vector index — not found (created at runtime)")
    else:
        print("\n--- Index Check (SQLite) ---")
        print("  [INFO] Detailed index validation skipped for SQLite")
        for table, index_name in EXPECTED_PG_INDICES:
            if table not in existing_tables:
                continue
            indices = inspector.get_indexes(table)
            index_names = {idx["name"] for idx in indices}
            if index_name in index_names:
                print(f"  [PASS] {index_name}")
            else:
                print(f"  [INFO] {index_name} — will be created on PostgreSQL")

    print(f"\n{'='*60}")
    if passed:
        print("RESULT: ALL CHECKS PASSED")
    else:
        print("RESULT: SOME CHECKS FAILED — review output above")
    print(f"{'='*60}\n")

    engine.dispose()
    return passed


if __name__ == "__main__":
    success = validate()
    sys.exit(0 if success else 1)
