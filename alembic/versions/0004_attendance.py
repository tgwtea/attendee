"""Add attendance series, Draft sessions, and fixed roster snapshots.

Revision ID: 0004_attendance
Revises: 0003_candidate_rejected

Plain SQLAlchemy types keep this revision independent of application code.
"""

import sqlalchemy as sa

from alembic import op

revision = "0004_attendance"
down_revision = "0003_candidate_rejected"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "attendance_series",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("normalized_name", sa.String(600), nullable=False),
        sa.Column("created_by", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("organization_id", "id", name="uq_attendance_series_org_id"),
        sa.UniqueConstraint("organization_id", "normalized_name", name="uq_attendance_series_name"),
        sa.CheckConstraint("length(name) BETWEEN 1 AND 200", name="valid_name"),
        sa.CheckConstraint("normalized_name <> ''", name="normalized_name_not_empty"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["organization_id", "created_by"],
            ["memberships.organization_id", "memberships.person_id"],
            ondelete="RESTRICT",
        ),
    )
    op.create_table(
        "attendance_sessions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), nullable=False),
        sa.Column("series_id", sa.Integer(), nullable=False),
        sa.Column("session_date", sa.Date(), nullable=False),
        sa.Column("label", sa.String(200)),
        sa.Column("deadline", sa.DateTime(), nullable=False),
        sa.Column("status", sa.String(10), nullable=False),
        sa.Column("created_by", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("creation_key", sa.String(64), nullable=False),
        sa.Column("request_fingerprint", sa.String(64), nullable=False),
        sa.UniqueConstraint("organization_id", "id", name="uq_attendance_sessions_org_id"),
        sa.UniqueConstraint(
            "organization_id", "creation_key", name="uq_attendance_sessions_creation"
        ),
        sa.CheckConstraint("status IN ('draft', 'open', 'closed')", name="valid_status"),
        sa.CheckConstraint("label IS NULL OR length(label) BETWEEN 1 AND 200", name="valid_label"),
        sa.ForeignKeyConstraint(
            ["organization_id", "series_id"],
            ["attendance_series.organization_id", "attendance_series.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "created_by"],
            ["memberships.organization_id", "memberships.person_id"],
            ondelete="RESTRICT",
        ),
    )
    op.create_index("ix_attendance_sessions_series_id", "attendance_sessions", ["series_id"])
    op.create_table(
        "session_roster_entries",
        sa.Column("organization_id", sa.Integer(), primary_key=True),
        sa.Column("session_id", sa.Integer(), primary_key=True),
        sa.Column("person_id", sa.Integer(), primary_key=True),
        sa.ForeignKeyConstraint(
            ["organization_id", "session_id"],
            ["attendance_sessions.organization_id", "attendance_sessions.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "person_id"],
            ["memberships.organization_id", "memberships.person_id"],
            ondelete="RESTRICT",
        ),
    )


def downgrade() -> None:
    op.drop_table("session_roster_entries")
    op.drop_index("ix_attendance_sessions_series_id", table_name="attendance_sessions")
    op.drop_table("attendance_sessions")
    op.drop_table("attendance_series")
