"""add user notification prefs and comment categories

Revision ID: 20260323_000008
Revises: 20260323_000007
Create Date: 2026-03-23 21:10:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260323_000008"
down_revision: Union[str, Sequence[str], None] = "20260323_000007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("users", sa.Column("timezone", sa.String(length=64), nullable=False, server_default="Europe/Moscow"))
    op.add_column("users", sa.Column("quiet_hours_start", sa.Time(), nullable=True))
    op.add_column("users", sa.Column("quiet_hours_end", sa.Time(), nullable=True))
    op.add_column("patient_comments", sa.Column("category", sa.String(length=50), nullable=False, server_default="note"))
    op.create_index(op.f("ix_patient_comments_category"), "patient_comments", ["category"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_patient_comments_category"), table_name="patient_comments")
    op.drop_column("patient_comments", "category")
    op.drop_column("users", "quiet_hours_end")
    op.drop_column("users", "quiet_hours_start")
    op.drop_column("users", "timezone")
