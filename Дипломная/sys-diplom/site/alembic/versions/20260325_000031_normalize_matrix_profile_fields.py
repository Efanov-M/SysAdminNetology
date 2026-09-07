"""normalize matrix profile fields

Revision ID: 20260325_000031
Revises: 20260325_000030
Create Date: 2026-03-25 12:50:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "20260325_000031"
down_revision = "20260325_000030"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        sa.text(
            """
            UPDATE users
            SET matrix_user_id = matrix_id
            WHERE (matrix_user_id IS NULL OR trim(matrix_user_id) = '')
              AND matrix_id IS NOT NULL
              AND trim(matrix_id) <> ''
            """
        )
    )
    op.execute(
        sa.text(
            """
            UPDATE users
            SET matrix_id = matrix_user_id
            WHERE (matrix_id IS NULL OR trim(matrix_id) = '')
              AND matrix_user_id IS NOT NULL
              AND trim(matrix_user_id) <> ''
            """
        )
    )
    op.execute(
        sa.text(
            """
            UPDATE matrix_profiles
            SET matrix_user_id = users.matrix_user_id
            FROM users
            WHERE matrix_profiles.user_id = users.id
              AND (matrix_profiles.matrix_user_id IS NULL OR trim(matrix_profiles.matrix_user_id) = '')
              AND users.matrix_user_id IS NOT NULL
              AND trim(users.matrix_user_id) <> ''
            """
        )
    )
    op.execute(
        sa.text(
            """
            UPDATE matrix_profiles
            SET is_linked = connected
            WHERE is_linked IS FALSE AND connected IS TRUE
            """
        )
    )
    op.execute(
        sa.text(
            """
            UPDATE matrix_profiles
            SET connected = is_linked
            WHERE connected IS FALSE AND is_linked IS TRUE
            """
        )
    )


def downgrade() -> None:
    # Data normalization only; no reversible schema change.
    pass
