"""add per-patient alert rules and inbox acknowledgements

Revision ID: 20260324_000026
Revises: 20260324_000025
Create Date: 2026-03-24 21:00:00
"""

from alembic import op
import sqlalchemy as sa


revision = "20260324_000026"
down_revision = "20260324_000025"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("alert_settings", sa.Column("extra_recipients", sa.JSON(), nullable=False, server_default="[]"))
    op.add_column("alert_settings", sa.Column("blood_pressure_sys_threshold", sa.Integer(), nullable=True))
    op.add_column("alert_settings", sa.Column("blood_pressure_dia_threshold", sa.Integer(), nullable=True))
    op.add_column("alert_settings", sa.Column("blood_sugar_threshold", sa.Float(), nullable=True))
    op.add_column("alert_settings", sa.Column("quiet_hours_start", sa.Time(), nullable=True))
    op.add_column("alert_settings", sa.Column("quiet_hours_end", sa.Time(), nullable=True))

    op.add_column("patient_checkins", sa.Column("acknowledged_by_user_id", sa.Integer(), nullable=True))
    op.add_column("patient_checkins", sa.Column("acknowledged_at", sa.DateTime(), nullable=True))
    op.add_column("patient_checkins", sa.Column("acknowledgment_note", sa.Text(), nullable=True))
    op.create_index("ix_patient_checkins_acknowledged_by_user_id", "patient_checkins", ["acknowledged_by_user_id"])
    op.create_index("ix_patient_checkins_acknowledged_at", "patient_checkins", ["acknowledged_at"])
    op.create_foreign_key(
        "fk_patient_checkins_acknowledged_by_user_id_users",
        "patient_checkins",
        "users",
        ["acknowledged_by_user_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_patient_checkins_acknowledged_by_user_id_users", "patient_checkins", type_="foreignkey")
    op.drop_index("ix_patient_checkins_acknowledged_at", table_name="patient_checkins")
    op.drop_index("ix_patient_checkins_acknowledged_by_user_id", table_name="patient_checkins")
    op.drop_column("patient_checkins", "acknowledgment_note")
    op.drop_column("patient_checkins", "acknowledged_at")
    op.drop_column("patient_checkins", "acknowledged_by_user_id")

    op.drop_column("alert_settings", "quiet_hours_end")
    op.drop_column("alert_settings", "quiet_hours_start")
    op.drop_column("alert_settings", "blood_sugar_threshold")
    op.drop_column("alert_settings", "blood_pressure_dia_threshold")
    op.drop_column("alert_settings", "blood_pressure_sys_threshold")
    op.drop_column("alert_settings", "extra_recipients")
