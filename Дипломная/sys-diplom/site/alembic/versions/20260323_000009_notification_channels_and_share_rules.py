"""add notification channels and share reminder rules

Revision ID: 20260323_000009
Revises: 20260323_000008
Create Date: 2026-03-23 22:00:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260323_000009"
down_revision: Union[str, Sequence[str], None] = "20260323_000008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("users", sa.Column("notification_channels", sa.JSON(), nullable=False, server_default='["log"]'))
    op.add_column("patient_shares", sa.Column("receive_reminders", sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade() -> None:
    op.drop_column("patient_shares", "receive_reminders")
    op.drop_column("users", "notification_channels")
