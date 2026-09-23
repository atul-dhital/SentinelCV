"""Add 3D face recognition tables (US-FUT-033).

Revision ID: 004
Revises: 003
Create Date: 2026-04-02 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '004'
down_revision = '003'
branch_labels = None
depends_on = None


def json_type():
    return postgresql.JSONB().with_variant(sa.JSON(), "sqlite")


def upgrade():
    """Add 3D face recognition tables."""
    # 3D face data table
    op.create_table(
        'three_d_face_data',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False, primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column('visitor_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('detection_log_id', postgresql.UUID(as_uuid=True), nullable=True),
        
        # 3D data
        sa.Column('depth_map_path', sa.String(512), nullable=True),             # Depth map path
        sa.Column('point_cloud_path', sa.String(512), nullable=True),           # 3D point cloud path
        sa.Column('face_mesh', json_type(), nullable=True),              # Mesh vertices/faces
        sa.Column('texture_map_path', sa.String(512), nullable=True),           # Texture map path
        
        # Calculated 3D metrics
        sa.Column('face_width_mm', sa.Float(), nullable=True),
        sa.Column('face_height_mm', sa.Float(), nullable=True),
        sa.Column('face_depth_mm', sa.Float(), nullable=True),
        sa.Column('forehead_width_mm', sa.Float(), nullable=True),
        sa.Column('nose_height_mm', sa.Float(), nullable=True),
        
        # 3D embedding
        sa.Column('embedding_3d', json_type(), nullable=True),           # 256-d 3D embedding
        sa.Column('embedding_confidence', sa.Float(), default=0.0),
        
        # Quality metrics
        sa.Column('capture_quality_score', sa.Float(), default=0.0),            # 0-1 quality
        sa.Column('mesh_density', sa.Integer(), nullable=True),                 # Number of vertices
        sa.Column('depth_map_resolution', sa.String(20), nullable=True),        # e.g., '640x480'
        
        sa.Column('created_at', sa.DateTime(), default=sa.func.now()),
        
        sa.ForeignKeyConstraint(['visitor_id'], ['visitors.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['detection_log_id'], ['detection_logs.id'], ondelete='SET NULL'),
    )
    op.create_index('ix_3d_face_data_visitor_id', 'three_d_face_data', ['visitor_id'])
    op.create_index('ix_3d_face_data_embedding_confidence', 'three_d_face_data', ['embedding_confidence'])
    
    # 3D face comparison results table
    op.create_table(
        'three_d_face_comparisons',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False, primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column('face_data_1_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('face_data_2_id', postgresql.UUID(as_uuid=True), nullable=False),
        
        # Comparison metrics
        sa.Column('euclidean_distance', sa.Float(), nullable=True),
        sa.Column('cosine_similarity', sa.Float(), nullable=True),
        sa.Column('l2_distance', sa.Float(), nullable=True),
        sa.Column('shape_similarity', sa.Float(), nullable=True),               # Shape matching score
        sa.Column('texture_similarity', sa.Float(), nullable=True),             # Texture matching score
        sa.Column('geometric_liveness_score', sa.Float(), nullable=True),       # 3D liveness detection
        
        # Final match confidence
        sa.Column('match_confidence', sa.Float(), default=0.0),
        sa.Column('is_same_person', sa.Boolean(), default=False),
        
        sa.Column('created_at', sa.DateTime(), default=sa.func.now()),
        
        sa.ForeignKeyConstraint(['face_data_1_id'], ['three_d_face_data.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['face_data_2_id'], ['three_d_face_data.id'], ondelete='CASCADE'),
    )
    op.create_index('ix_3d_comparisons_confidence', 'three_d_face_comparisons', ['match_confidence'])


def downgrade():
    """Remove 3D face tables."""
    op.drop_index('ix_3d_comparisons_confidence')
    op.drop_table('three_d_face_comparisons')
    
    op.drop_index('ix_3d_face_data_embedding_confidence')
    op.drop_index('ix_3d_face_data_visitor_id')
    op.drop_table('three_d_face_data')
