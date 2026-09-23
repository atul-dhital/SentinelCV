"""Add federated learning tables (US-FUT-016).

Revision ID: 005
Revises: 004
Create Date: 2026-04-02 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '005'
down_revision = '004'
branch_labels = None
depends_on = None


def json_type():
    return postgresql.JSONB().with_variant(sa.JSON(), "sqlite")


def upgrade():
    """Add federated learning tables."""
    op.create_table(
        'federated_rounds',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False, primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column('organization_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('model_type', sa.String(50), nullable=False),
        sa.Column('round_number', sa.Integer(), default=1),
        sa.Column('num_participants', sa.Integer(), default=1),
        sa.Column('status', sa.String(50), default='initialized'),
        sa.Column('global_accuracy_before', sa.Float(), nullable=True),
        sa.Column('global_accuracy_after', sa.Float(), nullable=True),
        sa.Column('aggregated_weights', json_type(), nullable=True),
        sa.Column('config', json_type(), nullable=True),
        sa.Column('created_at', sa.DateTime(), default=sa.func.now()),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
    )
    op.create_index(
        'ix_federated_rounds_org_model_round',
        'federated_rounds',
        ['organization_id', 'model_type', 'round_number']
    )

    op.create_table(
        'federated_updates',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False, primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column('round_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('participant_id', sa.String(255), nullable=False),
        sa.Column('local_accuracy', sa.Float(), nullable=True),
        sa.Column('local_loss', sa.Float(), nullable=True),
        sa.Column('num_samples', sa.Integer(), default=0),
        sa.Column('weight_deltas', json_type(), nullable=True),
        sa.Column('submitted_at', sa.DateTime(), default=sa.func.now()),
        sa.ForeignKeyConstraint(['round_id'], ['federated_rounds.id'], ondelete='CASCADE'),
    )
    op.create_index('ix_federated_updates_round_id', 'federated_updates', ['round_id'])


def downgrade():
    """Remove federated learning tables."""
    op.drop_index('ix_federated_updates_round_id')
    op.drop_table('federated_updates')

    op.drop_index('ix_federated_rounds_org_model_round')
    op.drop_table('federated_rounds')
