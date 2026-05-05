"""Webex API 어댑터 단위 테스트.

httpx.MockTransport 로 라우팅. respx 도 의존에 있지만 표준 라이브러리만으로
충분한 케이스라 MockTransport 를 직접 사용한다.
"""
from __future__ import annotations

import httpx
import pytest

from app.adapters import webex_client as wc


def _make_client(handler: httpx.MockTransport) -> wc.WebexClient:
    httpx_client = httpx.Client(transport=handler)
    return wc.WebexClient(token="dummy-token", client=httpx_client)


def test_should_followLinkHeader_when_listingRoomsAcrossPages() -> None:
    """RFC5988 Link 헤더 페이지네이션 검증 (`rel="next"` 따라가기)."""
    page_calls = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        page_calls["count"] += 1
        # Bearer 토큰 주입 검증.
        assert request.headers["Authorization"] == "Bearer dummy-token"
        if page_calls["count"] == 1:
            assert request.url.path == "/v1/rooms"
            assert request.url.params.get("type") == "group"
            return httpx.Response(
                200,
                json={"items": [{"id": "R1"}, {"id": "R2"}]},
                headers={
                    "Link": (
                        '<https://webexapis.com/v1/rooms?cursor=abc>; rel="next"'
                    )
                },
            )
        # 두 번째 페이지 — next URL 그대로 호출됨.
        assert "cursor=abc" in str(request.url)
        return httpx.Response(200, json={"items": [{"id": "R3"}]})

    client = _make_client(httpx.MockTransport(handler))
    rooms = list(client.list_rooms(room_type="group"))

    assert [r["id"] for r in rooms] == ["R1", "R2", "R3"]
    assert page_calls["count"] == 2


def test_should_filterByGroupType_when_listingRooms() -> None:
    """`type=group` 쿼리 파라미터 주입 검증."""
    captured: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["type"] = request.url.params.get("type", "")
        return httpx.Response(200, json={"items": []})

    client = _make_client(httpx.MockTransport(handler))
    list(client.list_rooms(room_type="group"))

    assert captured["type"] == "group"


def test_should_retryAfterRateLimit_when_429Returned(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """429 + Retry-After → 대기 후 재시도, 200 본문 반환."""
    sleeps: list[float] = []
    monkeypatch.setattr(wc.time, "sleep", lambda s: sleeps.append(s))

    state = {"calls": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        state["calls"] += 1
        if state["calls"] == 1:
            return httpx.Response(429, headers={"Retry-After": "2"})
        return httpx.Response(200, json={"items": [{"id": "R1"}]})

    client = _make_client(httpx.MockTransport(handler))
    rooms = list(client.list_rooms())

    assert [r["id"] for r in rooms] == ["R1"]
    assert state["calls"] == 2
    assert sleeps == [2.0]


def test_should_capRetryAfter_when_serverReturnsHugeValue(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """비정상적으로 큰 Retry-After 값은 max_retry_after 로 클램프."""
    sleeps: list[float] = []
    monkeypatch.setattr(wc.time, "sleep", lambda s: sleeps.append(s))
    state = {"calls": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        state["calls"] += 1
        if state["calls"] == 1:
            return httpx.Response(429, headers={"Retry-After": "9999"})
        return httpx.Response(200, json={"items": []})

    httpx_client = httpx.Client(transport=httpx.MockTransport(handler))
    client = wc.WebexClient(
        token="dummy-token", client=httpx_client, max_retry_after=10.0
    )
    list(client.list_rooms())

    assert sleeps == [10.0]


def test_should_raiseAuthError_when_401Returned() -> None:
    """401 → WebexAuthError (운영자 토큰 만료 시그널)."""

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"message": "Unauthorized"})

    client = _make_client(httpx.MockTransport(handler))
    with pytest.raises(wc.WebexAuthError):
        list(client.list_rooms())


def test_should_passBeforeMessageCursor_when_provided() -> None:
    """list_messages 의 beforeMessage 파라미터 전달 검증."""
    captured: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["beforeMessage"] = request.url.params.get("beforeMessage", "")
        captured["roomId"] = request.url.params.get("roomId", "")
        return httpx.Response(200, json={"items": []})

    client = _make_client(httpx.MockTransport(handler))
    list(client.list_messages(room_id="ROOM1", before_message="MSG_X"))

    assert captured["roomId"] == "ROOM1"
    assert captured["beforeMessage"] == "MSG_X"


def test_should_returnPerson_when_getPersonCalled() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/people/PERSON1"
        return httpx.Response(200, json={"id": "PERSON1", "emails": ["x@webex.bot"]})

    client = _make_client(httpx.MockTransport(handler))
    person = client.get_person("PERSON1")

    assert person["id"] == "PERSON1"


def test_should_parseNextLink_when_quotedRel() -> None:
    """헤더 변형(따옴표 유무)도 허용."""
    assert (
        wc._parse_next_link('<https://x/v1/rooms?cursor=1>; rel="next"')
        == "https://x/v1/rooms?cursor=1"
    )
    assert (
        wc._parse_next_link("<https://x/v1/rooms?cursor=2>; rel=next")
        == "https://x/v1/rooms?cursor=2"
    )
    assert wc._parse_next_link("<https://x/v1/rooms>; rel=prev") is None
    assert wc._parse_next_link(None) is None


def test_should_rejectEmptyToken_when_constructed() -> None:
    with pytest.raises(ValueError):
        wc.WebexClient(token="")
