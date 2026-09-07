"""add matrix profiles

Revision ID: 20260324_000020
Revises: 20260324_000019
Create Date: 2026-03-24 07:45:00
"""

from alembic import op
import sqlalchemy as sa


revision = "20260324_000020"
down_revision = "20260324_000019"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "matrix_profiles",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("matrix_user_id", sa.String(length=255), nullable=True),
        sa.Column("matrix_room_id", sa.String(length=255), nullable=True),
        sa.Column("link_code", sa.String(length=32), nullable=True),
        sa.Column("connected", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    op.create_index("ix_matrix_profiles_id", "matrix_profiles", ["id"])
    op.create_index("ix_matrix_profiles_user_id", "matrix_profiles", ["user_id"], unique=True)
    op.create_index("ix_matrix_profiles_matrix_user_id", "matrix_profiles", ["matrix_user_id"])
    op.create_index("ix_matrix_profiles_link_code", "matrix_profiles", ["link_code"])
    op.create_index("ix_matrix_profiles_connected", "matrix_profiles", ["connected"])


def downgrade() -> None:
    op.drop_index("ix_matrix_profiles_connected", table_name="matrix_profiles")
    op.drop_index("ix_matrix_profiles_link_code", table_name="matrix_profiles")
    op.drop_index("ix_matrix_profiles_matrix_user_id", table_name="matrix_profiles")
    op.drop_index("ix_matrix_profiles_user_id", table_name="matrix_profiles")
    op.drop_index("ix_matrix_profiles_id", table_name="matrix_profiles")
    op.drop_table("matrix_profiles")
