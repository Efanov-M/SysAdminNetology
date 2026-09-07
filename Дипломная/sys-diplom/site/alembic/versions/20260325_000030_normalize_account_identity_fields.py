"""normalize account identity fields

Revision ID: 20260325_000030
Revises: 20260325_000029
Create Date: 2026-03-25 12:40:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "20260325_000030"
down_revision = "20260325_000029"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        sa.text(
            """
            UPDATE users
            SET login = lower(trim(email))
            WHERE (login IS NULL OR trim(login) = '')
              AND email IS NOT NULL
              AND trim(email) <> ''
            """
        )
    )
    op.execute(
        sa.text(
            """
            UPDATE users
            SET email = lower(trim(login))
            WHERE (email IS NULL OR trim(email) = '')
              AND login IS NOT NULL
              AND trim(login) <> ''
            """
        )
    )
    op.execute(
        sa.text(
            """
            UPDATE invites
            SET login = lower(trim(email))
            WHERE (login IS NULL OR trim(login) = '')
              AND email IS NOT NULL
              AND trim(email) <> ''
            """
        )
    )
    op.execute(
        sa.text(
            """
            UPDATE invites
            SET email = lower(trim(login))
            WHERE (email IS NULL OR trim(email) = '')
              AND login IS NOT NULL
              AND trim(login) <> ''
            """
        )
    )


def downgrade() -> None:
    # Data normalization only; no reversible schema change.
    pass
