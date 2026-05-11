"""도메인 액션 API 통합 테스트."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.adapters.opensoma_client import OpenSomaClient
from app.api.deps import get_db, get_opensoma_client
from app.domain.models import Base
from app.main import create_app


@pytest.fixture
def opensoma_mock() -> MagicMock:
    return MagicMock(spec=OpenSomaClient)


@pytest.fixture
def db_session() -> Session:
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    return SessionLocal()


@pytest.fixture
def client(opensoma_mock: MagicMock, db_session: Session) -> TestClient:
    app = create_app()
    # Dependency overrides
    app.dependency_overrides[get_opensoma_client] = lambda: opensoma_mock
    app.dependency_overrides[get_db] = lambda: db_session
    return TestClient(app)


def test_should_returnTraceId_in_actionResponse(client: TestClient, opensoma_mock: MagicMock) -> None:
    # Given
    opensoma_mock.mentoring_get.return_value = {
        "title": "테스트 멘토링",
        "status": "접수중",
        "sessionDate": "2026-05-31",
        "sessionTime": {"start": "20:00", "end": "22:00"},
    }
    opensoma_mock.mentoring_apply.return_value = {"apply_sn": 1, "qustnr_sn": 2}
    
    # When
    response = client.post(
        "/api/v1/actions/execute",
        json={
            "actionType": "MENTORING_APPLY",
            "payload": {"mentoringId": 123},
            "somaUserId": "user-1",
        },
        headers={"X-Soma-Session": "dummy-session"}
    )
    
    # Then
    assert response.status_code == 200
    data = response.json()
    assert "traceId" in data
    assert data["status"] == "success"
    assert data["actionType"] == "MENTORING_APPLY"


def test_should_return422_when_invalidActionType(client: TestClient) -> None:
    # When
    response = client.post(
        "/api/v1/actions/execute",
        json={
            "actionType": "INVALID_TYPE",
            "payload": {},
            "somaUserId": "user-1",
        },
        headers={"X-Soma-Session": "dummy-session"}
    )
    
    # Then
    assert response.status_code == 422
    data = response.json()
    assert data["code"] == "INVALID_ACTION_TYPE"
