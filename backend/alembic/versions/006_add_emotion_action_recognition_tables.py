"""Add emotion and action recognition tables (US-FUT-035, US-FUT-036).

Revision ID: 006
Revises: 005
Create Date: 2026-04-02 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '006'
down_revision = '005'
branch_labels = None
depends_on = None


def binary_type():
    return postgresql.BYTEA().with_variant(sa.LargeBinary(), "sqlite")


def upgrade():
    """Add emotion and action recognition tables."""
    # Emotion detection results table
    op.create_table(
        'emotion_detections',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False, primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column('visitor_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('detection_log_id', postgresql.UUID(as_uuid=True), nullable=False),
        
        # Emotion scores (0-1)
        sa.Column('emotion_neutral', sa.Float(), default=0.0),
        sa.Column('emotion_happy', sa.Float(), default=0.0),
        sa.Column('emotion_sad', sa.Float(), default=0.0),
        sa.Column('emotion_angry', sa.Float(), default=0.0),
        sa.Column('emotion_fearful', sa.Float(), default=0.0),
        sa.Column('emotion_disgusted', sa.Float(), default=0.0),
        sa.Column('emotion_surprised', sa.Float(), default=0.0),
        
        # Primary emotion
        sa.Column('primary_emotion', sa.String(50), nullable=True),
        sa.Column('emotion_confidence', sa.Float(), default=0.0),
        
        # Valence and arousal
        sa.Column('valence_score', sa.Float(), nullable=True),      # Positive to negative (-1 to 1)
        sa.Column('arousal_score', sa.Float(), nullable=True),      # Low to high energy (0 to 1)
        
        sa.Column('created_at', sa.DateTime(), default=sa.func.now()),
        
        sa.ForeignKeyConstraint(['visitor_id'], ['visitors.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['detection_log_id'], ['detection_logs.id'], ondelete='CASCADE'),
    )
    op.create_index('ix_emotion_detections_visitor_id', 'emotion_detections', ['visitor_id'])
    op.create_index('ix_emotion_detections_primary_emotion', 'emotion_detections', ['primary_emotion'])
    
    # Action/gesture recognition results table
    op.create_table(
        'action_detections',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False, primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column('visitor_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('detection_log_id', postgresql.UUID(as_uuid=True), nullable=False),
        
        # Detected actions/gestures
        sa.Column('action_name', sa.String(100), nullable=False),               # e.g., 'pointing', 'waving'
        sa.Column('action_confidence', sa.Float(), default=0.0),
        sa.Column('action_duration_ms', sa.Integer(), nullable=True),
        
        # Body pose keypoints
        sa.Column('pose_keypoints', sa.JSON(), nullable=True),                  # Skeleton joints
        sa.Column('hand_keypoints', sa.JSON(), nullable=True),                  # Hand landmarks
        
        # Motion vectors
        sa.Column('motion_vector', binary_type(), nullable=True),          # Optical flow
        sa.Column('motion_magnitude', sa.Float(), nullable=True),               # Movement intensity
        
        # Detected interactions
        sa.Column('interacting_with_camera', sa.Boolean(), default=False),
        sa.Column('eye_contact_score', sa.Float(), nullable=True),              # 0-1 if looking at camera
        sa.Column('gesture_type', sa.String(50), nullable=True),                # pointing, waving, thumbs_up, etc
        
        sa.Column('created_at', sa.DateTime(), default=sa.func.now()),
        
        sa.ForeignKeyConstraint(['visitor_id'], ['visitors.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['detection_log_id'], ['detection_logs.id'], ondelete='CASCADE'),
    )
    op.create_index('ix_action_detections_visitor_id', 'action_detections', ['visitor_id'])
    op.create_index('ix_action_detections_action_name', 'action_detections', ['action_name'])


def downgrade():
    """Remove emotion and action tables."""
    op.drop_index('ix_action_detections_action_name')
    op.drop_index('ix_action_detections_visitor_id')
    op.drop_table('action_detections')
    
    op.drop_index('ix_emotion_detections_primary_emotion')
    op.drop_index('ix_emotion_detections_visitor_id')
    op.drop_table('emotion_detections')
