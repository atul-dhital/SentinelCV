"""Add edge deployment and ONNX model tables.

Revision ID: 011
Revises: 010
Create Date: 2026-04-02 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from db.base import Base
from models import models  # noqa: F401

revision = '011'
down_revision = '010'
branch_labels = None
depends_on = None


def binary_type():
    return postgresql.BYTEA().with_variant(sa.LargeBinary(), "sqlite")

EDGE_RUNTIME_TABLES = {
    "edge_devices",
    "edge_device_events",
}


def _sorted_metadata_tables(names: set[str]) -> list[sa.Table]:
    return [table for table in Base.metadata.sorted_tables if table.name in names]


def upgrade():
    """Add edge deployment tables."""
    Base.metadata.create_all(
        bind=op.get_bind(),
        tables=_sorted_metadata_tables(EDGE_RUNTIME_TABLES),
        checkfirst=True,
    )

    # ONNX model registry table
    op.create_table(
        'onnx_model_registry',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False, primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column('organization_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('model_version_id', postgresql.UUID(as_uuid=True), nullable=False),
        
        # ONNX specific info
        sa.Column('onnx_version', sa.String(20), nullable=False),               # ONNX opset version
        sa.Column('onnx_model_bytes', binary_type(), nullable=True),       # Serialized ONNX model
        sa.Column('input_shape', sa.JSON(), nullable=True),                    # e.g., [1, 3, 224, 224]
        sa.Column('output_shape', sa.JSON(), nullable=True),
        
        # Quantization info
        sa.Column('is_quantized', sa.Boolean(), default=False),
        sa.Column('quantization_type', sa.String(50), nullable=True),          # int8, float16, etc
        sa.Column('quantized_model_size_mb', sa.Float(), nullable=True),
        
        # Optimization metrics
        sa.Column('inference_latency_cpu_ms', sa.Float(), nullable=True),
        sa.Column('inference_latency_gpu_ms', sa.Float(), nullable=True),
        sa.Column('inference_latency_npu_ms', sa.Float(), nullable=True),       # Neural Processing Unit
        
        # Validation
        sa.Column('accuracy_maintained_percent', sa.Float(), nullable=True),    # Accuracy after conversion
        sa.Column('is_validated', sa.Boolean(), default=False),
        
        sa.Column('created_at', sa.DateTime(), default=sa.func.now()),
        
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id']),
        sa.ForeignKeyConstraint(['model_version_id'], ['model_versions.id']),
    )
    op.create_index('ix_onnx_models_org_quantized', 'onnx_model_registry', 
                    ['organization_id', 'is_quantized'])
    
    # Edge device deployment table
    op.create_table(
        'edge_device_deployments',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False, primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column('edge_device_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('onnx_model_id', postgresql.UUID(as_uuid=True), nullable=False),
        
        # Deployment info
        sa.Column('deployment_time', sa.DateTime(), default=sa.func.now()),
        sa.Column('is_active', sa.Boolean(), default=False),
        
        # Device performance
        sa.Column('cpu_memory_usage_mb', sa.Float(), nullable=True),
        sa.Column('gpu_memory_usage_mb', sa.Float(), nullable=True),
        sa.Column('avg_inference_latency_ms', sa.Float(), nullable=True),
        sa.Column('throughput_fps', sa.Float(), nullable=True),
        
        # Health metrics
        sa.Column('last_inference_time', sa.DateTime(), nullable=True),
        sa.Column('total_inferences', sa.Integer(), default=0),
        sa.Column('failed_inferences', sa.Integer(), default=0),
        sa.Column('error_rate_percent', sa.Float(), default=0.0),
        
        sa.Column('updated_at', sa.DateTime(), onupdate=sa.func.now()),
        
        sa.ForeignKeyConstraint(['edge_device_id'], ['edge_devices.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['onnx_model_id'], ['onnx_model_registry.id']),
    )
    op.create_index('ix_edge_deployments_device_active', 'edge_device_deployments', 
                    ['edge_device_id', 'is_active'])


def downgrade():
    """Remove edge deployment tables."""
    op.drop_index('ix_edge_deployments_device_active')
    op.drop_table('edge_device_deployments')
    
    op.drop_index('ix_onnx_models_org_quantized')
    op.drop_table('onnx_model_registry')

    bind = op.get_bind()
    for table in reversed(_sorted_metadata_tables(EDGE_RUNTIME_TABLES)):
        table.drop(bind=bind, checkfirst=True)
