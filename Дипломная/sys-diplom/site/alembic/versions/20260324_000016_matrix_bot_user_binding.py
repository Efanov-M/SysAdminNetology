"""add matrix bot user binding

Revision ID: 20260324_000016
Revises: 20260324_000015
Create Date: 2026-03-24 08:15:00
"""

from alembic import op
import sqlalchemy as sa


revision = "20260324_000016"
down_revision = "20260324_000015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("matrix_user_id", sa.String(length=255), nullable=True))
    op.create_index("ix_users_matrix_user_id", "users", ["matrix_user_id"], unique=False)
    op.execute(sa.text("UPDATE users SET matrix_user_id = matrix_id WHERE matrix_user_id IS NULL AND matrix_id IS NOT NULL"))


def downgrade() -> None:
    op.drop_index("ix_users_matrix_user_id", table_name="users")
    op.drop_column("users", "matrix_user_id")
