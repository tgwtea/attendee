"""Add unresolved Telegram matches and canonical handles.

Revision ID: 0002_import_matching
Revises: 0001_identity
Create Date: 2026-10-04

Existing handles become canonical: no whitespace, no leading "@", lowercase.
A stored handle that Telegram would reject becomes NULL. The downgrade keeps canonical handles.
This revision uses plain SQLAlchemy types and its own handle rule, so later code changes
cannot alter it.
"""

import re
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0002_import_matching"
down_revision: str | Sequence[str] | None = "0001_identity"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_HANDLE = re.compile(r"[a-z][a-z0-9_]{3,31}")


def _canonical(handle: str) -> str | None:
    canonical = handle.strip().removeprefix("@").lower()
    return canonical if _HANDLE.fullmatch(canonical) else None


def upgrade() -> None:
    connection = op.get_bind()
    people = sa.table(
        "people", sa.column("id", sa.Integer()), sa.column("telegram_handle", sa.String())
    )
    rows = connection.execute(
        sa.select(people.c.id, people.c.telegram_handle).where(
            people.c.telegram_handle.is_not(None)
        )
    ).all()
    for person_id, handle in rows:
        canonical = _canonical(handle)
        if canonical != handle:
            connection.execute(
                people.update().where(people.c.id == person_id).values(telegram_handle=canonical)
            )
    op.create_index(op.f("ix_people_telegram_handle"), "people", ["telegram_handle"])
    op.create_table(
        "unresolved_matches",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("organization_id", sa.Integer(), nullable=False),
        sa.Column("telegram_user_id", sa.BigInteger(), nullable=False),
        sa.Column("telegram_handle", sa.String(length=64), nullable=True),
        sa.Column(
            "reason",
            sa.Enum(
                "no_match",
                "ambiguous",
                "telegram_id_taken",
                name="unresolved_reason",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("resolved_at", sa.DateTime(), nullable=True),
        sa.CheckConstraint(
            "telegram_user_id > 0",
            name=op.f("ck_unresolved_matches_telegram_user_id_positive"),
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_unresolved_matches_organization_id_organizations"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_unresolved_matches")),
        sa.UniqueConstraint(
            "organization_id",
            "telegram_user_id",
            name="uq_unresolved_matches_organization_id_telegram_user_id",
        ),
    )


def downgrade() -> None:
    op.drop_table("unresolved_matches")
    op.drop_index(op.f("ix_people_telegram_handle"), table_name="people")
