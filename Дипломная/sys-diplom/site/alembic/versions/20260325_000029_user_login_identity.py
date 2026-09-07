"""add neutral login identity fields

Revision ID: 20260325_000029
Revises: 20260324_000028
Create Date: 2026-03-25 11:30:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "20260325_000029"
down_revision = "20260324_000028"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("login", sa.String(length=255), nullable=True))
    op.add_column("invites", sa.Column("login", sa.String(length=255), nullable=True))

    op.execute(sa.text("UPDATE users SET login = lower(trim(email)) WHERE login IS NULL"))
    op.execute(sa.text("UPDATE invites SET login = lower(trim(email)) WHERE login IS NULL"))

    with op.batch_alter_table("users") as batch_op:
        batch_op.alter_column("login", existing_type=sa.String(length=255), nullable=False)
        batch_op.create_index("ix_users_login", ["login"], unique=True)

    with op.batch_alter_table("invites") as batch_op:
        batch_op.alter_column("login", existing_type=sa.String(length=255), nullable=False)
        batch_op.create_index("ix_invites_login", ["login"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("invites") as batch_op:
        batch_op.drop_index("ix_invites_login")
    with op.batch_alter_table("users") as batch_op:
        batch_op.drop_index("ix_users_login")
    op.drop_column("invites", "login")
    op.drop_column("users", "login")
