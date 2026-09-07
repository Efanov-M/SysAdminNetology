"""separate emergency alerts reminders and inbox domains

Revision ID: 20260324_000027
Revises: 20260324_000026
Create Date: 2026-03-24 23:30:00
"""

from alembic import op
import sqlalchemy as sa


revision = "20260324_000027"
down_revision = "20260324_000026"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("patients", sa.Column("weight", sa.Float(), nullable=False, server_default="0"))
    op.add_column("patients", sa.Column("emergency_contact_name", sa.String(length=255), nullable=True))
    op.add_column("patients", sa.Column("emergency_contact_phone", sa.String(length=64), nullable=True))

    op.add_column("documents", sa.Column("text_content", sa.Text(), nullable=True))
    op.execute(sa.text("UPDATE documents SET text_content = extracted_text WHERE text_content IS NULL"))

    op.add_column("matrix_profiles", sa.Column("is_linked", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.execute(sa.text("UPDATE matrix_profiles SET is_linked = connected"))
    op.alter_column("matrix_profiles", "is_linked", server_default=None)

    op.create_table(
        "emergency_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("patient_id", sa.Integer(), sa.ForeignKey("patients.id", ondelete="CASCADE"), nullable=False),
        sa.Column("type", sa.String(length=20), nullable=False),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("acknowledged_at", sa.DateTime(), nullable=True),
        sa.Column("acknowledged_by", sa.String(length=255), nullable=True),
        sa.Column("comment", sa.Text(), nullable=True),
    )
    op.create_index("ix_emergency_events_patient_id", "emergency_events", ["patient_id"])
    op.create_index("ix_emergency_events_status", "emergency_events", ["status"])
    op.create_index("ix_emergency_events_created_at", "emergency_events", ["created_at"])

    op.create_table(
        "alert_rules",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("patient_id", sa.Integer(), sa.ForeignKey("patients.id", ondelete="CASCADE"), nullable=False),
        sa.Column("type", sa.String(length=32), nullable=False),
        sa.Column("systolic_max", sa.Integer(), nullable=True),
        sa.Column("diastolic_max", sa.Integer(), nullable=True),
        sa.Column("glucose_max", sa.Float(), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_alert_rules_patient_id", "alert_rules", ["patient_id"])
    op.create_index("ix_alert_rules_type", "alert_rules", ["type"])
    op.create_index("ix_alert_rules_enabled", "alert_rules", ["enabled"])
    op.create_index("ix_alert_rules_created_at", "alert_rules", ["created_at"])

    op.create_table(
        "alert_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("patient_id", sa.Integer(), sa.ForeignKey("patients.id", ondelete="CASCADE"), nullable=False),
        sa.Column("rule_id", sa.Integer(), sa.ForeignKey("alert_rules.id", ondelete="SET NULL"), nullable=True),
        sa.Column("value", sa.Text(), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_alert_events_patient_id", "alert_events", ["patient_id"])
    op.create_index("ix_alert_events_rule_id", "alert_events", ["rule_id"])
    op.create_index("ix_alert_events_status", "alert_events", ["status"])
    op.create_index("ix_alert_events_created_at", "alert_events", ["created_at"])

    op.create_table(
        "reminders",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("patient_id", sa.Integer(), sa.ForeignKey("patients.id", ondelete="CASCADE"), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("type", sa.String(length=32), nullable=False),
        sa.Column("time", sa.Time(), nullable=False),
        sa.Column("repeat_type", sa.String(length=20), nullable=False, server_default="daily"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_reminders_patient_id", "reminders", ["patient_id"])
    op.create_index("ix_reminders_type", "reminders", ["type"])
    op.create_index("ix_reminders_time", "reminders", ["time"])
    op.create_index("ix_reminders_enabled", "reminders", ["enabled"])
    op.create_index("ix_reminders_created_at", "reminders", ["created_at"])

    op.create_table(
        "reminder_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("reminder_id", sa.Integer(), sa.ForeignKey("reminders.id", ondelete="CASCADE"), nullable=False),
        sa.Column("patient_id", sa.Integer(), sa.ForeignKey("patients.id", ondelete="CASCADE"), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("scheduled_at", sa.DateTime(), nullable=False),
        sa.Column("done_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_reminder_events_reminder_id", "reminder_events", ["reminder_id"])
    op.create_index("ix_reminder_events_patient_id", "reminder_events", ["patient_id"])
    op.create_index("ix_reminder_events_status", "reminder_events", ["status"])
    op.create_index("ix_reminder_events_scheduled_at", "reminder_events", ["scheduled_at"])
    op.create_index("ix_reminder_events_done_at", "reminder_events", ["done_at"])

    op.create_table(
        "inbox_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("patient_id", sa.Integer(), sa.ForeignKey("patients.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source_type", sa.String(length=20), nullable=False),
        sa.Column("source_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="new"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_inbox_events_patient_id", "inbox_events", ["patient_id"])
    op.create_index("ix_inbox_events_source_type", "inbox_events", ["source_type"])
    op.create_index("ix_inbox_events_source_id", "inbox_events", ["source_id"])
    op.create_index("ix_inbox_events_status", "inbox_events", ["status"])
    op.create_index("ix_inbox_events_created_at", "inbox_events", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_inbox_events_created_at", table_name="inbox_events")
    op.drop_index("ix_inbox_events_status", table_name="inbox_events")
    op.drop_index("ix_inbox_events_source_id", table_name="inbox_events")
    op.drop_index("ix_inbox_events_source_type", table_name="inbox_events")
    op.drop_index("ix_inbox_events_patient_id", table_name="inbox_events")
    op.drop_table("inbox_events")

    op.drop_index("ix_reminder_events_done_at", table_name="reminder_events")
    op.drop_index("ix_reminder_events_scheduled_at", table_name="reminder_events")
    op.drop_index("ix_reminder_events_status", table_name="reminder_events")
    op.drop_index("ix_reminder_events_patient_id", table_name="reminder_events")
    op.drop_index("ix_reminder_events_reminder_id", table_name="reminder_events")
    op.drop_table("reminder_events")

    op.drop_index("ix_reminders_created_at", table_name="reminders")
    op.drop_index("ix_reminders_enabled", table_name="reminders")
    op.drop_index("ix_reminders_time", table_name="reminders")
    op.drop_index("ix_reminders_type", table_name="reminders")
    op.drop_index("ix_reminders_patient_id", table_name="reminders")
    op.drop_table("reminders")

    op.drop_index("ix_alert_events_created_at", table_name="alert_events")
    op.drop_index("ix_alert_events_status", table_name="alert_events")
    op.drop_index("ix_alert_events_rule_id", table_name="alert_events")
    op.drop_index("ix_alert_events_patient_id", table_name="alert_events")
    op.drop_table("alert_events")

    op.drop_index("ix_alert_rules_created_at", table_name="alert_rules")
    op.drop_index("ix_alert_rules_enabled", table_name="alert_rules")
    op.drop_index("ix_alert_rules_type", table_name="alert_rules")
    op.drop_index("ix_alert_rules_patient_id", table_name="alert_rules")
    op.drop_table("alert_rules")

    op.drop_index("ix_emergency_events_created_at", table_name="emergency_events")
    op.drop_index("ix_emergency_events_status", table_name="emergency_events")
    op.drop_index("ix_emergency_events_patient_id", table_name="emergency_events")
    op.drop_table("emergency_events")

    op.drop_column("matrix_profiles", "is_linked")
    op.drop_column("documents", "text_content")
    op.drop_column("patients", "emergency_contact_phone")
    op.drop_column("patients", "emergency_contact_name")
    op.drop_column("patients", "weight")
