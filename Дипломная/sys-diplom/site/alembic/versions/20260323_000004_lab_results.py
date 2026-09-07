"""lab results normalized"""

from alembic import op
import sqlalchemy as sa


revision = "20260323_000004"
down_revision = "20260323_000003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "lab_results",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("patient_id", sa.Integer(), sa.ForeignKey("patients.id", ondelete="CASCADE"), nullable=False),
        sa.Column("panel_name", sa.String(length=100), nullable=True),
        sa.Column("test_name", sa.String(length=255), nullable=False),
        sa.Column("value", sa.Float(), nullable=False),
        sa.Column("unit", sa.String(length=50), nullable=True),
        sa.Column("reference_low", sa.Float(), nullable=True),
        sa.Column("reference_high", sa.Float(), nullable=True),
        sa.Column("reference_text", sa.String(length=100), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_lab_results_id", "lab_results", ["id"])
    op.create_index("ix_lab_results_patient_id", "lab_results", ["patient_id"])
    op.create_index("ix_lab_results_panel_name", "lab_results", ["panel_name"])
    op.create_index("ix_lab_results_test_name", "lab_results", ["test_name"])
    op.create_index("ix_lab_results_created_at", "lab_results", ["created_at"])

    op.execute(
        """
        INSERT INTO lab_results (patient_id, panel_name, test_name, value, unit, reference_low, reference_high, reference_text, created_at)
        SELECT
            patient_id,
            value->>'panel',
            COALESCE(value->>'test_name', 'Анализ'),
            CAST(COALESCE(value->>'value', '0') AS DOUBLE PRECISION),
            value->>'unit',
            NULL,
            NULL,
            NULL,
            created_at
        FROM observations
        WHERE type = 'lab_result'
        """
    )
    op.execute("DELETE FROM observations WHERE type = 'lab_result'")


def downgrade() -> None:
    op.drop_index("ix_lab_results_created_at", table_name="lab_results")
    op.drop_index("ix_lab_results_test_name", table_name="lab_results")
    op.drop_index("ix_lab_results_panel_name", table_name="lab_results")
    op.drop_index("ix_lab_results_patient_id", table_name="lab_results")
    op.drop_index("ix_lab_results_id", table_name="lab_results")
    op.drop_table("lab_results")
