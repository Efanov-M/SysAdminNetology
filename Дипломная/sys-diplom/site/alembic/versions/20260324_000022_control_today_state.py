"""add reminder and event today state fields

Revision ID: 20260324_000022
Revises: 20260324_000021
Create Date: 2026-03-24 15:30:00
"""

from alembic import op
import sqlalchemy as sa


revision = "20260324_000022"
down_revision = "20260324_000021"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("patient_reminders", sa.Column("repeat_mode", sa.String(length=20), nullable=False, server_default="daily"))
    op.add_column("patient_reminders", sa.Column("one_time_date", sa.Date(), nullable=True))
    op.add_column("patient_reminders", sa.Column("snoozed_until", sa.DateTime(), nullable=True))
    op.add_column("patient_reminders", sa.Column("last_completed_at", sa.DateTime(), nullable=True))
    op.create_index("ix_patient_reminders_one_time_date", "patient_reminders", ["one_time_date"])
    op.create_index("ix_patient_reminders_snoozed_until", "patient_reminders", ["snoozed_until"])
    op.create_index("ix_patient_reminders_last_completed_at", "patient_reminders", ["last_completed_at"])

    op.add_column("care_events", sa.Column("snoozed_until", sa.DateTime(), nullable=True))
    op.add_column("care_events", sa.Column("completed_at", sa.DateTime(), nullable=True))
    op.add_column("care_events", sa.Column("status", sa.String(length=20), nullable=False, server_default="scheduled"))
    op.create_index("ix_care_events_snoozed_until", "care_events", ["snoozed_until"])
    op.create_index("ix_care_events_completed_at", "care_events", ["completed_at"])
    op.create_index("ix_care_events_status", "care_events", ["status"])

    op.execute(sa.text("UPDATE patient_reminders SET repeat_mode = 'daily' WHERE repeat_mode IS NULL"))
    op.execute(sa.text("UPDATE care_events SET status = 'scheduled' WHERE status IS NULL"))


def downgrade() -> None:
    op.drop_index("ix_care_events_status", table_name="care_events")
    op.drop_index("ix_care_events_completed_at", table_name="care_events")
    op.drop_index("ix_care_events_snoozed_until", table_name="care_events")
    op.drop_column("care_events", "status")
    op.drop_column("care_events", "completed_at")
    op.drop_column("care_events", "snoozed_until")

    op.drop_index("ix_patient_reminders_last_completed_at", table_name="patient_reminders")
    op.drop_index("ix_patient_reminders_snoozed_until", table_name="patient_reminders")
    op.drop_index("ix_patient_reminders_one_time_date", table_name="patient_reminders")
    op.drop_column("patient_reminders", "last_completed_at")
    op.drop_column("patient_reminders", "snoozed_until")
    op.drop_column("patient_reminders", "one_time_date")
    op.drop_column("patient_reminders", "repeat_mode")
