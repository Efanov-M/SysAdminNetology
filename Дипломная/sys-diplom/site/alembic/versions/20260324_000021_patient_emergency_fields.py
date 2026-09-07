"""move emergency info fields into patients

Revision ID: 20260324_000021
Revises: 20260324_000020
Create Date: 2026-03-24 14:00:00
"""

from alembic import op
import sqlalchemy as sa


revision = "20260324_000021"
down_revision = "20260324_000020"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("patients", sa.Column("blood_type", sa.String(length=32), nullable=True))
    op.add_column("patients", sa.Column("allergies", sa.Text(), nullable=True))
    op.add_column("patients", sa.Column("chronic_diseases", sa.Text(), nullable=True))
    op.add_column("patients", sa.Column("permanent_medications", sa.Text(), nullable=True))
    op.add_column("patients", sa.Column("emergency_contacts", sa.Text(), nullable=True))

    op.execute(
        sa.text(
            """
            UPDATE patients
            SET
                blood_type = emergency_info.blood_type,
                allergies = emergency_info.allergies,
                chronic_diseases = emergency_info.diagnoses,
                emergency_contacts = emergency_info.emergency_contacts
            FROM emergency_info
            WHERE emergency_info.patient_id = patients.id
            """
        )
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            """
            UPDATE emergency_info
            SET
                blood_type = patients.blood_type,
                allergies = patients.allergies,
                diagnoses = patients.chronic_diseases,
                emergency_contacts = patients.emergency_contacts
            FROM patients
            WHERE emergency_info.patient_id = patients.id
            """
        )
    )

    op.drop_column("patients", "emergency_contacts")
    op.drop_column("patients", "permanent_medications")
    op.drop_column("patients", "chronic_diseases")
    op.drop_column("patients", "allergies")
    op.drop_column("patients", "blood_type")
