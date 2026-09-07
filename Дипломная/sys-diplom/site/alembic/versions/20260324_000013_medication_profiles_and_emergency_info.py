"""medication profiles and emergency info

Revision ID: 20260324_000013
Revises: 20260324_000012
Create Date: 2026-03-24 16:30:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "20260324_000013"
down_revision = "20260324_000012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("medications", sa.Column("instructions", sa.Text(), nullable=True))
    op.add_column("medications", sa.Column("start_date", sa.Date(), nullable=True))
    op.add_column("medications", sa.Column("end_date", sa.Date(), nullable=True))
    op.add_column("medications", sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")))
    op.create_index("ix_medications_is_active", "medications", ["is_active"])

    op.create_table(
        "emergency_info",
        sa.Column("patient_id", sa.Integer(), sa.ForeignKey("patients.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("blood_type", sa.String(length=32), nullable=True),
        sa.Column("allergies", sa.Text(), nullable=True),
        sa.Column("diagnoses", sa.Text(), nullable=True),
        sa.Column("emergency_contacts", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("emergency_info")
    op.drop_index("ix_medications_is_active", table_name="medications")
    op.drop_column("medications", "is_active")
    op.drop_column("medications", "end_date")
    op.drop_column("medications", "start_date")
    op.drop_column("medications", "instructions")
