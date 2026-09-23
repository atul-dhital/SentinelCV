"""Add cross-camera re-identification tables.

Revision ID: 007
Revises: 006
Create Date: 2026-04-02 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '007'
down_revision = '006'
branch_labels = None
depends_on = None


def upgrade():
    """Add cross-camera re-identification tables."""
    # Camera transitions table
    op.create_table(
        'camera_transitions',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False, primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column('visitor_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('from_camera_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('to_camera_id', postgresql.UUID(as_uuid=True), nullable=False),
        
        # Transition info
        sa.Column('from_detection_log_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('to_detection_log_id', postgresql.UUID(as_uuid=True), nullable=False),
        
        # Timing and distance
        sa.Column('transition_time_seconds', sa.Float(), nullable=True),
        sa.Column('estimated_distance_meters', sa.Float(), nullable=True),     # 3D distance between cameras
        sa.Column('estimated_speed_mps', sa.Float(), nullable=True),           # meters per second
        
        # Confidence scores
        sa.Column('reid_confidence', sa.Float(), default=0.0),                 # Re-ID matching confidence
        sa.Column('motion_continuity_score', sa.Float(), nullable=True),       # Is motion path realistic?
        sa.Column('is_valid_transition', sa.Boolean(), default=True),          # Passes sanity checks
        
        # Movement summary
        sa.Column('movement_summary', sa.String(255), nullable=True),          # e.g., "North direction"
        
        sa.Column('created_at', sa.DateTime(), default=sa.func.now()),
        
        sa.ForeignKeyConstraint(['visitor_id'], ['visitors.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['from_camera_id'], ['cameras.id']),
        sa.ForeignKeyConstraint(['to_camera_id'], ['cameras.id']),
        sa.ForeignKeyConstraint(['from_detection_log_id'], ['detection_logs.id']),
        sa.ForeignKeyConstraint(['to_detection_log_id'], ['detection_logs.id']),
    )
    op.create_index('ix_camera_transitions_visitor_id', 'camera_transitions', ['visitor_id'])
    op.create_index('ix_camera_transitions_reid_confidence', 'camera_transitions', ['reid_confidence'])
    op.create_index('ix_camera_transitions_created_at', 'camera_transitions', ['created_at'])
    
    # Visitor movement summary table
    op.create_table(
        'visitor_movement_summaries',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False, primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column('visitor_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('organization_id', postgresql.UUID(as_uuid=True), nullable=False),
        
        # Movement info
        sa.Column('cameras_visited', sa.Integer(), default=0),
        sa.Column('total_transitions', sa.Integer(), default=0),
        sa.Column('estimated_total_distance_meters', sa.Float(), nullable=True),
        sa.Column('average_speed_mps', sa.Float(), nullable=True),
        
        # Coverage and patterns
        sa.Column('movement_pattern', sa.String(100), nullable=True),          # 'linear', 'circular', 'erratic', etc
        sa.Column('last_known_location', sa.String(255), nullable=True),
        sa.Column('time_in_facility_minutes', sa.Integer(), nullable=True),
        
        # Temporal data
        sa.Column('entry_time', sa.DateTime(), nullable=True),
        sa.Column('exit_time', sa.DateTime(), nullable=True),
        sa.Column('last_updated', sa.DateTime(), onupdate=sa.func.now()),
        
        sa.ForeignKeyConstraint(['visitor_id'], ['visitors.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id']),
    )
    op.create_index('ix_visitor_movement_summaries_visitor_id', 'visitor_movement_summaries', ['visitor_id'])
    op.create_index('ix_visitor_movement_summaries_last_updated', 'visitor_movement_summaries', ['last_updated'])


def downgrade():
    """Remove cross-camera re-identification tables."""
    op.drop_index('ix_visitor_movement_summaries_last_updated')
    op.drop_index('ix_visitor_movement_summaries_visitor_id')
    op.drop_table('visitor_movement_summaries')
    
    op.drop_index('ix_camera_transitions_created_at')
    op.drop_index('ix_camera_transitions_reid_confidence')
    op.drop_index('ix_camera_transitions_visitor_id')
    op.drop_table('camera_transitions')
