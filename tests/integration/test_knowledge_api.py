"""knowledge ask API integration tests with mocked external adapters."""
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
        self.messages: list[dict[str, object]] | None = None

    def chat(self, messages, **kwargs):  # type: ignore[no-untyped-def]
        self.messages = messages
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
            "/api/v1/knowledge/ask",
            json={"query": "백엔드 멘토링 추천해줘", "source_types": ["MENTORING"], "k": 3},
        )

    assert res.status_code == 200
    body = res.json()
    assert body["answer"] == "백엔드 멘토링으로 테스트 멘토링을 추천합니다."
    assert body["llm_used"] is True
    assert body["sources"][0]["source_id"] == "10786"
    assert qdrant.calls[0]["source_types"] == ["MENTORING"]
    assert qdrant.calls[0]["k"] == 3
    assert chat.messages is not None


def test_should_skipLlm_when_noHitsFound() -> None:
    qdrant = FakeQdrant([])
    solar = FakeSolar()
    chat = FakeChat()

    with _client(qdrant, solar, chat) as client:
        res = client.post("/api/v1/knowledge/ask", json={"query": "없는 내용"})

    assert res.status_code == 200
    body = res.json()
    assert body["answer"] == "관련 결과를 찾지 못했습니다."
    assert body["sources"] == []
    assert body["llm_used"] is False
    assert chat.messages is None
