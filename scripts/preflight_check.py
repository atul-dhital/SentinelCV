#!/usr/bin/env python
"""Startup preflight checks for SentinelCV.

This catches the same class of setup/runtime issues we hit during manual
startup: missing Python dependencies, blocked optional native modules,
missing frontend dependencies, and occupied service ports.
"""

from __future__ import annotations

import argparse
import importlib
import json
import os
import shutil
import socket
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import List


PROJECT_ROOT = Path(__file__).resolve().parents[1]


@dataclass
class CheckResult:
    name: str
    status: str
    message: str
    suggestion: str | None = None


def _import_check(module_name: str, name: str, suggestion: str, optional: bool = False) -> CheckResult:
    try:
        importlib.import_module(module_name)
        return CheckResult(name=name, status="ok", message=f"{module_name} import succeeded")
    except Exception as exc:
        return CheckResult(
            name=name,
            status="warn" if optional else "error",
            message=f"{module_name} import failed: {exc}",
            suggestion=suggestion,
        )


def _tool_check(tool_name: str, command_name: str | None = None, optional: bool = False) -> CheckResult:
    resolved = shutil.which(command_name or tool_name)
    if resolved:
        return CheckResult(name=tool_name, status="ok", message=f"Found at {resolved}")
    return CheckResult(
        name=tool_name,
        status="warn" if optional else "error",
        message=f"{tool_name} not found on PATH",
        suggestion=f"Install {tool_name} and ensure it is available on PATH.",
    )


def _path_check(path: Path, name: str, suggestion: str, optional: bool = False) -> CheckResult:
    if path.exists():
        return CheckResult(name=name, status="ok", message=str(path))
    return CheckResult(
        name=name,
        status="warn" if optional else "error",
        message=f"Missing path: {path}",
        suggestion=suggestion,
    )


def _port_check(port: int) -> CheckResult:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.5)
        in_use = sock.connect_ex(("127.0.0.1", port)) == 0
    if in_use:
        return CheckResult(
            name=f"port:{port}",
            status="warn",
            message=f"Port {port} is already in use",
            suggestion="Stop the existing process or change the service port before starting SentinelCV.",
        )
    return CheckResult(name=f"port:{port}", status="ok", message=f"Port {port} is available")


_PRODUCTION_FORBIDDEN_ENV_VARS = (
    # These env vars are deliberately permissive for dev/CI. In production
    # they relax security guards added by the audit-driven remediation.
    "ALLOW_SYNTHETIC_BIOMETRIC_FALLBACK",
    "ALLOW_PRIVATE_RTSP_TARGETS",
    "SKIP_USER_PATH_EXISTS_CHECK",
)
_PRODUCTION_REQUIRED_ENV_VARS = (
    "SECRET_KEY",
    "EMBEDDING_KEY_SECRET",
    "METRICS_TOKEN",
    "INTERNAL_SERVICE_KEY",
    "DATABASE_URL",
    "ALLOWED_HOSTS",
    "FRONTEND_URL",
)


def _env_truthy(name: str) -> bool:
    raw = (os.getenv(name) or "").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def _production_env_checks() -> List[CheckResult]:
    """Return checks that only fire when ``SENTINELCV_ENV=production``."""
    results: List[CheckResult] = []
    if (os.getenv("SENTINELCV_ENV") or "").strip().lower() != "production":
        return results

    for var in _PRODUCTION_REQUIRED_ENV_VARS:
        value = (os.getenv(var) or "").strip()
        if not value:
            results.append(CheckResult(
                name=f"env:{var}",
                status="error",
                message=f"{var} must be set in production",
                suggestion=f"Set {var} in .env.production or your secret store.",
            ))
            continue
        if var == "SECRET_KEY" and len(value) < 32:
            results.append(CheckResult(
                name=f"env:{var}",
                status="error",
                message=f"SECRET_KEY is {len(value)} chars; require ≥32",
                suggestion="Regenerate with python -c \"import secrets; print(secrets.token_hex(64))\".",
            ))
            continue
        if var == "DATABASE_URL" and not value.startswith("postgresql"):
            results.append(CheckResult(
                name=f"env:{var}",
                status="error",
                message="DATABASE_URL is not PostgreSQL — production rejects SQLite",
                suggestion="Use a postgresql:// URL.",
            ))
            continue
        if var == "ALLOWED_HOSTS" and ("*" in value or value == ""):
            results.append(CheckResult(
                name=f"env:{var}",
                status="error",
                message="ALLOWED_HOSTS must be a concrete comma-separated list",
                suggestion="Replace * with the real hostnames serving the app.",
            ))
            continue
        if var == "EMBEDDING_KEY_SECRET" and value == os.getenv("SECRET_KEY"):
            results.append(CheckResult(
                name=f"env:{var}",
                status="error",
                message="EMBEDDING_KEY_SECRET is identical to SECRET_KEY",
                suggestion="Generate a distinct value with python -c \"import secrets; print(secrets.token_urlsafe(48))\".",
            ))
            continue
        results.append(CheckResult(name=f"env:{var}", status="ok", message="set"))

    for var in _PRODUCTION_FORBIDDEN_ENV_VARS:
        if _env_truthy(var):
            results.append(CheckResult(
                name=f"env:{var}",
                status="error",
                message=f"{var} is enabled — must be unset in production",
                suggestion=f"Remove {var} from your environment / .env.production.",
            ))
        else:
            results.append(CheckResult(name=f"env:{var}", status="ok", message="not set"))

    if (os.getenv("AUTO_INIT_DB") or "").strip() == "1":
        results.append(CheckResult(
            name="env:AUTO_INIT_DB",
            status="error",
            message="AUTO_INIT_DB=1 in production drives schema drift",
            suggestion="Set AUTO_INIT_DB=0 and use Alembic for schema management.",
        ))
    if not _env_truthy("ENFORCE_TENANT_FILTER"):
        results.append(CheckResult(
            name="env:ENFORCE_TENANT_FILTER",
            status="warn",
            message="Global tenant filter is OFF",
            suggestion="Set ENFORCE_TENANT_FILTER=1 once integration tests are passing against staging.",
        ))
    if not _env_truthy("AUDIT_BIOMETRIC_READS"):
        results.append(CheckResult(
            name="env:AUDIT_BIOMETRIC_READS",
            status="warn",
            message="Biometric read-event auditing is OFF",
            suggestion="Set AUDIT_BIOMETRIC_READS=1 to record visitor reads and embedding matches.",
        ))

    # SMTP / password-reset email delivery
    smtp_host = (os.getenv("SMTP_HOST") or "").strip()
    smtp_from = (os.getenv("PASSWORD_RESET_FROM_EMAIL") or "").strip()
    if not smtp_host or not smtp_from:
        results.append(CheckResult(
            name="smtp:password_reset",
            status="warn",
            message=(
                "SMTP is not configured (SMTP_HOST and/or PASSWORD_RESET_FROM_EMAIL missing). "
                "Password reset will return 503 for end-users."
            ),
            suggestion=(
                "Set SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD, and "
                "PASSWORD_RESET_FROM_EMAIL in your secret store."
            ),
        ))
    else:
        results.append(CheckResult(
            name="smtp:password_reset",
            status="ok",
            message=f"SMTP configured ({smtp_host}, from {smtp_from})",
        ))

    # pgvector biometric embedding encryption
    db_url = (os.getenv("DATABASE_URL") or "").strip()
    if db_url.startswith("postgresql"):
        results.append(CheckResult(
            name="security:pgvector_encryption_at_rest",
            status="warn",
            message=(
                "pgvector stores face embeddings as plain float vectors — "
                "application-level encryption is not possible without breaking ANN search. "
                "Storage-level encryption (PostgreSQL TDE, AWS RDS storage_encrypted=true, "
                "GCP CMEK, or Azure TDE) MUST be enabled at the infrastructure layer."
            ),
            suggestion=(
                "Verify that your PostgreSQL host has encryption-at-rest enabled. "
                "For AWS RDS: storage_encrypted=true. For GCP Cloud SQL: CMEK. "
                "For self-hosted: pg_tde extension or filesystem encryption (dm-crypt/LUKS)."
            ),
        ))

    return results


def _recognition_backend_check() -> CheckResult:
    """Verify a real ArcFace recognition backend (InsightFace/AdaFace) is loadable.

    Without it, face recognition silently degrades to a weak 32x32 pixel fallback
    (or is refused entirely in strict mode). In production this is an error; in
    dev it is a warning so the app still runs without the ONNX models installed.
    """
    ai_dir = PROJECT_ROOT / "ai_services"
    if str(ai_dir) not in sys.path:
        sys.path.insert(0, str(ai_dir))
    try:
        from face_engine import recognition_backend_status
        status = recognition_backend_status()
    except Exception as exc:
        return CheckResult(
            name="ai:face_recognition_backend",
            status="warn",
            message=f"Could not probe recognition engine: {exc}",
            suggestion="Install ai_services requirements (insightface, onnxruntime) then re-run.",
        )

    is_prod = (os.getenv("SENTINELCV_ENV") or "").strip().lower() == "production"
    if status.get("real_recognition"):
        backends = [name for name, ok in status.get("backends", {}).items() if ok]
        return CheckResult(
            name="ai:face_recognition_backend",
            status="ok",
            message=f"Real recognition backend available: {', '.join(backends) or 'unknown'}",
        )
    return CheckResult(
        name="ai:face_recognition_backend",
        status="error" if is_prod else "warn",
        message=(
            "No real ArcFace backend loaded — recognition would use the weak pixel "
            "fallback (or be refused when SENTINELCV_STRICT_RECOGNITION=1)."
        ),
        suggestion=(
            "Run: python scripts/setup_models.py --install  (installs insightface/"
            "onnxruntime + downloads & warms the ArcFace model). Then verify with "
            "GET http://localhost:8001/health -> recognition.real_recognition == true."
        ),
    )


def run_checks() -> List[CheckResult]:
    results: List[CheckResult] = [
        CheckResult("python", "ok", sys.executable),
        _tool_check("node"),
        _tool_check("npm", "npm.cmd" if os.name == "nt" else "npm"),
        _path_check(PROJECT_ROOT / ".env", ".env", "Copy .env.example to .env and review the values."),
        _path_check(
            PROJECT_ROOT / "frontend" / "node_modules",
            "frontend dependencies",
            "Run npm install inside frontend/.",
        ),
    ]
    results.extend(_production_env_checks())

    results.extend(
        [
            _import_check("fastapi", "backend:fastapi", "Install backend requirements."),
            _import_check("uvicorn", "backend:uvicorn", "Install backend requirements."),
            _import_check("sqlalchemy", "backend:sqlalchemy", "Install backend requirements."),
            _import_check("requests", "backend:requests", "Install backend requirements."),
            _import_check("cv2", "ai:opencv", "Install ai_services requirements."),
            _import_check("numpy", "ai:numpy", "Install ai_services requirements."),
            _import_check("ultralytics", "ai:ultralytics", "Install ai_services requirements."),
        ]
    )

    results.extend(
        [
            _import_check(
                "lap",
                "ai:lap",
                "Tracking will fall back to detection-only mode. Install or allow lap if you want ByteTrack/BoT-SORT.",
                optional=True,
            ),
            _import_check(
                "deepface",
                "ai:deepface",
                "Face embeddings will use fallback mode. Install deepface for higher-quality embeddings.",
                optional=True,
            ),
            _import_check(
                "sklearn",
                "training:scikit-learn",
                "Training endpoints will be unavailable until scikit-learn is installed.",
                optional=True,
            ),
            _import_check(
                "optuna",
                "training:optuna",
                "Hyperparameter optimization will use simplified behavior until optuna is installed.",
                optional=True,
            ),
            _import_check(
                "pytest",
                "tests:pytest",
                "Automated test commands will fail until pytest is installed in the active environment.",
                optional=True,
            ),
        ]
    )

    results.append(_recognition_backend_check())

    results.extend(_port_check(port) for port in (3001, 8000, 8001))
    return results


def print_results(results: List[CheckResult]) -> None:
    symbols = {"ok": "OK", "warn": "WARN", "error": "ERROR"}
    print("=" * 72)
    print("SentinelCV Preflight Check")
    print("=" * 72)
    for result in results:
        print(f"[{symbols[result.status]:5}] {result.name:<24} {result.message}")
        if result.suggestion:
            print(f"        -> {result.suggestion}")

    errors = [r for r in results if r.status == "error"]
    warnings = [r for r in results if r.status == "warn"]
    print("-" * 72)
    print(f"Summary: {len(errors)} error(s), {len(warnings)} warning(s)")
    if errors:
        print("Preflight failed. Resolve the errors above before starting services.")
    else:
        print("Preflight passed. Warnings are non-blocking but worth reviewing.")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run SentinelCV startup preflight checks.")
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON instead of text.")
    args = parser.parse_args()

    results = run_checks()
    if args.json:
        print(json.dumps([asdict(result) for result in results], indent=2))
    else:
        print_results(results)

    return 1 if any(result.status == "error" for result in results) else 0


if __name__ == "__main__":
    raise SystemExit(main())
