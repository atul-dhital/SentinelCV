#!/usr/bin/env python3
"""Cleanup cached sessions in Redis or fallback storage.

Usage:
  python scripts/cleanup_sessions.py --env-file .env.staging
  python scripts/cleanup_sessions.py --max-keys 500
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Dict

PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = PROJECT_ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from services.redis_service import get_redis_service


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


def _print_summary(result: Dict[str, object]) -> None:
    mode = result.get("mode")
    scanned = result.get("scanned", 0)
    cleaned = result.get("cleaned", 0)
    print("Session cleanup summary")
    print("=" * 40)
    print(f"mode: {mode}")
    print(f"scanned: {scanned}")
    print(f"cleaned: {cleaned}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Cleanup Redis session keys")
    parser.add_argument("--env-file", default=".env.staging", help="Env file to load")
    parser.add_argument("--max-keys", type=int, default=500, help="Maximum keys to scan")
    args = parser.parse_args()

    _load_env_file(args.env_file)

    redis_service = get_redis_service()
    result = redis_service.cleanup_sessions(max_keys=args.max_keys)
    _print_summary(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
