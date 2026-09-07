"""add matrix notification settings to users

Revision ID: 20260323_000010
Revises: 20260323_000009
Create Date: 2026-03-23 23:30:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260323_000010"
down_revision: Union[str, Sequence[str], None] = "20260323_000009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("users", sa.Column("matrix_id", sa.String(length=255), nullable=True))
    op.add_column("users", sa.Column("matrix_notifications_enabled", sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade() -> None:
    op.drop_column("users", "matrix_notifications_enabled")
    op.drop_column("users", "matrix_id")
