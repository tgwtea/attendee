"""Add organizations, global people, and organization memberships.

Revision ID: 0001_identity
Revises:
Create Date: 2026-10-04

Timestamps are naive UTC in SQLite. The application type returns aware UTC values.
This revision uses plain SQLAlchemy types so later code changes cannot alter it.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0001_identity"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "organizations",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("slug", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint("name <> ''", name=op.f("ck_organizations_name_not_empty")),
        sa.CheckConstraint("slug <> ''", name=op.f("ck_organizations_slug_not_empty")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_organizations")),
        sa.UniqueConstraint("slug", name=op.f("uq_organizations_slug")),
    )
    op.create_table(
        "people",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("display_name", sa.String(length=200), nullable=True),
        sa.Column("telegram_user_id", sa.BigInteger(), nullable=True),
        sa.Column("telegram_handle", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "display_name IS NOT NULL OR telegram_user_id IS NOT NULL",
            name=op.f("ck_people_has_identity"),
        ),
        sa.CheckConstraint(
            "telegram_user_id > 0", name=op.f("ck_people_telegram_user_id_positive")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_people")),
        sa.UniqueConstraint("telegram_user_id", name=op.f("uq_people_telegram_user_id")),
    )
    op.create_table(
        "memberships",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("organization_id", sa.Integer(), nullable=False),
        sa.Column("person_id", sa.Integer(), nullable=False),
        sa.Column(
            "role",
            sa.Enum("member", "admin", name="role", native_enum=False, create_constraint=True),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_memberships_organization_id_organizations"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["person_id"],
            ["people.id"],
            name=op.f("fk_memberships_person_id_people"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_memberships")),
        sa.UniqueConstraint(
            "organization_id", "person_id", name="uq_memberships_organization_id_person_id"
        ),
    )
    op.create_index(op.f("ix_memberships_person_id"), "memberships", ["person_id"])


def downgrade() -> None:
    op.drop_index(op.f("ix_memberships_person_id"), table_name="memberships")
    op.drop_table("memberships")
    op.drop_table("people")
    op.drop_table("organizations")
