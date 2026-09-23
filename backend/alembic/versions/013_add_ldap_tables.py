"""Add LDAP configuration tables.

Revision ID: 013
Revises: 012
Create Date: 2026-04-02 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa
from db.base import Base
from models import models  # noqa: F401

revision = '013'
down_revision = '012'
branch_labels = None
depends_on = None

LDAP_RUNTIME_TABLES = {
    "ldap_configs",
    "ldap_sync_logs",
}


def _sorted_metadata_tables(names: set[str]) -> list[sa.Table]:
    return [table for table in Base.metadata.sorted_tables if table.name in names]


def upgrade():
    """Add LDAP configuration and sync log tables."""
    Base.metadata.create_all(
        bind=op.get_bind(),
        tables=_sorted_metadata_tables(LDAP_RUNTIME_TABLES),
        checkfirst=True,
    )
    op.create_index('ix_ldap_configs_org', 'ldap_configs', ['organization_id'])
    op.create_index('ix_ldap_configs_active', 'ldap_configs', ['organization_id', 'active'])

    op.create_index('ix_ldap_sync_logs_org', 'ldap_sync_logs', ['organization_id'])
    op.create_index('ix_ldap_sync_logs_config', 'ldap_sync_logs', ['ldap_config_id', 'created_at'])


def downgrade():
    """Remove LDAP configuration tables."""
    op.drop_index('ix_ldap_sync_logs_config')
    op.drop_index('ix_ldap_sync_logs_org')

    op.drop_index('ix_ldap_configs_active')
    op.drop_index('ix_ldap_configs_org')
    bind = op.get_bind()
    for table in reversed(_sorted_metadata_tables(LDAP_RUNTIME_TABLES)):
        table.drop(bind=bind, checkfirst=True)
