import os
import sys
from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool
from alembic import context
from dotenv import load_dotenv

# Add the backend directory to path so models can be imported
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# The runtime backend reads its configuration from backend/.env.  Use the same
# source for migrations so a local migration cannot accidentally target a
# root-level or production DATABASE_URL.
_backend_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(_backend_root, ".env"))

# this is the Alembic Config object
config = context.config

# Override sqlalchemy.url from environment variable
# Normalize postgres:// → postgresql:// (Vercel/Supabase style)
_raw_url = os.getenv("DATABASE_URL") or next(
    (os.getenv(k) for k in ("POSTGRES_URL_NON_POOLING", "POSTGRES_URL", "POSTGRES_PRISMA_URL") if os.getenv(k)),
    None,
)
if not _raw_url:
    raise RuntimeError(
        "DATABASE_URL environment variable must be set before running migrations."
    )
database_url = _raw_url.replace("postgres://", "postgresql://", 1) if _raw_url.startswith("postgres://") else _raw_url
config.set_main_option("sqlalchemy.url", database_url)

# Interpret the config file for Python logging
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Import all models so Alembic can detect them
from db.base import Base
from models.models import (  # noqa: F401
    Organization, User, Visitor, FaceData, Camera, VisitorLog,
    LivenessScore, LivenessChallenge,
    AuditLog, PasswordResetToken, VideoProcessingJob,
    CameraSession, DetectionLog, VisitorAlert,
    Webhook, WebhookLog, ApiKey,
    Notification, CameraGroup, DataRetentionPolicy,
    FutureEnhancement, RateLimitRule, CarbonMetrics,
    TrainingJob, HPOJob, Ensemble, ActiveLearningJob,
    AlertConfig, AlertRule,
)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
