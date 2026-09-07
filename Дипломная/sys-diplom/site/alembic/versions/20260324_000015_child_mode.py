"""child patient mode

Revision ID: 20260324_000015
Revises: 20260324_000014
Create Date: 2026-03-24 19:20:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "20260324_000015"
down_revision = "20260324_000014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("patients", sa.Column("patient_type", sa.String(length=32), nullable=False, server_default="elderly"))
    op.create_index("ix_patients_patient_type", "patients", ["patient_type"])

    op.create_table(
        "growth_records",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("patient_id", sa.Integer(), sa.ForeignKey("patients.id", ondelete="CASCADE"), nullable=False),
        sa.Column("height", sa.Float(), nullable=True),
        sa.Column("weight", sa.Float(), nullable=True),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_growth_records_id", "growth_records", ["id"])
    op.create_index("ix_growth_records_patient_id", "growth_records", ["patient_id"])
    op.create_index("ix_growth_records_date", "growth_records", ["date"])
    op.create_index("ix_growth_records_created_at", "growth_records", ["created_at"])

    op.create_table(
        "vaccine_records",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("patient_id", sa.Integer(), sa.ForeignKey("patients.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("date", sa.Date(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="planned"),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_vaccine_records_id", "vaccine_records", ["id"])
    op.create_index("ix_vaccine_records_patient_id", "vaccine_records", ["patient_id"])
    op.create_index("ix_vaccine_records_status", "vaccine_records", ["status"])
    op.create_index("ix_vaccine_records_date", "vaccine_records", ["date"])
    op.create_index("ix_vaccine_records_created_at", "vaccine_records", ["created_at"])

    op.create_table(
        "health_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("patient_id", sa.Integer(), sa.ForeignKey("patients.id", ondelete="CASCADE"), nullable=False),
        sa.Column("temperature", sa.Float(), nullable=True),
        sa.Column("symptoms", sa.Text(), nullable=True),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_health_events_id", "health_events", ["id"])
    op.create_index("ix_health_events_patient_id", "health_events", ["patient_id"])
    op.create_index("ix_health_events_date", "health_events", ["date"])
    op.create_index("ix_health_events_created_at", "health_events", ["created_at"])

    op.create_table(
        "child_medications",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("patient_id", sa.Integer(), sa.ForeignKey("patients.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("dosage", sa.String(length=255), nullable=True),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_child_medications_id", "child_medications", ["id"])
    op.create_index("ix_child_medications_patient_id", "child_medications", ["patient_id"])
    op.create_index("ix_child_medications_date", "child_medications", ["date"])
    op.create_index("ix_child_medications_created_at", "child_medications", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_child_medications_created_at", table_name="child_medications")
    op.drop_index("ix_child_medications_date", table_name="child_medications")
    op.drop_index("ix_child_medications_patient_id", table_name="child_medications")
    op.drop_index("ix_child_medications_id", table_name="child_medications")
    op.drop_table("child_medications")

    op.drop_index("ix_health_events_created_at", table_name="health_events")
    op.drop_index("ix_health_events_date", table_name="health_events")
    op.drop_index("ix_health_events_patient_id", table_name="health_events")
    op.drop_index("ix_health_events_id", table_name="health_events")
    op.drop_table("health_events")

    op.drop_index("ix_vaccine_records_created_at", table_name="vaccine_records")
    op.drop_index("ix_vaccine_records_date", table_name="vaccine_records")
    op.drop_index("ix_vaccine_records_status", table_name="vaccine_records")
    op.drop_index("ix_vaccine_records_patient_id", table_name="vaccine_records")
    op.drop_index("ix_vaccine_records_id", table_name="vaccine_records")
    op.drop_table("vaccine_records")

    op.drop_index("ix_growth_records_created_at", table_name="growth_records")
    op.drop_index("ix_growth_records_date", table_name="growth_records")
    op.drop_index("ix_growth_records_patient_id", table_name="growth_records")
    op.drop_index("ix_growth_records_id", table_name="growth_records")
    op.drop_table("growth_records")

    op.drop_index("ix_patients_patient_type", table_name="patients")
    op.drop_column("patients", "patient_type")
