"""Add watchlists table (G2 — VIP / banned / person-of-interest).

Revision ID: 025
Revises: 024
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "025"
down_revision = "024"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    is_pg = bind.dialect.name == "postgresql"
    uuid_type = postgresql.UUID(as_uuid=True) if is_pg else sa.String(36)
    id_default = sa.text("gen_random_uuid()") if is_pg else None

    op.create_table(
        "watchlists",
        sa.Column("id", uuid_type, primary_key=True, nullable=False, server_default=id_default),
        sa.Column("organization_id", uuid_type, nullable=False),
        sa.Column("visitor_id", uuid_type, nullable=False),
        sa.Column("category", sa.String(32), nullable=False, server_default="poi"),
        sa.Column("severity", sa.String(16), nullable=False, server_default="medium"),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true") if is_pg else sa.text("1")),
        sa.Column("created_by", uuid_type, nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["visitor_id"], ["visitors.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
    )
    op.create_index("ix_watchlists_org", "watchlists", ["organization_id"])
    op.create_index("ix_watchlists_visitor", "watchlists", ["visitor_id"])


def downgrade():
    op.drop_index("ix_watchlists_visitor", table_name="watchlists")
    op.drop_index("ix_watchlists_org", table_name="watchlists")
    op.drop_table("watchlists")
