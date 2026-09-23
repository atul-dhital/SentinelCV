"""Add user_sessions and analytics_predictions tables.

Both models have existed in models.py since the analytics work but no
migration ever created them, so they were only present on SQLite via
create_all. On an Alembic-managed Postgres database they are missing, and
`DELETE /api/v1/visitors/{id}` fails outright — delete_visitor nulls the
visitor_id on user_sessions and hits UndefinedTable.

Revision ID: 027
Revises: 026
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "027"
down_revision = "026"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    is_pg = bind.dialect.name == "postgresql"
    uuid_type = postgresql.UUID(as_uuid=True) if is_pg else sa.String(36)
    json_type = postgresql.JSONB() if is_pg else sa.JSON()
    id_default = sa.text("gen_random_uuid()") if is_pg else None

    inspector = sa.inspect(bind)
    existing = set(inspector.get_table_names())

    if "user_sessions" not in existing:
        op.create_table(
            "user_sessions",
            sa.Column("id", uuid_type, primary_key=True, nullable=False, server_default=id_default),
            sa.Column("organization_id", uuid_type, nullable=True),
            sa.Column("visitor_id", uuid_type, nullable=True),
            sa.Column("session_start", sa.DateTime(), server_default=sa.func.now()),
            sa.Column("session_end", sa.DateTime(), nullable=True),
            sa.Column("current_position", json_type, nullable=True),
            sa.Column("path", json_type, nullable=True),
            sa.Column("status", sa.String(), server_default="active"),
            sa.Column("last_updated", sa.DateTime(), server_default=sa.func.now()),
            sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
            sa.ForeignKeyConstraint(["visitor_id"], ["visitors.id"]),
        )
        # delete_visitor filters by visitor_id; the dashboard lists by org + status.
        op.create_index("ix_user_sessions_visitor", "user_sessions", ["visitor_id"])
        op.create_index("ix_user_sessions_org_status", "user_sessions", ["organization_id", "status"])

    if "analytics_predictions" not in existing:
        op.create_table(
            "analytics_predictions",
            sa.Column("id", uuid_type, primary_key=True, nullable=False, server_default=id_default),
            sa.Column("organization_id", uuid_type, nullable=True),
            sa.Column("prediction_type", sa.String(), nullable=False),
            sa.Column("date_range", json_type, nullable=True),
            sa.Column("predicted_value", sa.Float(), nullable=False),
            sa.Column("confidence", sa.Float(), nullable=True),
            sa.Column("model_used", sa.String(), nullable=True),
            sa.Column("actual_value", sa.Float(), nullable=True),
            sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
            sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        )
        op.create_index(
            "ix_analytics_predictions_org_type",
            "analytics_predictions",
            ["organization_id", "prediction_type"],
        )


def downgrade():
    bind = op.get_bind()
    existing = set(sa.inspect(bind).get_table_names())

    if "analytics_predictions" in existing:
        op.drop_index("ix_analytics_predictions_org_type", table_name="analytics_predictions")
        op.drop_table("analytics_predictions")

    if "user_sessions" in existing:
        op.drop_index("ix_user_sessions_org_status", table_name="user_sessions")
        op.drop_index("ix_user_sessions_visitor", table_name="user_sessions")
        op.drop_table("user_sessions")
