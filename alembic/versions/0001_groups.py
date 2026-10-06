"""Add groups and every group-scoped table (decisions T80–T86).

Revision ID: 0001_groups
Revises:
Create Date: 2026-10-07

This baseline replaces revisions 0001_identity to 0007_session_responses. No live data existed.
Timestamps are naive UTC in SQLite. The application type returns aware UTC values.
Plain SQLAlchemy types keep this revision independent of application code.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0001_groups"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

REASON_RULE = (
    "(status = 'coming' AND reason IS NULL) OR "
    "(status <> 'coming' AND length(reason) BETWEEN 1 AND 1000)"
)


def upgrade() -> None:
    op.create_table(
        "groups",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("telegram_chat_id", sa.BigInteger(), nullable=False),
        sa.Column("chat_type", sa.String(length=10), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "chat_type IN ('group', 'supergroup')", name=op.f("ck_groups_valid_chat_type")
        ),
        sa.CheckConstraint("length(title) BETWEEN 1 AND 200", name=op.f("ck_groups_valid_title")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_groups")),
        sa.UniqueConstraint("telegram_chat_id", name=op.f("uq_groups_telegram_chat_id")),
    )
    op.create_table(
        "attendance_series",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("group_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("normalized_name", sa.String(length=600), nullable=False),
        sa.Column("created_by", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "normalized_name <> ''", name=op.f("ck_attendance_series_normalized_name_not_empty")
        ),
        sa.CheckConstraint("created_by > 0", name=op.f("ck_attendance_series_created_by_positive")),
        sa.CheckConstraint(
            "length(name) BETWEEN 1 AND 200", name=op.f("ck_attendance_series_valid_name")
        ),
        sa.ForeignKeyConstraint(
            ["group_id"],
            ["groups.id"],
            name=op.f("fk_attendance_series_group_id_groups"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_attendance_series")),
        sa.UniqueConstraint("group_id", "id", name="uq_attendance_series_group_id"),
        sa.UniqueConstraint("group_id", "normalized_name", name="uq_attendance_series_name"),
    )
    op.create_table(
        "people",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("group_id", sa.Integer(), nullable=False),
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
        sa.ForeignKeyConstraint(
            ["group_id"], ["groups.id"], name=op.f("fk_people_group_id_groups"), ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_people")),
        sa.UniqueConstraint("group_id", "id", name="uq_people_group_id"),
        sa.UniqueConstraint(
            "group_id", "telegram_user_id", name="uq_people_group_telegram_user_id"
        ),
    )
    op.create_index("ix_people_group_handle", "people", ["group_id", "telegram_handle"])
    op.create_table(
        "unresolved_matches",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("group_id", sa.Integer(), nullable=False),
        sa.Column("telegram_user_id", sa.BigInteger(), nullable=False),
        sa.Column("telegram_handle", sa.String(length=64), nullable=True),
        sa.Column(
            "reason",
            sa.Enum(
                "no_match",
                "ambiguous",
                "telegram_id_taken",
                "candidate_rejected",
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
            "telegram_user_id > 0", name=op.f("ck_unresolved_matches_telegram_user_id_positive")
        ),
        sa.ForeignKeyConstraint(
            ["group_id"],
            ["groups.id"],
            name=op.f("fk_unresolved_matches_group_id_groups"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_unresolved_matches")),
        sa.UniqueConstraint(
            "group_id", "telegram_user_id", name="uq_unresolved_matches_group_telegram_user_id"
        ),
    )
    op.create_table(
        "attendance_sessions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("group_id", sa.Integer(), nullable=False),
        sa.Column("series_id", sa.Integer(), nullable=False),
        sa.Column("session_date", sa.Date(), nullable=False),
        sa.Column("label", sa.String(length=200), nullable=True),
        sa.Column("deadline", sa.DateTime(), nullable=False),
        sa.Column("status", sa.String(length=10), nullable=False),
        sa.Column("created_by", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("creation_key", sa.String(length=64), nullable=False),
        sa.Column("request_fingerprint", sa.String(length=64), nullable=False),
        sa.CheckConstraint(
            "status IN ('draft', 'open', 'closed')",
            name=op.f("ck_attendance_sessions_valid_status"),
        ),
        sa.CheckConstraint(
            "created_by > 0", name=op.f("ck_attendance_sessions_created_by_positive")
        ),
        sa.CheckConstraint(
            "label IS NULL OR length(label) BETWEEN 1 AND 200",
            name=op.f("ck_attendance_sessions_valid_label"),
        ),
        sa.ForeignKeyConstraint(
            ["group_id", "series_id"],
            ["attendance_series.group_id", "attendance_series.id"],
            name=op.f("fk_attendance_sessions_group_id_attendance_series"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["group_id"],
            ["groups.id"],
            name=op.f("fk_attendance_sessions_group_id_groups"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_attendance_sessions")),
        sa.UniqueConstraint("group_id", "creation_key", name="uq_attendance_sessions_creation"),
        sa.UniqueConstraint("group_id", "id", name="uq_attendance_sessions_group_id"),
    )
    op.create_index(op.f("ix_attendance_sessions_series_id"), "attendance_sessions", ["series_id"])
    op.create_table(
        "session_publications",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("group_id", sa.Integer(), nullable=False),
        sa.Column("session_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("requested_by", sa.BigInteger(), nullable=False),
        sa.Column("lease_expires_at", sa.DateTime(), nullable=False),
        sa.Column("telegram_message_id", sa.BigInteger(), nullable=True),
        sa.Column("failure", sa.String(length=64), nullable=True),
        sa.Column("resolved_by", sa.BigInteger(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "status IN ('publishing', 'published', 'publish_unknown', 'failed')",
            name=op.f("ck_session_publications_valid_publication_status"),
        ),
        sa.CheckConstraint(
            "telegram_message_id IS NULL OR status = 'published'",
            name=op.f("ck_session_publications_message_only_published"),
        ),
        sa.CheckConstraint(
            "requested_by > 0", name=op.f("ck_session_publications_requested_by_positive")
        ),
        sa.CheckConstraint(
            "resolved_by IS NULL OR resolved_by > 0",
            name=op.f("ck_session_publications_resolved_by_positive"),
        ),
        sa.ForeignKeyConstraint(
            ["group_id", "session_id"],
            ["attendance_sessions.group_id", "attendance_sessions.id"],
            name=op.f("fk_session_publications_group_id_attendance_sessions"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_session_publications")),
    )
    op.create_index(
        "ix_session_publications_lease", "session_publications", ["status", "lease_expires_at"]
    )
    op.create_index(
        "uq_session_publications_active",
        "session_publications",
        ["session_id"],
        unique=True,
        sqlite_where=sa.text("status IN ('publishing', 'publish_unknown', 'published')"),
    )
    op.create_table(
        "session_roster_entries",
        sa.Column("group_id", sa.Integer(), nullable=False),
        sa.Column("session_id", sa.Integer(), nullable=False),
        sa.Column("person_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["group_id", "person_id"],
            ["people.group_id", "people.id"],
            name=op.f("fk_session_roster_entries_group_id_people"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["group_id", "session_id"],
            ["attendance_sessions.group_id", "attendance_sessions.id"],
            name=op.f("fk_session_roster_entries_group_id_attendance_sessions"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint(
            "group_id", "session_id", "person_id", name=op.f("pk_session_roster_entries")
        ),
    )
    op.create_table(
        "session_response_events",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("group_id", sa.Integer(), nullable=False),
        sa.Column("session_id", sa.Integer(), nullable=False),
        sa.Column("person_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("reason", sa.String(length=1000), nullable=True),
        sa.Column("telegram_user_id", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            REASON_RULE,
            name=op.f("ck_session_response_events_reason_matches_status"),
        ),
        sa.CheckConstraint(
            "status IN ('coming', 'not_coming', 'late', 'leaving_early')",
            name=op.f("ck_session_response_events_valid_response_status"),
        ),
        sa.CheckConstraint(
            "telegram_user_id > 0",
            name=op.f("ck_session_response_events_telegram_user_id_positive"),
        ),
        sa.ForeignKeyConstraint(
            ["group_id", "session_id", "person_id"],
            [
                "session_roster_entries.group_id",
                "session_roster_entries.session_id",
                "session_roster_entries.person_id",
            ],
            name=op.f("fk_session_response_events_group_id_session_roster_entries"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_session_response_events")),
    )
    op.create_index(
        "ix_session_response_events_member", "session_response_events", ["session_id", "person_id"]
    )
    op.create_table(
        "session_responses",
        sa.Column("group_id", sa.Integer(), nullable=False),
        sa.Column("session_id", sa.Integer(), nullable=False),
        sa.Column("person_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("reason", sa.String(length=1000), nullable=True),
        sa.Column("responded_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            REASON_RULE,
            name=op.f("ck_session_responses_reason_matches_status"),
        ),
        sa.CheckConstraint(
            "status IN ('coming', 'not_coming', 'late', 'leaving_early')",
            name=op.f("ck_session_responses_valid_response_status"),
        ),
        sa.ForeignKeyConstraint(
            ["group_id", "session_id", "person_id"],
            [
                "session_roster_entries.group_id",
                "session_roster_entries.session_id",
                "session_roster_entries.person_id",
            ],
            name=op.f("fk_session_responses_group_id_session_roster_entries"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint(
            "group_id", "session_id", "person_id", name=op.f("pk_session_responses")
        ),
    )


def downgrade() -> None:
    op.drop_table("session_responses")
    op.drop_index("ix_session_response_events_member", table_name="session_response_events")
    op.drop_table("session_response_events")
    op.drop_table("session_roster_entries")
    op.drop_index("uq_session_publications_active", table_name="session_publications")
    op.drop_index("ix_session_publications_lease", table_name="session_publications")
    op.drop_table("session_publications")
    op.drop_index(op.f("ix_attendance_sessions_series_id"), table_name="attendance_sessions")
    op.drop_table("attendance_sessions")
    op.drop_table("unresolved_matches")
    op.drop_index("ix_people_group_handle", table_name="people")
    op.drop_table("people")
    op.drop_table("attendance_series")
    op.drop_table("groups")
