"""Add registered organization chats.

Revision ID: 0005_organization_chats
Revises: 0004_attendance

Plain SQLAlchemy types keep this revision independent of application code.
"""

import sqlalchemy as sa

from alembic import op

revision = "0005_organization_chats"
down_revision = "0004_attendance"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "organization_chats",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), nullable=False),
        sa.Column("telegram_chat_id", sa.BigInteger(), nullable=False),
        sa.Column("chat_type", sa.String(10), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("registered_by", sa.Integer(), nullable=False),
        sa.Column("registered_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("organization_id", "id", name="uq_organization_chats_org_id"),
        sa.UniqueConstraint("telegram_chat_id", name="uq_organization_chats_telegram_chat_id"),
        sa.CheckConstraint("chat_type IN ('group', 'supergroup')", name="valid_chat_type"),
        sa.CheckConstraint("length(title) BETWEEN 1 AND 200", name="valid_title"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["organization_id", "registered_by"],
            ["memberships.organization_id", "memberships.person_id"],
            ondelete="RESTRICT",
        ),
    )


def downgrade() -> None:
    op.drop_table("organization_chats")
