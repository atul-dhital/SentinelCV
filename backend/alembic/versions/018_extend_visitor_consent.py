"""Extend visitor_consent for biometric-data audit evidence.

Revision ID: 018
Revises: 017
Create Date: 2026-04-26 00:00:00.000000

The VisitorConsent table previously held only (visitor_id, consent_type,
consent_given, consent_date, consent_withdrawn_date). The audit required
linking every biometric-template enrolment to a contemporaneous, evidenced
consent record with a clear lawful basis. This migration adds the
metadata columns needed to satisfy GDPR Art 7 / Art 9 evidentiary
requirements and APP 3 / APP 11 traceability.

The new columns are nullable so the migration is non-blocking; the
application will populate them on new writes and a backfill task can
fill historic rows once the data steward has confirmed the lawful basis.
"""

from alembic import op
import sqlalchemy as sa


revision = "018"
down_revision = "017"
branch_labels = None
depends_on = None


def _has_column(table_name: str, column_name: str) -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return column_name in {column["name"] for column in inspector.get_columns(table_name)}


_NEW_COLUMNS = (
    ("organization_id", sa.String(length=36)),
    ("data_subject_email", sa.String(length=255)),
    ("lawful_basis", sa.String(length=64)),
    ("consent_text_version", sa.String(length=32)),
    ("capture_method", sa.String(length=32)),
    ("ip_address", sa.String(length=64)),
    ("user_agent", sa.String(length=512)),
    ("evidence_url", sa.String(length=1024)),
)


def upgrade() -> None:
    for name, col_type in _NEW_COLUMNS:
        if not _has_column("visitor_consent", name):
            op.add_column(
                "visitor_consent",
                sa.Column(name, col_type, nullable=True),
            )

    # Make visitor_id nullable so we can record consent before a Visitor row
    # exists (intake form). SQLite cannot ALTER COLUMN, so the conversion is
    # only attempted on dialects that support it.
    bind = op.get_bind()
    if bind.dialect.name != "sqlite":
        op.alter_column(
            "visitor_consent",
            "visitor_id",
            existing_type=sa.String(length=36),
            nullable=True,
        )

    op.create_index(
        "ix_visitor_consent_organization_id",
        "visitor_consent",
        ["organization_id"],
        if_not_exists=True,
    )
    op.create_index(
        "ix_visitor_consent_data_subject_email",
        "visitor_consent",
        ["data_subject_email"],
        if_not_exists=True,
    )


def downgrade() -> None:
    for name, _col_type in _NEW_COLUMNS:
        if _has_column("visitor_consent", name):
            op.drop_column("visitor_consent", name)
    op.drop_index(
        "ix_visitor_consent_organization_id",
        table_name="visitor_consent",
        if_exists=True,
    )
    op.drop_index(
        "ix_visitor_consent_data_subject_email",
        table_name="visitor_consent",
        if_exists=True,
    )
