"""add webex rooms and messages

Revision ID: 001_webex
Revises:
Create Date: 2026-05-05 11:30:00.000000

SPEC §3.1: webex_rooms / webex_messages.

설계 결정:
- room_type 은 ENUM('group','direct') (MySQL ENUM 사용).
- 시간 컬럼은 DATETIME(3) 으로 ms 정밀도 (Webex API 의 ISO8601 ms 보존).
- creator_key/sender_key 는 CHAR(32) — HMAC-SHA256 hexdigest 앞 32자.
- mentioned_*, files, attachments 는 JSON 컬럼.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

# revision identifiers, used by Alembic.
revision = "001_webex"
down_revision: str | None = None
branch_labels: tuple[str, ...] | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "webex_rooms",
        sa.Column("id", sa.BigInteger(), autoincrement=True, primary_key=True),
        sa.Column("room_id", sa.String(length=255), nullable=False, unique=True),
        sa.Column("room_name", sa.String(length=500), nullable=True),
        sa.Column(
            "room_type",
            sa.Enum("group", "direct", name="webex_room_type"),
            nullable=False,
        ),
        sa.Column("is_locked", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("is_public", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column(
            "is_announcement_only",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column("team_id", sa.String(length=255), nullable=True),
        sa.Column("creator_key", sa.CHAR(length=32), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "room_created_at",
            mysql.DATETIME(fsp=3),
            nullable=False,
        ),
        sa.Column(
            "last_activity_at",
            mysql.DATETIME(fsp=3),
            nullable=True,
        ),
        sa.Column(
            "last_synced_at",
            mysql.DATETIME(fsp=3),
            nullable=True,
        ),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
    )

    op.create_table(
        "webex_messages",
        sa.Column("id", sa.BigInteger(), autoincrement=True, primary_key=True),
        sa.Column("message_id", sa.String(length=255), nullable=False, unique=True),
        sa.Column("room_id", sa.String(length=255), nullable=False),
        sa.Column(
            "room_type",
            sa.Enum("group", "direct", name="webex_room_type"),
            nullable=True,
        ),
        sa.Column("parent_id", sa.String(length=255), nullable=True),
        sa.Column("sender_key", sa.CHAR(length=32), nullable=False),
        sa.Column(
            "is_bot_sender",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column("text", mysql.MEDIUMTEXT(), nullable=True),
        sa.Column("markdown", mysql.MEDIUMTEXT(), nullable=True),
        sa.Column("html", mysql.MEDIUMTEXT(), nullable=True),
        sa.Column("mentioned_person_keys", sa.JSON(), nullable=True),
        sa.Column("mentioned_groups", sa.JSON(), nullable=True),
        sa.Column("files", sa.JSON(), nullable=True),
        sa.Column("attachments", sa.JSON(), nullable=True),
        sa.Column(
            "created_at",
            mysql.DATETIME(fsp=3),
            nullable=False,
        ),
        sa.Column(
            "edited_at",
            mysql.DATETIME(fsp=3),
            nullable=True,
        ),
        sa.Column(
            "collected_at",
            mysql.DATETIME(fsp=3),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["room_id"],
            ["webex_rooms.room_id"],
            ondelete="CASCADE",
            name="fk_webex_messages_room_id",
        ),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
    )

    op.create_index(
        "ix_webex_messages_room_created",
        "webex_messages",
        ["room_id", "created_at"],
    )
    op.create_index(
        "ix_webex_messages_parent_id",
        "webex_messages",
        ["parent_id"],
    )
    op.create_index(
        "ix_webex_messages_edited_at",
        "webex_messages",
        ["edited_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_webex_messages_edited_at", table_name="webex_messages")
    op.drop_index("ix_webex_messages_parent_id", table_name="webex_messages")
    op.drop_index("ix_webex_messages_room_created", table_name="webex_messages")
    op.drop_table("webex_messages")
    op.drop_table("webex_rooms")
