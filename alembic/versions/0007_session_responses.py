"""Add current session responses and their append-only audit rows.

Revision ID: 0007_session_responses
Revises: 0006_session_publications

Plain SQLAlchemy types keep this revision independent of application code.
"""

import sqlalchemy as sa

from alembic import op

revision = "0007_session_responses"
down_revision = "0006_session_publications"
branch_labels = None
depends_on = None

STATUS = "status IN ('coming', 'not_coming', 'late', 'leaving_early')"
REASON = (
    "(status = 'coming' AND reason IS NULL) OR "
    "(status <> 'coming' AND length(reason) BETWEEN 1 AND 1000)"
)
ROSTER_COLUMNS = ["organization_id", "session_id", "person_id"]
ROSTER_TARGET = [
    "session_roster_entries.organization_id",
    "session_roster_entries.session_id",
    "session_roster_entries.person_id",
]


def upgrade() -> None:
    op.create_table(
        "session_responses",
        sa.Column("organization_id", sa.Integer(), primary_key=True),
        sa.Column("session_id", sa.Integer(), primary_key=True),
        sa.Column("person_id", sa.Integer(), primary_key=True),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("reason", sa.String(1000)),
        sa.Column("responded_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(STATUS, name="valid_response_status"),
        sa.CheckConstraint(REASON, name="reason_matches_status"),
        sa.ForeignKeyConstraint(ROSTER_COLUMNS, ROSTER_TARGET, ondelete="RESTRICT"),
    )
    op.create_table(
        "session_response_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), nullable=False),
        sa.Column("session_id", sa.Integer(), nullable=False),
        sa.Column("person_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("reason", sa.String(1000)),
        sa.Column("telegram_user_id", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(STATUS, name="valid_response_status"),
        sa.CheckConstraint(REASON, name="reason_matches_status"),
        sa.CheckConstraint("telegram_user_id > 0", name="telegram_user_id_positive"),
        sa.ForeignKeyConstraint(ROSTER_COLUMNS, ROSTER_TARGET, ondelete="RESTRICT"),
    )
    op.create_index(
        "ix_session_response_events_member",
        "session_response_events",
        ["session_id", "person_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_session_response_events_member", table_name="session_response_events")
    op.drop_table("session_response_events")
    op.drop_table("session_responses")
