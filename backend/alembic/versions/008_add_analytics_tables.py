"""Add analytics and behavior analysis tables.

Revision ID: 008
Revises: 007
Create Date: 2026-04-02 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '008'
down_revision = '007'
branch_labels = None
depends_on = None


def upgrade():
    """Add advanced analytics tables."""
    # Behavior analytics table
    op.create_table(
        'behavior_analytics',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False, primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column('visitor_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('organization_id', postgresql.UUID(as_uuid=True), nullable=False),
        
        # Daily metrics
        sa.Column('visit_date', sa.Date(), nullable=False),
        sa.Column('visit_count', sa.Integer(), default=0),
        sa.Column('total_dwell_seconds', sa.Integer(), default=0),               # Total time in facility
        sa.Column('zones_visited', sa.Integer(), default=0),
        sa.Column('interactions_count', sa.Integer(), default=0),
        
        # Behavioral patterns
        sa.Column('typical_entry_hour', sa.Integer(), nullable=True),            # Hour of day (0-23)
        sa.Column('typical_dwell_minutes', sa.Integer(), nullable=True),
        sa.Column('visit_frequency', sa.String(20), nullable=True),             # 'daily', 'weekly', 'occasional'
        
        # Anomalies
        sa.Column('is_anomalous', sa.Boolean(), default=False),
        sa.Column('anomaly_score', sa.Float(), nullable=True),                  # 0-1 anomaly probability
        sa.Column('anomaly_reason', sa.String(255), nullable=True),             # Why is this anomalous?
        
        # Emotional patterns
        sa.Column('avg_emotion_valence', sa.Float(), nullable=True),
        sa.Column('avg_emotion_arousal', sa.Float(), nullable=True),
        sa.Column('dominant_emotion', sa.String(50), nullable=True),
        
        sa.Column('created_at', sa.DateTime(), default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), onupdate=sa.func.now()),
        
        sa.ForeignKeyConstraint(['visitor_id'], ['visitors.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id']),
    )
    op.create_index('ix_behavior_analytics_visitor_date', 'behavior_analytics', 
                    ['visitor_id', 'visit_date'])
    op.create_index('ix_behavior_analytics_anomaly', 'behavior_analytics', ['is_anomalous'])
    
    # Organization-wide analytics table
    op.create_table(
        'organization_analytics',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False, primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column('organization_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('analytics_date', sa.Date(), nullable=False),
        
        # Daily metrics
        sa.Column('total_visitors', sa.Integer(), default=0),
        sa.Column('identified_visitors', sa.Integer(), default=0),
        sa.Column('unidentified_visitors', sa.Integer(), default=0),
        sa.Column('total_detections', sa.Integer(), default=0),
        
        # Facility metrics
        sa.Column('avg_facility_occupancy', sa.Integer(), nullable=True),       # Number of people
        sa.Column('peak_occupancy_time', sa.String(10), nullable=True),         # HH:MM
        sa.Column('busiest_zone', sa.String(255), nullable=True),
        
        # Performance metrics
        sa.Column('avg_recognition_latency_ms', sa.Float(), nullable=True),
        sa.Column('avg_recognition_confidence', sa.Float(), nullable=True),
        sa.Column('false_positive_rate', sa.Float(), nullable=True),
        sa.Column('false_negative_rate', sa.Float(), nullable=True),
        
        sa.Column('created_at', sa.DateTime(), default=sa.func.now()),
        
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id']),
    )
    op.create_index('ix_org_analytics_org_date', 'organization_analytics', 
                    ['organization_id', 'analytics_date'])


def downgrade():
    """Remove analytics tables."""
    op.drop_index('ix_org_analytics_org_date')
    op.drop_table('organization_analytics')
    
    op.drop_index('ix_behavior_analytics_anomaly')
    op.drop_index('ix_behavior_analytics_visitor_date')
    op.drop_table('behavior_analytics')
