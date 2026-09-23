"""Add performance indexes for high-volume tables.

visitor_logs (org_id, timestamp DESC) — used by dashboard stats and log listing.
visitor_logs (org_id, status)         — used by unidentified-log filter.
visitors name/email trigram           — enables fast ILIKE search via pg_trgm.
password_reset_tokens (expires_at)    — used by cleanup cron; partial on unused only.

Revision ID: 022
Revises: 021
Create Date: 2026-06-01
"""

from alembic import op

revision = "022"
down_revision = "021"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.engine.name != "postgresql":
        return  # SQLite uses AUTO_INIT_DB; indexes created by SQLAlchemy

    # ── visitor_logs performance indexes ─────────────────────────────────────
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_visitor_logs_org_ts "
        "ON visitor_logs (organization_id, timestamp DESC)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_visitor_logs_org_status "
        "ON visitor_logs (organization_id, status)"
    )

    # ── pg_trgm: fast ILIKE search on visitors ────────────────────────────────
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_visitors_name_trgm "
        "ON visitors USING gin (name gin_trgm_ops)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_visitors_email_trgm "
        "ON visitors USING gin (email gin_trgm_ops)"
    )

    # ── password_reset_tokens cleanup index ───────────────────────────────────
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_password_reset_tokens_expires "
        "ON password_reset_tokens (expires_at) WHERE used = false"
    )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.engine.name != "postgresql":
        return

    op.execute("DROP INDEX IF EXISTS ix_visitor_logs_org_ts")
    op.execute("DROP INDEX IF EXISTS ix_visitor_logs_org_status")
    op.execute("DROP INDEX IF EXISTS ix_visitors_name_trgm")
    op.execute("DROP INDEX IF EXISTS ix_visitors_email_trgm")
    op.execute("DROP INDEX IF EXISTS ix_password_reset_tokens_expires")
