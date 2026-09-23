"""Add GDPR compliance tables.

Revision ID: 002_add_gdpr_tables
Revises: 001_add_sso_tables
Create Date: 2026-04-02

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "002_add_gdpr_tables"
down_revision = "001_add_sso_tables"
branch_labels = None
depends_on = None


def _table_exists(bind, table_name: str) -> bool:
    inspector = sa.inspect(bind)
    return table_name in inspector.get_table_names()


def _index_exists(bind, table_name: str, index_name: str) -> bool:
    inspector = sa.inspect(bind)
    return any(index.get("name") == index_name for index in inspector.get_indexes(table_name))


def _column_names(bind, table_name: str) -> set[str]:
    inspector = sa.inspect(bind)
    return {column.get("name") for column in inspector.get_columns(table_name)}


def upgrade() -> None:
    """Create GDPR request, consent, and retention policy tables."""
    bind = op.get_bind()

    if not _table_exists(bind, "gdpr_requests"):
        op.create_table(
            "gdpr_requests",
            sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False, server_default=sa.text("gen_random_uuid()")),
            sa.Column("visitor_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("request_type", sa.String(50), nullable=False),  # 'data_export', 'data_deletion', 'consent_withdrawal'
            sa.Column("status", sa.String(20), nullable=False, server_default=sa.text("'pending'")),  # 'pending', 'processing', 'completed'
            sa.Column("request_date", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.Column("completion_date", sa.DateTime(timezone=True), nullable=True),
            sa.Column("response_file_url", sa.String(255), nullable=True),
            sa.Column("notes", sa.Text(), nullable=True),
            sa.ForeignKeyConstraint(["visitor_id"], ["visitors.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )
    if not _index_exists(bind, "gdpr_requests", "ix_gdpr_requests_visitor_id"):
        op.create_index("ix_gdpr_requests_visitor_id", "gdpr_requests", ["visitor_id"])
    if not _index_exists(bind, "gdpr_requests", "ix_gdpr_requests_status"):
        op.create_index("ix_gdpr_requests_status", "gdpr_requests", ["status"])
    if not _index_exists(bind, "gdpr_requests", "ix_gdpr_requests_request_type"):
        op.create_index("ix_gdpr_requests_request_type", "gdpr_requests", ["request_type"])

    if not _table_exists(bind, "visitor_consent"):
        op.create_table(
            "visitor_consent",
            sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False, server_default=sa.text("gen_random_uuid()")),
            sa.Column("visitor_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("consent_type", sa.String(50), nullable=False),  # 'face_recognition', 'tracking', 'analytics'
            sa.Column("consent_given", sa.Boolean(), nullable=False),
            sa.Column("consent_date", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.Column("consent_withdrawn_date", sa.DateTime(timezone=True), nullable=True),
            sa.ForeignKeyConstraint(["visitor_id"], ["visitors.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )
    if not _index_exists(bind, "visitor_consent", "ix_visitor_consent_visitor_id"):
        op.create_index("ix_visitor_consent_visitor_id", "visitor_consent", ["visitor_id"])
    if not _index_exists(bind, "visitor_consent", "ix_visitor_consent_consent_type"):
        op.create_index("ix_visitor_consent_consent_type", "visitor_consent", ["consent_type"])

    if not _table_exists(bind, "data_retention_policies"):
        op.create_table(
            "data_retention_policies",
            sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False, server_default=sa.text("gen_random_uuid()")),
            sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("data_type", sa.String(50), nullable=False),  # 'face_images', 'face_embeddings', 'logs'
            sa.Column("retention_days", sa.Integer(), nullable=False),
            sa.Column("auto_delete_enabled", sa.Boolean(), nullable=False, server_default=sa.text("TRUE")),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )
    else:
        columns = _column_names(bind, "data_retention_policies")
        if "data_type" not in columns and "entity_type" in columns:
            op.alter_column(
                "data_retention_policies",
                "entity_type",
                new_column_name="data_type",
                existing_type=sa.String(50),
            )
            columns = _column_names(bind, "data_retention_policies")
        if "auto_delete_enabled" not in columns and "auto_delete" in columns:
            op.alter_column(
                "data_retention_policies",
                "auto_delete",
                new_column_name="auto_delete_enabled",
                existing_type=sa.Boolean(),
            )
            columns = _column_names(bind, "data_retention_policies")
        if "data_type" not in columns:
            op.add_column(
                "data_retention_policies",
                sa.Column("data_type", sa.String(50), nullable=True),
            )
        if "auto_delete_enabled" not in columns:
            op.add_column(
                "data_retention_policies",
                sa.Column("auto_delete_enabled", sa.Boolean(), nullable=True),
            )
    if not _index_exists(bind, "data_retention_policies", "ix_data_retention_policies_organization_id"):
        op.create_index("ix_data_retention_policies_organization_id", "data_retention_policies", ["organization_id"])
    if not _index_exists(bind, "data_retention_policies", "ix_data_retention_policies_data_type"):
        op.create_index("ix_data_retention_policies_data_type", "data_retention_policies", ["data_type"])


def downgrade() -> None:
    """Drop GDPR tables."""
    op.drop_index("ix_data_retention_policies_data_type", table_name="data_retention_policies")
    op.drop_index("ix_data_retention_policies_organization_id", table_name="data_retention_policies")
    op.drop_table("data_retention_policies")

    op.drop_index("ix_visitor_consent_consent_type", table_name="visitor_consent")
    op.drop_index("ix_visitor_consent_visitor_id", table_name="visitor_consent")
    op.drop_table("visitor_consent")

    op.drop_index("ix_gdpr_requests_request_type", table_name="gdpr_requests")
    op.drop_index("ix_gdpr_requests_status", table_name="gdpr_requests")
    op.drop_index("ix_gdpr_requests_visitor_id", table_name="gdpr_requests")
    op.drop_table("gdpr_requests")
