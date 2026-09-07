"""add document type categories

Revision ID: 20260324_000023
Revises: 20260324_000022
Create Date: 2026-03-24 18:15:00
"""

from alembic import op
import sqlalchemy as sa


revision = "20260324_000023"
down_revision = "20260324_000022"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("documents", sa.Column("document_type", sa.String(length=20), nullable=False, server_default="lab"))
    op.create_index("ix_documents_document_type", "documents", ["document_type"])


def downgrade() -> None:
    op.drop_index("ix_documents_document_type", table_name="documents")
    op.drop_column("documents", "document_type")
