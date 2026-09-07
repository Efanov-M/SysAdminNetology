"""add alert rule escalation settings

Revision ID: 20260324_000028
Revises: 20260324_000027
Create Date: 2026-03-24 18:20:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "20260324_000028"
down_revision = "20260324_000027"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("alert_rules", sa.Column("quiet_hours_start", sa.Time(), nullable=True))
    op.add_column("alert_rules", sa.Column("quiet_hours_end", sa.Time(), nullable=True))
    op.add_column("alert_rules", sa.Column("escalation_targets", sa.JSON(), nullable=True))

    op.execute(sa.text("UPDATE alert_rules SET escalation_targets = '[]' WHERE escalation_targets IS NULL"))
    with op.batch_alter_table("alert_rules") as batch_op:
        batch_op.alter_column("escalation_targets", existing_type=sa.JSON(), nullable=False)


def downgrade() -> None:
    op.drop_column("alert_rules", "escalation_targets")
    op.drop_column("alert_rules", "quiet_hours_end")
    op.drop_column("alert_rules", "quiet_hours_start")
