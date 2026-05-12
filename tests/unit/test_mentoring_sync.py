"""멘토링 동기화 서비스 — 객체 응답 컬럼 분할 + applicants HMAC."""
from __future__ import annotations

from datetime import date
from typing import Any

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.domain.models import Base
from app.domain.models.mentoring import Mentoring, MentoringApplicant
from app.services import mentoring as mentoring_service


@pytest.fixture(autouse=True)
def _set_salt(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("WEBEX_SENDER_SALT", "test-salt-32chars-min-aaaaaaaa")
    # get_settings()는 lru_cache라 cache flush 필요. 새 Settings 강제.
    from app import config as app_config
    app_config.get_settings.cache_clear()
    yield
    app_config.get_settings.cache_clear()


class FakeOpenSoma:
    def __init__(self, list_pages: list[dict[str, Any]], details: dict[int, dict[str, Any]]):
        self._list_pages = list_pages
        self._details = details
        self.detail_calls: list[int] = []

    def mentoring_list(self, session_id: str, page: int = 1, **_: Any) -> dict[str, Any]:
        return self._list_pages[page - 1] if page <= len(self._list_pages) else {"items": []}

    def mentoring_get(self, session_id: str, mentoring_id: int) -> dict[str, Any]:
        self.detail_calls.append(mentoring_id)
        return self._details[mentoring_id]


class FakeQdrant:
    def __init__(self) -> None:
        self.deleted: list[tuple[str, str]] = []
        self.upserted = 0
        self.existing_sources: set[tuple[str, str]] = set()

    def delete_by_source(self, source_type: str, source_id: str) -> None:
        self.deleted.append((source_type, source_id))

    def upsert(self, points: list[Any]) -> None:
        self.upserted += len(points)

    def source_exists(self, source_type: str, source_id: str) -> bool:
        return (source_type, source_id) in self.existing_sources


class FakeSolar:
    def embed_passages(self, texts: list[str]) -> list[list[float]]:
        return [[0.1] * 4096 for _ in texts]


@pytest.fixture
def db() -> Session:
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    return SessionLocal()


_SAMPLE_LIST_ITEM = {
    "id": 10786,
    "title": "[CSBE] Ch.2 — print() 한 줄이 API를 140배 느리게",
    "type": "멘토 특강",
    "registrationPeriod": {"start": "2026-04-27", "end": "2026-05-31"},
    "sessionDate": "2026-05-31",
    "sessionTime": {"start": "20:00", "end": "22:00"},
    "attendees": {"current": 20, "max": 20},
    "approved": True,
    "status": "마감",
    "author": "장태영",
    "createdAt": "2026-04-26",
}

_SAMPLE_DETAIL = {
    "id": 10786,
    "title": _SAMPLE_LIST_ITEM["title"],
    "content": "<p>설명</p>",
    "venue": "온라인 Webex",
    "applicants": [
        {"name": "홍길동", "appliedAt": "2026-04-27", "status": "approved"},
        {"name": "김철수", "appliedAt": "2026-04-28", "status": "approved"},
    ],
}


def test_should_splitObjectFields_when_listItemHasNestedStructure(db: Session) -> None:
    fake = FakeOpenSoma(
        [{"items": [_SAMPLE_LIST_ITEM], "pagination": {"totalPages": 1}}],
        {10786: _SAMPLE_DETAIL},
    )
    stats = mentoring_service.run_sync(db, fake, session_id="sid")  # type: ignore[arg-type]
    assert stats.inserted == 1
    row = db.execute(select(Mentoring)).scalar_one()
    assert row.mentoring_type == "멘토 특강"
    assert row.mentoring_status == "마감"
    assert row.attendees_current == 20
    assert row.attendees_max == 20
    assert row.approved is True
    assert row.session_date.isoformat() == "2026-05-31"
    assert row.session_start_time.strftime("%H:%M") == "20:00"
    assert row.session_end_time.strftime("%H:%M") == "22:00"
    assert row.session_started_at is not None
    assert row.session_started_at.hour == 20
    assert row.content_html is None
    assert row.venue is None
    assert fake.detail_calls == []


def test_should_notPersistApplicants_when_syncingListOnly(db: Session) -> None:
    fake = FakeOpenSoma(
        [{"items": [_SAMPLE_LIST_ITEM], "pagination": {"totalPages": 1}}],
        {10786: _SAMPLE_DETAIL},
    )
    stats = mentoring_service.run_sync(db, fake, session_id="sid")  # type: ignore[arg-type]
    rows = db.execute(select(MentoringApplicant)).scalars().all()
    assert rows == []
    assert stats.applicants_persisted == 0
    assert fake.detail_calls == []


def test_should_preserveDetailOnlyFields_when_resyncingListOnly(db: Session) -> None:
    fake = FakeOpenSoma(
        [{"items": [_SAMPLE_LIST_ITEM], "pagination": {"totalPages": 1}}],
        {10786: _SAMPLE_DETAIL},
    )
    mentoring_service.run_sync(db, fake, session_id="sid")  # type: ignore[arg-type]
    row = db.execute(select(Mentoring)).scalar_one()
    row.content_html = "<p>기존 상세</p>"
    row.venue = "기존 장소"
    db.commit()

    # 응답이 바뀐 상태 시뮬레이션 (content_hash 변경 유도)
    item2 = dict(_SAMPLE_LIST_ITEM, status="진행중")
    fake2 = FakeOpenSoma(
        [{"items": [item2], "pagination": {"totalPages": 1}}],
        {10786: _SAMPLE_DETAIL},
    )
    stats = mentoring_service.run_sync(db, fake2, session_id="sid")  # type: ignore[arg-type]
    assert stats.updated == 1
    row = db.execute(select(Mentoring)).scalar_one()
    assert row.mentoring_status == "진행중"
    assert row.content_html == "<p>기존 상세</p>"
    assert row.venue == "기존 장소"
    assert fake2.detail_calls == []


def test_should_skipUnchanged_when_listResponseIdentical(db: Session) -> None:
    fake = FakeOpenSoma(
        [{"items": [_SAMPLE_LIST_ITEM], "pagination": {"totalPages": 1}}],
        {10786: _SAMPLE_DETAIL},
    )
    mentoring_service.run_sync(db, fake, session_id="sid")  # type: ignore[arg-type]
    stats = mentoring_service.run_sync(db, fake, session_id="sid")  # type: ignore[arg-type]
    assert stats.skipped == 1
    assert stats.inserted == 0


def test_should_indexOnlyTodayOrFutureMentorings_when_qdrantEnabled(db: Session) -> None:
    past = dict(_SAMPLE_LIST_ITEM, id=1, title="어제 멘토링", sessionDate="2026-05-08")
    today = dict(_SAMPLE_LIST_ITEM, id=2, title="오늘 멘토링", sessionDate="2026-05-09")
    future = dict(_SAMPLE_LIST_ITEM, id=3, title="내일 멘토링", sessionDate="2026-05-10")
    fake = FakeOpenSoma(
        [{"items": [past, today, future], "pagination": {"totalPages": 1}}],
        {},
    )
    qdrant = FakeQdrant()
    solar = FakeSolar()

    stats = mentoring_service.run_sync(
        db,
        fake,
        session_id="sid",
        qdrant=qdrant,  # type: ignore[arg-type]
        solar=solar,  # type: ignore[arg-type]
        today=date(2026, 5, 9),
    )

    assert stats.inserted == 3
    assert stats.indexed == 2
    assert stats.removed_from_index == 1
    assert qdrant.deleted == [
        ("MENTORING", "1"),
        ("MENTORING", "2"),
        ("MENTORING", "3"),
    ]
    assert qdrant.upserted == 2
    rows = db.execute(select(Mentoring).order_by(Mentoring.mentoring_id)).scalars().all()
    assert [row.is_active for row in rows] == [False, True, True]


def test_should_deletePastMentoringFromIndex_when_itemUnchanged(db: Session) -> None:
    past = dict(_SAMPLE_LIST_ITEM, id=1, title="어제 멘토링", sessionDate="2026-05-08")
    fake = FakeOpenSoma(
        [{"items": [past], "pagination": {"totalPages": 1}}],
        {},
    )
    mentoring_service.run_sync(db, fake, session_id="sid", today=date(2026, 5, 9))  # type: ignore[arg-type]
    qdrant = FakeQdrant()

    stats = mentoring_service.run_sync(
        db,
        fake,
        session_id="sid",
        qdrant=qdrant,  # type: ignore[arg-type]
        today=date(2026, 5, 9),
    )

    assert stats.skipped == 1
    assert stats.removed_from_index == 1
    assert qdrant.deleted == [("MENTORING", "1")]


def test_should_reindexUnchangedFutureMentoring_when_qdrantSourceMissing(db: Session) -> None:
    future = dict(_SAMPLE_LIST_ITEM, id=2, title="오늘 멘토링", sessionDate="2026-05-09")
    fake = FakeOpenSoma(
        [{"items": [future], "pagination": {"totalPages": 1}}],
        {},
    )
    mentoring_service.run_sync(db, fake, session_id="sid", today=date(2026, 5, 9))  # type: ignore[arg-type]
    qdrant = FakeQdrant()
    solar = FakeSolar()

    stats = mentoring_service.run_sync(
        db,
        fake,
        session_id="sid",
        qdrant=qdrant,  # type: ignore[arg-type]
        solar=solar,  # type: ignore[arg-type]
        today=date(2026, 5, 9),
    )

    assert stats.skipped == 1
    assert stats.indexed == 1
    assert qdrant.deleted == [("MENTORING", "2")]
    assert qdrant.upserted == 1


def test_should_markUnchangedPastMentoringInactive_when_resyncing(db: Session) -> None:
    past = dict(_SAMPLE_LIST_ITEM, id=1, title="어제 멘토링", sessionDate="2026-05-08")
    fake = FakeOpenSoma(
        [{"items": [past], "pagination": {"totalPages": 1}}],
        {},
    )
    mentoring_service.run_sync(db, fake, session_id="sid", today=date(2026, 5, 8))  # type: ignore[arg-type]
    row = db.execute(select(Mentoring)).scalar_one()
    assert row.is_active is True

    stats = mentoring_service.run_sync(db, fake, session_id="sid", today=date(2026, 5, 9))  # type: ignore[arg-type]

    row = db.execute(select(Mentoring)).scalar_one()
    assert row.is_active is False
    assert stats.skipped == 1
    assert stats.updated == 1
