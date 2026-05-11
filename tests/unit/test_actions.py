"""도메인 액션 디스패처 단위 테스트."""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.adapters.opensoma_client import OpenSomaClient
from app.domain.models import Base
from app.domain.models.application import Application
from app.errors.exceptions import InvalidActionType, InvalidRequest
from app.services.actions import action_service


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


@pytest.fixture
def opensoma() -> MagicMock:
    return MagicMock(spec=OpenSomaClient)


def test_should_applyMentoring_when_statusOpen(db: Session, opensoma: MagicMock) -> None:
    # Given
    opensoma.mentoring_get.return_value = {
        "title": "테스트 멘토링",
        "status": "접수중",
        "sessionDate": "2026-05-31",
        "sessionTime": {"start": "20:00", "end": "22:00"},
        "venue": "온라인",
    }
    opensoma.mentoring_apply.return_value = {
        "apply_sn": 123,
        "qustnr_sn": 456,
        "title": "테스트 멘토링",
    }

    # When
    res = action_service.execute(
        db, opensoma, "sess-1", "user-1", "MENTORING_APPLY",
        {"mentoringId": 1001}, "trace-1"
    )

    # Then
    assert res.status == "success"
    assert res.payload["apply_sn"] == 123
    assert res.payload["calendarInvite"]["status"] == "success"
    opensoma.mentoring_apply.assert_called_once_with("sess-1", 1001)


def test_should_returnConflict_when_mentoringStatusClosed(db: Session, opensoma: MagicMock) -> None:
    # Given
    opensoma.mentoring_get.return_value = {
        "title": "마감된 멘토링",
        "status": "마감",
    }

    # When
    res = action_service.execute(
        db, opensoma, "sess-1", "user-1", "MENTORING_APPLY",
        {"mentoringId": 1001}, "trace-1"
    )

    # Then
    assert res.status == "failed"
    assert "불가능한 상태" in res.message
    opensoma.mentoring_apply.assert_not_called()


def test_should_cancelWithDirectSns_when_payloadProvidesThem(db: Session, opensoma: MagicMock) -> None:
    # When
    res = action_service.execute(
        db, opensoma, "sess-1", "user-1", "MENTORING_CANCEL",
        {"applySn": 123, "qustnrSn": 456}, "trace-1"
    )

    # Then
    assert res.status == "success"
    opensoma.mentoring_cancel.assert_called_once_with("sess-1", apply_sn=123, qustnr_sn=456)


def test_should_cancelWithMapping_when_onlyMentoringIdProvided(db: Session, opensoma: MagicMock) -> None:
    # Given
    opensoma.mentoring_get.return_value = {"title": "매핑용 멘토링"}
    # 사용자의 신청 내역 미리 저장 (캐시)
    db.add(Application(
        soma_user_id="user-1", title="매핑용 멘토링", apply_sn=123, qustnr_sn=456
    ))
    db.commit()

    # When
    res = action_service.execute(
        db, opensoma, "sess-1", "user-1", "MENTORING_CANCEL",
        {"mentoringId": 1001}, "trace-1"
    )

    # Then
    assert res.status == "success"
    assert res.payload["apply_sn"] == 123
    opensoma.mentoring_cancel.assert_called_once_with("sess-1", apply_sn=123, qustnr_sn=456)


def test_should_retryMappingWithForceRefresh_when_initialCacheMiss(db: Session, opensoma: MagicMock) -> None:
    # Given
    opensoma.mentoring_get.return_value = {"title": "신규 신청건"}
    # history 조회 시 나올 데이터 설정
    opensoma.application_history.return_value = {
        "items": [{
            "id": 999,
            "title": "신규 신청건",
            "url": "?qustnrSn=888",
        }],
        "pagination": {"totalPages": 1}
    }

    # When
    res = action_service.execute(
        db, opensoma, "sess-1", "user-1", "MENTORING_CANCEL",
        {"mentoringId": 1001}, "trace-1"
    )

    # Then
    assert res.status == "success"
    assert res.payload["apply_sn"] == 999
    # 캐시 미스로 인해 opensoma 호출이 발생했어야 함
    assert opensoma.application_history.called


def test_should_raiseInvalidRequest_when_onlyOneSnProvided(db: Session, opensoma: MagicMock) -> None:
    # When/Then
    with pytest.raises(InvalidRequest) as exc:
        action_service.execute(
            db, opensoma, "sess-1", "user-1", "MENTORING_CANCEL",
            {"applySn": 123}, "trace-1"
        )
    assert "Both applySn and qustnrSn" in str(exc.value)


def test_should_raiseInvalidActionType_when_unknownType(db: Session, opensoma: MagicMock) -> None:
    # When/Then
    with pytest.raises(InvalidActionType):
        action_service.execute(
            db, opensoma, "sess-1", "user-1", "UNKNOWN_ACTION",
            {}, "trace-1"
        )
