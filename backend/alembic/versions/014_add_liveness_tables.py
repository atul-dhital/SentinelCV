"""Add liveness detection tables (US-FUT-042).

Revision ID: 014
Revises: 013
Create Date: 2026-04-02 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers
revision = "014"
down_revision = "013"
branch_labels = None
depends_on = None


def json_type():
    return postgresql.JSONB().with_variant(sa.JSON(), "sqlite")


def upgrade() -> None:
    """Create liveness scores and challenges tables."""
    op.create_table(
        "liveness_scores",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("visitor_log_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("is_live", sa.Boolean(), nullable=False),
        sa.Column("overall_score", sa.Float(), nullable=False),
        sa.Column("rejection_reason", sa.String(), nullable=True),
        sa.Column("texture_score", sa.Float(), nullable=True),
        sa.Column("motion_score", sa.Float(), nullable=True),
        sa.Column("deep_learning_score", sa.Float(), nullable=True),
        sa.Column("video_required", sa.Boolean(), nullable=False, server_default=sa.text("TRUE")),
        sa.Column("video_duration_frames", sa.Integer(), nullable=True),
        sa.Column("has_sufficient_motion", sa.Boolean(), nullable=True),
        sa.Column("blink_count", sa.Integer(), nullable=True),
        sa.Column("attack_indicators", json_type(), nullable=True),
        sa.Column("face_size", sa.Integer(), nullable=True),
        sa.Column("illumination_score", sa.Float(), nullable=True),
        sa.Column("blur_score", sa.Float(), nullable=True),
        sa.Column("noise_level", sa.Float(), nullable=True),
        sa.Column("challenge_type", sa.String(), nullable=True),
        sa.Column("challenge_passed", sa.Boolean(), nullable=True),
        sa.Column("challenge_attempts", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("method_used", sa.String(), nullable=False),
        sa.Column("model_version", sa.String(), nullable=True),
        sa.Column("processing_time_ms", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), onupdate=sa.func.now()),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["visitor_log_id"], ["visitor_logs.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_liveness_scores_org_id", "liveness_scores", ["organization_id"])
    op.create_index("ix_liveness_scores_log_id", "liveness_scores", ["visitor_log_id"])
    op.create_index("ix_liveness_scores_created_at", "liveness_scores", ["created_at"])

    op.create_table(
        "liveness_challenges",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("visitor_log_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("challenge_type", sa.String(), nullable=False, server_default=sa.text("'blink'")),
        sa.Column("status", sa.String(), nullable=False, server_default=sa.text("'pending'")),
        sa.Column("instruction", sa.String(), nullable=True),
        sa.Column("timeout_seconds", sa.Integer(), nullable=False, server_default=sa.text("30")),
        sa.Column("verified", sa.Boolean(), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("details", json_type(), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("verified_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["visitor_log_id"], ["visitor_logs.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_liveness_challenges_org_id", "liveness_challenges", ["organization_id"])
    op.create_index("ix_liveness_challenges_log_id", "liveness_challenges", ["visitor_log_id"])
    op.create_index("ix_liveness_challenges_status", "liveness_challenges", ["status"])


def downgrade() -> None:
    """Drop liveness tables."""
    op.drop_index("ix_liveness_challenges_status", table_name="liveness_challenges")
    op.drop_index("ix_liveness_challenges_log_id", table_name="liveness_challenges")
    op.drop_index("ix_liveness_challenges_org_id", table_name="liveness_challenges")
    op.drop_table("liveness_challenges")

    op.drop_index("ix_liveness_scores_created_at", table_name="liveness_scores")
    op.drop_index("ix_liveness_scores_log_id", table_name="liveness_scores")
    op.drop_index("ix_liveness_scores_org_id", table_name="liveness_scores")
    op.drop_table("liveness_scores")
