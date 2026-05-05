"""OpenSoma sidecar 어댑터 단위 테스트. httpx MockTransport로 sidecar 응답 흉내."""
from __future__ import annotations

import httpx
import pytest

from app.adapters.opensoma_client import OpenSomaClient, OpenSomaClientError


def make_client(handler) -> OpenSomaClient:  # type: ignore[no-untyped-def]
    transport = httpx.MockTransport(handler)
    client = OpenSomaClient(base_url="http://test")
    # 실 httpx.Client 대신 MockTransport 기반 client로 교체
    client._http.close()
    client._http = httpx.Client(transport=transport, base_url="http://test")
    return client


def test_should_returnLoginResult_when_loginSucceeds() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url.path == "/sessions"
        return httpx.Response(
            200,
            json={
                "session_id": "abc-123",
                "soma_user_id": "user@example.com",
                "user_no": "abc123abc123abc123abc123abc123ab",
                "user_name": "홍길동",
                "role": "TRAINEE",
            },
        )

    client = make_client(handler)
    result = client.login("user@example.com", "pw")

    assert result.session_id == "abc-123"
    assert result.soma_user_id == "user@example.com"
    assert result.user_no == "abc123abc123abc123abc123abc123ab"
    assert result.user_name == "홍길동"
    assert result.role == "TRAINEE"


def test_should_raiseInvalidCredentials_when_sidecarReturns401() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"code": "INVALID_CREDENTIALS", "message": "login failed"})

    client = make_client(handler)
    with pytest.raises(OpenSomaClientError) as exc:
        client.login("u", "p")
    assert exc.value.status == 401
    assert exc.value.code == "INVALID_CREDENTIALS"


def test_should_raiseUpstreamError_when_sidecarReturns502() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(502, json={"code": "UPSTREAM_ERROR", "message": "boom"})

    client = make_client(handler)
    with pytest.raises(OpenSomaClientError) as exc:
        client.login("u", "p")
    assert exc.value.status == 502
    assert exc.value.code == "UPSTREAM_ERROR"


def test_should_returnWhoamiResult_when_sessionValid() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers.get("X-Soma-Session") == "sid"
        return httpx.Response(
            200,
            json={
                "soma_user_id": "u@x.com",
                "user_no": "u" * 32,
                "user_name": "name",
                "role": "MENTOR",
            },
        )

    client = make_client(handler)
    result = client.whoami("sid")
    assert result.soma_user_id == "u@x.com"
    assert result.role == "MENTOR"


def test_should_raiseSessionExpired_when_whoamiReturns401() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"code": "SESSION_EXPIRED", "message": "expired"})

    client = make_client(handler)
    with pytest.raises(OpenSomaClientError) as exc:
        client.whoami("sid")
    assert exc.value.code == "SESSION_EXPIRED"


def test_should_succeedSilently_when_logoutOnUnknownSession() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(404)

    client = make_client(handler)
    # 404도 정상 종료 (멱등성)
    client.logout("sid")


def test_should_raiseError_when_logoutReturnsServerError() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"code": "ERR", "message": "x"})

    client = make_client(handler)
    with pytest.raises(OpenSomaClientError):
        client.logout("sid")
