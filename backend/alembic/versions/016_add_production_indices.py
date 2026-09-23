"""Add production performance indices for critical query paths.

Revision ID: 016
Revises: 015
Create Date: 2026-04-09 00:00:00.000000
"""

from alembic import op

revision = "016"
down_revision = "015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # face_data: visitor-scoped lookups, primary face queries, quality filtering
    op.create_index(
        "ix_face_data_visitor_id",
        "face_data",
        ["visitor_id"],
        if_not_exists=True,
    )
    op.create_index(
        "ix_face_data_is_primary",
        "face_data",
        ["is_primary"],
        if_not_exists=True,
    )
    op.create_index(
        "ix_face_data_quality_score",
        "face_data",
        ["quality_score"],
        if_not_exists=True,
    )

    # visitor_logs: composite indices for time-series and org-scoped queries
    op.create_index(
        "ix_visitor_logs_visitor_timestamp",
        "visitor_logs",
        ["visitor_id", "timestamp"],
        if_not_exists=True,
    )
    op.create_index(
        "ix_visitor_logs_org_timestamp",
        "visitor_logs",
        ["organization_id", "timestamp"],
        if_not_exists=True,
    )

    # visitors: org-scoped filtering by known/active status
    op.create_index(
        "ix_visitors_org_is_known",
        "visitors",
        ["organization_id", "is_known"],
        if_not_exists=True,
    )
    op.create_index(
        "ix_visitors_org_is_active",
        "visitors",
        ["organization_id", "is_active"],
        if_not_exists=True,
    )

    # liveness_scores: org-scoped temporal queries
    op.create_index(
        "ix_liveness_scores_org_created",
        "liveness_scores",
        ["organization_id", "created_at"],
        if_not_exists=True,
    )


def downgrade() -> None:
    op.drop_index("ix_liveness_scores_org_created", table_name="liveness_scores")
    op.drop_index("ix_visitors_org_is_active", table_name="visitors")
    op.drop_index("ix_visitors_org_is_known", table_name="visitors")
    op.drop_index("ix_visitor_logs_org_timestamp", table_name="visitor_logs")
    op.drop_index("ix_visitor_logs_visitor_timestamp", table_name="visitor_logs")
    op.drop_index("ix_face_data_quality_score", table_name="face_data")
    op.drop_index("ix_face_data_is_primary", table_name="face_data")
    op.drop_index("ix_face_data_visitor_id", table_name="face_data")
