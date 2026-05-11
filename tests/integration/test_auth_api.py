"""/auth/* 엔드포인트 통합 테스트.

- 실 sidecar 대신 OpenSomaClient를 mock으로 대체 (FastAPI 의존성 오버라이드).
- DB는 인메모리 SQLite (engine 교체).
"""
from __future__ import annotations

from collections.abc import Generator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.adapters.opensoma_client import (
    LoginResult,
    OpenSomaClient,
    OpenSomaClientError,
    WhoamiResult,
)
from app.api import deps
from app.domain.models import Base
from app.main import create_app


class FakeOpenSomaClient(OpenSomaClient):
    """테스트용 가짜 sidecar 클라이언트. 메소드를 마음대로 monkey-patch 가능."""

    def __init__(self) -> None:
        # super().__init__() 호출 안 함 — settings 의존 회피
        self.calls: list[tuple[str, Any]] = []

    def login(self, username: str, password: str) -> LoginResult:  # type: ignore[override]
        self.calls.append(("login", (username, password)))
        if username == "bad":
            raise OpenSomaClientError(401, "INVALID_CREDENTIALS", "login failed")
        return LoginResult(
            session_id="test-sid",
            soma_user_id=username,
            user_no="0" * 32,
            user_name="테스트",
            role="TRAINEE",
        )

    def logout(self, session_id: str) -> None:  # type: ignore[override]
        self.calls.append(("logout", session_id))

    def whoami(self, session_id: str) -> WhoamiResult:  # type: ignore[override]
        self.calls.append(("whoami", session_id))
        if session_id == "expired":
            raise OpenSomaClientError(401, "SESSION_EXPIRED", "expired")
        return WhoamiResult(
            soma_user_id="u@x.com",
            user_no="0" * 32,
            user_name="테스트",
            role="TRAINEE",
        )


@pytest.fixture
def client_and_state() -> Generator[tuple[TestClient, FakeOpenSomaClient], None, None]:
    # SQLite :memory: 는 연결별로 새 DB를 만드므로 StaticPool로 단일 연결 공유.
    engine = create_engine(
        "sqlite:///:memory:",
        echo=False,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    fake = FakeOpenSomaClient()

    def _override_db() -> Generator[Session, None, None]:
        db = SessionLocal()
        try:
            yield db
        finally:
            db.close()

    def _override_client() -> OpenSomaClient:
        return fake

    app = create_app()
    app.dependency_overrides[deps.get_db] = _override_db
    app.dependency_overrides[deps.get_opensoma_client] = _override_client

    with TestClient(app) as tc:
        yield tc, fake


def test_should_returnSessionId_when_loginSuccessful(
    client_and_state: tuple[TestClient, FakeOpenSomaClient],
) -> None:
    client, _ = client_and_state
    res = client.post("/auth/login", json={"username": "user@x.com", "password": "pw"})
    assert res.status_code == 200
    body = res.json()
    assert body["session_id"] == "test-sid"
    assert body["soma_user_id"] == "user@x.com"
    assert body["role"] == "TRAINEE"


def test_should_return401_when_credentialsInvalid(
    client_and_state: tuple[TestClient, FakeOpenSomaClient],
) -> None:
    client, _ = client_and_state
    res = client.post("/auth/login", json={"username": "bad", "password": "pw"})
    assert res.status_code == 401
    assert res.json()["code"] == "INVALID_CREDENTIALS"


def test_should_return422_when_loginBodyEmpty(
    client_and_state: tuple[TestClient, FakeOpenSomaClient],
) -> None:
    client, _ = client_and_state
    res = client.post("/auth/login", json={})
    assert res.status_code == 422


def test_should_return401_when_sessionHeaderMissing(
    client_and_state: tuple[TestClient, FakeOpenSomaClient],
) -> None:
    client, _ = client_and_state
    res = client.get("/auth/whoami")
    assert res.status_code == 401
    assert res.json()["code"] == "SOMA_AUTH_REQUIRED"


def test_should_returnSessionExpiredHeader_when_sidecarReports401Expired(
    client_and_state: tuple[TestClient, FakeOpenSomaClient],
) -> None:
    client, _ = client_and_state
    res = client.get("/auth/whoami", headers={"X-Soma-Session": "expired"})
    assert res.status_code == 401
    assert res.json()["code"] == "SESSION_EXPIRED"
    assert res.headers.get("x-soma-session-expired") == "true"


def test_should_persistUserUpsert_when_loginSucceeds(
    client_and_state: tuple[TestClient, FakeOpenSomaClient],
) -> None:
    client, fake = client_and_state
    client.post("/auth/login", json={"username": "user@x.com", "password": "pw"})
    # 같은 user_no로 두 번째 로그인 시 단일 행 유지
    client.post("/auth/login", json={"username": "user@x.com", "password": "pw2"})
    # whoami 호출도 같은 행에 갱신
    client.get("/auth/whoami", headers={"X-Soma-Session": "test-sid"})
    # FakeClient는 호출 추적
    assert any(c[0] == "login" for c in fake.calls)
    assert any(c[0] == "whoami" for c in fake.calls)


def test_should_logout_when_sessionHeaderProvided(
    client_and_state: tuple[TestClient, FakeOpenSomaClient],
) -> None:
    client, fake = client_and_state
    res = client.delete("/auth/session", headers={"X-Soma-Session": "test-sid"})
    assert res.status_code == 204
    assert ("logout", "test-sid") in fake.calls
