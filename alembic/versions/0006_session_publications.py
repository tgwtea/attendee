"""Add session publication attempts.

Revision ID: 0006_session_publications
Revises: 0005_organization_chats

Plain SQLAlchemy types keep this revision independent of application code.
"""

import sqlalchemy as sa

from alembic import op

revision = "0006_session_publications"
down_revision = "0005_organization_chats"
branch_labels = None
depends_on = None

ACTIVE = "status IN ('publishing', 'publish_unknown', 'published')"


def upgrade() -> None:
    op.create_table(
        "session_publications",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), nullable=False),
        sa.Column("session_id", sa.Integer(), nullable=False),
        sa.Column("organization_chat_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("requested_by", sa.Integer(), nullable=False),
        sa.Column("lease_expires_at", sa.DateTime(), nullable=False),
        sa.Column("telegram_message_id", sa.BigInteger()),
        sa.Column("failure", sa.String(64)),
        sa.Column("resolved_by", sa.Integer()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "status IN ('publishing', 'published', 'publish_unknown', 'failed')",
            name="valid_publication_status",
        ),
        sa.CheckConstraint(
            "telegram_message_id IS NULL OR status = 'published'", name="message_only_published"
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "session_id"],
            ["attendance_sessions.organization_id", "attendance_sessions.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "organization_chat_id"],
            ["organization_chats.organization_id", "organization_chats.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "requested_by"],
            ["memberships.organization_id", "memberships.person_id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "resolved_by"],
            ["memberships.organization_id", "memberships.person_id"],
            ondelete="RESTRICT",
        ),
    )
    op.create_index(
        "uq_session_publications_active",
        "session_publications",
        ["session_id"],
        unique=True,
        sqlite_where=sa.text(ACTIVE),
    )
    op.create_index(
        "ix_session_publications_lease",
        "session_publications",
        ["status", "lease_expires_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_session_publications_lease", table_name="session_publications")
    op.drop_index("uq_session_publications_active", table_name="session_publications")
    op.drop_table("session_publications")
