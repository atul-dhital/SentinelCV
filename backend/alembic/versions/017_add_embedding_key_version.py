"""Add embedding_key_version to face_data for crypto rotation.

Revision ID: 017
Revises: 016
Create Date: 2026-04-26 00:00:00.000000

Tracks which key version was used to wrap the embedding so we can rotate
the embedding-encryption key without re-wrapping every row eagerly.

Existing rows have NULL ``embedding_key_version`` and are treated as
legacy ciphertext (decrypted with the old SHA-256(SECRET_KEY) key) until
they are next updated, at which point the application re-wraps them
with the current key.
"""

from alembic import op
import sqlalchemy as sa


revision = "017"
down_revision = "016"
branch_labels = None
depends_on = None


def _has_column(table_name: str, column_name: str) -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return column_name in {column["name"] for column in inspector.get_columns(table_name)}


def upgrade() -> None:
    if not _has_column("face_data", "embedding_key_version"):
        op.add_column(
            "face_data",
            sa.Column("embedding_key_version", sa.String(length=16), nullable=True),
        )


def downgrade() -> None:
    if _has_column("face_data", "embedding_key_version"):
        op.drop_column("face_data", "embedding_key_version")
