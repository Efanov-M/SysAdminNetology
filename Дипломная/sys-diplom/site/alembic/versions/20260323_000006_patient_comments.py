"""add patient comments

Revision ID: 20260323_000006
Revises: 20260323_000005
Create Date: 2026-03-23 19:35:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260323_000006"
down_revision: Union[str, Sequence[str], None] = "20260323_000005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "patient_comments",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("patient_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["patient_id"], ["patients.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_patient_comments_id"), "patient_comments", ["id"], unique=False)
    op.create_index(op.f("ix_patient_comments_patient_id"), "patient_comments", ["patient_id"], unique=False)
    op.create_index(op.f("ix_patient_comments_user_id"), "patient_comments", ["user_id"], unique=False)
    op.create_index(op.f("ix_patient_comments_created_at"), "patient_comments", ["created_at"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_patient_comments_created_at"), table_name="patient_comments")
    op.drop_index(op.f("ix_patient_comments_user_id"), table_name="patient_comments")
    op.drop_index(op.f("ix_patient_comments_patient_id"), table_name="patient_comments")
    op.drop_index(op.f("ix_patient_comments_id"), table_name="patient_comments")
    op.drop_table("patient_comments")
