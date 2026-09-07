"""add document processing architecture fields

Revision ID: 20260324_000025
Revises: 20260324_000024
Create Date: 2026-03-24 20:05:00
"""

from alembic import op
import sqlalchemy as sa


revision = "20260324_000025"
down_revision = "20260324_000024"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("documents", sa.Column("original_file_path", sa.String(length=500), nullable=True))
    op.add_column("documents", sa.Column("processed_file_path", sa.String(length=500), nullable=True))
    op.add_column("documents", sa.Column("extracted_text", sa.Text(), nullable=True))
    op.add_column("documents", sa.Column("processing_status", sa.String(length=20), nullable=False, server_default="uploaded"))
    op.create_index("ix_documents_processing_status", "documents", ["processing_status"])

    op.execute("UPDATE documents SET original_file_path = file_path WHERE original_file_path IS NULL")
    op.alter_column("documents", "original_file_path", existing_type=sa.String(length=500), nullable=False)


def downgrade() -> None:
    op.drop_index("ix_documents_processing_status", table_name="documents")
    op.drop_column("documents", "processing_status")
    op.drop_column("documents", "extracted_text")
    op.drop_column("documents", "processed_file_path")
    op.drop_column("documents", "original_file_path")
