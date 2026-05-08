"""Webex 동기화 서비스. SPEC §7.4.

함수 위주 — 의존성(`db`, `client`) 은 인자로 주입받아 단위 테스트하기 쉽게.

흐름 요약:
  1. `client.list_rooms('group')` → group 룸 upsert.
  2. 활동 룸별 `list_messages` 페이지네이션:
       - 응답이 desc(최신→과거) 라서 `created_at` 이 cutoff 보다 작아질 때까지만 수집.
       - cutoff = (last_synced_at - 24h) 로 두어 수정 메시지 흡수 윈도우 확보.
  3. 각 메시지: HMAC 익명화 + upsert.
  4. `webex_rooms.last_synced_at = max(last_activity_at, now)`.

수정/삭제 한계: SPEC §7.4 — Compliance Events API 가 없으므로 24h 윈도우
재조회로 `edited_at` 변경분만 흡수. 삭제는 v2 Webhook.

이번 이슈 범위는 RDB 저장 + 익명화 + Qdrant 인덱싱.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

import structlog
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.adapters.webex_client import WebexClient
from app.domain.contracts.knowledge import KnowledgeSourceType
from app.domain.models.webex import WebexMessage, WebexRoom
from app.services.rag_indexer import index_chunks
from app.utils.hashing import anonymize_many, anonymize_person_id

if TYPE_CHECKING:
    from app.adapters.qdrant_client import QdrantAdapter
    from app.adapters.solar_client import SolarClient

logger = structlog.get_logger(__name__)

# 매 사이클 재조회 윈도우 — 수정 메시지 흡수용 (SPEC §7.4).
_RESCAN_WINDOW = timedelta(hours=24)
_BOT_EMAIL_SUFFIX = "@webex.bot"


@dataclass
class SyncStats:
    """`run_sync` 결과 메트릭."""

    rooms_processed: int = 0
    rooms_skipped: int = 0
    messages_inserted: int = 0
    messages_updated: int = 0
    messages_indexed: int = 0


def run_sync(
    db: Session,
    client: WebexClient,
    *,
    qdrant: QdrantAdapter | None = None,
    solar: SolarClient | None = None,
    now: datetime | None = None,
) -> SyncStats:
    """Webex 동기화 1회 실행. SPEC §7.4 진입점.

    Args:
        db: SQLAlchemy 세션 (sync).
        client: Webex API 어댑터.
        qdrant: Qdrant 어댑터 (인덱싱용).
        solar: Solar API 어댑터 (임베딩용).
        now: 현재 시각 (테스트에서 주입). 기본은 UTC now.

    Returns:
        SyncStats — 처리된 룸/메시지 카운트.
    """
    current_time = now or _utc_now()
    stats = SyncStats()

    for room_payload in client.list_rooms(room_type="group"):
        room, was_skipped = _upsert_room(db, room_payload, now=current_time)
        if was_skipped:
            stats.rooms_skipped += 1
            continue

        stats.rooms_processed += 1

        cutoff = _calc_cutoff(room.last_synced_at, current_time)

        room_inserted = 0
        room_updated = 0
        room_indexed = 0
        for msg_payload in client.list_messages(room_id=room.room_id):
            created_at = _parse_iso(msg_payload.get("created"))
            if created_at and created_at < cutoff:
                # desc 정렬이라 cutoff 이전이면 더 이상 새 메시지 없음.
                break
            inserted, updated = _upsert_message(
                db, msg_payload, default_room_type=room.room_type, now=current_time
            )
            room_inserted += int(inserted)
            room_updated += int(updated)

            # 신규 또는 수정된 메시지면 Qdrant 인덱싱 수행
            if (inserted or updated) and qdrant and solar and msg_payload.get("text"):
                index_chunks(
                    qdrant,
                    solar,
                    source_type=KnowledgeSourceType.WEBEX_MESSAGE,
                    source_id=msg_payload["id"],
                    title=f"Message in {room.room_name}",
                    texts=[msg_payload.get("text")],
                    official=False,
                    room_name=room.room_name,
                    created_at=created_at,
                )
                room_indexed += 1

        stats.messages_inserted += room_inserted
        stats.messages_updated += room_updated
        stats.messages_indexed += room_indexed

        # 워터마크는 last_activity_at 과 now 중 더 큰 값 (SPEC §7.4).
        room.last_synced_at = (
            max(room.last_activity_at, current_time)
            if room.last_activity_at
            else current_time
        )

        logger.info(
            "webex.room_synced",
            room_id=room.room_id,
            inserted=room_inserted,
            updated=room_updated,
        )

    db.commit()
    logger.info(
        "webex.sync_done",
        rooms_processed=stats.rooms_processed,
        rooms_skipped=stats.rooms_skipped,
        messages_inserted=stats.messages_inserted,
        messages_updated=stats.messages_updated,
        messages_indexed=stats.messages_indexed,
    )
    return stats


# ============================================================ helpers (room)


def _upsert_room(
    db: Session, payload: dict[str, Any], *, now: datetime
) -> tuple[WebexRoom, bool]:
    """룸 upsert. `last_activity_at <= last_synced_at` 면 메시지 동기화 skip.

    Returns:
        (room, skip_messages) — skip_messages 가 True 면 호출자가 메시지 단계 생략.
    """
    room_id = payload["id"]
    room: WebexRoom | None = db.execute(
        select(WebexRoom).where(WebexRoom.room_id == room_id)
    ).scalar_one_or_none()

    last_activity = _parse_iso(payload.get("lastActivity"))
    creator_id = payload.get("creatorId")
    creator_key = anonymize_person_id(creator_id) if creator_id else None

    if room is None:
        room = WebexRoom(
            room_id=room_id,
            room_name=payload.get("title"),
            room_type=payload.get("type", "group"),
            is_locked=bool(payload.get("isLocked", False)),
            is_public=bool(payload.get("isPublic", False)),
            is_announcement_only=bool(payload.get("isAnnouncementOnly", False)),
            team_id=payload.get("teamId"),
            creator_key=creator_key,
            description=payload.get("description"),
            room_created_at=_parse_iso(payload.get("created")) or now,
            last_activity_at=last_activity,
            last_synced_at=None,
        )
        db.add(room)
        db.flush()
        return room, False

    # 메타 갱신 — 룸 이름/플래그는 운영 중 변경될 수 있다.
    room.room_name = payload.get("title", room.room_name)
    room.room_type = payload.get("type", room.room_type)
    room.is_locked = bool(payload.get("isLocked", room.is_locked))
    room.is_public = bool(payload.get("isPublic", room.is_public))
    room.is_announcement_only = bool(
        payload.get("isAnnouncementOnly", room.is_announcement_only)
    )
    room.team_id = payload.get("teamId", room.team_id)
    if creator_key is not None:
        room.creator_key = creator_key
    room.description = payload.get("description", room.description)
    room.last_activity_at = last_activity or room.last_activity_at

    # 활동 없는 룸은 메시지 단계 skip.
    if (
        room.last_synced_at
        and room.last_activity_at
        and room.last_activity_at <= room.last_synced_at
    ):
        return room, True

    return room, False


# ========================================================= helpers (message)


def _upsert_message(
    db: Session,
    payload: dict[str, Any],
    *,
    default_room_type: str | None,
    now: datetime,
) -> tuple[bool, bool]:
    """메시지 upsert. Returns (inserted, updated_existing)."""
    message_id = payload["id"]
    person_id = payload.get("personId")
    if not person_id:
        # personId 없는 메시지는 거의 없으나, 발견 시 sender_key 익명화 불가 → skip.
        logger.warning("webex.message_no_person", message_id=message_id)
        return False, False

    sender_key = anonymize_person_id(person_id)
    is_bot = _detect_bot(payload.get("personEmail"))
    mentioned_keys = anonymize_many(payload.get("mentionedPeople"))
    mentioned_groups = payload.get("mentionedGroups") or None
    files = payload.get("files") or None
    attachments = payload.get("attachments") or None

    created_at = _parse_iso(payload.get("created")) or now
    edited_at = _parse_iso(payload.get("updated"))  # 수정된 메시지에만 존재

    existing: WebexMessage | None = db.execute(
        select(WebexMessage).where(WebexMessage.message_id == message_id)
    ).scalar_one_or_none()

    if existing is None:
        msg = WebexMessage(
            message_id=message_id,
            room_id=payload["roomId"],
            room_type=payload.get("roomType", default_room_type),
            parent_id=payload.get("parentId"),
            sender_key=sender_key,
            is_bot_sender=is_bot,
            text=payload.get("text"),
            markdown=payload.get("markdown"),
            html=payload.get("html"),
            mentioned_person_keys=mentioned_keys,
            mentioned_groups=mentioned_groups,
            files=files,
            attachments=attachments,
            created_at=created_at,
            edited_at=edited_at,
            collected_at=now,
        )
        db.add(msg)
        db.flush()
        return True, False

    # 기존 메시지 — 수정/내용 변경 흡수.
    changed = False
    if edited_at and existing.edited_at != edited_at:
        existing.edited_at = edited_at
        changed = True
    for column, new_value in (
        ("text", payload.get("text")),
        ("markdown", payload.get("markdown")),
        ("html", payload.get("html")),
    ):
        if new_value is not None and getattr(existing, column) != new_value:
            setattr(existing, column, new_value)
            changed = True
    return False, changed


def _detect_bot(person_email: str | None) -> bool:
    """SPEC §7.4 — `@webex.bot` 휴리스틱.

    /people/{id} 캐시 기반 정확 판정은 v2(person_cache 테이블) 도입 후.
    """
    if not person_email:
        return False
    return person_email.lower().endswith(_BOT_EMAIL_SUFFIX)


# =============================================================== helpers (time)


def _calc_cutoff(last_synced_at: datetime | None, now: datetime) -> datetime:
    """24h 재조회 윈도우. last_synced_at 없으면 매우 오래전(epoch)으로."""
    if last_synced_at is None:
        # 첫 동기화 — 모든 메시지 수집. cutoff 를 epoch로 두어 break 하지 않게.
        return datetime(1970, 1, 1, tzinfo=now.tzinfo)
    return last_synced_at - _RESCAN_WINDOW


def _parse_iso(value: str | None) -> datetime | None:
    """Webex ISO8601 (`...Z`) → naive UTC datetime.

    DB 컬럼이 timezone-naive DATETIME(3) 이라 tzinfo 를 떼서 저장한다.
    """
    if not value:
        return None
    s = value.replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        logger.warning("webex.parse_iso_failed", value=value)
        return None
    if dt.tzinfo is not None:
        dt = dt.astimezone(UTC).replace(tzinfo=None)
    return dt


def _utc_now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)
