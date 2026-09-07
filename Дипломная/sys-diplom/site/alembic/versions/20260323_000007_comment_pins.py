"""add pinned flag to patient comments

Revision ID: 20260323_000007
Revises: 20260323_000006
Create Date: 2026-03-23 20:30:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260323_000007"
down_revision: Union[str, Sequence[str], None] = "20260323_000006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "patient_comments",
        sa.Column("pinned", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    op.drop_column("patient_comments", "pinned")
