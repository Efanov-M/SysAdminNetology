"""add active patient for matrix profile

Revision ID: 20260325_000032
Revises: 20260325_000031
Create Date: 2026-03-25 15:40:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "20260325_000032"
down_revision = "20260325_000031"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("matrix_profiles") as batch_op:
        batch_op.add_column(sa.Column("active_patient_id", sa.Integer(), nullable=True))
        batch_op.create_index("ix_matrix_profiles_active_patient_id", ["active_patient_id"], unique=False)
        batch_op.create_foreign_key(
            "fk_matrix_profiles_active_patient_id_patients",
            "patients",
            ["active_patient_id"],
            ["id"],
            ondelete="SET NULL",
        )


def downgrade() -> None:
    with op.batch_alter_table("matrix_profiles") as batch_op:
        batch_op.drop_constraint("fk_matrix_profiles_active_patient_id_patients", type_="foreignkey")
        batch_op.drop_index("ix_matrix_profiles_active_patient_id")
        batch_op.drop_column("active_patient_id")
