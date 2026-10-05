"""Add the candidate_rejected unresolved match reason.

Revision ID: 0003_candidate_rejected
Revises: 0002_import_matching
Create Date: 2026-10-04

A member who rejects a proposed candidate name gets an unresolved match with this reason.
SQLite cannot change a CHECK constraint in place, so a batch operation copies the table.
The downgrade sets candidate_rejected rows to no_match before it restores the old constraint.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0003_candidate_rejected"
down_revision: str | Sequence[str] | None = "0002_import_matching"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_OLD = ("no_match", "ambiguous", "telegram_id_taken")
_NEW = (*_OLD, "candidate_rejected")
_CHECK = "ck_unresolved_matches_unresolved_reason"


def _reason(values: tuple[str, ...]) -> sa.Enum:
    return sa.Enum(*values, name="unresolved_reason", native_enum=False, create_constraint=True)


def _change(old: tuple[str, ...], new: tuple[str, ...]) -> None:
    with op.batch_alter_table("unresolved_matches", recreate="always") as batch:
        batch.drop_constraint(op.f(_CHECK), type_="check")
        batch.alter_column(
            "reason", existing_type=_reason(old), type_=_reason(new), existing_nullable=False
        )


def upgrade() -> None:
    _change(_OLD, _NEW)


def downgrade() -> None:
    unresolved = sa.table("unresolved_matches", sa.column("reason", sa.String()))
    op.execute(
        unresolved.update()
        .where(unresolved.c.reason == "candidate_rejected")
        .values(reason="no_match")
    )
    _change(_NEW, _OLD)
