"""chat API integration tests with mocked external adapters."""
from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager
from datetime import datetime
from types import SimpleNamespace

from fastapi.testclient import TestClient

from app.adapters.solar_chat_client import ChatResponse
from app.api import deps
from app.main import create_app


class FakeSolar:
    def embed_query(self, query: str) -> list[float]:
        self.query = query
        return [0.1] * 8


class FakeQdrant:
    def __init__(self, points: list[SimpleNamespace]) -> None:
        self.points = points
        self.calls: list[dict[str, object]] = []

    def search(self, vector, *, source_types, official_only, room_name, k):  # type: ignore[no-untyped-def]
        self.calls.append(
            {
                "source_types": source_types,
                "official_only": official_only,
                "room_name": room_name,
                "k": k,
            }
        )
        return self.points[:k]


class FakeChat:
    def __init__(self) -> None:
        self.messages: list[list[dict[str, object]]] = []

    def chat(self, messages, **kwargs):  # type: ignore[no-untyped-def]
        self.messages.append(messages)
        if len(self.messages) == 1:
            return ChatResponse(
                content=(
                    '{"query":"백엔드 멘토링","source_types":["MENTORING"],'
                    '"official_only":true,"k":3}'
                )
            )
        return ChatResponse(content="백엔드 멘토링으로 테스트 멘토링을 추천합니다.")


def _point(**payload):  # type: ignore[no-untyped-def]
    return SimpleNamespace(id=payload.get("chunk_id"), score=0.91, payload=payload)


@contextmanager
def _client(
    qdrant: FakeQdrant,
    solar: FakeSolar,
    chat: FakeChat,
) -> Generator[TestClient, None, None]:
    app = create_app()
    app.dependency_overrides[deps.get_qdrant_adapter] = lambda: qdrant
    app.dependency_overrides[deps.get_solar_client] = lambda: solar
    app.dependency_overrides[deps.get_solar_chat_client] = lambda: chat
    with TestClient(app) as tc:
        yield tc


def test_should_returnAnswerAndSources_when_hitsFound() -> None:
    qdrant = FakeQdrant(
        [
            _point(
                chunk_id="m-1-0",
                source_type="MENTORING",
                source_id="10786",
                title="테스트 멘토링",
                text="백엔드 API 멘토링",
                official=True,
                created_at=datetime(2026, 5, 1).isoformat(),
                source_url="https://example.test/mentoring/10786",
            )
        ]
    )
    solar = FakeSolar()
    chat = FakeChat()

    with _client(qdrant, solar, chat) as client:
        res = client.post(
            "/api/v1/chat",
            json={"message": "백엔드 멘토링 추천해줘"},
        )

    assert res.status_code == 200
    body = res.json()
    assert body["answer"] == "백엔드 멘토링으로 테스트 멘토링을 추천합니다."
    assert body["llm_used"] is True
    assert body["sources"][0]["source_id"] == "10786"
    assert qdrant.calls[0]["source_types"] == ["MENTORING"]
    assert qdrant.calls[0]["official_only"] is True
    assert qdrant.calls[0]["room_name"] is None
    assert qdrant.calls[0]["k"] == 3
    assert body["metadata"]["resolved_query"] == "백엔드 멘토링"
    assert body["metadata"]["source_types"] == ["MENTORING"]
    assert body["metadata"]["official_only"] is True
    assert body["metadata"]["k"] == 3
    assert body["metadata"]["router"] == "llm"
    assert len(chat.messages) == 2


def test_should_skipLlm_when_noHitsFound() -> None:
    qdrant = FakeQdrant([])
    solar = FakeSolar()
    chat = FakeChat()

    with _client(qdrant, solar, chat) as client:
        res = client.post("/api/v1/chat", json={"message": "없는 내용"})

    assert res.status_code == 200
    body = res.json()
    assert body["answer"] == "관련 결과를 찾지 못했습니다."
    assert body["sources"] == []
    assert body["llm_used"] is False
    assert len(chat.messages) == 1


def test_should_fallbackToAllSources_when_routerReturnsInvalidJson() -> None:
    class InvalidRouterChat(FakeChat):
        def chat(self, messages, **kwargs):  # type: ignore[no-untyped-def]
            self.messages.append(messages)
            if len(self.messages) == 1:
                return ChatResponse(content="not-json")
            return ChatResponse(content="fallback answer")

    qdrant = FakeQdrant(
        [
            _point(
                chunk_id="n-1-0",
                source_type="NOTICE",
                source_id="1",
                title="공지",
                text="백엔드 관련 공지",
                official=True,
            )
        ]
    )
    solar = FakeSolar()
    chat = InvalidRouterChat()

    with _client(qdrant, solar, chat) as client:
        res = client.post("/api/v1/chat", json={"message": "백엔드 알려줘"})

    assert res.status_code == 200
    body = res.json()
    assert body["answer"] == "fallback answer"
    assert qdrant.calls[0]["source_types"] is None
    assert qdrant.calls[0]["official_only"] is False
    assert qdrant.calls[0]["k"] == 5
    assert body["metadata"]["router"] == "fallback"
    assert body["metadata"]["router_error"]


def test_shouldClampK_when_routerReturnsOutOfRangeK() -> None:
    class LargeKRouterChat(FakeChat):
        def chat(self, messages, **kwargs):  # type: ignore[no-untyped-def]
            self.messages.append(messages)
            if len(self.messages) == 1:
                return ChatResponse(
                    content='{"query":"공지","source_types":["NOTICE"],"official_only":true,"k":100}'
                )
            return ChatResponse(content="공지 답변")

    qdrant = FakeQdrant(
        [
            _point(
                chunk_id="n-1-0",
                source_type="NOTICE",
                source_id="1",
                title="공지",
                text="공지",
                official=True,
            )
        ]
    )
    solar = FakeSolar()
    chat = LargeKRouterChat()

    with _client(qdrant, solar, chat) as client:
        res = client.post("/api/v1/chat", json={"message": "공지 전부 알려줘"})

    assert res.status_code == 200
    body = res.json()
    assert qdrant.calls[0]["k"] == 20
    assert body["metadata"]["k"] == 20
