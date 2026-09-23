"""add HNSW index on detection_logs.embedding_snapshot for face search (G1)

Revision ID: 024
Revises: 023

The live recognition path stores a pgvector embedding on every DetectionLog.
The G1 face-search endpoint (POST /api/v1/search/face) runs an ANN cosine search
over that history; this index keeps it fast at scale. Postgres-only (pgvector).
"""
from alembic import op

revision = "024"
down_revision = "023"
branch_labels = None
depends_on = None

INDEX_NAME = "ix_detection_logs_embedding_hnsw"


def upgrade():
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    op.execute(
        f"CREATE INDEX IF NOT EXISTS {INDEX_NAME} "
        "ON detection_logs USING hnsw (embedding_snapshot vector_cosine_ops)"
    )


def downgrade():
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    op.execute(f"DROP INDEX IF EXISTS {INDEX_NAME}")
