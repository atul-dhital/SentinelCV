"""Add HNSW index for pgvector.

Revision ID: 020
Revises: 019
Create Date: 2026-05-26 14:36:00.000000
"""

from alembic import op
import sqlalchemy as sa

revision = "020"
down_revision = "019"
branch_labels = None
depends_on = None

def upgrade() -> None:
    bind = op.get_bind()
    if bind.engine.name == 'postgresql':
        op.execute(
            "CREATE INDEX IF NOT EXISTS ix_face_data_embedding_hnsw "
            "ON face_data USING hnsw (embedding vector_cosine_ops)"
        )

def downgrade() -> None:
    bind = op.get_bind()
    if bind.engine.name == 'postgresql':
        op.execute("DROP INDEX IF EXISTS ix_face_data_embedding_hnsw")
