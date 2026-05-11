"""Application history TTL 캐시 동작 검증."""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.domain.models import Base
from app.domain.models.application import Application
from app.services import application as app_service


class FakeOpenSoma:
    def __init__(self, pages: list[dict[str, Any]]) -> None:
        self.pages = pages
        self.calls = 0

    def application_history(self, session_id: str, page: int = 1) -> dict[str, Any]:
        self.calls += 1
        return self.pages[page - 1] if page <= len(self.pages) else {"items": [], "pagination": {}}


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


_ITEM_TRIFLAM = {
    "id": 59,
    "category": "자유멘토링",
    "title": "[염승헌] TRIFLAM",
    "url": "/sw/mypage/mentoLec/view.do?qustnrSn=11258&menuNo=200046",
    "author": "염승헌",
    "sessionDate": "2026-05-05(화) 16:00:00 ~ 17:30:00",
    "appliedAt": "2026-05-05 12:31",
    "applicationStatus": "접수완료",
    "approvalStatus": "OK",
    "applicationDetail": "-",
    "note": "-",
}


def test_should_callSidecar_when_cacheEmpty(db: Session) -> None:
    fake = FakeOpenSoma([{"items": [_ITEM_TRIFLAM], "pagination": {"totalPages": 1}}])
    result = app_service.get_history(db, fake, "sid", "user@x.com")  # type: ignore[arg-type]
    assert result.refreshed is True
    assert len(result.items) == 1
    assert result.items[0].apply_sn == 59
    assert result.items[0].qustnr_sn == 11258
    assert fake.calls == 1


def test_should_useCache_when_freshEntriesExist(db: Session) -> None:
    fake = FakeOpenSoma([{"items": [_ITEM_TRIFLAM], "pagination": {"totalPages": 1}}])
    app_service.get_history(db, fake, "sid", "user@x.com")  # type: ignore[arg-type]
    fake.calls = 0
    result = app_service.get_history(db, fake, "sid", "user@x.com")  # type: ignore[arg-type]
    assert result.refreshed is False
    assert fake.calls == 0


def test_should_refreshFromSidecar_when_cacheStale(db: Session) -> None:
    fake = FakeOpenSoma([{"items": [_ITEM_TRIFLAM], "pagination": {"totalPages": 1}}])
    app_service.get_history(db, fake, "sid", "user@x.com")  # type: ignore[arg-type]

    # 강제로 cached_at을 6분 전으로
    rows = db.execute(select(Application)).scalars().all()
    stale_ts = datetime.utcnow() - timedelta(minutes=6)
    for r in rows:
        r.cached_at = stale_ts
    db.commit()

    fake.calls = 0
    result = app_service.get_history(db, fake, "sid", "user@x.com")  # type: ignore[arg-type]
    assert result.refreshed is True
    assert fake.calls == 1


def test_should_invalidate_when_called(db: Session) -> None:
    fake = FakeOpenSoma([{"items": [_ITEM_TRIFLAM], "pagination": {"totalPages": 1}}])
    app_service.get_history(db, fake, "sid", "user@x.com")  # type: ignore[arg-type]
    removed = app_service.invalidate(db, "user@x.com")
    assert removed == 1
    assert db.execute(select(Application)).scalars().all() == []


def test_should_extractQustnrSnFromUrl_when_storingHistory(db: Session) -> None:
    fake = FakeOpenSoma([{"items": [_ITEM_TRIFLAM], "pagination": {"totalPages": 1}}])
    result = app_service.get_history(db, fake, "sid", "user@x.com")  # type: ignore[arg-type]
    assert result.items[0].qustnr_sn == 11258


def test_should_handleEmptyUrl_when_qustnrSnMissing(db: Session) -> None:
    item = dict(_ITEM_TRIFLAM, url=None)
    fake = FakeOpenSoma([{"items": [item], "pagination": {"totalPages": 1}}])
    result = app_service.get_history(db, fake, "sid", "user@x.com")  # type: ignore[arg-type]
    assert result.items[0].qustnr_sn is None
