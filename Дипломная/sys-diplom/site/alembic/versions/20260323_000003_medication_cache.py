"""medication cache"""

from alembic import op
import sqlalchemy as sa


revision = "20260323_000003"
down_revision = "20260323_000002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "medication_info_cache",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("query", sa.String(length=255), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False, server_default=sa.text("'[]'::json")),
        sa.Column("fetched_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_medication_info_cache_id", "medication_info_cache", ["id"])
    op.create_index("ix_medication_info_cache_query", "medication_info_cache", ["query"], unique=True)
    op.create_index("ix_medication_info_cache_fetched_at", "medication_info_cache", ["fetched_at"])


def downgrade() -> None:
    op.drop_index("ix_medication_info_cache_fetched_at", table_name="medication_info_cache")
    op.drop_index("ix_medication_info_cache_query", table_name="medication_info_cache")
    op.drop_index("ix_medication_info_cache_id", table_name="medication_info_cache")
    op.drop_table("medication_info_cache")
