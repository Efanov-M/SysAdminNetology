"""add matrix link tokens

Revision ID: 20260324_000017
Revises: 20260324_000016
Create Date: 2026-03-24 09:35:00
"""

from alembic import op
import sqlalchemy as sa


revision = "20260324_000017"
down_revision = "20260324_000016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "matrix_link_tokens",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("token", sa.String(length=32), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("used", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token"),
    )
    op.create_index("ix_matrix_link_tokens_user_id", "matrix_link_tokens", ["user_id"], unique=False)
    op.create_index("ix_matrix_link_tokens_token", "matrix_link_tokens", ["token"], unique=False)
    op.create_index("ix_matrix_link_tokens_expires_at", "matrix_link_tokens", ["expires_at"], unique=False)
    op.create_index("ix_matrix_link_tokens_used", "matrix_link_tokens", ["used"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_matrix_link_tokens_used", table_name="matrix_link_tokens")
    op.drop_index("ix_matrix_link_tokens_expires_at", table_name="matrix_link_tokens")
    op.drop_index("ix_matrix_link_tokens_token", table_name="matrix_link_tokens")
    op.drop_index("ix_matrix_link_tokens_user_id", table_name="matrix_link_tokens")
    op.drop_table("matrix_link_tokens")
