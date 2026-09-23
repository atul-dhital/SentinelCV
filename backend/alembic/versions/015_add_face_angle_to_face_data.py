"""Add face_angle to face_data for multi-angle matching.

Revision ID: 015
Revises: 014
Create Date: 2026-04-08 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "015"
down_revision = "014"
branch_labels = None
depends_on = None


def _has_column(table_name: str, column_name: str) -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return column_name in {column["name"] for column in inspector.get_columns(table_name)}


def upgrade() -> None:
    """Add the optional face angle column expected by live recognition flows."""
    if not _has_column("face_data", "face_angle"):
        op.add_column("face_data", sa.Column("face_angle", sa.String(), nullable=True))


def downgrade() -> None:
    """Remove face_angle from face_data."""
    if _has_column("face_data", "face_angle"):
        op.drop_column("face_data", "face_angle")
