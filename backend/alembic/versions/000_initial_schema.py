"""Initial schema baseline marker.

This migration is intentionally empty.  The base schema (organizations, users,
visitors, visitor_logs, cameras, face_data, etc.) was created on first deploy
via AUTO_INIT_DB=1 (SQLAlchemy create_all), NOT via Alembic.  This revision
acts as the root so that:

  - ``alembic downgrade base`` has a safe target to stop at.
  - ``alembic stamp 000`` can be used on existing installations to inject
    Alembic version tracking without re-running migrations.
  - CI ``alembic downgrade base`` completes cleanly.

Production bootstrap procedure (fresh PostgreSQL):
  1. Start backend once with AUTO_INIT_DB=1 to create all tables.
  2. Run:  alembic stamp head
  3. Set  AUTO_INIT_DB=0  permanently.
  4. All future schema changes go through Alembic migrations (001+).

Revision ID: 000
Revises: None
Create Date: 2026-06-01
"""

from alembic import op

revision = "000"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Schema already exists from AUTO_INIT_DB bootstrap — nothing to do.
    pass


def downgrade() -> None:
    # Dropping the entire base schema is intentionally not automated here.
    # To fully reset, drop and recreate the database, then re-bootstrap.
    pass
