"""Add multimodal learning tables (US-FUT-001).

Revision ID: 003
Revises: 002
Create Date: 2026-04-02 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers
revision = '003'
down_revision = '002_add_gdpr_tables'
branch_labels = None
depends_on = None


def json_type():
    return postgresql.JSONB().with_variant(sa.JSON(), "sqlite")


def upgrade():
    """Add multimodal embedding tables."""
    # Multimodal embeddings table
    op.create_table(
        'multimodal_embeddings',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False, primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column('visitor_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('detection_log_id', postgresql.UUID(as_uuid=True), nullable=True),
        
        # Embeddings
        sa.Column('face_embedding', json_type(), nullable=True),  # 512-d vector
        sa.Column('audio_embedding', json_type(), nullable=True),  # 128-d vector
        sa.Column('text_embedding', json_type(), nullable=True),   # 256-d vector
        sa.Column('sensor_data', json_type(), nullable=True),      # temperature, humidity, etc
        sa.Column('fusion_score', sa.Float(), default=0.0),              # multimodal confidence
        
        # Metadata
        sa.Column('embedding_model_version', sa.String(50), default='1.0'),
        sa.Column('audio_present', sa.Boolean(), default=False),
        sa.Column('text_present', sa.Boolean(), default=False),
        sa.Column('created_at', sa.DateTime(), default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), onupdate=sa.func.now()),
        
        sa.ForeignKeyConstraint(['visitor_id'], ['visitors.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['detection_log_id'], ['detection_logs.id'], ondelete='SET NULL'),
    )
    
    op.create_index('ix_multimodal_embeddings_visitor_id', 'multimodal_embeddings', ['visitor_id'])
    op.create_index('ix_multimodal_embeddings_fusion_score', 'multimodal_embeddings', ['fusion_score'])
    op.create_index('ix_multimodal_embeddings_created_at', 'multimodal_embeddings', ['created_at'])
    
    # Audio features table
    op.create_table(
        'audio_features',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False, primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column('visitor_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('detection_log_id', postgresql.UUID(as_uuid=True), nullable=True),
        
        # Audio features
        sa.Column('mfcc_features', json_type(), nullable=True),      # Mel-frequency cepstral coefficients
        sa.Column('spectral_energy', sa.Float(), nullable=True),
        sa.Column('zero_crossing_rate', sa.Float(), nullable=True),
        sa.Column('voice_confidence', sa.Float(), default=0.0),
        sa.Column('pitch_frequency', sa.Float(), nullable=True),
        sa.Column('audio_duration_ms', sa.Integer(), nullable=True),
        
        sa.Column('created_at', sa.DateTime(), default=sa.func.now()),
        
        sa.ForeignKeyConstraint(['visitor_id'], ['visitors.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['detection_log_id'], ['detection_logs.id'], ondelete='SET NULL'),
    )
    
    op.create_index('ix_audio_features_visitor_id', 'audio_features', ['visitor_id'])
    op.create_index('ix_audio_features_voice_confidence', 'audio_features', ['voice_confidence'])
    
    # Text bio features table
    op.create_table(
        'text_bio_features',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False, primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column('visitor_id', postgresql.UUID(as_uuid=True), nullable=False),
        
        # Text/bio data
        sa.Column('name', sa.String(255), nullable=True),
        sa.Column('department', sa.String(255), nullable=True),
        sa.Column('position', sa.String(255), nullable=True),
        sa.Column('phone_number', sa.String(20), nullable=True),
        sa.Column('email', sa.String(255), nullable=True),
        sa.Column('notes', sa.Text(), nullable=True),
        
        # Computed embeddings
        sa.Column('text_embedding', json_type(), nullable=True),   # 256-d from BERT
        sa.Column('embedding_confidence', sa.Float(), default=0.0),
        
        sa.Column('created_at', sa.DateTime(), default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), onupdate=sa.func.now()),
        
        sa.ForeignKeyConstraint(['visitor_id'], ['visitors.id'], ondelete='CASCADE'),
    )
    
    op.create_index('ix_text_bio_features_visitor_id', 'text_bio_features', ['visitor_id'])
    op.create_index('ix_text_bio_features_email', 'text_bio_features', ['email'])
    
    # Multimodal fusion config table
    op.create_table(
        'multimodal_fusion_configs',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False, primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column('organization_id', postgresql.UUID(as_uuid=True), nullable=False),
        
        # Fusion weights
        sa.Column('face_weight', sa.Float(), default=0.6),      # Face embeddings weight
        sa.Column('audio_weight', sa.Float(), default=0.2),     # Audio embeddings weight
        sa.Column('text_weight', sa.Float(), default=0.1),      # Text embeddings weight
        sa.Column('sensor_weight', sa.Float(), default=0.1),    # Sensor data weight
        
        # Fusion strategy
        sa.Column('fusion_strategy', sa.String(50), default='weighted_mean'),  # weighted_mean, attention, mlp
        sa.Column('fusion_threshold', sa.Float(), default=0.7),  # Confidence threshold
        
        # Modality requirements
        sa.Column('require_face', sa.Boolean(), default=True),
        sa.Column('require_audio', sa.Boolean(), default=False),
        sa.Column('require_text', sa.Boolean(), default=False),
        
        sa.Column('created_at', sa.DateTime(), default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), onupdate=sa.func.now()),
        
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
    )
    
    op.create_index('ix_multimodal_fusion_configs_org_id', 'multimodal_fusion_configs', ['organization_id'])


def downgrade():
    """Remove multimodal tables."""
    op.drop_index('ix_multimodal_fusion_configs_org_id')
    op.drop_table('multimodal_fusion_configs')
    
    op.drop_index('ix_text_bio_features_email')
    op.drop_index('ix_text_bio_features_visitor_id')
    op.drop_table('text_bio_features')
    
    op.drop_index('ix_audio_features_voice_confidence')
    op.drop_index('ix_audio_features_visitor_id')
    op.drop_table('audio_features')
    
    op.drop_index('ix_multimodal_embeddings_created_at')
    op.drop_index('ix_multimodal_embeddings_fusion_score')
    op.drop_index('ix_multimodal_embeddings_visitor_id')
    op.drop_table('multimodal_embeddings')
