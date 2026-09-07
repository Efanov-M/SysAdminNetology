"""drug cache local search

Revision ID: 20260324_000014
Revises: 20260324_000013
Create Date: 2026-03-24 18:10:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "20260324_000014"
down_revision = "20260324_000013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "drug_cache",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(length=255), nullable=False, unique=True),
        sa.Column("raw_name", sa.String(length=255), nullable=False),
        sa.Column("dosage_forms", sa.Text(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("instructions", sa.Text(), nullable=True),
        sa.Column("source", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_drug_cache_id", "drug_cache", ["id"])
    op.create_index("ix_drug_cache_name", "drug_cache", ["name"], unique=True)
    op.create_index("ix_drug_cache_raw_name", "drug_cache", ["raw_name"])
    op.create_index("ix_drug_cache_created_at", "drug_cache", ["created_at"])
    op.create_index("ix_drug_cache_updated_at", "drug_cache", ["updated_at"])


def downgrade() -> None:
    op.drop_index("ix_drug_cache_updated_at", table_name="drug_cache")
    op.drop_index("ix_drug_cache_created_at", table_name="drug_cache")
    op.drop_index("ix_drug_cache_raw_name", table_name="drug_cache")
    op.drop_index("ix_drug_cache_name", table_name="drug_cache")
    op.drop_index("ix_drug_cache_id", table_name="drug_cache")
    op.drop_table("drug_cache")
