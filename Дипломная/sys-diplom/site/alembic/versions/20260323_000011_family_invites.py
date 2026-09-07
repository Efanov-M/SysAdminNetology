"""add family ownership, user-patient links and invites

Revision ID: 20260323_000011
Revises: 20260323_000010
Create Date: 2026-03-23 23:55:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260323_000011"
down_revision: Union[str, Sequence[str], None] = "20260323_000010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "families",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("owner_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    op.create_index("ix_families_id", "families", ["id"])
    op.create_index("ix_families_owner_id", "families", ["owner_id"])

    op.add_column("users", sa.Column("family_id", sa.Integer(), nullable=True))
    op.add_column("users", sa.Column("role", sa.String(length=32), nullable=True, server_default="member"))
    op.create_foreign_key("fk_users_family_id_families", "users", "families", ["family_id"], ["id"], ondelete="CASCADE")
    op.create_index("ix_users_family_id", "users", ["family_id"])
    op.create_index("ix_users_role", "users", ["role"])

    op.add_column("patients", sa.Column("family_id", sa.Integer(), nullable=True))
    op.add_column("patients", sa.Column("created_by_user_id", sa.Integer(), nullable=True))
    op.create_foreign_key("fk_patients_family_id_families", "patients", "families", ["family_id"], ["id"], ondelete="CASCADE")
    op.create_foreign_key("fk_patients_created_by_user_id_users", "patients", "users", ["created_by_user_id"], ["id"], ondelete="SET NULL")
    op.create_index("ix_patients_family_id", "patients", ["family_id"])
    op.create_index("ix_patients_created_by_user_id", "patients", ["created_by_user_id"])

    op.create_table(
        "user_patients",
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("patient_id", sa.Integer(), sa.ForeignKey("patients.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    )

    op.create_table(
        "invites",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("family_id", sa.Integer(), sa.ForeignKey("families.id", ondelete="CASCADE"), nullable=False),
        sa.Column("role", sa.String(length=32), nullable=False, server_default="member"),
        sa.Column("patient_id", sa.Integer(), sa.ForeignKey("patients.id", ondelete="SET NULL"), nullable=True),
        sa.Column("token", sa.String(length=255), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("used", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("used_by_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    op.create_index("ix_invites_id", "invites", ["id"])
    op.create_index("ix_invites_email", "invites", ["email"])
    op.create_index("ix_invites_family_id", "invites", ["family_id"])
    op.create_index("ix_invites_patient_id", "invites", ["patient_id"])
    op.create_index("ix_invites_token", "invites", ["token"], unique=True)
    op.create_index("ix_invites_expires_at", "invites", ["expires_at"])
    op.create_index("ix_invites_used", "invites", ["used"])

    bind = op.get_bind()
    metadata = sa.MetaData()
    users = sa.Table("users", metadata, sa.Column("id", sa.Integer()), sa.Column("email", sa.String()), sa.Column("family_id", sa.Integer()), sa.Column("role", sa.String()))
    patients = sa.Table("patients", metadata, sa.Column("id", sa.Integer()), sa.Column("user_id", sa.Integer()), sa.Column("family_id", sa.Integer()), sa.Column("created_by_user_id", sa.Integer()))
    patient_shares = sa.Table("patient_shares", metadata, sa.Column("viewer_user_id", sa.Integer()), sa.Column("patient_id", sa.Integer()))
    families = sa.Table("families", metadata, sa.Column("id", sa.Integer()), sa.Column("name", sa.String()), sa.Column("owner_id", sa.Integer()))
    user_patients = sa.Table("user_patients", metadata, sa.Column("user_id", sa.Integer()), sa.Column("patient_id", sa.Integer()))

    user_rows = bind.execute(sa.select(users.c.id, users.c.email)).fetchall()
    family_map: dict[int, int] = {}
    for user_id, email in user_rows:
        family_name = f"Семья {(email or 'PHR').split('@', 1)[0]}"
        result = bind.execute(
            sa.insert(families)
            .values(name=family_name)
            .returning(families.c.id)
        )
        family_id = result.scalar()
        family_map[user_id] = family_id
        bind.execute(users.update().where(users.c.id == user_id).values(family_id=family_id, role="owner"))
        bind.execute(families.update().where(families.c.id == family_id).values(owner_id=user_id))

    patient_rows = bind.execute(sa.select(patients.c.id, patients.c.user_id)).fetchall()
    patient_family_map: dict[int, int] = {}
    for patient_id, user_id in patient_rows:
        family_id = family_map.get(user_id)
        patient_family_map[patient_id] = family_id
        bind.execute(
            patients.update()
            .where(patients.c.id == patient_id)
            .values(family_id=family_id, created_by_user_id=user_id)
        )

    share_rows = bind.execute(sa.select(patient_shares.c.viewer_user_id, patient_shares.c.patient_id)).fetchall()
    seen_links: set[tuple[int, int]] = set()
    for viewer_user_id, patient_id in share_rows:
        family_id = patient_family_map.get(patient_id)
        if family_id is None:
            continue
        bind.execute(users.update().where(users.c.id == viewer_user_id).values(family_id=family_id, role="member"))
        link_key = (viewer_user_id, patient_id)
        if link_key not in seen_links:
            bind.execute(user_patients.insert().values(user_id=viewer_user_id, patient_id=patient_id))
            seen_links.add(link_key)

    op.alter_column("users", "family_id", nullable=False)
    op.alter_column("users", "role", nullable=False, server_default=None)
    op.alter_column("patients", "family_id", nullable=False)


def downgrade() -> None:
    op.drop_index("ix_invites_used", table_name="invites")
    op.drop_index("ix_invites_expires_at", table_name="invites")
    op.drop_index("ix_invites_token", table_name="invites")
    op.drop_index("ix_invites_patient_id", table_name="invites")
    op.drop_index("ix_invites_family_id", table_name="invites")
    op.drop_index("ix_invites_email", table_name="invites")
    op.drop_index("ix_invites_id", table_name="invites")
    op.drop_table("invites")
    op.drop_table("user_patients")

    op.drop_index("ix_patients_created_by_user_id", table_name="patients")
    op.drop_index("ix_patients_family_id", table_name="patients")
    op.drop_constraint("fk_patients_created_by_user_id_users", "patients", type_="foreignkey")
    op.drop_constraint("fk_patients_family_id_families", "patients", type_="foreignkey")
    op.drop_column("patients", "created_by_user_id")
    op.drop_column("patients", "family_id")

    op.drop_index("ix_users_role", table_name="users")
    op.drop_index("ix_users_family_id", table_name="users")
    op.drop_constraint("fk_users_family_id_families", "users", type_="foreignkey")
    op.drop_column("users", "role")
    op.drop_column("users", "family_id")

    op.drop_index("ix_families_owner_id", table_name="families")
    op.drop_index("ix_families_id", table_name="families")
    op.drop_table("families")
