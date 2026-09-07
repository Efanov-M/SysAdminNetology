"""add doctor type to report documents

Revision ID: 20260324_000024
Revises: 20260324_000023
Create Date: 2026-03-24 18:40:00
"""

from alembic import op
import sqlalchemy as sa


revision = "20260324_000024"
down_revision = "20260324_000023"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("documents", sa.Column("doctor_type", sa.String(length=30), nullable=True))
    op.create_index("ix_documents_doctor_type", "documents", ["doctor_type"])


def downgrade() -> None:
    op.drop_index("ix_documents_doctor_type", table_name="documents")
    op.drop_column("documents", "doctor_type")
