from __future__ import annotations
from collections import defaultdict
from datetime import datetime, timedelta, timezone
import fnmatch
import logging
import re
from threading import Lock
import time
from typing import Any, Dict, List, Optional, Tuple, Union

from pathlib import Path
from fastapi import Depends, FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from dotenv import load_dotenv
from sqlalchemy import text
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.responses import JSONResponse, PlainTextResponse, Response
from starlette.status import WS_1008_POLICY_VIOLATION
import uvicorn
import os
import httpx
from core.env_loader import load_encrypted_env_file
from core.logging_setup import configure_logging, init_sentry

load_dotenv()

# Load encrypted env values before importing modules that read env at import time.
load_encrypted_env_file()
configure_logging()
init_sentry()

# Granular per-module experimental flags (roadmap: "Use separate flags rather
# than one large Phase 3 switch"). Each mounts only its own router(s) without
# requiring the sledgehammer ENABLE_EXPERIMENTAL_FEATURES/ENABLE_PHASE3_FEATURES
# switch. All still default OFF and are blocked in production by the same
# startup guard as the two coarse flags — see _validate_startup_env below.
GRANULAR_FEATURE_FLAGS: tuple[str, ...] = (
    "ENABLE_EMOTION_RECOGNITION",
    "ENABLE_ACTION_RECOGNITION",
    "ENABLE_CROSS_CAMERA_REID",
    "ENABLE_MULTIMODAL",
    "ENABLE_3D_FACE",
    "ENABLE_FEDERATED_LEARNING",
    "ENABLE_VIT_RECOGNITION",
    "ENABLE_MULTISPECTRAL",
    "ENABLE_MODEL_AB_TESTING",
    "ENABLE_SYNTHETIC_DATA",
    "ENABLE_TEMPORAL_AUGMENTATION",
    "ENABLE_MOBILE_SYNC",
    "ENABLE_ADVANCED_SECURITY",
)


def _validate_startup_env(db_url: str | None = None):
    """Validate critical environment variables at startup."""
    _logger = logging.getLogger("sentinelcv.startup")
    warnings = []

    def _env_truthy(name: str, default: bool = False) -> bool:
        raw = os.getenv(name)
        if raw is None:
            return default
        return raw.strip().lower() in {"1", "true", "yes", "on"}

    secret = os.getenv("SECRET_KEY", "")
    db_url = (db_url or os.getenv("DATABASE_URL", "")).strip()
    is_production = os.getenv("SENTINELCV_ENV", "development") == "production"

    # SECRET_KEY must be strong in production (hard fail, not warn)
    if not secret or secret == "your-super-secret-key-for-mvp":
        if is_production:
            _logger.critical(
                "SECRET_KEY is not set or using default value in production! "
                "Set a strong random secret (>=32 chars)."
            )
            raise SystemExit(1)
        warnings.append("SECRET_KEY using default dev value")
    elif len(secret) < 32:
        if is_production:
            _logger.critical(
                "SECRET_KEY is too short (%d chars) for production; require >=32.",
                len(secret),
            )
            raise SystemExit(1)
        warnings.append(f"SECRET_KEY is short ({len(secret)} chars); recommend >=32")

    embedding_key_secret = (os.getenv("EMBEDDING_KEY_SECRET") or "").strip()
    if not embedding_key_secret:
        if is_production:
            _logger.critical(
                "EMBEDDING_KEY_SECRET is not set in production. Configure a dedicated "
                "embedding-encryption secret distinct from SECRET_KEY."
            )
            raise SystemExit(1)
        warnings.append("EMBEDDING_KEY_SECRET not set; using development-only fallback key")
    elif embedding_key_secret == secret:
        if is_production:
            _logger.critical(
                "EMBEDDING_KEY_SECRET matches SECRET_KEY in production. Use a dedicated secret."
            )
            raise SystemExit(1)
        warnings.append("EMBEDDING_KEY_SECRET matches SECRET_KEY; use a dedicated secret")

    # DATABASE_URL
    if db_url and db_url.startswith("postgresql"):
        _logger.info("Database: PostgreSQL (%s...)", db_url[:40])
    elif db_url and db_url.startswith("sqlite"):
        warnings.append("Database: SQLite (not recommended for production)")
    elif not db_url:
        warnings.append("DATABASE_URL not set; will use default SQLite")

    # METRICS_TOKEN must be set in production — /metrics is otherwise public
    metrics_token = (os.getenv("METRICS_TOKEN") or "").strip()
    if not metrics_token:
        if is_production:
            _logger.critical(
                "METRICS_TOKEN is not set in production. The /metrics endpoint would be "
                "publicly accessible without authentication. Set a strong random token."
            )
            raise SystemExit(1)
        warnings.append("METRICS_TOKEN not set; /metrics endpoint is publicly accessible")

    # REDIS_URL
    if not os.getenv("REDIS_URL"):
        warnings.append("REDIS_URL not set; background jobs will not function")

    # AI_SERVICE_URL
    if not os.getenv("AI_SERVICE_URL"):
        warnings.append("AI_SERVICE_URL not set; AI features will not function")

    # ALLOWED_HOSTS is required in production so TrustedHostMiddleware stays on.
    allowed_hosts = [h.strip() for h in (os.getenv("ALLOWED_HOSTS") or "").split(",") if h.strip()]
    if is_production and (not allowed_hosts or "*" in allowed_hosts):
        _logger.critical(
            "ALLOWED_HOSTS is not configured safely in production. "
            "Set a comma-separated allow-list and never use '*'."
        )
        raise SystemExit(1)
    if not allowed_hosts or "*" in allowed_hosts:
        warnings.append("ALLOWED_HOSTS not set safely; TrustedHostMiddleware is disabled")

    internal_service_key = (os.getenv("INTERNAL_SERVICE_KEY") or "").strip()
    if not internal_service_key:
        if is_production:
            _logger.critical(
                "INTERNAL_SERVICE_KEY is not set in production. "
                "Internal ingestion endpoints will fail closed."
            )
            raise SystemExit(1)
        warnings.append("INTERNAL_SERVICE_KEY not set; internal AI-service calls will fail")

    tenant_filter_enabled = _env_truthy("ENFORCE_TENANT_FILTER", True)
    if is_production and not tenant_filter_enabled:
        _logger.critical(
            "ENFORCE_TENANT_FILTER must stay enabled in production. "
            "Cross-tenant isolation is disabled when this flag is off."
        )
        raise SystemExit(1)
    if not tenant_filter_enabled:
        warnings.append("ENFORCE_TENANT_FILTER disabled; cross-tenant isolation is reduced")

    if _env_truthy("AUTO_INIT_DB", db_url.startswith("sqlite")):
        warnings.append("AUTO_INIT_DB enabled; ensure it is only used for first-time bootstrap")

    # LOCAL_ONLY: opt-in guard for fully-local development. When enabled, refuse to
    # start if the database, cache, or AI service points at a non-local host, so the
    # app can never silently fall back to a remote/cloud dependency. Default off.
    if _env_truthy("LOCAL_ONLY", False):
        import re as _re

        def _host_is_local(url: str) -> bool:
            if not url:
                return True
            host_match = _re.search(r"@([^/:?]+)", url) or _re.search(r"//([^/:?]+)", url)
            host = (host_match.group(1) if host_match else "").lower()
            return host in {"", "localhost", "127.0.0.1", "::1", "0.0.0.0"}

        _local_targets = {
            "DATABASE_URL": db_url,
            "REDIS_URL": os.getenv("REDIS_URL", ""),
            "AI_SERVICE_URL": os.getenv("AI_SERVICE_URL", ""),
        }
        _remote = [name for name, url in _local_targets.items() if not _host_is_local(url)]
        if _remote:
            _logger.critical(
                "LOCAL_ONLY is enabled but these point to non-local hosts: %s. "
                "Fix the URLs or unset LOCAL_ONLY.",
                ", ".join(_remote),
            )
            raise SystemExit(1)
        _logger.info("LOCAL_ONLY enabled; database, cache, and AI service are all local.")

    if is_production and _env_truthy("ALLOW_SYNTHETIC_BIOMETRIC_FALLBACK", False):
        _logger.critical(
            "ALLOW_SYNTHETIC_BIOMETRIC_FALLBACK is enabled in production. "
            "Synthetic biometric embeddings are not allowed in production."
        )
        raise SystemExit(1)
    if is_production and _env_truthy("ALLOW_PRIVATE_RTSP_TARGETS", False):
        _logger.critical(
            "ALLOW_PRIVATE_RTSP_TARGETS is enabled in production. "
            "Private RTSP targets must remain blocked."
        )
        raise SystemExit(1)
    if is_production and _env_truthy("SKIP_USER_PATH_EXISTS_CHECK", False):
        _logger.critical(
            "SKIP_USER_PATH_EXISTS_CHECK is enabled in production. "
            "Path-existence validation must remain active."
        )
        raise SystemExit(1)
    if is_production and _env_truthy("ENABLE_EXPERIMENTAL_FEATURES", False):
        _logger.critical(
            "ENABLE_EXPERIMENTAL_FEATURES is enabled in production. "
            "Experimental routers are not production-hardened."
        )
        raise SystemExit(1)
    if is_production and _env_truthy("ENABLE_PHASE3_FEATURES", False):
        _logger.critical(
            "ENABLE_PHASE3_FEATURES is enabled in production. "
            "Phase 3 routers are not production-hardened."
        )
        raise SystemExit(1)
    if is_production:
        enabled_granular = [name for name in GRANULAR_FEATURE_FLAGS if _env_truthy(name, False)]
        if enabled_granular:
            _logger.critical(
                "The following experimental feature flags are enabled in production: %s. "
                "Each mounts an unaudited router — none may be on in production.",
                ", ".join(enabled_granular),
            )
            raise SystemExit(1)

    # Storage encryption at rest — pgvector stores biometric embeddings as plain
    # floats; application-level encryption is not possible without breaking ANN
    # search. The operator must confirm storage-level encryption via their cloud
    # provider and acknowledge it by setting STORAGE_ENCRYPTED=verified.
    if db_url.startswith("postgresql"):
        storage_encrypted = (os.getenv("STORAGE_ENCRYPTED") or "").strip().lower()
        if storage_encrypted != "verified":
            _msg = (
                "STORAGE_ENCRYPTED is not set to 'verified'. "
                "Confirm that your PostgreSQL provider has encryption at rest enabled "
                "(Supabase: on by default; AWS RDS: storage_encrypted=true; "
                "GCP Cloud SQL: CMEK; self-hosted: pg_tde or dm-crypt). "
                "Then set STORAGE_ENCRYPTED=verified."
            )
            if is_production:
                _logger.warning("SECURITY: %s", _msg)
            warnings.append(_msg)

    # Object storage: if S3/R2 is requested but credentials are incomplete,
    # uploads silently fall back to local-only storage — data is lost on pod restart.
    _storage_type = (os.getenv("STORAGE_TYPE") or "").strip().lower()
    if _storage_type in {"s3", "r2"}:
        def _any_env(*names: str) -> bool:
            return any((os.getenv(n) or "").strip() for n in names)
        _missing_storage = [
            label for label, check in [
                ("bucket",           _any_env("OBJECT_STORAGE_BUCKET", "R2_BUCKET", "AWS_S3_BUCKET")),
                ("endpoint_url",     _any_env("OBJECT_STORAGE_ENDPOINT_URL", "R2_ENDPOINT_URL", "AWS_S3_ENDPOINT_URL")),
                ("access_key_id",    _any_env("OBJECT_STORAGE_ACCESS_KEY_ID", "R2_ACCESS_KEY_ID", "AWS_ACCESS_KEY_ID")),
                ("secret_access_key",_any_env("OBJECT_STORAGE_SECRET_ACCESS_KEY", "R2_SECRET_ACCESS_KEY", "AWS_SECRET_ACCESS_KEY")),
            ]
            if not check
        ]
        if _missing_storage:
            _msg = (
                f"STORAGE_TYPE={_storage_type} but credentials are incomplete "
                f"(missing: {', '.join(_missing_storage)}). "
                "Uploads will fall back to local-only storage — data will be lost on pod restart."
            )
            if is_production:
                _logger.critical(_msg)
                raise SystemExit(1)
            warnings.append(_msg)
    elif is_production and not _env_truthy("ALLOW_LOCAL_MEDIA_STORAGE", False):
        _logger.critical(
            "Production media storage is local-only. Set STORAGE_TYPE=s3 or STORAGE_TYPE=r2 "
            "with complete object-storage credentials, or explicitly set "
            "ALLOW_LOCAL_MEDIA_STORAGE=1 for single-node deployments."
        )
        raise SystemExit(1)

    for w in warnings:
        _logger.warning("ENV CHECK: %s", w)

    if warnings:
        _logger.info("Startup env validation: %d warnings", len(warnings))
    else:
        _logger.info("Startup env validation: all checks passed")

from api import auth, visitors, video, logs, organizations, cameras, users, audit_logs, camera, models_api, ldap
from api import search, watchlists
from api import missing_persons
from api import edge_devices
from api import recommendations, accuracy, data_quality, analytics_api, webhooks, compliance, notifications, enhancements, liveness, training, alerts, synthetic_data, temporal_augmentation, future_enhancements
from api import learning, multimodal, three_d_face
from api import model_versioning, federated_learning, sso, sso_api, gdpr_api, reports
from api import vision_transformers, advanced_recognition
from api import carbon_metrics
from api.phase3_complete_api_scaffold import (
    router_liveness_adv, router_emotion_action, router_reid,
    router_edge, router_adv_analytics, router_vit,
    router_ms_ir, router_mobile, router_integrations,
    router_ab_testing, router_security,
)
from core.security import decode_token
from db.base import (
    engine,
    Base,
    init_db,
    log_sqlite_parity_warnings,
    SQLALCHEMY_DATABASE_URL,
    set_current_tenant,
    reset_current_tenant,
)
from core.realtime import realtime_manager
from core.paths import DATA_DIR, FACE_IMAGE_DIR, RAW_VIDEO_DIR
from core.storage import storage
from db.base import SessionLocal
from services import video_queue_service, password_reset_email_service, mlflow_registry_service
from services.redis_service import get_redis_service
from services.phase3_service_scaffolds import BiometricBackendUnavailable

# CRITICAL: Import all models BEFORE creating tables so all model classes are registered
from models import models

_validate_startup_env(SQLALCHEMY_DATABASE_URL)

logger = logging.getLogger("sentinelcv.main")


def _env_flag(name: str, default: bool) -> bool:
    raw_value = os.getenv(name)
    if raw_value is None:
        return default
    return raw_value.strip().lower() in {"1", "true", "yes", "on"}


def _database_backend() -> str:
    db_url = (SQLALCHEMY_DATABASE_URL or "").strip().lower()
    if db_url.startswith("sqlite"):
        return "sqlite"
    if db_url.startswith("postgresql"):
        return "postgresql"
    return "other"


def _pgvector_extension_check() -> dict:
    if _database_backend() != "postgresql":
        return {
            "status": "warn",
            "value": "not_applicable",
            "detail": "pgvector validation is only available when PostgreSQL is configured.",
        }

    db = SessionLocal()
    try:
        result = db.execute(text("SELECT extname FROM pg_extension WHERE extname = 'vector'")).scalar()
        if result == "vector":
            return {
                "status": "pass",
                "value": "installed",
                "detail": "pgvector extension is available.",
            }
        return {
            "status": "fail",
            "value": "missing",
            "detail": "PostgreSQL is configured but pgvector extension is not installed.",
        }
    except Exception as exc:
        return {
            "status": "fail",
            "value": "unverified",
            "detail": f"Unable to verify pgvector extension: {exc}",
        }
    finally:
        db.close()


def _pgvector_face_index_check() -> dict:
    if _database_backend() != "postgresql":
        return {
            "status": "warn",
            "value": "not_applicable",
            "detail": "pgvector ANN index validation is only available when PostgreSQL is configured.",
            "indexes": [],
        }

    expected_index_type = (os.getenv("PGVECTOR_INDEX_TYPE", "hnsw") or "hnsw").strip().lower()
    if expected_index_type not in {"hnsw", "ivfflat"}:
        expected_index_type = "hnsw"

    db = SessionLocal()
    try:
        rows = db.execute(
            text(
                """
                SELECT indexname, indexdef
                FROM pg_indexes
                WHERE schemaname = ANY(current_schemas(false))
                  AND tablename = 'face_data'
                  AND indexdef ILIKE '%embedding%'
                """
            )
        ).all()
        indexes = [
            {
                "name": row[0],
                "definition": row[1],
            }
            for row in rows
        ]
        matching_indexes = [
            item for item in indexes
            if expected_index_type in item["name"].lower() or expected_index_type in item["definition"].lower()
        ]
        if matching_indexes:
            return {
                "status": "pass",
                "value": expected_index_type,
                "detail": f"Verified {expected_index_type} ANN index on face_data embeddings.",
                "indexes": matching_indexes,
            }
        if indexes:
            return {
                "status": "warn",
                "value": expected_index_type,
                "detail": (
                    f"Embedding indexes exist, but the expected {expected_index_type} ANN index "
                    "was not found on face_data."
                ),
                "indexes": indexes,
            }
        return {
            "status": "warn",
            "value": expected_index_type,
            "detail": "pgvector is installed, but no embedding ANN index was found on face_data.",
            "indexes": [],
        }
    except Exception as exc:
        return {
            "status": "fail",
            "value": "unverified",
            "detail": f"Unable to verify pgvector embedding indexes: {exc}",
            "indexes": [],
        }
    finally:
        db.close()


def _pgvector_index_name(index_type: str) -> str:
    normalized = (index_type or "hnsw").strip().lower()
    if normalized == "ivfflat":
        return "ix_face_data_embedding_ivfflat"
    return "ix_face_data_embedding_hnsw"


def _pgvector_ivfflat_lists() -> int:
    raw_value = (os.getenv("PGVECTOR_IVFFLAT_LISTS") or "").strip()
    try:
        value = int(raw_value) if raw_value else 100
    except ValueError:
        value = 100
    return max(1, min(value, 5000))


def _ensure_pgvector_face_index() -> dict:
    if _database_backend() != "postgresql":
        return {
            "status": "skipped",
            "detail": "Auto pgvector index ensure is only applicable to PostgreSQL.",
        }

    expected_index_type = (os.getenv("PGVECTOR_INDEX_TYPE", "hnsw") or "hnsw").strip().lower()
    if expected_index_type not in {"hnsw", "ivfflat"}:
        expected_index_type = "hnsw"

    index_name = _pgvector_index_name(expected_index_type)

    db = SessionLocal()
    try:
        extension_present = bool(
            db.execute(text("SELECT 1 FROM pg_extension WHERE extname = 'vector' LIMIT 1")).scalar()
        )
        if not extension_present:
            return {
                "status": "warn",
                "detail": "pgvector extension is not installed; skipping ANN index creation.",
            }

        table_exists = bool(
            db.execute(
                text(
                    """
                    SELECT 1
                    FROM information_schema.tables
                    WHERE table_schema = ANY(current_schemas(false))
                      AND table_name = 'face_data'
                    LIMIT 1
                    """
                )
            ).scalar()
        )
        if not table_exists:
            return {
                "status": "warn",
                "detail": "face_data table is not available; skipping ANN index creation.",
            }

        existing = db.execute(
            text(
                """
                SELECT indexname
                FROM pg_indexes
                WHERE schemaname = ANY(current_schemas(false))
                  AND tablename = 'face_data'
                  AND indexname = :index_name
                LIMIT 1
                """
            ),
            {"index_name": index_name},
        ).scalar()
        if existing:
            return {
                "status": "pass",
                "detail": f"{index_name} already present.",
            }

        if expected_index_type == "ivfflat":
            lists = _pgvector_ivfflat_lists()
            create_sql = (
                "CREATE INDEX IF NOT EXISTS ix_face_data_embedding_ivfflat "
                "ON face_data USING ivfflat (embedding vector_cosine_ops) "
                f"WITH (lists = {lists})"
            )
        else:
            create_sql = (
                "CREATE INDEX IF NOT EXISTS ix_face_data_embedding_hnsw "
                "ON face_data USING hnsw (embedding vector_cosine_ops)"
            )

        db.execute(text(create_sql))
        db.execute(text("ANALYZE face_data"))
        db.commit()

        return {
            "status": "pass",
            "detail": f"Ensured {index_name} for pgvector cosine search.",
        }
    except Exception as exc:
        db.rollback()
        return {
            "status": "warn",
            "detail": f"Failed to ensure pgvector ANN index: {exc}",
        }
    finally:
        db.close()


def _pg_stat_statements_enabled() -> bool:
    if _database_backend() != "postgresql":
        return False

    db = SessionLocal()
    try:
        result = db.execute(text("SELECT extname FROM pg_extension WHERE extname = 'pg_stat_statements'")).scalar()
        return result == "pg_stat_statements"
    except Exception:
        return False
    finally:
        db.close()


AUTO_INIT_DB = _env_flag("AUTO_INIT_DB", _database_backend() == "sqlite")

# Initialize database conditionally (Alembic-first for production deployments)
if AUTO_INIT_DB:
    init_db()
else:
    logger.info("AUTO_INIT_DB disabled; expecting schema managed via Alembic migrations.")

log_sqlite_parity_warnings()

AUTO_ENSURE_PGVECTOR_FACE_INDEX = _env_flag(
    "AUTO_ENSURE_PGVECTOR_FACE_INDEX",
    _database_backend() == "postgresql",
)
if AUTO_ENSURE_PGVECTOR_FACE_INDEX:
    index_ensure_result = _ensure_pgvector_face_index()
    if index_ensure_result.get("status") == "pass":
        logger.info("pgvector index ensure: %s", index_ensure_result.get("detail"))
    else:
        logger.warning("pgvector index ensure: %s", index_ensure_result.get("detail"))

_IS_PRODUCTION = os.getenv("SENTINELCV_ENV", "development").strip().lower() == "production"


async def _face_recognition_engine_check() -> dict:
    """Query the AI service for real vs. weak-fallback face-recognition status.

    `real_recognition=False` means the AI service has no loadable ArcFace/AdaFace
    backend and would fall back to a non-discriminative 32x32 grayscale pixel
    embedding (refused outright when SENTINELCV_STRICT_RECOGNITION=1). Readiness
    must fail — not just warn — in production so a misconfigured deploy is
    caught before visitors are enrolled with unusable embeddings.
    """
    ai_service_url = os.getenv("AI_SERVICE_URL", "http://127.0.0.1:8001")
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{ai_service_url}/health")
            resp.raise_for_status()
            data = resp.json()
        recognition = data.get("recognition", {})
        real_recognition = bool(recognition.get("real_recognition"))
        backends = recognition.get("backends", {})
        if real_recognition:
            return {
                "status": "pass",
                "value": {"real_recognition": True, "backends": backends},
                "detail": "Real face-recognition backend (ArcFace/AdaFace) is loaded.",
            }
        return {
            "status": "fail" if _IS_PRODUCTION else "warn",
            "value": {"real_recognition": False, "backends": backends},
            "detail": (
                "No real ArcFace/AdaFace backend is loaded on the AI service; recognition "
                "would rely on the weak pixel-similarity fallback (refused entirely when "
                "SENTINELCV_STRICT_RECOGNITION=1). This must not run in production."
            ),
        }
    except Exception as exc:
        return {
            "status": "fail" if _IS_PRODUCTION else "warn",
            "value": {"error": str(exc)},
            "detail": f"Could not reach AI service at {ai_service_url}/health to verify the recognition backend: {exc}",
        }


app = FastAPI(
    title="SentinelCV - Visitor Tracking & Identification API",
    description="AI-powered visitor tracking and face recognition system",
    version="1.0.0",
    # API docs are disabled in production to prevent schema enumeration.
    # Access /docs and /redoc in development only.
    docs_url=None if _IS_PRODUCTION else "/docs",
    redoc_url=None if _IS_PRODUCTION else "/redoc",
    openapi_url=None if _IS_PRODUCTION else "/openapi.json",
)

APP_STARTED_AT = time.time()
_metrics_lock = Lock()
# Prometheus-style latency histogram buckets (seconds). The "+Inf" bucket is
# implicit and emitted as `request_latency_count`.
_LATENCY_BUCKETS_SECONDS = (
    0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0,
)
_backend_metrics = {
    "requests_total": 0,
    "errors_total": 0,
    "latency_total_seconds": 0.0,
    "path_counts": defaultdict(int),
    "latency_bucket_counts": [0] * len(_LATENCY_BUCKETS_SECONDS),
}

# ─── /metrics aggregate cache ────────────────────────────────────────────────
# Prometheus typically scrapes every 15s. Running a fresh `COUNT(*)` against
# every interesting table on each scrape is a sequential-scan amplifier on a
# busy database. Cache the aggregates for a short window.
_METRICS_AGGREGATE_TTL_SECONDS = float(os.getenv("METRICS_AGGREGATE_CACHE_TTL_SECONDS", "15"))
_metrics_aggregate_lock = Lock()
_metrics_aggregate_cache: dict[str, Any] = {"ts": 0.0, "data": None}


def _record_latency_bucket(elapsed_seconds: float) -> None:
    bucket_index = len(_LATENCY_BUCKETS_SECONDS)
    for index, threshold in enumerate(_LATENCY_BUCKETS_SECONDS):
        if elapsed_seconds <= threshold:
            bucket_index = index
            break
    if bucket_index < len(_LATENCY_BUCKETS_SECONDS):
        _backend_metrics["latency_bucket_counts"][bucket_index] += 1
_RATE_LIMIT_EXACT_EXEMPT_PATHS = {
    "/",
    "/health",
    "/metrics",
    "/api/v1/health",
    "/openapi.json",  # only reachable in dev; exempt to avoid throttling schema fetches
}
_RATE_LIMIT_PREFIX_EXEMPT_PATHS = (
    "/docs",
    "/redoc",
    "/static",
    "/api/v1/auth/login",
    "/api/v1/auth/refresh",
)

# ── Request body size limit (50 MB default; override via MAX_REQUEST_BODY_BYTES) ──
_MAX_BODY = int(os.getenv("MAX_REQUEST_BODY_BYTES", str(50 * 1024 * 1024)))


class LimitRequestSizeMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        content_length = request.headers.get("content-length")
        if content_length and int(content_length) > _MAX_BODY:
            return Response("Request body too large", status_code=413)
        return await call_next(request)


app.add_middleware(LimitRequestSizeMiddleware)

# ── Trusted host enforcement (set ALLOWED_HOSTS in production) ─────────────
_allowed_hosts = [h.strip() for h in os.getenv("ALLOWED_HOSTS", "").split(",") if h.strip()]
if _allowed_hosts and _allowed_hosts != ["*"]:
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=_allowed_hosts)

# ── CORS — in production only the real frontend domain is allowed ───────────
def _build_cors_origins() -> list[str]:
    # Explicit list from env takes priority
    env_origins = [o.strip() for o in os.getenv("ALLOWED_ORIGINS", "").split(",") if o.strip()]
    if env_origins:
        return env_origins
    
    is_prod = os.getenv("SENTINELCV_ENV") == "production"
    frontend_url = os.getenv("FRONTEND_URL")
    
    # In prod, we don't fallback to localhost if FRONTEND_URL isn't set.
    origins = [frontend_url] if frontend_url else (["http://localhost:3001"] if not is_prod else [])
    
    if not is_prod:
        origins += [
            "http://localhost:3000",
            "http://127.0.0.1:3000",
            "http://localhost:3001",
            "http://127.0.0.1:3001",
        ]
    return origins


app.add_middleware(
    CORSMiddleware,
    allow_origins=_build_cors_origins(),
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=[
        "Accept",
        "Accept-Language",
        "Authorization",
        "Content-Type",
        "Origin",
        "X-Requested-With",
    ],
    expose_headers=["Content-Disposition"],
)

_CSRF_EXEMPT_PREFIXES = ("/api/v1/ws/", "/api/v1/health", "/api/v1/metrics")
_CSRF_STATE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
_ALLOWED_ORIGINS_SET: set[str] = set(_build_cors_origins())


@app.middleware("http")
async def enforce_csrf_origin(request, call_next):
    """Reject state-changing cookie-authenticated requests whose Origin is not in the allow-list.

    Bearer-authenticated requests are CSRF-safe by construction (browsers can't set
    Authorization headers cross-origin). This middleware only applies to cookie-auth
    flows where CORS SameSite alone may be insufficient.
    """
    if request.method in _CSRF_STATE_METHODS:
        path = request.url.path
        if not any(path.startswith(p) for p in _CSRF_EXEMPT_PREFIXES):
            # Bearer-authenticated requests are safe to pass through.
            has_bearer = request.headers.get("authorization", "").lower().startswith("bearer ")
            # Internal service key requests are safe.
            has_internal_key = bool(request.headers.get("x-internal-api-key"))
            if not has_bearer and not has_internal_key:
                origin = request.headers.get("origin", "")
                if origin and origin not in _ALLOWED_ORIGINS_SET:
                    return JSONResponse(
                        status_code=403,
                        content={"detail": "CSRF check failed: origin not allowed"},
                    )
    return await call_next(request)


# Ensure storage directories exist for uploaded face images / video snippets.
# Static files are NOT mounted here — biometric assets must require authentication.
# See the auth-gated /static/{file_path:path} route below.
os.makedirs(FACE_IMAGE_DIR, exist_ok=True)
os.makedirs(os.path.join(FACE_IMAGE_DIR, "known"), exist_ok=True)
os.makedirs(os.path.join(FACE_IMAGE_DIR, "unknown"), exist_ok=True)
os.makedirs(RAW_VIDEO_DIR, exist_ok=True)

_STATIC_DATA_ROOT = Path(DATA_DIR).resolve()


def _resolve_static_path(file_path: str) -> str:
    if not file_path or file_path.startswith(("/", "\\")):
        raise HTTPException(status_code=400, detail="Invalid static path")
    normalized = os.path.normpath(file_path).replace("\\", "/")
    if normalized.startswith("..") or "/../" in normalized or normalized in {".", ""}:
        raise HTTPException(status_code=400, detail="Invalid static path")
    try:
        local_path = storage.ensure_local_file(normalized)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Asset not found")
    except RuntimeError:
        logger.exception("Failed to hydrate static asset %s from storage", normalized)
        raise HTTPException(status_code=502, detail="Asset storage is unavailable")

    # Final resolved-path boundary check — blocks symlink escapes, Windows drive
    # letters, and any path that storage.ensure_local_file() might have placed
    # outside the intended data directory.
    try:
        resolved = Path(local_path).resolve()
        resolved.relative_to(_STATIC_DATA_ROOT)  # raises ValueError if outside
    except ValueError:
        logger.error(
            "Static asset resolved outside data root (requested=%s resolved=%s root=%s)",
            normalized,
            local_path,
            _STATIC_DATA_ROOT,
        )
        raise HTTPException(status_code=400, detail="Invalid static path")

    return str(local_path)

# Include API Routers - all under /api/v1
API_PREFIX = "/api/v1"
app.include_router(auth.router, prefix=API_PREFIX)
app.include_router(visitors.router, prefix=API_PREFIX)
app.include_router(search.router, prefix=API_PREFIX)
app.include_router(watchlists.router, prefix=API_PREFIX)
app.include_router(missing_persons.router, prefix=API_PREFIX)
app.include_router(video.router, prefix=API_PREFIX)
app.include_router(logs.router, prefix=API_PREFIX)
app.include_router(organizations.router, prefix=API_PREFIX)
app.include_router(cameras.router, prefix=API_PREFIX)
app.include_router(edge_devices.router, prefix=API_PREFIX)
app.include_router(users.router, prefix=API_PREFIX)
app.include_router(audit_logs.router, prefix=API_PREFIX)
app.include_router(camera.router, prefix=API_PREFIX)
app.include_router(models_api.router, prefix=API_PREFIX)
app.include_router(recommendations.router, prefix=API_PREFIX)
app.include_router(accuracy.router, prefix=API_PREFIX)
app.include_router(data_quality.router, prefix=API_PREFIX)
app.include_router(analytics_api.router, prefix=API_PREFIX)
app.include_router(webhooks.router, prefix=API_PREFIX)
app.include_router(compliance.router, prefix=API_PREFIX)
app.include_router(notifications.router, prefix=API_PREFIX)
app.include_router(enhancements.router, prefix=API_PREFIX)
app.include_router(future_enhancements.router, prefix=API_PREFIX)
app.include_router(liveness.router, prefix=API_PREFIX)
app.include_router(alerts.router, prefix=API_PREFIX)
app.include_router(ldap.router, prefix=API_PREFIX)
app.include_router(sso_api.router)
app.include_router(gdpr_api.router)
app.include_router(reports.router, prefix=API_PREFIX)
app.include_router(carbon_metrics.router, prefix=API_PREFIX)

# Experimental / research routers — not mounted by default.
# Set ENABLE_EXPERIMENTAL_FEATURES=1 to mount all of them, or set the specific
# granular flag below to mount just one module without opting into the rest.
# None of this is production-hardened: unaudited auth flows, scaffold
# implementations, or hardware/model dependencies not available by default.
# GRANULAR_FEATURE_FLAGS lists every name below; both are blocked in
# production by the startup guard in _validate_startup_env.
_ENABLE_EXPERIMENTAL = _env_flag("ENABLE_EXPERIMENTAL_FEATURES", False)
_enabled_modules: list[str] = []


def _mount_if_enabled(router, module_name: str, *flag_names: str) -> None:
    if _ENABLE_EXPERIMENTAL or any(_env_flag(name, False) for name in flag_names):
        app.include_router(router, prefix=API_PREFIX)
        _enabled_modules.append(module_name)


_mount_if_enabled(vision_transformers.router, "vision_transformers", "ENABLE_VIT_RECOGNITION")
_mount_if_enabled(
    advanced_recognition.router, "advanced_recognition",
    "ENABLE_EMOTION_RECOGNITION", "ENABLE_ACTION_RECOGNITION", "ENABLE_CROSS_CAMERA_REID",
)
_mount_if_enabled(training.router, "training")
_mount_if_enabled(synthetic_data.router, "synthetic_data", "ENABLE_SYNTHETIC_DATA")
_mount_if_enabled(temporal_augmentation.router, "temporal_augmentation", "ENABLE_TEMPORAL_AUGMENTATION")
_mount_if_enabled(learning.router, "learning")
_mount_if_enabled(multimodal.router, "multimodal", "ENABLE_MULTIMODAL")
_mount_if_enabled(three_d_face.router, "three_d_face", "ENABLE_3D_FACE")
_mount_if_enabled(model_versioning.router, "model_versioning")
_mount_if_enabled(federated_learning.router, "federated_learning", "ENABLE_FEDERATED_LEARNING")
# Legacy OAuth2 flow (Google/GitHub) — unaudited for PKCE/state replay.
# Prefer sso_api.py (SAML/OIDC provider management) for production SSO.
_mount_if_enabled(sso.router, "legacy_sso")

if _enabled_modules:
    logger.info("Experimental routers mounted: %s", ", ".join(_enabled_modules))
else:
    logger.info(
        "Experimental routers disabled (vision_transformers, advanced_recognition, "
        "training, synthetic_data, temporal_augmentation, learning, multimodal, "
        "three_d_face, model_versioning, federated_learning, legacy sso); "
        "set ENABLE_EXPERIMENTAL_FEATURES=1 or the specific ENABLE_* flag to enable"
    )

# Phase 3 experimental routers — opt-in only, same pattern as above.
# Set ENABLE_PHASE3_FEATURES=1 to mount all of them, or the specific granular
# flag to mount just one. Excluded from the default route table either way.
_ENABLE_PHASE3 = _env_flag("ENABLE_PHASE3_FEATURES", False)
_enabled_phase3_modules: list[str] = []


def _mount_phase3_if_enabled(router, module_name: str, *flag_names: str) -> None:
    if _ENABLE_PHASE3 or any(_env_flag(name, False) for name in flag_names):
        app.include_router(router, prefix=API_PREFIX)
        _enabled_phase3_modules.append(module_name)


_mount_phase3_if_enabled(router_liveness_adv, "liveness_advanced")
_mount_phase3_if_enabled(router_emotion_action, "emotion_action", "ENABLE_EMOTION_RECOGNITION", "ENABLE_ACTION_RECOGNITION")
_mount_phase3_if_enabled(router_reid, "cross_camera_reid", "ENABLE_CROSS_CAMERA_REID")
_mount_phase3_if_enabled(router_edge, "edge_deployment")
_mount_phase3_if_enabled(router_adv_analytics, "advanced_analytics")
# Same ENABLE_VIT_RECOGNITION flag as the experimental-tier vision_transformers.py
# above — there are two independent ViT surfaces in this codebase (roadmap §5.4
# duplicate-route concern also applies here, not just camera/SSO/GDPR).
_mount_phase3_if_enabled(router_vit, "vit_phase3", "ENABLE_VIT_RECOGNITION")
_mount_phase3_if_enabled(router_ms_ir, "multispectral", "ENABLE_MULTISPECTRAL")
_mount_phase3_if_enabled(router_mobile, "mobile_sync", "ENABLE_MOBILE_SYNC")
_mount_phase3_if_enabled(router_integrations, "integrations")
_mount_phase3_if_enabled(router_ab_testing, "model_ab_testing", "ENABLE_MODEL_AB_TESTING")
_mount_phase3_if_enabled(router_security, "advanced_security", "ENABLE_ADVANCED_SECURITY")

if _enabled_phase3_modules:
    logger.info("Phase 3 routers mounted: %s", ", ".join(_enabled_phase3_modules))
else:
    logger.info(
        "Phase 3 routers disabled; set ENABLE_PHASE3_FEATURES=1 or the specific "
        "ENABLE_* flag to enable"
    )


@app.get("/")
async def root():
    return {
        "message": "SentinelCV API is running",
        "docs": "/docs",
        "version": "1.0.0",
    }


@app.get("/static/{file_path:path}")
async def serve_static_asset(
    file_path: str,
    request: Request,
    token: str | None = None,
):
    """Auth-gated replacement for the previous unauthenticated StaticFiles mount.

    Biometric assets (face crops, raw video clips) require a valid access token
    so they are never publicly addressable by UUID alone. Token may arrive via
    ?token= query param (img/video tags cannot set Authorization headers) or
    the Authorization header — validated manually below, not via the
    OAuth2PasswordBearer dependency, which only reads the header and would
    reject all <img> requests with 401 before the query token is checked.
    """
    bearer = _resolve_request_token(request, token)
    if not bearer:
        raise HTTPException(status_code=401, detail="Could not validate credentials")
    payload = decode_token(bearer)
    if not payload or payload.get("type") != "access":
        raise HTTPException(status_code=401, detail="Could not validate credentials")
    resolved = _resolve_static_path(file_path)
    return FileResponse(resolved)


@app.get("/health")
async def health():
    return {"status": "healthy"}


@app.get("/health/readiness")
async def health_readiness():
    db_backend = _database_backend()
    redis_status = get_redis_service().status()
    queue_status = video_queue_service.get_video_job_queue_status()
    synthetic_queue_status = video_queue_service.get_job_queue_status("synthetic")
    temporal_queue_status = video_queue_service.get_job_queue_status("temporal")
    pgvector_status = _pgvector_extension_check()
    pgvector_index_status = _pgvector_face_index_check()
    pool_metrics = _collect_pool_metrics()
    connection_metrics = _collect_pg_connection_metrics()
    max_connections = _collect_pg_connection_limit()
    pool_health = _evaluate_pool_health(pool_metrics)
    connection_health = _evaluate_connection_health(connection_metrics, max_connections)
    face_recognition_engine_check = await _face_recognition_engine_check()

    secret_key = os.getenv("SECRET_KEY", "")
    strong_secret = len(secret_key) >= 32
    embedding_key_secret = (os.getenv("EMBEDDING_KEY_SECRET") or "").strip()
    dedicated_embedding_key = bool(embedding_key_secret) and embedding_key_secret != secret_key

    smtp_config = password_reset_email_service.get_password_reset_email_config()
    smtp_missing = smtp_config.get("missing", [])
    password_reset_email_ready = bool(smtp_config.get("configured"))

    # Encryption at rest — cannot be verified from SQL; requires an operator to
    # confirm that the storage layer has TDE/disk encryption enabled and to set
    # STORAGE_ENCRYPTED=verified in the environment.
    storage_encrypted_flag = (os.getenv("STORAGE_ENCRYPTED") or "").strip().lower()
    storage_encrypted_check: dict = {}
    if storage_encrypted_flag == "verified":
        storage_encrypted_check = {
            "status": "pass",
            "value": "verified",
            "detail": "Operator has confirmed storage encryption at rest is enabled.",
        }
    elif db_backend == "postgresql":
        storage_encrypted_check = {
            "status": "warn",
            "value": "unverified",
            "detail": (
                "pgvector stores face embeddings as plain floats — storage-level "
                "encryption at rest (TDE/disk encryption) is required. "
                "Set STORAGE_ENCRYPTED=verified once confirmed with your cloud provider."
            ),
        }
    else:
        storage_encrypted_check = {
            "status": "warn",
            "value": "not_applicable",
            "detail": "SQLite — only used in development; no encryption check required.",
        }

    checks = {
        "database_backend": {
            "status": "pass" if db_backend == "postgresql" else "warn",
            "value": db_backend,
            "detail": "PostgreSQL recommended for production deployments." if db_backend != "postgresql" else "PostgreSQL configured.",
        },
        "pgvector_extension": pgvector_status,
        "pgvector_face_index": pgvector_index_status,
        "face_recognition_engine": face_recognition_engine_check,
        "schema_management": {
            "status": "pass" if not AUTO_INIT_DB else "warn",
            "value": "alembic" if not AUTO_INIT_DB else "runtime_init_db",
            "detail": "Disable AUTO_INIT_DB in production to enforce Alembic-managed schema changes." if AUTO_INIT_DB else "Runtime auto-init disabled.",
        },
        "redis_connectivity": {
            "status": "pass" if redis_status.get("connected") and not redis_status.get("using_fallback") else "warn",
            "value": {
                "connected": redis_status.get("connected"),
                "using_fallback": redis_status.get("using_fallback"),
            },
            "detail": "Redis connected." if redis_status.get("connected") and not redis_status.get("using_fallback") else "Redis unavailable or using in-memory fallback; rate limiting and queue durability are degraded.",
        },
        "video_queue_backend": {
            "status": "pass" if queue_status.get("mode") == "redis" and queue_status.get("active") else "warn",
            "value": queue_status,
            "detail": "Redis-backed queue recommended for durable background processing." if queue_status.get("mode") != "redis" or not queue_status.get("active") else "Redis queue is active.",
        },
        "synthetic_queue_backend": {
            "status": "pass" if synthetic_queue_status.get("mode") == "redis" and synthetic_queue_status.get("active") else "warn",
            "value": synthetic_queue_status,
            "detail": "Synthetic generation jobs should use Redis-backed queueing for durable processing." if synthetic_queue_status.get("mode") != "redis" or not synthetic_queue_status.get("active") else "Synthetic job queue is active.",
        },
        "temporal_queue_backend": {
            "status": "pass" if temporal_queue_status.get("mode") == "redis" and temporal_queue_status.get("active") else "warn",
            "value": temporal_queue_status,
            "detail": "Temporal augmentation jobs should use Redis-backed queueing for durable processing." if temporal_queue_status.get("mode") != "redis" or not temporal_queue_status.get("active") else "Temporal job queue is active.",
        },
        "secret_key_strength": {
            "status": "pass" if strong_secret else "fail",
            "value": len(secret_key),
            "detail": "SECRET_KEY should be at least 32 characters.",
        },
        "embedding_key_separation": {
            "status": "pass" if dedicated_embedding_key else "warn",
            "value": "dedicated" if dedicated_embedding_key else "shared_or_missing",
            "detail": (
                "Embedding encryption uses a dedicated EMBEDDING_KEY_SECRET."
                if dedicated_embedding_key
                else "Set EMBEDDING_KEY_SECRET to a value distinct from SECRET_KEY to avoid coupling JWT signing and biometric encryption."
            ),
        },
        "storage_encryption_at_rest": storage_encrypted_check,
        "db_pool_health": pool_health,
        "db_connection_health": connection_health,
        "password_reset_email": {
            "status": "pass" if password_reset_email_ready else "warn",
            "value": "configured" if password_reset_email_ready else "not_configured",
            "detail": (
                f"Password reset email delivery requires SMTP settings ({len(smtp_missing)} missing)."
                if not password_reset_email_ready
                else "SMTP settings present."
            ),
        },
    }

    status_values = [item["status"] for item in checks.values()]
    overall = "ready" if all(value == "pass" for value in status_values) else ("degraded" if "fail" not in status_values else "not_ready")

    return {
        "status": overall,
        "checks": checks,
        "experimental_modules_enabled": _enabled_modules + _enabled_phase3_modules,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


def _escape_prometheus_label(value: str) -> str:
    return value.replace("\\", "\\\\").replace("\n", "\\n").replace('"', '\\"')


_POOL_STATUS_PATTERN = re.compile(
    r"Pool size: (?P<pool_size>\d+)\s+Connections in pool: (?P<in_pool>\d+)\s+"
    r"Current Overflow: (?P<overflow>-?\d+)\s+Current Checked out connections: (?P<checked_out>\d+)"
)


def _parse_float_env(name: str, default: float) -> float:
    raw_value = os.getenv(name)
    if raw_value is None:
        return default
    try:
        return float(raw_value)
    except ValueError:
        return default


def _collect_pool_metrics() -> dict[str, int] | None:
    if _database_backend() == "sqlite":
        return None

    try:
        status = engine.pool.status()
    except Exception:
        return None

    match = _POOL_STATUS_PATTERN.search(status)
    if not match:
        return None

    return {
        "pool_size": int(match.group("pool_size")),
        "connections_in_pool": int(match.group("in_pool")),
        "checked_out": int(match.group("checked_out")),
        "overflow": int(match.group("overflow")),
    }


def _collect_pg_connection_metrics() -> dict[str, int] | None:
    if _database_backend() != "postgresql":
        return None

    db = SessionLocal()
    try:
        row = db.execute(
            text(
                """
                SELECT
                    COUNT(*) AS total_connections,
                    COUNT(*) FILTER (WHERE state = 'active') AS active_connections,
                    COUNT(*) FILTER (WHERE state = 'idle') AS idle_connections,
                    COUNT(*) FILTER (WHERE state = 'idle in transaction') AS idle_in_transaction
                FROM pg_stat_activity
                WHERE datname = current_database();
                """
            )
        ).mappings().first()
        if not row:
            return None
        return {
            "total_connections": int(row.get("total_connections", 0)),
            "active_connections": int(row.get("active_connections", 0)),
            "idle_connections": int(row.get("idle_connections", 0)),
            "idle_in_transaction": int(row.get("idle_in_transaction", 0)),
        }
    except Exception:
        return None
    finally:
        db.close()


def _collect_slow_query_count(threshold_ms: float) -> int | None:
    if _database_backend() != "postgresql" or not _pg_stat_statements_enabled():
        return None

    db = SessionLocal()
    try:
        value = db.execute(
            text(
                """
                SELECT COUNT(*)
                FROM pg_stat_statements
                WHERE mean_time >= :threshold
                  AND query NOT LIKE '%pg_stat_statements%';
                """
            ),
            {"threshold": threshold_ms},
        ).scalar()
        return int(value) if value is not None else 0
    except Exception:
        return None
    finally:
        db.close()


def _collect_pg_connection_limit() -> int | None:
    if _database_backend() != "postgresql":
        return None

    db = SessionLocal()
    try:
        value = db.execute(text("SHOW max_connections;")).scalar()
        return int(value) if value is not None else None
    except Exception:
        return None
    finally:
        db.close()


def _collect_metrics_aggregates_cached() -> dict[str, int]:
    """Return cached counts for the /metrics endpoint.

    Skipped per-request DB scans by caching for METRICS_AGGREGATE_CACHE_TTL_SECONDS
    (default 15s). Suitable for Prometheus scrape cadence.
    """
    now_ts = time.time()
    with _metrics_aggregate_lock:
        cached_data = _metrics_aggregate_cache.get("data")
        cached_ts = float(_metrics_aggregate_cache.get("ts") or 0.0)
        if cached_data is not None and (now_ts - cached_ts) < _METRICS_AGGREGATE_TTL_SECONDS:
            return cached_data

    db = SessionLocal()
    # Bypass the global tenant filter — /metrics is operator-only, scoped at the
    # nginx layer, and must observe the whole DB.
    db.info["skip_tenant_filter"] = True
    try:
        camera_count = db.query(models.Camera).execution_options(skip_tenant_filter=True).count()
        visitor_log_count = db.query(models.VisitorLog).execution_options(skip_tenant_filter=True).count()
        behavior_event_count = db.query(models.BehaviorEvent).execution_options(skip_tenant_filter=True).count()
        open_signal_count = (
            db.query(models.ContinuousLearningSignal)
            .filter(models.ContinuousLearningSignal.status == "open")
            .execution_options(skip_tenant_filter=True)
            .count()
        )
        queued_signal_count = (
            db.query(models.ContinuousLearningSignal)
            .filter(models.ContinuousLearningSignal.status == "queued")
            .execution_options(skip_tenant_filter=True)
            .count()
        )
        movement_summary_count = (
            db.query(models.CrossCameraMovementSummary)
            .execution_options(skip_tenant_filter=True)
            .count()
        )
    finally:
        db.close()

    aggregates = {
        "camera_count": camera_count,
        "visitor_log_count": visitor_log_count,
        "behavior_event_count": behavior_event_count,
        "open_signal_count": open_signal_count,
        "queued_signal_count": queued_signal_count,
        "movement_summary_count": movement_summary_count,
    }
    with _metrics_aggregate_lock:
        _metrics_aggregate_cache["ts"] = now_ts
        _metrics_aggregate_cache["data"] = aggregates
    return aggregates


def _evaluate_pool_health(metrics: dict[str, int] | None) -> dict[str, str | float | int]:
    if _database_backend() == "sqlite":
        return {
            "status": "warn",
            "value": "not_applicable",
            "detail": "Connection pool health not applicable for SQLite.",
        }

    if not metrics:
        return {
            "status": "warn",
            "value": "unavailable",
            "detail": "Unable to resolve SQLAlchemy pool status.",
        }

    pool_size = metrics.get("pool_size", 0)
    checked_out = metrics.get("checked_out", 0)
    overflow = metrics.get("overflow", 0)
    utilization = (checked_out / pool_size) if pool_size else 0.0

    warn_threshold = _parse_float_env("DB_POOL_WARN_UTILIZATION", 0.8)
    critical_threshold = _parse_float_env("DB_POOL_CRITICAL_UTILIZATION", 0.95)

    status = "pass"
    detail = "DB pool utilization healthy."
    if pool_size == 0:
        status = "warn"
        detail = "DB pool size is zero; review pool configuration."
    elif utilization >= critical_threshold:
        status = "fail"
        detail = "DB pool utilization exceeds critical threshold."
    elif utilization >= warn_threshold or overflow > 0:
        status = "warn"
        detail = "DB pool utilization is high or overflow in use."

    return {
        "status": status,
        "value": {
            **metrics,
            "utilization": round(utilization, 4),
        },
        "detail": detail,
    }


def _evaluate_connection_health(
    metrics: dict[str, int] | None,
    max_connections: int | None,
) -> dict[str, str | float | int]:
    if _database_backend() != "postgresql":
        return {
            "status": "warn",
            "value": "not_applicable",
            "detail": "Connection limits not applicable for SQLite.",
        }

    if not metrics or not max_connections:
        return {
            "status": "warn",
            "value": "unavailable",
            "detail": "Unable to resolve database connection utilization.",
        }

    total = metrics.get("total_connections", 0)
    utilization = total / max_connections if max_connections else 0.0

    warn_threshold = _parse_float_env("DB_CONNECTION_WARN_UTILIZATION", 0.8)
    critical_threshold = _parse_float_env("DB_CONNECTION_CRITICAL_UTILIZATION", 0.95)

    status = "pass"
    detail = "Database connection utilization healthy."
    if utilization >= critical_threshold:
        status = "fail"
        detail = "Database connection utilization exceeds critical threshold."
    elif utilization >= warn_threshold:
        status = "warn"
        detail = "Database connection utilization is high."

    return {
        "status": status,
        "value": {
            **metrics,
            "max_connections": max_connections,
            "utilization": round(utilization, 4),
        },
        "detail": detail,
    }


def _should_skip_rate_limit(path: str, method: str) -> bool:
    if method.upper() == "OPTIONS":
        return True
    if path in _RATE_LIMIT_EXACT_EXEMPT_PATHS:
        return True
    return any(path.startswith(prefix) for prefix in _RATE_LIMIT_PREFIX_EXEMPT_PATHS)


def _normalize_db_timestamp(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _resolve_request_organization_id(request, db) -> str | None:
    auth_header = request.headers.get("authorization", "")
    if not auth_header.startswith("Bearer "):
        return None

    token = auth_header.split(" ", 1)[1]
    payload = decode_token(token)
    user_id = payload.get("sub") if payload else None
    if not user_id:
        return None

    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user:
        return None
    if not user.organization_id:
        return None
    return str(user.organization_id)



def _pattern_specificity(pattern: str) -> tuple[int, int]:
    return (len(pattern.replace("*", "")), -pattern.count("*"))


# ─── Rate-limit rule cache ──────────────────────────────────────────────────
#
# The previous implementation mutated `RateLimitRule` rows on every request
# (UPDATE + COMMIT per hit). Under load this becomes a serialised hot row and
# inflates write traffic. Counters now live in Redis (atomic INCR + EXPIRE);
# the database table is config-only.
_RATE_LIMIT_RULES_CACHE: dict[str, tuple[float, list[dict[str, Any]]]] = {}
_RATE_LIMIT_RULES_LOCK = Lock()
_RATE_LIMIT_RULE_TTL_SECONDS = float(os.getenv("RATE_LIMIT_RULE_CACHE_TTL_SECONDS", "60"))


def _load_rate_limit_rules_for_org(db, organization_id: str) -> list[dict[str, Any]]:
    """Return a snapshot list of active rate-limit rules for an org."""
    cache_key = str(organization_id)
    now_ts = time.time()
    with _RATE_LIMIT_RULES_LOCK:
        cached = _RATE_LIMIT_RULES_CACHE.get(cache_key)
        if cached and (now_ts - cached[0]) < _RATE_LIMIT_RULE_TTL_SECONDS:
            return cached[1]

    rules = db.query(models.RateLimitRule).filter(
        models.RateLimitRule.organization_id == organization_id,
        models.RateLimitRule.is_active.is_(True),
    ).all()

    snapshot = [
        {
            "id": str(rule.id),
            "pattern": rule.endpoint_pattern or "*",
            "max_requests": int(rule.max_requests),
            "window_seconds": int(rule.window_seconds),
            "priority": int(rule.priority or 0),
            "burst_limit": int(rule.burst_limit) if rule.burst_limit else 0,
            "burst_window_seconds": int(rule.burst_window_seconds) if rule.burst_window_seconds else 0,
        }
        for rule in rules
    ]

    with _RATE_LIMIT_RULES_LOCK:
        _RATE_LIMIT_RULES_CACHE[cache_key] = (now_ts, snapshot)
    return snapshot


def _apply_rate_limit_rules(db, organization_id: str, path: str, now: datetime) -> tuple[bool, dict[str, str]]:
    rules = _load_rate_limit_rules_for_org(db, organization_id)
    matching_rules = [
        rule for rule in rules
        if fnmatch.fnmatchcase(path, rule["pattern"])
    ]
    if not matching_rules:
        return True, {}

    matching_rules.sort(
        key=lambda rule: (_pattern_specificity(rule["pattern"]), rule["priority"]),
        reverse=True,
    )

    redis_service = get_redis_service()
    response_headers: dict[str, str] = {}

    for index, rule in enumerate(matching_rules):
        # Window counter
        window_result = redis_service.check_rate_limit(
            key=f"org:{organization_id}:rule:{rule['id']}:window",
            max_requests=rule["max_requests"],
            window_seconds=rule["window_seconds"],
        )
        if not window_result.get("allowed", True):
            retry_after = window_result.get("retry_after") or rule["window_seconds"]
            return False, {
                "Retry-After": str(retry_after),
                "X-RateLimit-Limit": str(rule["max_requests"]),
                "X-RateLimit-Remaining": "0",
                "X-RateLimit-Reset": str(int(now.timestamp() + retry_after)),
                "X-RateLimit-Rule": rule["pattern"],
                "X-RateLimit-Priority": str(rule["priority"]),
            }

        # Burst counter (optional)
        if rule["burst_limit"] and rule["burst_window_seconds"]:
            burst_result = redis_service.check_rate_limit(
                key=f"org:{organization_id}:rule:{rule['id']}:burst",
                max_requests=rule["burst_limit"],
                window_seconds=rule["burst_window_seconds"],
            )
            if not burst_result.get("allowed", True):
                retry_after = burst_result.get("retry_after") or rule["burst_window_seconds"]
                return False, {
                    "Retry-After": str(retry_after),
                    "X-RateLimit-Burst-Limit": str(rule["burst_limit"]),
                    "X-RateLimit-Burst-Remaining": "0",
                    "X-RateLimit-Burst-Reset": str(int(now.timestamp() + retry_after)),
                    "X-RateLimit-Rule": rule["pattern"],
                    "X-RateLimit-Priority": str(rule["priority"]),
                }

        if index == 0:
            window_remaining = window_result.get("remaining", 0)
            window_retry_after = window_result.get("retry_after") or rule["window_seconds"]
            response_headers = {
                "X-RateLimit-Limit": str(rule["max_requests"]),
                "X-RateLimit-Remaining": str(window_remaining),
                "X-RateLimit-Reset": str(int(now.timestamp() + window_retry_after)),
                "X-RateLimit-Rule": rule["pattern"],
                "X-RateLimit-Priority": str(rule["priority"]),
            }
            if rule["burst_limit"] and rule["burst_window_seconds"]:
                burst_remaining = burst_result.get("remaining", 0) if "burst_result" in locals() else rule["burst_limit"]
                response_headers["X-RateLimit-Burst-Limit"] = str(rule["burst_limit"])
                response_headers["X-RateLimit-Burst-Remaining"] = str(burst_remaining)
                response_headers["X-RateLimit-Burst-Reset"] = str(
                    int(now.timestamp() + rule["burst_window_seconds"])
                )

    return True, response_headers


_METRICS_TOKEN = (os.getenv("METRICS_TOKEN") or "").strip()

# Per-IP fixed-window rate limit for /metrics: max 30 req/60s by default
_METRICS_RATE_LIMIT_MAX = int(os.getenv("METRICS_RATE_LIMIT_MAX", "30"))
_METRICS_RATE_LIMIT_WINDOW = int(os.getenv("METRICS_RATE_LIMIT_WINDOW_SECONDS", "60"))
_metrics_rate_counters: dict[str, tuple[int, float]] = {}  # ip -> (count, window_start)
_metrics_rate_lock = Lock()


def _check_metrics_rate_limit(request: Request) -> None:
    """Fixed-window per-IP rate limit for /metrics to prevent expensive-query DoS."""
    client_ip = (request.headers.get("x-forwarded-for", "") or "").split(",")[0].strip()
    if not client_ip and request.client:
        client_ip = request.client.host or "unknown"
    now = time.monotonic()
    with _metrics_rate_lock:
        count, window_start = _metrics_rate_counters.get(client_ip, (0, now))
        if now - window_start >= _METRICS_RATE_LIMIT_WINDOW:
            count, window_start = 0, now
        count += 1
        _metrics_rate_counters[client_ip] = (count, window_start)
        if count > _METRICS_RATE_LIMIT_MAX:
            raise HTTPException(status_code=429, detail="Metrics rate limit exceeded")


def _check_metrics_auth(request: Request) -> None:
    """Require METRICS_TOKEN when configured. Prometheus scrapers use Authorization: Bearer <token>."""
    _check_metrics_rate_limit(request)
    if not _METRICS_TOKEN:
        return
    auth_header = request.headers.get("authorization", "")
    if auth_header.lower().startswith("bearer "):
        candidate = auth_header.split(" ", 1)[1].strip()
        if candidate == _METRICS_TOKEN:
            return
    x_token = request.headers.get("x-metrics-token", "").strip()
    if x_token == _METRICS_TOKEN:
        return
    raise HTTPException(status_code=401, detail="Missing or invalid metrics token")


@app.get("/metrics")
async def metrics(request: Request):
    _check_metrics_auth(request)
    with _metrics_lock:
        requests_total = int(_backend_metrics["requests_total"])
        errors_total = int(_backend_metrics["errors_total"])
        latency_total_seconds = float(_backend_metrics["latency_total_seconds"])
        path_counts = dict(_backend_metrics["path_counts"])
        latency_bucket_counts = list(_backend_metrics["latency_bucket_counts"])

    request_latency_average = latency_total_seconds / requests_total if requests_total else 0.0
    cumulative_bucket_counts: list[int] = []
    running_total = 0
    for count in latency_bucket_counts:
        running_total += int(count)
        cumulative_bucket_counts.append(running_total)

    aggregates = _collect_metrics_aggregates_cached()
    camera_count = aggregates["camera_count"]
    visitor_log_count = aggregates["visitor_log_count"]
    behavior_event_count = aggregates["behavior_event_count"]
    open_signal_count = aggregates["open_signal_count"]
    queued_signal_count = aggregates["queued_signal_count"]
    movement_summary_count = aggregates["movement_summary_count"]

    pool_metrics = _collect_pool_metrics()
    pg_connection_metrics = _collect_pg_connection_metrics()
    redis_metrics: dict[str, object] = {}
    max_connections = _collect_pg_connection_limit()
    slow_query_threshold_ms = _parse_float_env("DB_SLOW_QUERY_THRESHOLD_MS", 250.0)
    slow_query_count = _collect_slow_query_count(slow_query_threshold_ms) if slow_query_threshold_ms > 0 else None
    try:
        redis_metrics = get_redis_service().get_metrics()
    except Exception:
        redis_metrics = {}

    mlflow_state = mlflow_registry_service.load_mlflow_registry()
    mlflow_available = 1 if mlflow_state.get("mlflow_available") else 0
    mlflow_model_count = len(mlflow_state.get("models", [])) if isinstance(mlflow_state.get("models"), list) else 0

    lines = [
        "# HELP sentinelcv_backend_requests_total Total HTTP requests handled by the backend API.",
        "# TYPE sentinelcv_backend_requests_total counter",
        f"sentinelcv_backend_requests_total {requests_total}",
        "# HELP sentinelcv_backend_errors_total Total backend requests that resulted in a server error.",
        "# TYPE sentinelcv_backend_errors_total counter",
        f"sentinelcv_backend_errors_total {errors_total}",
        "# HELP sentinelcv_backend_request_latency_average_seconds Average backend request latency in seconds.",
        "# TYPE sentinelcv_backend_request_latency_average_seconds gauge",
        f"sentinelcv_backend_request_latency_average_seconds {request_latency_average:.6f}",
        "# HELP sentinelcv_backend_request_latency_seconds Histogram of backend request latency in seconds.",
        "# TYPE sentinelcv_backend_request_latency_seconds histogram",
    ]
    for threshold, count in zip(_LATENCY_BUCKETS_SECONDS, cumulative_bucket_counts):
        lines.append(
            f'sentinelcv_backend_request_latency_seconds_bucket{{le="{threshold}"}} {count}'
        )
    lines.extend([
        f'sentinelcv_backend_request_latency_seconds_bucket{{le="+Inf"}} {requests_total}',
        f"sentinelcv_backend_request_latency_seconds_sum {latency_total_seconds:.6f}",
        f"sentinelcv_backend_request_latency_seconds_count {requests_total}",
        "# HELP sentinelcv_backend_uptime_seconds Backend process uptime in seconds.",
        "# TYPE sentinelcv_backend_uptime_seconds gauge",
        f"sentinelcv_backend_uptime_seconds {time.time() - APP_STARTED_AT:.2f}",
        "# HELP sentinelcv_backend_cameras_total Number of registered cameras.",
        "# TYPE sentinelcv_backend_cameras_total gauge",
        f"sentinelcv_backend_cameras_total {camera_count}",
        "# HELP sentinelcv_backend_visitor_logs_total Number of persisted visitor log entries.",
        "# TYPE sentinelcv_backend_visitor_logs_total gauge",
        f"sentinelcv_backend_visitor_logs_total {visitor_log_count}",
        "# HELP sentinelcv_backend_behavior_events_total Number of persisted behavior events.",
        "# TYPE sentinelcv_backend_behavior_events_total gauge",
        f"sentinelcv_backend_behavior_events_total {behavior_event_count}",
        "# HELP sentinelcv_backend_open_learning_signals Number of open continuous-learning signals.",
        "# TYPE sentinelcv_backend_open_learning_signals gauge",
        f"sentinelcv_backend_open_learning_signals {open_signal_count}",
        "# HELP sentinelcv_backend_queued_learning_signals Number of queued continuous-learning signals.",
        "# TYPE sentinelcv_backend_queued_learning_signals gauge",
        f"sentinelcv_backend_queued_learning_signals {queued_signal_count}",
        "# HELP sentinelcv_backend_cross_camera_movements_total Number of persisted cross-camera movement summaries.",
        "# TYPE sentinelcv_backend_cross_camera_movements_total gauge",
        f"sentinelcv_backend_cross_camera_movements_total {movement_summary_count}",
        "# HELP sentinelcv_backend_mlflow_available Whether MLflow is available in the backend runtime.",
        "# TYPE sentinelcv_backend_mlflow_available gauge",
        f"sentinelcv_backend_mlflow_available {mlflow_available}",
        "# HELP sentinelcv_backend_mlflow_registry_models Total models tracked in the MLflow registry snapshot.",
        "# TYPE sentinelcv_backend_mlflow_registry_models gauge",
        f"sentinelcv_backend_mlflow_registry_models {mlflow_model_count}",
        "# HELP sentinelcv_backend_path_requests_total Requests grouped by path.",
        "# TYPE sentinelcv_backend_path_requests_total counter",
    ])
    if pool_metrics:
        pool_size = pool_metrics.get("pool_size", 0)
        checked_out = pool_metrics.get("checked_out", 0)
        pool_utilization = (checked_out / pool_size) if pool_size else 0.0
        lines.extend(
            [
                "# HELP sentinelcv_backend_db_pool_size Configured DB pool size.",
                "# TYPE sentinelcv_backend_db_pool_size gauge",
                f"sentinelcv_backend_db_pool_size {pool_metrics['pool_size']}",
                "# HELP sentinelcv_backend_db_pool_connections_in_pool Connections currently in the pool.",
                "# TYPE sentinelcv_backend_db_pool_connections_in_pool gauge",
                f"sentinelcv_backend_db_pool_connections_in_pool {pool_metrics['connections_in_pool']}",
                "# HELP sentinelcv_backend_db_pool_checked_out Connections checked out from the pool.",
                "# TYPE sentinelcv_backend_db_pool_checked_out gauge",
                f"sentinelcv_backend_db_pool_checked_out {pool_metrics['checked_out']}",
                "# HELP sentinelcv_backend_db_pool_overflow Current pool overflow count.",
                "# TYPE sentinelcv_backend_db_pool_overflow gauge",
                f"sentinelcv_backend_db_pool_overflow {pool_metrics['overflow']}",
                "# HELP sentinelcv_backend_db_pool_utilization Ratio of checked-out connections to pool size.",
                "# TYPE sentinelcv_backend_db_pool_utilization gauge",
                f"sentinelcv_backend_db_pool_utilization {pool_utilization:.4f}",
            ]
        )
    if pg_connection_metrics:
        lines.extend(
            [
                "# HELP sentinelcv_backend_db_connections_total Total database connections for current DB.",
                "# TYPE sentinelcv_backend_db_connections_total gauge",
                f"sentinelcv_backend_db_connections_total {pg_connection_metrics['total_connections']}",
                "# HELP sentinelcv_backend_db_connections_active Active database connections.",
                "# TYPE sentinelcv_backend_db_connections_active gauge",
                f"sentinelcv_backend_db_connections_active {pg_connection_metrics['active_connections']}",
                "# HELP sentinelcv_backend_db_connections_idle Idle database connections.",
                "# TYPE sentinelcv_backend_db_connections_idle gauge",
                f"sentinelcv_backend_db_connections_idle {pg_connection_metrics['idle_connections']}",
                "# HELP sentinelcv_backend_db_connections_idle_in_transaction Idle-in-transaction database connections.",
                "# TYPE sentinelcv_backend_db_connections_idle_in_transaction gauge",
                f"sentinelcv_backend_db_connections_idle_in_transaction {pg_connection_metrics['idle_in_transaction']}",
            ]
        )
    if max_connections:
        connection_utilization = (
            pg_connection_metrics.get("total_connections", 0) / max_connections
            if pg_connection_metrics and max_connections > 0
            else 0.0
        )
        lines.extend(
            [
                "# HELP sentinelcv_backend_db_connections_limit Max configured PostgreSQL connections.",
                "# TYPE sentinelcv_backend_db_connections_limit gauge",
                f"sentinelcv_backend_db_connections_limit {max_connections}",
                "# HELP sentinelcv_backend_db_connection_utilization Ratio of total connections to limit.",
                "# TYPE sentinelcv_backend_db_connection_utilization gauge",
                f"sentinelcv_backend_db_connection_utilization {connection_utilization:.4f}",
            ]
        )
    if slow_query_count is not None:
        lines.extend(
            [
                "# HELP sentinelcv_backend_db_slow_queries_total Count of queries above threshold in pg_stat_statements.",
                "# TYPE sentinelcv_backend_db_slow_queries_total gauge",
                f"sentinelcv_backend_db_slow_queries_total {slow_query_count}",
                "# HELP sentinelcv_backend_db_slow_query_threshold_ms Slow query threshold in milliseconds.",
                "# TYPE sentinelcv_backend_db_slow_query_threshold_ms gauge",
                f"sentinelcv_backend_db_slow_query_threshold_ms {slow_query_threshold_ms:.2f}",
            ]
        )
    if redis_metrics:
        lines.extend(
            [
                "# HELP sentinelcv_backend_cache_hits_total Cache hits across Redis and fallback.",
                "# TYPE sentinelcv_backend_cache_hits_total counter",
                f"sentinelcv_backend_cache_hits_total {int(redis_metrics.get('cache_hits', 0))}",
                "# HELP sentinelcv_backend_cache_misses_total Cache misses across Redis and fallback.",
                "# TYPE sentinelcv_backend_cache_misses_total counter",
                f"sentinelcv_backend_cache_misses_total {int(redis_metrics.get('cache_misses', 0))}",
                "# HELP sentinelcv_backend_cache_hit_ratio Cache hit ratio for Redis-backed caches.",
                "# TYPE sentinelcv_backend_cache_hit_ratio gauge",
                f"sentinelcv_backend_cache_hit_ratio {float(redis_metrics.get('cache_hit_ratio', 0.0))}",
                "# HELP sentinelcv_backend_cache_sets_total Cache set operations.",
                "# TYPE sentinelcv_backend_cache_sets_total counter",
                f"sentinelcv_backend_cache_sets_total {int(redis_metrics.get('cache_sets', 0))}",
                "# HELP sentinelcv_backend_cache_deletes_total Cache delete operations.",
                "# TYPE sentinelcv_backend_cache_deletes_total counter",
                f"sentinelcv_backend_cache_deletes_total {int(redis_metrics.get('cache_deletes', 0))}",
                "# HELP sentinelcv_backend_cache_errors_total Cache errors when talking to Redis.",
                "# TYPE sentinelcv_backend_cache_errors_total counter",
                f"sentinelcv_backend_cache_errors_total {int(redis_metrics.get('cache_errors', 0))}",
                "# HELP sentinelcv_backend_cache_fallback_reads_total Cache reads served by fallback storage.",
                "# TYPE sentinelcv_backend_cache_fallback_reads_total counter",
                f"sentinelcv_backend_cache_fallback_reads_total {int(redis_metrics.get('fallback_reads', 0))}",
                "# HELP sentinelcv_backend_cache_fallback_writes_total Cache writes served by fallback storage.",
                "# TYPE sentinelcv_backend_cache_fallback_writes_total counter",
                f"sentinelcv_backend_cache_fallback_writes_total {int(redis_metrics.get('fallback_writes', 0))}",
                "# HELP sentinelcv_backend_redis_connected Redis connectivity status (1=connected).",
                "# TYPE sentinelcv_backend_redis_connected gauge",
                f"sentinelcv_backend_redis_connected {1 if redis_metrics.get('connected') else 0}",
                "# HELP sentinelcv_backend_redis_fallback Redis fallback status (1=using fallback).",
                "# TYPE sentinelcv_backend_redis_fallback gauge",
                f"sentinelcv_backend_redis_fallback {1 if redis_metrics.get('using_fallback') else 0}",
            ]
        )
    for path, count in sorted(path_counts.items()):
        lines.append(f'sentinelcv_backend_path_requests_total{{path="{_escape_prometheus_label(path)}"}} {count}')

    return PlainTextResponse("\n".join(lines) + "\n", media_type="text/plain; version=0.0.4")


@app.get("/api/v1/health")
async def health_v1():
    return {"status": "healthy"}


def _resolve_websocket_token(websocket: WebSocket, query_token: str | None) -> str | None:
    if query_token:
        candidate = query_token.strip()
        if candidate:
            return candidate
    auth_header = websocket.headers.get("authorization", "")
    if auth_header.lower().startswith("bearer "):
        candidate = auth_header.split(" ", 1)[1].strip()
        if candidate:
            return candidate
    protocol_header = websocket.headers.get("sec-websocket-protocol", "")
    if protocol_header:
        for entry in protocol_header.split(","):
            candidate = entry.strip()
            if candidate:
                return candidate
    return None


def _resolve_request_token(request: Request, query_token: str | None) -> str | None:
    if query_token:
        candidate = query_token.strip()
        if candidate:
            return candidate
    auth_header = request.headers.get("authorization", "")
    if auth_header.lower().startswith("bearer "):
        candidate = auth_header.split(" ", 1)[1].strip()
        if candidate:
            return candidate
    return None


@app.websocket("/api/v1/ws/dashboard")
async def dashboard_websocket(websocket: WebSocket, token: str | None = None):
    """Authenticated dashboard websocket.

    The organization_id is derived from the access token (never trusted from
    the query string). The client may pass the token via:
      * ``?token=<jwt>`` query parameter, or
      * the ``Authorization: Bearer <jwt>`` header, or
      * the ``Sec-WebSocket-Protocol`` header (for browsers that cannot set
        custom headers on a websocket handshake).
    """
    bearer = _resolve_websocket_token(websocket, token)
    if not bearer:
        await websocket.close(code=WS_1008_POLICY_VIOLATION, reason="missing token")
        return

    payload = decode_token(bearer)
    if not payload or payload.get("type") != "access":
        await websocket.close(code=WS_1008_POLICY_VIOLATION, reason="invalid token")
        return

    user_id = payload.get("sub")
    if not user_id:
        await websocket.close(code=WS_1008_POLICY_VIOLATION, reason="invalid token")
        return

    db = SessionLocal()
    try:
        user = db.query(models.User).filter(models.User.id == user_id).first()
        if not user or not user.is_active or not user.organization_id:
            await websocket.close(code=WS_1008_POLICY_VIOLATION, reason="user not authorized")
            return
        organization_id = str(user.organization_id)
    finally:
        db.close()

    await realtime_manager.connect(organization_id, websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        logger.info(
            "Dashboard websocket disconnected for org=%s user=%s",
            organization_id,
            user_id,
        )
        realtime_manager.disconnect(organization_id, websocket)
    except Exception:
        logger.exception(
            "Dashboard websocket error for org=%s user=%s",
            organization_id,
            user_id,
        )
        realtime_manager.disconnect(organization_id, websocket)

# Global Exception Handler
@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    logger.error("Unhandled error at %s: %s", request.url.path, exc, exc_info=True)
    return JSONResponse(
        status_code=500,
        content={
            "detail": "An internal server error occurred. Please try again later.",
            "type": type(exc).__name__
        }
    )

@app.exception_handler(BiometricBackendUnavailable)
async def biometric_backend_unavailable_handler(request, exc):
    """A real biometric backend is required but missing.

    Surfacing this as a 503 means clients (and operators reading audit
    logs) see a clean "service unavailable" instead of a synthetic
    embedding being silently persisted.
    """
    logger.error("Biometric backend unavailable at %s: %s", request.url.path, exc)
    return JSONResponse(
        status_code=503,
        content={
            "detail": str(exc),
            "type": "BiometricBackendUnavailable",
        },
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(
    request: Request,
    exc: RequestValidationError,
) -> JSONResponse:
    logger.warning("Validation error at %s: %s", request.url.path, exc)
    return JSONResponse(
        status_code=422,
        content={"detail": "Input validation failed. Please check your request parameters."},
    )

@app.middleware("http")
async def populate_tenant_context(request, call_next):
    """Populate the ambient tenant ContextVar so the global SQLAlchemy filter
    (see db.base._global_tenant_filter) can scope every SELECT to the
    requesting user's organization."""
    db = SessionLocal()
    resolution_failed = False
    try:
        organization_id = _resolve_request_organization_id(request, db)
    except Exception:
        db.rollback()
        organization_id = None
        logger.exception("Tenant context resolution failed for %s", request.url.path)
        # If the request carries auth credentials, a resolution failure is a server
        # error — not a silent pass-through with no tenant scope.
        auth_header = request.headers.get("authorization", "")
        cookie_name = (os.getenv("REFRESH_COOKIE_NAME") or "sentinelcv_refresh_token").strip()
        has_auth = bool(auth_header) or bool(request.cookies.get(cookie_name))
        resolution_failed = has_auth
    finally:
        db.close()

    if resolution_failed:
        return JSONResponse(
            status_code=503,
            content={"detail": "Service temporarily unavailable. Please try again."},
        )

    set_current_tenant(organization_id)
    try:
        return await call_next(request)
    finally:
        reset_current_tenant()


@app.middleware("http")
async def enforce_rate_limits(request, call_next):
    path = request.url.path
    if _should_skip_rate_limit(path, request.method):
        return await call_next(request)

    db = SessionLocal()
    response_headers: dict[str, str] = {}
    try:
        organization_id = _resolve_request_organization_id(request, db)
        if organization_id:
            allowed, response_headers = _apply_rate_limit_rules(
                db,
                organization_id,
                path,
                datetime.now(timezone.utc),
            )
            if not allowed:
                return JSONResponse(
                    status_code=429,
                    content={
                        "detail": "Rate limit exceeded for this organization.",
                        "path": path,
                    },
                    headers=response_headers,
                )
    except Exception:
        db.rollback()
        logger.exception("Rate limit enforcement failed for %s", path)
    finally:
        db.close()

    response = await call_next(request)
    for header_name, header_value in response_headers.items():
        response.headers[header_name] = header_value
    return response


# Middlewares (e.g., Performance logging)
@app.middleware("http")
async def add_process_time_header(request, call_next):
    start_time = time.time()
    try:
        response = await call_next(request)
    except Exception:
        process_time = time.time() - start_time
        with _metrics_lock:
            _backend_metrics["requests_total"] += 1
            _backend_metrics["errors_total"] += 1
            _backend_metrics["latency_total_seconds"] += process_time
            _backend_metrics["path_counts"][request.url.path] += 1
            _record_latency_bucket(process_time)
        raise

    process_time = time.time() - start_time
    # Only emit timing header outside production — timing data enables oracle
    # attacks (e.g. distinguishing "user exists" from "user not found").
    if not _IS_PRODUCTION:
        response.headers["X-Process-Time"] = str(process_time)
    with _metrics_lock:
        _backend_metrics["requests_total"] += 1
        if response.status_code >= 500:
            _backend_metrics["errors_total"] += 1
        _backend_metrics["latency_total_seconds"] += process_time
        _backend_metrics["path_counts"][request.url.path] += 1
        _record_latency_bucket(process_time)
    return response


@app.middleware("http")
async def add_security_headers(request, call_next):
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    response.headers.setdefault(
        "Permissions-Policy",
        "camera=(self), microphone=(self), geolocation=()",
    )
    # Content-Security-Policy: restricts which resources the browser will load.
    # 'unsafe-inline' and 'unsafe-eval' are required by Next.js for hydration
    # and Tailwind CSS class injection. Tighten further once nonces are in place.
    response.headers.setdefault(
        "Content-Security-Policy",
        (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline' 'unsafe-eval'; "
            "style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data: blob:; "
            "connect-src 'self' ws: wss:; "
            "font-src 'self' data:; "
            "media-src 'self' blob:; "
            "frame-ancestors 'none';"
        ),
    )
    if request.url.scheme == "https":
        response.headers.setdefault(
            "Strict-Transport-Security",
            "max-age=31536000; includeSubDomains",
        )
    return response

try:
    from services.gdpr_cleanup_scheduler import start_gdpr_cleanup_scheduler
    start_gdpr_cleanup_scheduler()
except Exception as _gdpr_sched_exc:
    logger.critical(
        "GDPR cleanup scheduler failed to start — data retention enforcement is DISABLED: %s",
        _gdpr_sched_exc,
        exc_info=True,
    )

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
