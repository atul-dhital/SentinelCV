#!/usr/bin/env python3
"""Restore a PostgreSQL backup with optional decryption."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Optional

from cryptography.fernet import Fernet, InvalidToken


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


def _run_psql(psql: str, db_url: str, input_path: Path) -> None:
    command = [psql, "--dbname", db_url, "--file", str(input_path)]
    result = subprocess.run(command, check=False)
    if result.returncode != 0:
        raise RuntimeError("psql restore failed")


def main() -> int:
    parser = argparse.ArgumentParser(description="Restore a PostgreSQL backup")
    parser.add_argument("--env-file", default=".env.staging", help="Env file to load")
    parser.add_argument("--database-url", default="", help="Override DATABASE_URL")
    parser.add_argument("--input", required=True, help="Backup file path")
    parser.add_argument("--psql", default="psql", help="psql executable path")
    parser.add_argument("--encrypted", action="store_true", help="Input backup is encrypted")
    parser.add_argument("--key", default="", help="Backup encryption key value")
    parser.add_argument("--key-file", default="", help="Path to backup encryption key file")
    parser.add_argument("--key-env", default="SENTINELCV_BACKUP_KEY", help="Env var for backup key")

    args = parser.parse_args()
    _load_env_file(args.env_file)

    db_url = args.database_url or os.getenv("DATABASE_URL", "").strip()
    if not db_url:
        print("DATABASE_URL missing. Provide --database-url or set it in env file.", file=sys.stderr)
        return 1

    input_path = Path(args.input)
    if not input_path.exists():
        print(f"Backup file not found: {input_path}", file=sys.stderr)
        return 1

    if not args.encrypted:
        try:
            _run_psql(args.psql, db_url, input_path)
        except Exception as exc:
            print(f"Restore failed: {exc}", file=sys.stderr)
            return 1
        print("Restore complete.")
        return 0

    try:
        key_bytes = _read_key(args.key or None, args.key_file or None, args.key_env)
    except Exception as exc:
        print(f"Backup encryption key error: {exc}", file=sys.stderr)
        return 1

    fernet = Fernet(key_bytes)
    try:
        decrypted = fernet.decrypt(input_path.read_bytes())
    except InvalidToken as exc:
        print(f"Invalid backup encryption key: {exc}", file=sys.stderr)
        return 1

    with tempfile.NamedTemporaryFile(delete=False, suffix=".sql") as temp_file:
        temp_file.write(decrypted)
        temp_path = Path(temp_file.name)

    try:
        _run_psql(args.psql, db_url, temp_path)
    except Exception as exc:
        print(f"Restore failed: {exc}", file=sys.stderr)
        return 1
    finally:
        temp_path.unlink(missing_ok=True)

    print("Encrypted restore complete.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
