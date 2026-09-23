"""Add SSO provider and session tables.

Revision ID: 001_add_sso_tables
Revises: 
Create Date: 2026-04-02

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from db.base import Base
from models import models  # noqa: F401

# revision identifiers, used by Alembic.
revision = "001_add_sso_tables"
down_revision = "000"
branch_labels = None
depends_on = None

CORE_BOOTSTRAP_TABLES = {
    "organizations",
    "multi_angle_configs",
    "users",
    "visitors",
    "face_data",
    "cameras",
    "visitor_logs",
    "vision_analytics_events",
    "behavior_events",
    "cross_camera_movement_summaries",
    "continuous_learning_signals",
    "audit_logs",
    "password_reset_tokens",
    "refresh_token_sessions",
    "video_processing_jobs",
    "camera_sessions",
    "detection_logs",
    "visitor_alerts",
    "api_keys",
    "notifications",
    "camera_groups",
    "future_enhancements",
    "rate_limit_rules",
    "carbon_metrics",
    "bias_audit_records",
    "consent_records",
    "training_jobs",
    "hpo_jobs",
    "ensembles",
    "active_learning_jobs",
    "alert_configs",
    "learning_samples",
    "recognition_feedback",
    "data_quality_configs",
    "data_quality_audit_jobs",
    "quality_findings",
    "demographic_analyses",
    "quality_trend_analyses",
    "synthetic_data_configs",
    "synthesis_jobs",
    "generated_images",
    "quality_metrics_synthetic",
    "temporal_augmentation_configs",
    "augmentation_jobs",
    "generated_sequences",
    "expression_metrics",
    "gait_signatures",
    "voice_prints",
    "sso_connections",
}


def _sorted_metadata_tables(names: set[str]) -> list[sa.Table]:
    return [table for table in Base.metadata.sorted_tables if table.name in names]


def _table_exists(bind, table_name: str) -> bool:
    inspector = sa.inspect(bind)
    return table_name in inspector.get_table_names()


def _index_exists(bind, table_name: str, index_name: str) -> bool:
    inspector = sa.inspect(bind)
    return any(index.get("name") == index_name for index in inspector.get_indexes(table_name))


def upgrade() -> None:
    """Create SSO provider and session tables."""
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        bind.execute(sa.text("CREATE EXTENSION IF NOT EXISTS vector"))
        bind.execute(sa.text("CREATE EXTENSION IF NOT EXISTS pgcrypto"))

    Base.metadata.create_all(
        bind=bind,
        tables=_sorted_metadata_tables(CORE_BOOTSTRAP_TABLES),
        checkfirst=True,
    )

    # Create sso_providers table
    if not _table_exists(bind, "sso_providers"):
        op.create_table(
            "sso_providers",
            sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False, server_default=sa.text("gen_random_uuid()")),
            sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("provider_type", sa.String(50), nullable=False),  # 'saml', 'oauth2', 'openid'
            sa.Column("provider_name", sa.String(255), nullable=False),
            sa.Column("entity_id", sa.String(255), nullable=True),
            sa.Column("sso_url", sa.String(255), nullable=True),
            sa.Column("certificate", sa.Text(), nullable=True),
            sa.Column("attribute_mappings", sa.JSON(), nullable=True),
            sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.text("FALSE")),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )
    if not _index_exists(bind, "sso_providers", "ix_sso_providers_organization_id"):
        op.create_index("ix_sso_providers_organization_id", "sso_providers", ["organization_id"])
    if not _index_exists(bind, "sso_providers", "ix_sso_providers_active"):
        op.create_index("ix_sso_providers_active", "sso_providers", ["active"])

    # Create sso_sessions table
    if not _table_exists(bind, "sso_sessions"):
        op.create_table(
            "sso_sessions",
            sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False, server_default=sa.text("gen_random_uuid()")),
            sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("provider_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("token", sa.String(255), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["provider_id"], ["sso_providers.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )
    if not _index_exists(bind, "sso_sessions", "ix_sso_sessions_user_id"):
        op.create_index("ix_sso_sessions_user_id", "sso_sessions", ["user_id"])
    if not _index_exists(bind, "sso_sessions", "ix_sso_sessions_provider_id"):
        op.create_index("ix_sso_sessions_provider_id", "sso_sessions", ["provider_id"])
    if not _index_exists(bind, "sso_sessions", "ix_sso_sessions_expires_at"):
        op.create_index("ix_sso_sessions_expires_at", "sso_sessions", ["expires_at"])


def downgrade() -> None:
    """Drop SSO tables."""
    op.drop_index("ix_sso_sessions_expires_at", table_name="sso_sessions")
    op.drop_index("ix_sso_sessions_provider_id", table_name="sso_sessions")
    op.drop_index("ix_sso_sessions_user_id", table_name="sso_sessions")
    op.drop_table("sso_sessions")

    op.drop_index("ix_sso_providers_active", table_name="sso_providers")
    op.drop_index("ix_sso_providers_organization_id", table_name="sso_providers")
    op.drop_table("sso_providers")

    bind = op.get_bind()
    for table in reversed(_sorted_metadata_tables(CORE_BOOTSTRAP_TABLES)):
        table.drop(bind=bind, checkfirst=True)
