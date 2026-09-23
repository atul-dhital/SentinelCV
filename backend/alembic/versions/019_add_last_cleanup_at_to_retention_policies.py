"""Add last_cleanup_at to data_retention_policies.

Revision ID: 019
Revises: 018
Create Date: 2026-05-05 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "019"
down_revision = "018"
branch_labels = None
depends_on = None


def _has_column(table_name: str, column_name: str) -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return column_name in {column["name"] for column in inspector.get_columns(table_name)}


def upgrade() -> None:
    if not _has_column("data_retention_policies", "last_cleanup_at"):
        op.add_column(
            "data_retention_policies",
            sa.Column("last_cleanup_at", sa.DateTime(), nullable=True),
        )


def downgrade() -> None:
    if _has_column("data_retention_policies", "last_cleanup_at"):
        op.drop_column("data_retention_policies", "last_cleanup_at")
