"""add patient shares

Revision ID: 20260323_000005
Revises: 20260323_000004
Create Date: 2026-03-23 18:40:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260323_000005"
down_revision: Union[str, Sequence[str], None] = "20260323_000004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "patient_shares",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("patient_id", sa.Integer(), nullable=False),
        sa.Column("viewer_user_id", sa.Integer(), nullable=False),
        sa.Column("role", sa.String(length=32), nullable=False, server_default="read_only"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["patient_id"], ["patients.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["viewer_user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_patient_shares_id"), "patient_shares", ["id"], unique=False)
    op.create_index(op.f("ix_patient_shares_patient_id"), "patient_shares", ["patient_id"], unique=False)
    op.create_index(op.f("ix_patient_shares_viewer_user_id"), "patient_shares", ["viewer_user_id"], unique=False)
    op.create_unique_constraint(
        "uq_patient_shares_patient_viewer",
        "patient_shares",
        ["patient_id", "viewer_user_id"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_patient_shares_patient_viewer", "patient_shares", type_="unique")
    op.drop_index(op.f("ix_patient_shares_viewer_user_id"), table_name="patient_shares")
    op.drop_index(op.f("ix_patient_shares_patient_id"), table_name="patient_shares")
    op.drop_index(op.f("ix_patient_shares_id"), table_name="patient_shares")
    op.drop_table("patient_shares")
