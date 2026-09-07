"""care control reminders events checkins

Revision ID: 20260324_000012
Revises: 20260323_000011
Create Date: 2026-03-24 12:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "20260324_000012"
down_revision = "20260323_000011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "patient_reminders",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("patient_id", sa.Integer(), sa.ForeignKey("patients.id", ondelete="CASCADE"), nullable=False),
        sa.Column("reminder_type", sa.String(length=50), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("time_of_day", sa.Time(), nullable=False),
        sa.Column("weekdays", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("recipient_mode", sa.String(length=20), nullable=False, server_default="family"),
        sa.Column("recipient_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_patient_reminders_id", "patient_reminders", ["id"])
    op.create_index("ix_patient_reminders_patient_id", "patient_reminders", ["patient_id"])
    op.create_index("ix_patient_reminders_reminder_type", "patient_reminders", ["reminder_type"])
    op.create_index("ix_patient_reminders_recipient_user_id", "patient_reminders", ["recipient_user_id"])
    op.create_index("ix_patient_reminders_enabled", "patient_reminders", ["enabled"])

    op.create_table(
        "care_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("patient_id", sa.Integer(), sa.ForeignKey("patients.id", ondelete="CASCADE"), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("scheduled_at", sa.DateTime(), nullable=False),
        sa.Column("doctor", sa.String(length=255), nullable=True),
        sa.Column("place", sa.String(length=255), nullable=True),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("remind_day_before", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("remind_hours_before", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_care_events_id", "care_events", ["id"])
    op.create_index("ix_care_events_patient_id", "care_events", ["patient_id"])
    op.create_index("ix_care_events_scheduled_at", "care_events", ["scheduled_at"])

    op.create_table(
        "patient_checkins",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("patient_id", sa.Integer(), sa.ForeignKey("patients.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("checkin_type", sa.String(length=50), nullable=False),
        sa.Column("details", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_patient_checkins_id", "patient_checkins", ["id"])
    op.create_index("ix_patient_checkins_patient_id", "patient_checkins", ["patient_id"])
    op.create_index("ix_patient_checkins_user_id", "patient_checkins", ["user_id"])
    op.create_index("ix_patient_checkins_checkin_type", "patient_checkins", ["checkin_type"])
    op.create_index("ix_patient_checkins_created_at", "patient_checkins", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_patient_checkins_created_at", table_name="patient_checkins")
    op.drop_index("ix_patient_checkins_checkin_type", table_name="patient_checkins")
    op.drop_index("ix_patient_checkins_user_id", table_name="patient_checkins")
    op.drop_index("ix_patient_checkins_patient_id", table_name="patient_checkins")
    op.drop_index("ix_patient_checkins_id", table_name="patient_checkins")
    op.drop_table("patient_checkins")

    op.drop_index("ix_care_events_scheduled_at", table_name="care_events")
    op.drop_index("ix_care_events_patient_id", table_name="care_events")
    op.drop_index("ix_care_events_id", table_name="care_events")
    op.drop_table("care_events")

    op.drop_index("ix_patient_reminders_enabled", table_name="patient_reminders")
    op.drop_index("ix_patient_reminders_recipient_user_id", table_name="patient_reminders")
    op.drop_index("ix_patient_reminders_reminder_type", table_name="patient_reminders")
    op.drop_index("ix_patient_reminders_patient_id", table_name="patient_reminders")
    op.drop_index("ix_patient_reminders_id", table_name="patient_reminders")
    op.drop_table("patient_reminders")
