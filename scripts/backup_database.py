#!/usr/bin/env python3
"""Create a PostgreSQL backup with optional encryption."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from cryptography.fernet import Fernet


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


def _read_key(key: Optional[str], key_file: Optional[str], key_env: str) -> bytes:
    if key:
        return key.encode("utf-8")
    if key_file:
        return Path(key_file).read_text(encoding="utf-8").strip().encode("utf-8")
    env_value = os.getenv(key_env, "").strip()
    if env_value:
        return env_value.encode("utf-8")
    raise ValueError("Backup encryption key not provided.")


def _build_output_path(output_dir: str) -> Path:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    directory = Path(output_dir)
    directory.mkdir(parents=True, exist_ok=True)
    return directory / f"db_backup_{timestamp}.sql"


def _run_pg_dump(pg_dump: str, db_url: str, output_path: Path) -> None:
    command = [pg_dump, "--dbname", db_url, "--file", str(output_path)]
    result = subprocess.run(command, check=False)
    if result.returncode != 0:
        raise RuntimeError("pg_dump failed")


def main() -> int:
    parser = argparse.ArgumentParser(description="Create a PostgreSQL backup")
    parser.add_argument("--env-file", default=".env.staging", help="Env file to load")
    parser.add_argument("--database-url", default="", help="Override DATABASE_URL")
    parser.add_argument("--output-dir", default="./backups", help="Backup output directory")
    parser.add_argument("--pg-dump", default="pg_dump", help="pg_dump executable path")
    parser.add_argument("--encrypt", action="store_true", help="Encrypt backup output")
    parser.add_argument("--keep-plain", action="store_true", help="Keep plaintext backup when encrypting")
    parser.add_argument("--key", default="", help="Backup encryption key value")
    parser.add_argument("--key-file", default="", help="Path to backup encryption key file")
    parser.add_argument("--key-env", default="SENTINELCV_BACKUP_KEY", help="Env var for backup key")

    args = parser.parse_args()
    _load_env_file(args.env_file)

    db_url = args.database_url or os.getenv("DATABASE_URL", "").strip()
    if not db_url:
        print("DATABASE_URL missing. Provide --database-url or set it in env file.", file=sys.stderr)
        return 1

    output_path = _build_output_path(args.output_dir)
    try:
        _run_pg_dump(args.pg_dump, db_url, output_path)
    except Exception as exc:
        print(f"Backup failed: {exc}", file=sys.stderr)
        return 1

    if not args.encrypt:
        print(f"Backup created: {output_path}")
        return 0

    try:
        key_bytes = _read_key(args.key or None, args.key_file or None, args.key_env)
    except Exception as exc:
        print(f"Backup encryption key error: {exc}", file=sys.stderr)
        return 1

    fernet = Fernet(key_bytes)
    encrypted_path = output_path.with_suffix(output_path.suffix + ".encrypted")
    encrypted_path.write_bytes(fernet.encrypt(output_path.read_bytes()))

    if not args.keep_plain:
        output_path.unlink(missing_ok=True)

    print(f"Encrypted backup created: {encrypted_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
