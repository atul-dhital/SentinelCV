"""Add indexes on refresh_token_sessions for fast token lookup.

token_hash is queried on every token refresh, logout, and reuse-detection
check. Without an index this is a full-table scan under load.
token_jti is queried for JTI-mismatch detection on refresh.

SQLAlchemy defines these with index=True in the model, so AUTO_INIT_DB
environments already have them. This migration ensures they exist on
Alembic-managed PostgreSQL deployments where create_all() is not called.

Revision ID: 021
Revises: 020
Create Date: 2026-06-01
"""

from alembic import op

revision = "021"
down_revision = "020"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.engine.name != "postgresql":
        return

    # token_hash: unique index — used on every refresh / logout lookup
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS ix_refresh_token_sessions_token_hash "
        "ON refresh_token_sessions (token_hash)"
    )
    # token_jti: non-unique index — used for JTI-mismatch revocation checks
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_refresh_token_sessions_token_jti "
        "ON refresh_token_sessions (token_jti)"
    )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.engine.name != "postgresql":
        return

    op.execute("DROP INDEX IF EXISTS ix_refresh_token_sessions_token_hash")
    op.execute("DROP INDEX IF EXISTS ix_refresh_token_sessions_token_jti")
