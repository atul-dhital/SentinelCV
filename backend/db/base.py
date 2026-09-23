from contextvars import ContextVar
from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker, declarative_base, Session, Query, with_loader_criteria
import logging
import os
import socket
import uuid
from typing import Any, Generator, Iterable, Optional
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("sentinelcv.db")

DEFAULT_SQLITE_DATABASE_URL = os.getenv(
    "SQLITE_DATABASE_URL", "sqlite:///./sentinelcv.db"
)
VERCEL_POSTGRES_ENV_KEYS = (
    "POSTGRES_URL_NON_POOLING",
    "POSTGRES_URL",
    "POSTGRES_PRISMA_URL",
)


def _parse_int(value: Optional[str], default: int) -> int:
    if value is None or not value.strip():
        return default
    try:
        return int(value)
    except ValueError:
        return default


def _parse_bool(value: Optional[str], default: bool) -> bool:
    if value is None or not value.strip():
        return default
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "y", "on"}:
        return True
    if normalized in {"0", "false", "no", "n", "off"}:
        return False
    return default


def _can_reach_tcp_host(host: str, port: int, timeout_seconds: float) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout_seconds):
            return True
    except OSError:
        return False


def _normalize_database_url(url: str) -> str:
    normalized = (url or "").strip()
    if normalized.startswith("postgres://"):
        return "postgresql://" + normalized[len("postgres://"):]
    return normalized


def _resolve_database_url() -> str:
    requested_url = _normalize_database_url(
        (os.getenv("DATABASE_URL") or "").strip()
        or next(
            (
                value
                for value in (
                    (os.getenv(name) or "").strip()
                    for name in VERCEL_POSTGRES_ENV_KEYS
                )
                if value
            ),
            DEFAULT_SQLITE_DATABASE_URL,
        )
    )
    env_name = os.getenv("SENTINELCV_ENV", "development").strip().lower()
    is_production = env_name == "production"

    if is_production:
        if not requested_url.startswith("postgresql"):
            raise RuntimeError(
                "DATABASE_URL or a supported POSTGRES_* URL must be a PostgreSQL URL in production "
                "(SENTINELCV_ENV=production). SQLite fallback is disabled."
            )
        return requested_url

    allow_sqlite_fallback = _parse_bool(
        os.getenv("SENTINELCV_ALLOW_SQLITE_FALLBACK"),
        True,
    )

    if not requested_url.startswith("postgresql") or not allow_sqlite_fallback:
        return requested_url

    try:
        parsed_url = make_url(requested_url)
    except Exception:
        return requested_url

    host = (parsed_url.host or "").strip().lower()
    if host not in {"localhost", "127.0.0.1", "::1"}:
        return requested_url

    port = int(parsed_url.port or 5432)
    timeout_seconds = max(1, min(_parse_int(os.getenv("DB_CONNECT_TIMEOUT"), 30), 3))
    if _can_reach_tcp_host(host, port, timeout_seconds):
        return requested_url

    logger.warning(
        "DATABASE_URL points to PostgreSQL at %s:%s but the server is unreachable; "
        "falling back to SQLite at %s for local development. "
        "Set SENTINELCV_ALLOW_SQLITE_FALLBACK=0 to disable this behavior.",
        host,
        port,
        DEFAULT_SQLITE_DATABASE_URL,
    )
    return DEFAULT_SQLITE_DATABASE_URL


SQLALCHEMY_DATABASE_URL = _resolve_database_url()
IS_SQLITE = SQLALCHEMY_DATABASE_URL.startswith("sqlite")


# SQLite needs check_same_thread=False; PostgreSQL uses pool settings
connect_args: dict[str, Any] = {}
if IS_SQLITE:
    connect_args["check_same_thread"] = False
else:
    connect_timeout = _parse_int(os.getenv("DB_CONNECT_TIMEOUT"), 30)
    if connect_timeout > 0:
        connect_args["connect_timeout"] = connect_timeout

pool_pre_ping = False if IS_SQLITE else _parse_bool(os.getenv("DB_POOL_PRE_PING"), True)
pool_size = _parse_int(os.getenv("DB_POOL_SIZE"), 20)
max_overflow = _parse_int(os.getenv("DB_MAX_OVERFLOW"), 10)
pool_recycle = _parse_int(os.getenv("DB_POOL_RECYCLE"), 3600)

# Only use pool settings for non-SQLite DBs
engine_kwargs: dict[str, Any] = {
    "pool_pre_ping": pool_pre_ping,
    "connect_args": connect_args,
}
if not IS_SQLITE:
    engine_kwargs["pool_size"] = pool_size
    engine_kwargs["max_overflow"] = max_overflow
    engine_kwargs["pool_recycle"] = pool_recycle

engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    **engine_kwargs
)

class MultiTenantQuery(Query):
    """Custom Query class to automatically filter by organization_id."""
    _tenant_id = None

    def __init__(self, *args, **kwargs):
        super(MultiTenantQuery, self).__init__(*args, **kwargs)

    def get_tenant_id(self) -> Optional[str]:
        return self._tenant_id

    def with_tenant(self, tenant_id: str) -> "MultiTenantQuery":
        return self.filter_by(organization_id=tenant_id)


class TenantSession(Session):
    """A Session that can be configured with a tenant_id to auto-filter queries."""
    tenant_id = None

    def __init__(self, *args, **kwargs):
        super(TenantSession, self).__init__(*args, **kwargs)

    def set_tenant(self, tenant_id: str) -> None:
        self.tenant_id = tenant_id


SessionLocal = sessionmaker(
    autocommit=False, 
    autoflush=False, 
    bind=engine,
    class_=TenantSession,
    query_cls=MultiTenantQuery
)

Base = declarative_base()

def init_db() -> None:
    """Initializes the database and creates tables if they don't exist."""
    is_production = (os.getenv("SENTINELCV_ENV") or "development").strip().lower() == "production"
    try:
        Base.metadata.create_all(bind=engine)
        if IS_SQLITE:
            with engine.connect() as conn:
                conn.execute(text("PRAGMA foreign_keys = ON;"))
    except Exception:
        logger.exception("Database initialization failed")
        if is_production:
            raise


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_tenant_db(organization_id: str) -> Generator[TenantSession, None, None]:
    """
    Dependency to get a DB session pre-configured with a tenant ID.
    Usage: db: TenantSession = Depends(get_tenant_db(org_id))
    """
    db = SessionLocal()
    db.set_tenant(organization_id)
    try:
        yield db
    finally:
        db.close()


# ─── Multi-tenant global filter ──────────────────────────────────────────────
#
# Background: the audit flagged that organization_id filters were enforced
# manually in every router (~50+). A single missed filter is a cross-tenant
# data breach. We layer a global SQLAlchemy filter on top of the manual
# checks so the system fails closed.
#
# Mechanism:
#   * `_current_tenant_id` is a ContextVar populated by HTTP middleware
#     immediately after the JWT is decoded.
#   * A `do_orm_execute` event listener inspects every SELECT statement and
#     injects `with_loader_criteria(Model, Model.organization_id == tenant)`
#     for every mapped model that exposes an `organization_id` column.
#   * Manual `.filter(...)` calls remain in place — both apply, the SQL is
#     still valid (tenant_id == tenant_id is a no-op), and the manual call
#     becomes defence-in-depth rather than the primary control.
#
# Opt-in via ENFORCE_TENANT_FILTER=1 to give existing tests a soft launch.

_current_tenant_id: ContextVar[Optional[str]] = ContextVar(
    "sentinelcv_current_tenant_id", default=None
)


def set_current_tenant(tenant_id: Optional[str]) -> None:
    """Bind the current request's organization_id to the ambient context."""
    _current_tenant_id.set(tenant_id)


def get_current_tenant() -> Optional[str]:
    return _current_tenant_id.get()


def reset_current_tenant() -> None:
    _current_tenant_id.set(None)


ENFORCE_TENANT_FILTER = _parse_bool(os.getenv("ENFORCE_TENANT_FILTER"), True)


def _organization_scoped_models() -> Iterable[Any]:
    """Return mapped classes that have an `organization_id` column.

    Resolved lazily to avoid an import cycle with the models package, which
    imports from `db.base`.
    """
    discovered: list[Any] = []
    for mapper in Base.registry.mappers:
        cls = mapper.class_
        if hasattr(cls, "organization_id"):
            discovered.append(cls)
    return discovered


@event.listens_for(Session, "do_orm_execute")
def _global_tenant_filter(orm_execute_state):
    if not ENFORCE_TENANT_FILTER:
        return
    if not orm_execute_state.is_select:
        return
    if orm_execute_state.is_relationship_load or orm_execute_state.is_column_load:
        return
    if orm_execute_state.execution_options.get("skip_tenant_filter"):
        return

    tenant_id = _current_tenant_id.get()
    if tenant_id is None:
        return

    tenant_id = get_current_tenant()
    statement = orm_execute_state.statement
    for model_cls in _organization_scoped_models():
        statement = statement.options(
            with_loader_criteria(
                model_cls,
                lambda cls: cls.organization_id == tenant_id,
                include_aliases=True,
            )
        )
    orm_execute_state.statement = statement


def log_sqlite_parity_warnings() -> None:
    """Log warnings about SQLite-vs-PostgreSQL behavioral differences.

    Call once at startup so developers know which production features are
    unavailable or degraded in the current local environment.
    """
    if not IS_SQLITE:
        return

    warnings = [
        "Vector search uses brute-force Python cosine similarity instead of pgvector ANN index",
        "Face embeddings are stored as encrypted JSON text instead of native pgvector columns",
        "No connection pooling — SQLite does not support pool_size / max_overflow",
        "JSONB columns are stored as plain JSON text — no GIN indexing available",
        "Composite production indices (visitor_logs, visitors) may not accelerate SQLite queries",
    ]
    logger.warning(
        "Running on SQLite — the following production features behave differently:\n  - %s",
        "\n  - ".join(warnings),
    )
