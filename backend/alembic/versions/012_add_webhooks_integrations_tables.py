"""Add webhooks and integrations tables.

Revision ID: 012
Revises: 011
Create Date: 2026-04-02 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from db.base import Base
from models import models  # noqa: F401

revision = '012'
down_revision = '011'
branch_labels = None
depends_on = None

WEBHOOK_RUNTIME_TABLES = {
    "webhooks",
    "alert_rules",
    "webhook_logs",
}


def _sorted_metadata_tables(names: set[str]) -> list[sa.Table]:
    return [table for table in Base.metadata.sorted_tables if table.name in names]


def upgrade():
    """Add webhooks and integration tables."""
    Base.metadata.create_all(
        bind=op.get_bind(),
        tables=_sorted_metadata_tables(WEBHOOK_RUNTIME_TABLES),
        checkfirst=True,
    )
    op.create_index('ix_webhooks_org_active', 'webhooks', ['organization_id', 'is_active'])
    
    # Webhook execution logs table
    op.create_table(
        'webhook_execution_logs',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False, primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column('webhook_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('triggered_by_event_id', postgresql.UUID(as_uuid=True), nullable=True),       # e.g., detection_log_id
        
        # Execution details
        sa.Column('event_type', sa.String(50), nullable=False),
        sa.Column('request_payload', sa.Text(), nullable=True),
        sa.Column('request_headers', sa.JSON(), nullable=True),
        
        # Response details
        sa.Column('response_status_code', sa.Integer(), nullable=True),
        sa.Column('response_body', sa.Text(), nullable=True),
        sa.Column('response_headers', sa.JSON(), nullable=True),
        
        # Timing
        sa.Column('execution_time_ms', sa.Float(), nullable=True),
        sa.Column('retry_count', sa.Integer(), default=0),
        sa.Column('success', sa.Boolean(), default=False),
        sa.Column('error_message', sa.Text(), nullable=True),
        
        sa.Column('created_at', sa.DateTime(), default=sa.func.now()),
        
        sa.ForeignKeyConstraint(['webhook_id'], ['webhooks.id'], ondelete='CASCADE'),
    )
    op.create_index('ix_webhook_logs_webhook_success', 'webhook_execution_logs', 
                    ['webhook_id', 'success', 'created_at'])
    
    # External system integrations table (VMS, HR, CRM, etc)
    op.create_table(
        'external_integrations',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False, primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column('organization_id', postgresql.UUID(as_uuid=True), nullable=False),
        
        # Integration info
        sa.Column('integration_type', sa.String(50), nullable=False),          # vms, hr_system, crm, access_control
        sa.Column('system_name', sa.String(255), nullable=False),
        sa.Column('system_version', sa.String(50), nullable=True),
        
        # Connection details
        sa.Column('api_endpoint', sa.String(500), nullable=True),
        sa.Column('api_key', sa.String(500), nullable=True),                   # Encrypted
        sa.Column('client_id', sa.String(255), nullable=True),
        sa.Column('client_secret', sa.String(500), nullable=True),             # Encrypted
        
        # Sync configuration
        sa.Column('sync_enabled', sa.Boolean(), default=True),
        sa.Column('sync_interval_minutes', sa.Integer(), default=60),
        sa.Column('last_sync_time', sa.DateTime(), nullable=True),
        sa.Column('last_sync_status', sa.String(20), nullable=True),           # success, failed, partial
        
        # Data mapping
        sa.Column('field_mappings', sa.JSON(), nullable=True),                 # Map external fields to SentinelCV fields
        
        # Status
        sa.Column('is_active', sa.Boolean(), default=False),
        sa.Column('is_connected', sa.Boolean(), default=False),
        sa.Column('error_message', sa.Text(), nullable=True),
        
        sa.Column('created_at', sa.DateTime(), default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), onupdate=sa.func.now()),
        
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
    )
    op.create_index('ix_external_integrations_org_type', 'external_integrations', 
                    ['organization_id', 'integration_type'])


def downgrade():
    """Remove webhooks and integrations tables."""
    op.drop_index('ix_external_integrations_org_type')
    op.drop_table('external_integrations')
    
    op.drop_index('ix_webhook_logs_webhook_success')
    op.drop_table('webhook_execution_logs')
    
    op.drop_index('ix_webhooks_org_active')
    bind = op.get_bind()
    for table in reversed(_sorted_metadata_tables(WEBHOOK_RUNTIME_TABLES)):
        table.drop(bind=bind, checkfirst=True)
