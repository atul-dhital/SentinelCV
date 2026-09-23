"""Add infrared and multi-spectral recognition tables.

Revision ID: 009
Revises: 008
Create Date: 2026-04-02 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '009'
down_revision = '008'
branch_labels = None
depends_on = None


def binary_type():
    return postgresql.BYTEA().with_variant(sa.LargeBinary(), "sqlite")


def upgrade():
    """Add multi-spectral and infrared tables."""
    # Infrared face detection table
    op.create_table(
        'infrared_face_data',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False, primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column('visitor_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('detection_log_id', postgresql.UUID(as_uuid=True), nullable=False),
        
        # Infrared metrics
        sa.Column('forehead_temperature_c', sa.Float(), nullable=True),
        sa.Column('cheek_temperature_c', sa.Float(), nullable=True),
        sa.Column('nose_temperature_c', sa.Float(), nullable=True),
        sa.Column('face_avg_temperature_c', sa.Float(), nullable=True),
        sa.Column('ambient_temperature_c', sa.Float(), nullable=True),
        
        # Thermal pattern (as image)
        sa.Column('thermal_image', binary_type(), nullable=True),         # Thermal image data
        sa.Column('thermal_masks', binary_type(), nullable=True),         # Detected thermal anomalies
        
        # Thermal signature embedding
        sa.Column('thermal_embedding', binary_type(), nullable=True),     # 128-d thermal signature
        sa.Column('thermal_embedding_confidence', sa.Float(), default=0.0),
        
        # Thermal-based liveness detection
        sa.Column('blood_flow_detected', sa.Boolean(), default=False),
        sa.Column('blood_flow_confidence', sa.Float(), nullable=True),
        sa.Column('thermal_liveness_score', sa.Float(), nullable=True),        # 0-1 liveness score
        
        sa.Column('created_at', sa.DateTime(), default=sa.func.now()),
        
        sa.ForeignKeyConstraint(['visitor_id'], ['visitors.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['detection_log_id'], ['detection_logs.id'], ondelete='CASCADE'),
    )
    op.create_index('ix_infrared_face_data_visitor_id', 'infrared_face_data', ['visitor_id'])
    op.create_index('ix_infrared_face_data_thermal_liveness', 'infrared_face_data', ['thermal_liveness_score'])
    
    # Multi-spectral face detection table
    op.create_table(
        'multispectral_face_data',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False, primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column('visitor_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('detection_log_id', postgresql.UUID(as_uuid=True), nullable=False),
        
        # Multi-spectral images
        sa.Column('visible_spectrum_image', binary_type(), nullable=True),
        sa.Column('near_infrared_image', binary_type(), nullable=True),   # 700-1000nm
        sa.Column('short_wavelength_image', binary_type(), nullable=True), # 1000-2500nm
        sa.Column('thermal_image', binary_type(), nullable=True),         # 8000-14000nm
        
        # Multi-spectral embeddings
        sa.Column('ms_embedding', binary_type(), nullable=True),          # Fused 512-d embedding
        sa.Column('ms_embedding_confidence', sa.Float(), default=0.0),
        
        # Liveness detection from multiple spectra
        sa.Column('liveness_by_blood_flow', sa.Float(), nullable=True),
        sa.Column('liveness_by_reflection', sa.Float(), nullable=True),
        sa.Column('liveness_by_texture', sa.Float(), nullable=True),
        sa.Column('combined_ms_liveness_score', sa.Float(), nullable=True),
        
        # Spoofing detection
        sa.Column('spoofing_probability', sa.Float(), nullable=True),
        sa.Column('attack_type', sa.String(50), nullable=True),                # print, mask, replay, etc
        
        sa.Column('created_at', sa.DateTime(), default=sa.func.now()),
        
        sa.ForeignKeyConstraint(['visitor_id'], ['visitors.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['detection_log_id'], ['detection_logs.id'], ondelete='CASCADE'),
    )
    op.create_index('ix_multispectral_face_data_visitor_id', 'multispectral_face_data', ['visitor_id'])
    op.create_index('ix_multispectral_face_data_ms_liveness', 'multispectral_face_data', ['combined_ms_liveness_score'])


def downgrade():
    """Remove multi-spectral and infrared tables."""
    op.drop_index('ix_multispectral_face_data_ms_liveness')
    op.drop_index('ix_multispectral_face_data_visitor_id')
    op.drop_table('multispectral_face_data')
    
    op.drop_index('ix_infrared_face_data_thermal_liveness')
    op.drop_index('ix_infrared_face_data_visitor_id')
    op.drop_table('infrared_face_data')
