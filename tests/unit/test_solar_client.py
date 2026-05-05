"""Solar embedding 어댑터 단위 테스트. httpx MockTransport로 Upstage 응답 흉내."""
from __future__ import annotations

import httpx
import pytest

from app.adapters.solar_client import (
    SOLAR_EMBEDDINGS_URL,
    SolarClient,
    SolarClientError,
)


def _client(handler) -> SolarClient:  # type: ignore[no-untyped-def]
    transport = httpx.MockTransport(handler)
    return SolarClient(
        api_key="test-key",
        passage_model="embedding-passage",
        query_model="embedding-query",
        transport=transport,
    )


def test_should_returnVectors_when_embedPassagesSucceeds() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["auth"] = request.headers.get("Authorization")
        body = request.read().decode()
        captured["body"] = body
        return httpx.Response(
            200,
            json={
                "data": [
                    {"index": 0, "embedding": [0.1, 0.2, 0.3]},
                    {"index": 1, "embedding": [0.4, 0.5, 0.6]},
                ]
            },
        )

    client = _client(handler)
    vectors = client.embed_passages(["hello", "world"])

    assert vectors == [[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]]
    assert captured["url"] == SOLAR_EMBEDDINGS_URL
    assert captured["auth"] == "Bearer test-key"
    # input은 list로 전송됨 (배치 호출).
    assert "embedding-passage" in str(captured["body"])
    assert "hello" in str(captured["body"])


def test_should_returnSingleVector_when_embedQueryUsesQueryModel() -> None:
    captured_models: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = request.read().decode()
        if "embedding-query" in body:
            captured_models.append("query")
        return httpx.Response(
            200, json={"data": [{"index": 0, "embedding": [1.0, 2.0]}]}
        )

    client = _client(handler)
    vector = client.embed_query("find me")

    assert vector == [1.0, 2.0]
    assert captured_models == ["query"]


def test_should_returnEmptyList_when_embedPassagesGetsEmptyInput() -> None:
    """빈 입력에서는 API를 호출하지 않아야 한다 (비용/레이턴시 절감)."""
    call_count = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        return httpx.Response(200, json={"data": []})

    client = _client(handler)
    result = client.embed_passages([])

    assert result == []
    assert call_count == 0


def test_should_raiseSolarClientError_when_apiReturns401() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            401,
            json={"error": {"message": "invalid api key"}},
        )

    client = _client(handler)
    with pytest.raises(SolarClientError) as exc:
        client.embed_query("q")

    assert exc.value.status == 401
    assert "invalid api key" in exc.value.message


def test_should_reorderByIndex_when_apiReturnsOutOfOrder() -> None:
    """Upstage가 input 순서와 다른 순서로 응답해도 index로 재정렬해야 한다."""

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "data": [
                    {"index": 1, "embedding": [9.0]},
                    {"index": 0, "embedding": [1.0]},
                ]
            },
        )

    client = _client(handler)
    vectors = client.embed_passages(["first", "second"])

    assert vectors == [[1.0], [9.0]]
