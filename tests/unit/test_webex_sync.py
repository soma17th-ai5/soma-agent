"""Webex sync 서비스 단위 테스트.

SQLite in-memory + mock client 로 sync 흐름 전체를 검증.
"""
from __future__ import annotations

import re
from collections.abc import Iterator
from datetime import datetime, timedelta
from typing import Any
from unittest.mock import MagicMock

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from app.adapters.qdrant_client import QdrantAdapter
from app.adapters.solar_client import SolarClient
from app.config import get_settings
from app.domain.models import Base
from app.domain.models.webex import WebexMessage, WebexRoom
from app.services import webex as webex_sync
from app.utils import hashing


@pytest.fixture(autouse=True)
def _set_salt(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("WEBEX_SENDER_SALT", "test-salt-v1")
    get_settings.cache_clear()
    hashing.reset_salt_cache()


@pytest.fixture
def db() -> Iterator[Session]:
    """SQLite in-memory + ORM 메타데이터 create_all."""
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(
        bind=engine, autoflush=False, autocommit=False, expire_on_commit=False
    )
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


class FakeWebexClient:
    """`run_sync` 가 사용하는 인터페이스만 구현한 mock."""

    def __init__(
        self,
        rooms: list[dict[str, Any]],
        messages_by_room: dict[str, list[dict[str, Any]]],
    ) -> None:
        self.rooms = rooms
        self.messages_by_room = messages_by_room

    def list_rooms(self, room_type: str = "group") -> Iterator[dict[str, Any]]:
        yield from (r for r in self.rooms if r.get("type") == room_type)

    def list_messages(self, room_id: str, **_: Any) -> Iterator[dict[str, Any]]:
        # Webex 응답 순서(최신→과거)를 모방.
        msgs = sorted(
            self.messages_by_room.get(room_id, []),
            key=lambda m: m["created"],
            reverse=True,
        )
        yield from msgs


_NOW = datetime(2026, 5, 5, 12, 0, 0)
_ROOM_PAYLOAD = {
    "id": "ROOM1",
    "title": "soma17 main",
    "type": "group",
    "isLocked": False,
    "isPublic": False,
    "isAnnouncementOnly": False,
    "teamId": None,
    "creatorId": "creator-pid",
    "description": "main room",
    "created": "2026-04-01T00:00:00.000Z",
    "lastActivity": "2026-05-05T11:00:00.000Z",
}


def _msg(
    msg_id: str,
    *,
    created: str,
    updated: str | None = None,
    person_id: str = "person-A",
    email: str = "alice@example.com",
    text: str = "hello",
    parent_id: str | None = None,
    mentioned_people: list[str] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "id": msg_id,
        "roomId": "ROOM1",
        "roomType": "group",
        "personId": person_id,
        "personEmail": email,
        "text": text,
        "markdown": text,
        "html": f"<p>{text}</p>",
        "created": created,
        "parentId": parent_id,
    }
    if updated is not None:
        payload["updated"] = updated
    if mentioned_people is not None:
        payload["mentionedPeople"] = mentioned_people
    return payload


def test_should_insertNewRoomAndMessages_when_firstSync(db: Session) -> None:
    client = FakeWebexClient(
        rooms=[_ROOM_PAYLOAD],
        messages_by_room={
            "ROOM1": [
                _msg("M1", created="2026-05-05T10:00:00.000Z"),
                _msg("M2", created="2026-05-05T10:30:00.000Z"),
            ]
        },
    )

    stats = webex_sync.run_sync(db, client, now=_NOW)  # type: ignore[arg-type]

    assert stats.rooms_processed == 1
    assert stats.rooms_skipped == 0
    assert stats.messages_inserted == 2

    room = db.execute(select(WebexRoom)).scalar_one()
    assert room.room_id == "ROOM1"
    assert room.last_synced_at is not None
    # creator_key 가 HMAC-32hex 형태인지.
    assert room.creator_key is not None
    assert re.fullmatch(r"[0-9a-f]{32}", room.creator_key)

    msgs = db.execute(select(WebexMessage)).scalars().all()
    assert len(msgs) == 2
    for m in msgs:
        # sender_key 익명화 검증 — 평문이 새지 않음.
        assert re.fullmatch(r"[0-9a-f]{32}", m.sender_key)
        assert "person-A" not in m.sender_key


def test_should_skipUnchangedRoom_when_lastActivityNotAfterLastSynced(
    db: Session,
) -> None:
    """`last_activity_at <= last_synced_at` 인 룸은 메시지 단계 skip."""
    # 사전 상태: 룸이 이미 동기화되어 있고 last_activity 가 더 과거.
    pre_sync = datetime(2026, 5, 5, 11, 0, 0)
    db.add(
        WebexRoom(
            room_id="ROOM1",
            room_name="soma17 main",
            room_type="group",
            is_locked=False,
            is_public=False,
            is_announcement_only=False,
            room_created_at=datetime(2026, 4, 1),
            last_activity_at=datetime(2026, 5, 5, 10, 0, 0),
            last_synced_at=pre_sync,
        )
    )
    db.commit()

    payload = dict(_ROOM_PAYLOAD)
    # 응답상 last_activity 가 사전 last_synced 보다 과거.
    payload["lastActivity"] = "2026-05-05T10:00:00.000Z"

    client = FakeWebexClient(
        rooms=[payload],
        messages_by_room={"ROOM1": [_msg("M1", created="2026-05-05T09:00:00.000Z")]},
    )
    stats = webex_sync.run_sync(db, client, now=_NOW)  # type: ignore[arg-type]

    assert stats.rooms_skipped == 1
    assert stats.rooms_processed == 0
    assert stats.messages_inserted == 0


def test_should_updateEditedMessage_when_existingMessageHasNewUpdatedField(
    db: Session,
) -> None:
    """24h 윈도우 재조회로 `edited_at` 변경분 흡수."""
    # 1차 sync — 메시지 1개 insert.
    first_client = FakeWebexClient(
        rooms=[_ROOM_PAYLOAD],
        messages_by_room={
            "ROOM1": [_msg("M1", created="2026-05-05T11:30:00.000Z", text="original")]
        },
    )
    webex_sync.run_sync(db, first_client, now=_NOW)  # type: ignore[arg-type]

    # 2차 sync — 메시지 편집으로 룸 lastActivity 도 진전 (이전 last_synced_at 이후).
    payload2 = dict(_ROOM_PAYLOAD)
    payload2["lastActivity"] = "2026-05-05T12:30:00.000Z"
    second_client = FakeWebexClient(
        rooms=[payload2],
        messages_by_room={
            "ROOM1": [
                _msg(
                    "M1",
                    created="2026-05-05T11:30:00.000Z",
                    updated="2026-05-05T11:45:00.000Z",
                    text="edited",
                )
            ]
        },
    )
    later_now = _NOW + timedelta(hours=1)
    stats = webex_sync.run_sync(db, second_client, now=later_now)  # type: ignore[arg-type]

    assert stats.messages_inserted == 0
    assert stats.messages_updated == 1

    msg = db.execute(select(WebexMessage)).scalar_one()
    assert msg.edited_at is not None
    assert msg.text == "edited"


def test_should_breakLoop_when_messageOlderThanCutoff(db: Session) -> None:
    """24h 재조회 윈도우 외부 메시지(사전 last_synced 기준 24h 이전)는 무시."""
    pre_sync = datetime(2026, 5, 5, 11, 0, 0)
    db.add(
        WebexRoom(
            room_id="ROOM1",
            room_name="soma17 main",
            room_type="group",
            is_locked=False,
            is_public=False,
            is_announcement_only=False,
            room_created_at=datetime(2026, 4, 1),
            last_activity_at=datetime(2026, 5, 5, 12, 0, 0),
            last_synced_at=pre_sync,
        )
    )
    db.commit()

    payload = dict(_ROOM_PAYLOAD)
    payload["lastActivity"] = "2026-05-05T12:30:00.000Z"

    # cutoff = 2026-05-04 11:00. 그 이전 메시지가 섞여도 break.
    client = FakeWebexClient(
        rooms=[payload],
        messages_by_room={
            "ROOM1": [
                _msg("NEW", created="2026-05-05T12:00:00.000Z"),
                _msg("OLD", created="2026-05-03T10:00:00.000Z"),  # cutoff 이전
            ]
        },
    )
    stats = webex_sync.run_sync(db, client, now=_NOW)  # type: ignore[arg-type]

    assert stats.messages_inserted == 1
    msgs = db.execute(select(WebexMessage)).scalars().all()
    assert {m.message_id for m in msgs} == {"NEW"}


def test_should_markBotSender_when_emailEndsWithWebexBot(db: Session) -> None:
    client = FakeWebexClient(
        rooms=[_ROOM_PAYLOAD],
        messages_by_room={
            "ROOM1": [
                _msg(
                    "BOT1",
                    created="2026-05-05T10:00:00.000Z",
                    person_id="bot-pid",
                    email="somabot@webex.bot",
                    text="hi",
                ),
                _msg(
                    "HUMAN1",
                    created="2026-05-05T10:01:00.000Z",
                    person_id="alice-pid",
                    email="alice@example.com",
                ),
            ]
        },
    )
    webex_sync.run_sync(db, client, now=_NOW)  # type: ignore[arg-type]

    by_id = {
        m.message_id: m
        for m in db.execute(select(WebexMessage)).scalars().all()
    }
    assert by_id["BOT1"].is_bot_sender is True
    assert by_id["HUMAN1"].is_bot_sender is False
    # 봇 메시지도 RDB 저장은 함 (SPEC §7.4).
    assert by_id["BOT1"].text == "hi"


def test_should_anonymizeMentionedPeople_when_present(db: Session) -> None:
    client = FakeWebexClient(
        rooms=[_ROOM_PAYLOAD],
        messages_by_room={
            "ROOM1": [
                _msg(
                    "M1",
                    created="2026-05-05T10:00:00.000Z",
                    mentioned_people=["pid-1", "pid-2"],
                )
            ]
        },
    )
    webex_sync.run_sync(db, client, now=_NOW)  # type: ignore[arg-type]

    msg = db.execute(select(WebexMessage)).scalar_one()
    assert msg.mentioned_person_keys is not None
    assert len(msg.mentioned_person_keys) == 2
    for key in msg.mentioned_person_keys:
        assert re.fullmatch(r"[0-9a-f]{32}", key)
    # 평문 person id 가 새지 않음.
    assert "pid-1" not in msg.mentioned_person_keys
    assert "pid-2" not in msg.mentioned_person_keys


def test_should_storeFilesAndAttachmentsSeparately_when_present(db: Session) -> None:
    payload = _msg("M1", created="2026-05-05T10:00:00.000Z")
    payload["files"] = ["https://webex.com/files/a.pdf"]
    payload["attachments"] = [{"contentType": "application/vnd.microsoft.card.adaptive"}]

    client = FakeWebexClient(
        rooms=[_ROOM_PAYLOAD], messages_by_room={"ROOM1": [payload]}
    )
    webex_sync.run_sync(db, client, now=_NOW)  # type: ignore[arg-type]

    msg = db.execute(select(WebexMessage)).scalar_one()
    assert msg.files == ["https://webex.com/files/a.pdf"]
    assert msg.attachments is not None
    assert msg.attachments[0]["contentType"].endswith("card.adaptive")


def test_should_updateRoomMetadata_when_secondSync(db: Session) -> None:
    """1차 후 2차 sync — 룸 이름/플래그 갱신."""
    client1 = FakeWebexClient(
        rooms=[_ROOM_PAYLOAD],
        messages_by_room={"ROOM1": []},
    )
    webex_sync.run_sync(db, client1, now=_NOW)  # type: ignore[arg-type]

    payload2 = dict(_ROOM_PAYLOAD)
    payload2["title"] = "soma17 main (renamed)"
    payload2["lastActivity"] = "2026-05-06T10:00:00.000Z"
    client2 = FakeWebexClient(rooms=[payload2], messages_by_room={"ROOM1": []})
    later = _NOW + timedelta(days=1)
    webex_sync.run_sync(db, client2, now=later)  # type: ignore[arg-type]

    room = db.execute(select(WebexRoom)).scalar_one()
    assert room.room_name == "soma17 main (renamed)"
    assert room.last_synced_at is not None
    assert room.last_synced_at >= room.last_activity_at  # type: ignore[operator]


def test_should_indexMessagesToQdrant_when_qdrantAndSolarProvided(db: Session) -> None:
    """qdrant/solar 가 주입되면 메시지를 인덱싱해야 함."""
    client = FakeWebexClient(
        rooms=[_ROOM_PAYLOAD],
        messages_by_room={
            "ROOM1": [
                _msg("M1", created="2026-05-05T10:00:00.000Z", text="hello qdrant"),
            ]
        },
    )
    mock_qdrant = MagicMock(spec=QdrantAdapter)
    mock_solar = MagicMock(spec=SolarClient)
    # solar.embed_passages 가 호출되므로 리턴값 설정 (rag_indexer 가 내부에서 사용)
    mock_solar.embed_passages.return_value = [[0.1] * 128]

    stats = webex_sync.run_sync(
        db, client, qdrant=mock_qdrant, solar=mock_solar, now=_NOW
    )

    assert stats.messages_inserted == 1
    assert stats.messages_indexed == 1
    assert mock_qdrant.upsert.called
    assert mock_solar.embed_passages.called
