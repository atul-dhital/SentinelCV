#!/usr/bin/env python3
"""
SentinelCV — Storage Encryption At Rest Verification

pgvector stores face embeddings as plain vector(512) float columns.
Application-level encryption is not possible without destroying ANN search
capability. This means storage-level encryption MUST be confirmed at the
infrastructure layer.

Run this script before go-live to check whether your PostgreSQL provider has
encryption at rest enabled, and to generate the STORAGE_ENCRYPTED=verified
acknowledgement you must add to your production environment.

Usage:
    python scripts/verify_storage_encryption.py

Reads DATABASE_URL from the environment.
"""

from __future__ import annotations

import os
import sys
from urllib.parse import urlparse

GREEN = "\033[92m"
YELLOW = "\033[93m"
RED = "\033[91m"
BOLD = "\033[1m"
RESET = "\033[0m"


def ok(msg: str) -> None:
    print(f"  {GREEN}✓{RESET}  {msg}")


def warn(msg: str) -> None:
    print(f"  {YELLOW}⚠{RESET}  {msg}")


def fail(msg: str) -> None:
    print(f"  {RED}✗{RESET}  {msg}")


def header(msg: str) -> None:
    print(f"\n{BOLD}{msg}{RESET}")


def detect_provider(db_url: str) -> str:
    """Best-effort provider detection from the DATABASE_URL host."""
    host = (urlparse(db_url).hostname or "").lower()
    if "supabase" in host or "supabase.co" in host:
        return "supabase"
    if "amazonaws.com" in host or "rds.amazonaws" in host:
        return "aws_rds"
    if "cloudsql" in host or "google" in host:
        return "gcp_cloudsql"
    if "azure" in host or "database.windows.net" in host:
        return "azure"
    return "self_hosted"


def check_ssl_in_url(db_url: str) -> bool:
    return "sslmode=require" in db_url or "sslmode=verify" in db_url


def run_sql_check(db_url: str) -> dict:
    """Run basic SQL checks against the database."""
    try:
        import sqlalchemy as sa
        engine = sa.create_engine(db_url, connect_args={"connect_timeout": 10})
        with engine.connect() as conn:
            # Check SSL in use
            try:
                ssl_row = conn.execute(sa.text("SELECT ssl FROM pg_stat_ssl WHERE pid = pg_backend_pid()")).first()
                ssl_active = bool(ssl_row and ssl_row[0])
            except Exception:
                ssl_active = None

            # Check if pgvector is installed
            pgvector = bool(
                conn.execute(sa.text("SELECT 1 FROM pg_extension WHERE extname='vector'")).first()
            )

            # Check if face_data table exists
            face_data = bool(
                conn.execute(sa.text(
                    "SELECT 1 FROM information_schema.tables "
                    "WHERE table_name='face_data'"
                )).first()
            )

        return {"ssl_active": ssl_active, "pgvector": pgvector, "face_data": face_data, "error": None}
    except Exception as exc:
        return {"ssl_active": None, "pgvector": None, "face_data": None, "error": str(exc)}


def print_provider_instructions(provider: str) -> None:
    header("Provider-specific verification steps:")
    if provider == "supabase":
        ok("Supabase enables AES-256 encryption at rest for all projects by default.")
        ok("No action required — your data is encrypted.")
        print("""
  Verify at: https://supabase.com/docs/guides/platform/security#data-at-rest
  Or in your project dashboard: Settings → Infrastructure → Encryption""")

    elif provider == "aws_rds":
        warn("AWS RDS encryption must be enabled at instance creation time.")
        print("""
  Verify:
    aws rds describe-db-instances \\
        --query 'DBInstances[0].StorageEncrypted'
  Expected: true

  If false: you must create a new encrypted instance and migrate.
  Docs: https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/Overview.Encryption.html""")

    elif provider == "gcp_cloudsql":
        warn("GCP Cloud SQL uses Google-managed keys by default (CMEK optional).")
        print("""
  Verify:
    gcloud sql instances describe INSTANCE_NAME \\
        --format="value(diskEncryptionConfiguration)"

  For Customer-Managed Encryption Keys (CMEK):
  Docs: https://cloud.google.com/sql/docs/postgres/cmek""")

    elif provider == "azure":
        ok("Azure Database for PostgreSQL uses TDE by default.")
        print("""
  Verify in Azure Portal:
    Resource → Security → Transparent Data Encryption
  Docs: https://docs.microsoft.com/azure/postgresql/single-server/concepts-data-encryption-postgresql""")

    else:
        warn("Self-hosted PostgreSQL — you must configure encryption manually.")
        print("""
  Options:
  1. pg_tde extension (PostgreSQL 16+):
       CREATE EXTENSION IF NOT EXISTS pg_tde;
       Docs: https://github.com/percona/pg_tde

  2. Filesystem encryption (recommended):
       - Linux: dm-crypt/LUKS on the PostgreSQL data volume
         cryptsetup luksFormat /dev/sdb && cryptsetup luksOpen /dev/sdb pg_data
       - Ensure /var/lib/postgresql is on the encrypted volume

  3. Cloud VM disk encryption (AWS EBS, GCP PD, Azure Disk):
       Enable encryption on the disk where PostgreSQL stores data.

  Without one of the above, face embeddings are stored as plaintext on disk.""")


def main() -> int:
    print(f"\n{BOLD}SentinelCV — Storage Encryption At Rest Verification{RESET}")
    print("=" * 58)

    db_url = os.getenv("DATABASE_URL", "").strip()
    if not db_url:
        fail("DATABASE_URL is not set. Export it and re-run.")
        return 1

    if not db_url.startswith("postgresql"):
        warn("DATABASE_URL is not PostgreSQL — no encryption check needed for SQLite (dev only).")
        return 0

    provider = detect_provider(db_url)
    header(f"Detected provider: {provider.replace('_', ' ').title()}")

    # SSL check
    header("Connection security:")
    if check_ssl_in_url(db_url):
        ok("DATABASE_URL includes sslmode=require — connection is encrypted in transit.")
    else:
        warn("DATABASE_URL does not include sslmode=require. Add ?sslmode=require for encrypted transport.")

    # SQL checks
    header("Database checks:")
    result = run_sql_check(db_url)
    if result["error"]:
        fail(f"Could not connect: {result['error']}")
    else:
        if result["ssl_active"] is True:
            ok("pg_stat_ssl confirms SSL is active for this connection.")
        elif result["ssl_active"] is False:
            warn("pg_stat_ssl shows SSL is NOT active. Connection is unencrypted.")
        else:
            warn("Could not determine SSL status from pg_stat_ssl.")

        if result["pgvector"]:
            ok("pgvector extension is installed (face_data table uses vector columns).")
        if result["face_data"]:
            ok("face_data table exists — biometric data is stored here.")

    # Provider instructions
    print_provider_instructions(provider)

    # Acknowledgement
    header("Acknowledgement:")
    print("""
Once you have confirmed that storage encryption at rest is enabled,
add this to your production environment:

    STORAGE_ENCRYPTED=verified

This will change the /health/readiness check from 'warn' to 'pass'
and silence the startup warning.
""")

    already = os.getenv("STORAGE_ENCRYPTED", "").strip().lower()
    if already == "verified":
        ok("STORAGE_ENCRYPTED=verified is already set. Readiness check will show 'pass'.")
        return 0
    else:
        warn("STORAGE_ENCRYPTED is not set to 'verified' yet.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
