"""Webex 룸/메시지 ORM. SPEC §3.1 webex_rooms, webex_messages.

설계 메모:
- `room_type` / `mentioned_groups` 등 enum/json 컬럼은 MySQL 방언 의존.
  단위 테스트는 SQLite in-memory 를 쓰므로, 컬럼 정의는 `Enum` /
  `JSON` (vendor-neutral) 로 작성하고 길이 제약은 `String(N)` 으로 명시한다.
- `creator_key`, `sender_key` 는 SPEC §8.2 HMAC 익명화 결과(32-hex).
- `edited_at` 은 Webex API 의 `updated` 필드 — 수정된 메시지에만 존재.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.domain.models import Base

# Webex 룸 타입은 group/direct 만 사용 (huddle 등 신규 타입은 v2).
ROOM_TYPES = ("group", "direct")

# SQLite 는 BIGINT PRIMARY KEY autoincrement 를 지원하지 않으므로
# 단위 테스트에서는 INTEGER 로 fallback (운영은 MySQL BIGINT 그대로).
_PK_TYPE = BigInteger().with_variant(Integer, "sqlite")


class WebexRoom(Base):
    """Webex Space (room). MVP는 `group` 타입만 수집한다.

    `last_synced_at` 은 우리 워터마크. `last_activity_at < last_synced_at` 인
    룸은 다음 sync 사이클에서 메시지 페이지네이션을 건너뛴다.
    """

    __tablename__ = "webex_rooms"

    id: Mapped[int] = mapped_column(_PK_TYPE, primary_key=True, autoincrement=True)
    room_id: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    room_name: Mapped[str | None] = mapped_column(String(500), nullable=True)
    room_type: Mapped[str] = mapped_column(
        Enum(*ROOM_TYPES, name="webex_room_type"), nullable=False
    )
    is_locked: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_public: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_announcement_only: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )
    team_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    creator_key: Mapped[str | None] = mapped_column(String(32), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    room_created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    last_activity_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    messages: Mapped[list[WebexMessage]] = relationship(
        "WebexMessage",
        back_populates="room",
        primaryjoin="WebexRoom.room_id == WebexMessage.room_id",
        foreign_keys="WebexMessage.room_id",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class WebexMessage(Base):
    """Webex Message. `parent_id` 는 스레드 루트.

    `edited_at` 은 Webex `updated` 필드(수정된 메시지에만 존재).
    `mentioned_person_keys` 는 HMAC 익명화된 personId 목록.
    `files` 는 Webex 응답의 파일 URL 배열, `attachments` 는 Adaptive Card 정의.
    """

    __tablename__ = "webex_messages"

    id: Mapped[int] = mapped_column(_PK_TYPE, primary_key=True, autoincrement=True)
    message_id: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    room_id: Mapped[str] = mapped_column(
        String(255),
        ForeignKey("webex_rooms.room_id", ondelete="CASCADE"),
        nullable=False,
    )
    room_type: Mapped[str | None] = mapped_column(
        Enum(*ROOM_TYPES, name="webex_room_type"), nullable=True
    )
    parent_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    sender_key: Mapped[str] = mapped_column(String(32), nullable=False)
    is_bot_sender: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    text: Mapped[str | None] = mapped_column(Text, nullable=True)
    markdown: Mapped[str | None] = mapped_column(Text, nullable=True)
    html: Mapped[str | None] = mapped_column(Text, nullable=True)
    mentioned_person_keys: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    mentioned_groups: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    files: Mapped[list[Any] | None] = mapped_column(JSON, nullable=True)
    attachments: Mapped[list[Any] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    edited_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    collected_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    room: Mapped[WebexRoom] = relationship(
        "WebexRoom",
        back_populates="messages",
        primaryjoin="WebexRoom.room_id == WebexMessage.room_id",
        foreign_keys="WebexMessage.room_id",
    )

    __table_args__ = (
        Index("ix_webex_messages_room_created", "room_id", "created_at"),
        Index("ix_webex_messages_parent_id", "parent_id"),
        Index("ix_webex_messages_edited_at", "edited_at"),
    )
