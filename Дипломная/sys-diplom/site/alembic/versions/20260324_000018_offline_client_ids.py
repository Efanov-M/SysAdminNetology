"""add offline client ids

Revision ID: 20260324_000018
Revises: 20260324_000017
Create Date: 2026-03-24 10:20:00
"""

from alembic import op
import sqlalchemy as sa


revision = "20260324_000018"
down_revision = "20260324_000017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("observations", sa.Column("client_id", sa.String(length=64), nullable=True))
    op.create_index("ix_observations_client_id", "observations", ["client_id"], unique=True)

    op.add_column("medications", sa.Column("client_id", sa.String(length=64), nullable=True))
    op.create_index("ix_medications_client_id", "medications", ["client_id"], unique=True)

    op.add_column("care_events", sa.Column("client_id", sa.String(length=64), nullable=True))
    op.create_index("ix_care_events_client_id", "care_events", ["client_id"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_care_events_client_id", table_name="care_events")
    op.drop_column("care_events", "client_id")

    op.drop_index("ix_medications_client_id", table_name="medications")
    op.drop_column("medications", "client_id")

    op.drop_index("ix_observations_client_id", table_name="observations")
    op.drop_column("observations", "client_id")
