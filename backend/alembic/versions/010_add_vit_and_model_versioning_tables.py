"""Add vision transformer and advanced model tables.

Revision ID: 010
Revises: 009
Create Date: 2026-04-02 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from db.base import Base
from models import models  # noqa: F401

revision = '010'
down_revision = '009'
branch_labels = None
depends_on = None


def binary_type():
    return postgresql.BYTEA().with_variant(sa.LargeBinary(), "sqlite")

MODEL_VERSIONING_TABLES = {
    "model_versions",
    "ab_test_experiments",
    "ab_test_results",
}


def _sorted_metadata_tables(names: set[str]) -> list[sa.Table]:
    return [table for table in Base.metadata.sorted_tables if table.name in names]


def upgrade():
    """Add vision transformer and advanced model tables."""
    # Vision transformer embeddings table
    op.create_table(
        'vision_transformer_embeddings',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False, primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column('visitor_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('detection_log_id', postgresql.UUID(as_uuid=True), nullable=False),
        
        # ViT specific embeddings
        sa.Column('patch_embeddings', binary_type(), nullable=True),      # 196x768 patch embeddings
        sa.Column('cls_token_embedding', binary_type(), nullable=True),    # 768-d CLS token (final representation)
        sa.Column('attention_maps', binary_type(), nullable=True),         # Visual attention heatmaps
        sa.Column('layer_wise_embeddings', binary_type(), nullable=True),  # Embeddings from each ViT layer
        
        # ViT embeddings (multi-scale)
        sa.Column('vit_embedding_layer0', binary_type(), nullable=True),   # Early layers (fine details)
        sa.Column('vit_embedding_layer6', binary_type(), nullable=True),   # Middle layers (semantic)
        sa.Column('vit_embedding_layer12', binary_type(), nullable=True),  # Final layer (identity)
        
        # Confidence and quality
        sa.Column('vit_confidence', sa.Float(), default=0.0),
        sa.Column('attention_alignment_score', sa.Float(), nullable=True),      # Does attention match face region?
        
        sa.Column('created_at', sa.DateTime(), default=sa.func.now()),
        
        sa.ForeignKeyConstraint(['visitor_id'], ['visitors.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['detection_log_id'], ['detection_logs.id'], ondelete='CASCADE'),
    )
    op.create_index('ix_vit_embeddings_visitor_id', 'vision_transformer_embeddings', ['visitor_id'])
    
    Base.metadata.create_all(
        bind=op.get_bind(),
        tables=_sorted_metadata_tables(MODEL_VERSIONING_TABLES),
        checkfirst=True,
    )
    op.create_index('ix_model_versions_org_type_active', 'model_versions',
                    ['organization_id', 'model_type', 'is_active'])


def downgrade():
    """Remove vision transformer and model tables."""
    op.drop_index('ix_model_versions_org_type_active')
    bind = op.get_bind()
    for table in reversed(_sorted_metadata_tables(MODEL_VERSIONING_TABLES)):
        table.drop(bind=bind, checkfirst=True)
    
    op.drop_index('ix_vit_embeddings_visitor_id')
    op.drop_table('vision_transformer_embeddings')
