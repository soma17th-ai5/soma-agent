"""멘토링 apply/cancel needs_confirmation 흐름 검증."""
from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.domain.contracts.action import ActionProposal, ActionResult
from app.domain.models import Base
from app.domain.models.application import Application
from app.errors.exceptions import MentoringNotOpen
from app.services import mentoring as mentoring_service


class FakeOpenSoma:
    def __init__(self, *, detail: dict[str, Any], apply_response: dict[str, Any] | None = None) -> None:
        self._detail = detail
        self._apply_response = apply_response or {}
        self.apply_calls: list[int] = []
        self.cancel_calls: list[tuple[int, int]] = []

    def mentoring_get(self, session_id: str, mentoring_id: int) -> dict[str, Any]:
        return self._detail

    def mentoring_apply(self, session_id: str, mentoring_id: int) -> dict[str, Any]:
        self.apply_calls.append(mentoring_id)
        return self._apply_response

    def mentoring_cancel(self, session_id: str, *, apply_sn: int, qustnr_sn: int) -> None:
        self.cancel_calls.append((apply_sn, qustnr_sn))


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


_OPEN_DETAIL = {"id": 11001, "title": "팀빌딩 멘토링", "status": "접수중", "sessionDate": "2026-05-06"}
_CLOSED_DETAIL = {"id": 11001, "title": "팀빌딩 멘토링", "status": "마감"}


def test_should_returnActionProposal_when_applyNotConfirmed(db: Session) -> None:
    fake = FakeOpenSoma(detail=_OPEN_DETAIL)
    result = mentoring_service.apply(db, fake, "sid", "user@x.com", 11001, confirmed=False)  # type: ignore[arg-type]
    assert isinstance(result, ActionProposal)
    assert result.type == "opensoma.mentoring.apply"
    assert result.payload["mentoring_id"] == 11001
    assert result.payload["title"] == "팀빌딩 멘토링"
    assert fake.apply_calls == []


def test_should_callSidecar_when_applyConfirmed(db: Session) -> None:
    fake = FakeOpenSoma(
        detail=_OPEN_DETAIL,
        apply_response={
            "apply_sn": 999,
            "qustnr_sn": 11258,
            "mentoring_id": 11001,
            "title": "[염승헌] TRIFLAM",
            "applied_at": "2026-05-05 12:31",
            "application_status": "접수완료",
            "approval_status": "OK",
        },
    )
    result = mentoring_service.apply(db, fake, "sid", "user@x.com", 11001, confirmed=True)  # type: ignore[arg-type]
    assert isinstance(result, ActionResult)
    assert result.status == "success"
    assert result.payload["apply_sn"] == 999
    assert result.payload["qustnr_sn"] == 11258
    assert fake.apply_calls == [11001]


def test_should_raise_when_mentoringStatusClosed(db: Session) -> None:
    fake = FakeOpenSoma(detail=_CLOSED_DETAIL)
    with pytest.raises(MentoringNotOpen) as exc:
        mentoring_service.apply(db, fake, "sid", "user@x.com", 11001, confirmed=False)  # type: ignore[arg-type]
    assert exc.value.status_code == 409
    assert exc.value.code == "MENTORING_NOT_OPEN"
    assert "마감" in exc.value.message


def test_should_invalidateApplicationsCache_when_applyConfirmed(db: Session) -> None:
    # 캐시에 미리 행 추가
    db.add(Application(soma_user_id="user@x.com", apply_sn=58, qustnr_sn=11251, title="prev"))
    db.commit()

    fake = FakeOpenSoma(
        detail=_OPEN_DETAIL,
        apply_response={"apply_sn": 999, "qustnr_sn": 11258, "title": "t"},
    )
    mentoring_service.apply(db, fake, "sid", "user@x.com", 11001, confirmed=True)  # type: ignore[arg-type]
    # invalidate 후 행 없어야
    from sqlalchemy import select
    rows = db.execute(select(Application)).scalars().all()
    assert rows == []


def test_should_returnProposal_when_cancelNotConfirmed(db: Session) -> None:
    fake = FakeOpenSoma(detail=_OPEN_DETAIL)
    result = mentoring_service.cancel(db, fake, "sid", "user@x.com", apply_sn=999, qustnr_sn=11258, confirmed=False)  # type: ignore[arg-type]
    assert isinstance(result, ActionProposal)
    assert result.payload == {"apply_sn": 999, "qustnr_sn": 11258}
    assert fake.cancel_calls == []


def test_should_callSidecar_when_cancelConfirmed(db: Session) -> None:
    fake = FakeOpenSoma(detail=_OPEN_DETAIL)
    result = mentoring_service.cancel(db, fake, "sid", "user@x.com", apply_sn=999, qustnr_sn=11258, confirmed=True)  # type: ignore[arg-type]
    assert isinstance(result, ActionResult)
    assert result.status == "success"
    assert fake.cancel_calls == [(999, 11258)]


def test_should_invalidateCache_when_cancelConfirmed(db: Session) -> None:
    db.add(Application(soma_user_id="user@x.com", apply_sn=999, qustnr_sn=11258, title="t"))
    db.commit()
    fake = FakeOpenSoma(detail=_OPEN_DETAIL)
    mentoring_service.cancel(db, fake, "sid", "user@x.com", apply_sn=999, qustnr_sn=11258, confirmed=True)  # type: ignore[arg-type]
    from sqlalchemy import select
    assert db.execute(select(Application)).scalars().all() == []
