"""add alert settings

Revision ID: 20260324_000019
Revises: 20260324_000018
Create Date: 2026-03-24 07:00:00
"""

from alembic import op
import sqlalchemy as sa


revision = "20260324_000019"
down_revision = "20260324_000018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "alert_settings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("patient_id", sa.Integer(), sa.ForeignKey("patients.id", ondelete="CASCADE"), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("matrix_user_id", sa.String(length=255), nullable=True),
        sa.Column("matrix_room_id", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    op.create_index("ix_alert_settings_id", "alert_settings", ["id"])
    op.create_index("ix_alert_settings_user_id", "alert_settings", ["user_id"])
    op.create_index("ix_alert_settings_patient_id", "alert_settings", ["patient_id"])
    op.create_index("ix_alert_settings_enabled", "alert_settings", ["enabled"])
    op.create_unique_constraint("uq_alert_settings_user_patient", "alert_settings", ["user_id", "patient_id"])


def downgrade() -> None:
    op.drop_constraint("uq_alert_settings_user_patient", "alert_settings", type_="unique")
    op.drop_index("ix_alert_settings_enabled", table_name="alert_settings")
    op.drop_index("ix_alert_settings_patient_id", table_name="alert_settings")
    op.drop_index("ix_alert_settings_user_id", table_name="alert_settings")
    op.drop_index("ix_alert_settings_id", table_name="alert_settings")
    op.drop_table("alert_settings")
