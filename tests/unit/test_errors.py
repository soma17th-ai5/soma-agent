"""커스텀 예외 + 핸들러 단위 테스트.

검증 항목:
- 각 BaseAPIException 하위 클래스의 status_code/code/message 매핑
- SessionExpired 의 X-Soma-Session-Expired 헤더 보존
- api_error_handler / opensoma_error_handler / validation_error_handler 의 응답 포맷
"""
from __future__ import annotations

from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel

from app.adapters.opensoma_client import OpenSomaClientError
from app.errors import (
    BaseAPIException,
    DatabaseUnavailable,
    InvalidRequest,
    MentoringNotOpen,
    SessionExpired,
    SomaAuthRequired,
    UpstreamUnavailable,
)
from app.errors.handlers import (
    api_error_handler,
    opensoma_error_handler,
    validation_error_handler,
)

# ─── 예외 메타 검증 ────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "exc_cls,expected_status,expected_code",
    [
        (SomaAuthRequired, 401, "SOMA_AUTH_REQUIRED"),
        (SessionExpired, 401, "SESSION_EXPIRED"),
        (InvalidRequest, 422, "INVALID_REQUEST"),
        (MentoringNotOpen, 409, "MENTORING_NOT_OPEN"),
        (UpstreamUnavailable, 503, "UPSTREAM_UNAVAILABLE"),
        (DatabaseUnavailable, 503, "DATABASE_UNAVAILABLE"),
    ],
)
def test_should_carryStatusCodeAndCode_when_exceptionConstructed(
    exc_cls: type[BaseAPIException],
    expected_status: int,
    expected_code: str,
) -> None:
    err = exc_cls()
    assert err.status_code == expected_status
    assert err.code == expected_code


def test_should_carrySessionExpiredHeader_when_sessionExpiredRaised() -> None:
    err = SessionExpired()
    assert err.headers == {"X-Soma-Session-Expired": "true"}


def test_should_overrideMessage_when_messagePassedToConstructor() -> None:
    err = InvalidRequest("custom reason")
    assert err.message == "custom reason"
    assert err.code == "INVALID_REQUEST"


def test_should_carryDetails_when_detailsPassedToConstructor() -> None:
    err = InvalidRequest("nope", details=[{"field": "x", "reason": "missing"}])
    assert err.details == [{"field": "x", "reason": "missing"}]


# ─── 핸들러 응답 포맷 (실제 FastAPI 라우터에서 raise) ────────────────────────────


def _build_test_app() -> FastAPI:
    app = FastAPI()
    app.add_exception_handler(BaseAPIException, api_error_handler)
    app.add_exception_handler(OpenSomaClientError, opensoma_error_handler)
    from fastapi.exceptions import RequestValidationError

    app.add_exception_handler(RequestValidationError, validation_error_handler)

    @app.get("/raise-base")
    def _raise_base() -> Any:
        raise InvalidRequest("bad input")

    @app.get("/raise-session-expired")
    def _raise_session_expired() -> Any:
        raise SessionExpired()

    @app.get("/raise-upstream-401-expired")
    def _raise_upstream_expired() -> Any:
        raise OpenSomaClientError(401, "SESSION_EXPIRED", "expired")

    @app.get("/raise-upstream-401-other")
    def _raise_upstream_other() -> Any:
        raise OpenSomaClientError(401, "INVALID_CREDENTIALS", "login failed")

    @app.get("/raise-upstream-404")
    def _raise_upstream_404() -> Any:
        raise OpenSomaClientError(404, "NOT_FOUND", "no such resource")

    @app.get("/raise-upstream-500")
    def _raise_upstream_500() -> Any:
        raise OpenSomaClientError(500, "INTERNAL", "boom")

    @app.get("/raise-upstream-422-no-code")
    def _raise_upstream_422_no_code() -> Any:
        # sidecar가 code 필드를 안 주는 케이스 — handler의 폴백 경로.
        raise OpenSomaClientError(422, "", "missing field")

    @app.post("/needs-body")
    def _needs_body(payload: _Body) -> Any:
        return {"ok": True, "name": payload.name}

    return app


# `from __future__ import annotations`로 인해 Pydantic 모델 타입 힌트는 모듈 레벨에 둬야
# FastAPI가 body 파라미터로 인식한다 (closure 안에 두면 query로 잘못 해석됨).
class _Body(BaseModel):
    name: str


@pytest.fixture
def client() -> TestClient:
    return TestClient(_build_test_app(), raise_server_exceptions=False)


def test_should_returnFlatBody_when_baseAPIExceptionRaised(client: TestClient) -> None:
    res = client.get("/raise-base")
    assert res.status_code == 422
    body = res.json()
    assert body == {"code": "INVALID_REQUEST", "message": "bad input"}


def test_should_returnSessionExpiredHeader_when_sessionExpiredRaised(client: TestClient) -> None:
    res = client.get("/raise-session-expired")
    assert res.status_code == 401
    assert res.json()["code"] == "SESSION_EXPIRED"
    assert res.headers.get("x-soma-session-expired") == "true"


def test_should_mapUpstreamSessionExpired_when_opensomaClient401Expired(client: TestClient) -> None:
    res = client.get("/raise-upstream-401-expired")
    assert res.status_code == 401
    assert res.json()["code"] == "SESSION_EXPIRED"
    assert res.headers.get("x-soma-session-expired") == "true"


def test_should_preserveUpstreamCode_when_opensomaClient401NotExpired(client: TestClient) -> None:
    res = client.get("/raise-upstream-401-other")
    assert res.status_code == 401
    body = res.json()
    assert body["code"] == "INVALID_CREDENTIALS"
    assert body["message"] == "login failed"


def test_should_map404_when_opensomaClient404(client: TestClient) -> None:
    res = client.get("/raise-upstream-404")
    assert res.status_code == 404
    assert res.json()["code"] == "NOT_FOUND"


def test_should_abstract503_when_opensomaClient500(client: TestClient) -> None:
    """업스트림 5xx는 내부 진단 정보 노출 없이 503 UPSTREAM_UNAVAILABLE로 일반화."""
    res = client.get("/raise-upstream-500")
    assert res.status_code == 503
    body = res.json()
    assert body["code"] == "UPSTREAM_UNAVAILABLE"
    assert "boom" not in body["message"]  # 원본 에러 문구 비노출


def test_should_returnFlatValidationError_when_pydanticValidationFails(client: TestClient) -> None:
    res = client.post("/needs-body", json={})
    assert res.status_code == 422
    body = res.json()
    assert body["code"] == "VALIDATION_FAILED"
    assert "details" in body
    assert any(d["field"] == "name" for d in body["details"])


def test_should_fallbackUpstreamCode_when_opensomaClientCodeIsEmpty(client: TestClient) -> None:
    """sidecar가 code 필드를 비워서 보낸 경우, handler가 도메인 기본 코드로 폴백한다."""
    res = client.get("/raise-upstream-422-no-code")
    assert res.status_code == 422
    assert res.json()["code"] == "UPSTREAM_UNPROCESSABLE"
