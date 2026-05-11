"""공지 동기화 서비스 — content_hash 기반 변경 감지 + 인덱싱 hooking."""
from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.domain.models import Base
from app.domain.models.notice import Notice
from app.services import notice as notice_service


class FakeOpenSoma:
    def __init__(self, list_pages: list[dict[str, Any]], details: dict[int, dict[str, Any]]):
        self._list_pages = list_pages
        self._details = details
        self.detail_calls: list[int] = []

    def notice_list(self, session_id: str, page: int = 1) -> dict[str, Any]:
        return self._list_pages[page - 1] if page <= len(self._list_pages) else {"items": []}

    def notice_get(self, session_id: str, notice_id: int) -> dict[str, Any]:
        self.detail_calls.append(notice_id)
        return self._details[notice_id]


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


def test_should_insertNewNotices_when_dbEmpty(db: Session) -> None:
    pages = [
        {
            "items": [
                {"id": 1, "title": "t1", "author": "a", "createdAt": "2026.04.01 10:00:00"},
                {"id": 2, "title": "t2", "author": "b", "createdAt": "2026.04.02 10:00:00"},
            ],
            "pagination": {"totalPages": 1},
        }
    ]
    details = {
        1: {"id": 1, "content": "<p>본문1</p>"},
        2: {"id": 2, "content": "<p>본문2</p>"},
    }
    fake = FakeOpenSoma(pages, details)

    stats = notice_service.run_sync(db, fake, session_id="sid")  # type: ignore[arg-type]

    assert stats.inserted == 2
    assert stats.skipped == 0
    rows = db.execute(select(Notice)).scalars().all()
    assert {r.notice_id for r in rows} == {1, 2}
    # content_text가 HTML 제거된 형태
    assert all("본문" in r.content_text for r in rows)


def test_should_skipUnchanged_when_contentHashMatches(db: Session) -> None:
    page = {
        "items": [
            {"id": 1, "title": "t", "author": "a", "createdAt": "2026.04.01 10:00:00"},
        ],
        "pagination": {"totalPages": 1},
    }
    details = {1: {"id": 1, "content": "<p>x</p>"}}
    fake = FakeOpenSoma([page], details)

    notice_service.run_sync(db, fake, session_id="sid")  # type: ignore[arg-type]
    fake.detail_calls.clear()

    stats = notice_service.run_sync(db, fake, session_id="sid")  # type: ignore[arg-type]
    assert stats.skipped == 1
    assert stats.inserted == 0
    assert fake.detail_calls == []  # detail 재호출 안 함


def test_should_updateExisting_when_titleChanges(db: Session) -> None:
    page1 = {
        "items": [{"id": 1, "title": "old", "author": "a", "createdAt": "2026.04.01 10:00:00"}],
        "pagination": {"totalPages": 1},
    }
    page2 = {
        "items": [{"id": 1, "title": "new", "author": "a", "createdAt": "2026.04.01 10:00:00"}],
        "pagination": {"totalPages": 1},
    }
    details = {1: {"id": 1, "content": "<p>x</p>"}}

    fake = FakeOpenSoma([page1], details)
    notice_service.run_sync(db, fake, session_id="sid")  # type: ignore[arg-type]

    fake = FakeOpenSoma([page2], details)
    stats = notice_service.run_sync(db, fake, session_id="sid")  # type: ignore[arg-type]
    assert stats.updated == 1
    row = db.execute(select(Notice)).scalar_one()
    assert row.title == "new"


def test_should_parsePostedAt_when_createdAtIsKstFormat(db: Session) -> None:
    page = {
        "items": [{"id": 1, "title": "t", "author": "a", "createdAt": "2026.04.07 15:14:20"}],
        "pagination": {"totalPages": 1},
    }
    details = {1: {"id": 1, "content": "<p>x</p>"}}
    fake = FakeOpenSoma([page], details)
    notice_service.run_sync(db, fake, session_id="sid")  # type: ignore[arg-type]
    row = db.execute(select(Notice)).scalar_one()
    assert row.posted_at is not None
    assert row.posted_at.year == 2026
    assert row.posted_at.hour == 15


def test_should_collectErrors_when_detailCallFails(db: Session) -> None:
    page = {
        "items": [{"id": 1, "title": "t", "author": "a", "createdAt": "2026.04.01 10:00:00"}],
        "pagination": {"totalPages": 1},
    }

    class Failing(FakeOpenSoma):
        def notice_get(self, session_id: str, notice_id: int) -> dict[str, Any]:
            raise RuntimeError("upstream timeout")

    fake = Failing([page], {})
    stats = notice_service.run_sync(db, fake, session_id="sid")  # type: ignore[arg-type]
    assert stats.fetched == 1
    assert stats.inserted == 0
    assert len(stats.errors) == 1
    assert "notice_id=1" in stats.errors[0]
