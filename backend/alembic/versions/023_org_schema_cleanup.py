"""Organization schema cleanup.

- Drop organizations.api_key  — was generated as a plain UUID but never read
  for authentication anywhere in the codebase. The ApiKey model (with hashed
  keys) is the canonical API key system.

- Add organizations.notification_email_address (VARCHAR, nullable) — optional
  dedicated address for alert notification emails. When NULL the alert service
  falls back to the active admin users' email addresses.

Revision ID: 023
Revises: 022
Create Date: 2026-06-01
"""

from alembic import op
import sqlalchemy as sa

revision = "023"
down_revision = "022"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()

    if bind.engine.name == "postgresql":
        inspector = sa.inspect(bind)
        columns = {column["name"] for column in inspector.get_columns("organizations")}
        constraints = {
            constraint["name"]
            for constraint in inspector.get_unique_constraints("organizations")
            if constraint.get("name")
        }

        # Drop the unused api_key column.
        op.drop_index("ix_organizations_api_key", table_name="organizations", if_exists=True)
        if "organizations_api_key_key" in constraints:
            op.drop_constraint("organizations_api_key_key", "organizations", type_="unique")
        if "api_key" in columns:
            op.drop_column("organizations", "api_key")
        # Add the notification address column.
        if "notification_email_address" not in columns:
            op.add_column(
                "organizations",
                sa.Column("notification_email_address", sa.String(), nullable=True),
            )
    else:
        # SQLite: add the new column only (SQLite cannot drop columns without
        # recreating the table; api_key stays until a full SQLite reset).
        try:
            op.add_column(
                "organizations",
                sa.Column("notification_email_address", sa.String(), nullable=True),
            )
        except Exception:
            pass  # column already exists on repeated SQLite runs


def downgrade() -> None:
    bind = op.get_bind()

    if bind.engine.name == "postgresql":
        op.drop_column("organizations", "notification_email_address")
        # Restore api_key as a nullable column without a server default.
        # The original default used gen_random_uuid() which requires pgcrypto;
        # restoring it as nullable avoids that extension dependency and is safe
        # because the column was dead code — nothing reads it for auth.
        op.add_column(
            "organizations",
            sa.Column("api_key", sa.String(), nullable=True),
        )
        op.create_unique_constraint("organizations_api_key_key", "organizations", ["api_key"])
