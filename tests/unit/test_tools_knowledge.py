"""knowledge.search tool — qdrant/solar mock으로 동작 검증."""
from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

import pytest

from app.tools.base import ToolContext
from app.tools.knowledge import KnowledgeSearchTool


class _FakeSolar:
    def embed_query(self, query: str) -> list[float]:
        return [0.1] * 8


class _FakeQdrant:
    def __init__(self, points: list[SimpleNamespace]) -> None:
        self._points = points

    def search(self, vector, *, source_types, official_only, room_name, k):  # type: ignore[no-untyped-def]
        return self._points[:k]


def _point(**payload):  # type: ignore[no-untyped-def]
    return SimpleNamespace(id=payload.get("chunk_id"), score=0.9, payload=payload)


@pytest.mark.asyncio
async def test_should_returnHitsAndSources_when_qdrantReturnsResults() -> None:
    points = [
        _point(
            chunk_id="c1",
            source_type="NOTICE",
            source_id="n-1",
            title="공지 A",
            text="...",
            official=True,
            created_at=datetime(2026, 5, 1).isoformat(),
            source_url="http://example/n/1",
        )
    ]
    tool = KnowledgeSearchTool()
    ctx = ToolContext(solar=_FakeSolar(), qdrant=_FakeQdrant(points))  # type: ignore[arg-type]

    result = await tool.run({"query": "백엔드", "k": 5}, ctx)

    assert result.status == "success"
    assert len(result.sources) == 1
    src = result.sources[0]
    assert src.title == "공지 A"
    assert src.type == "notice"


@pytest.mark.asyncio
async def test_should_returnEmpty_when_queryBlank() -> None:
    tool = KnowledgeSearchTool()
    ctx = ToolContext(solar=_FakeSolar(), qdrant=_FakeQdrant([]))  # type: ignore[arg-type]

    result = await tool.run({"query": "  "}, ctx)

    assert result.status == "success"
    assert result.data == []


@pytest.mark.asyncio
async def test_should_returnFailed_when_dependenciesMissing() -> None:
    result = await KnowledgeSearchTool().run({"query": "x"}, ToolContext())

    assert result.status == "failed"
    assert result.error and result.error.code == "MISSING_DEPS"


@pytest.mark.asyncio
async def test_should_returnFailed_when_invalidSourceType() -> None:
    tool = KnowledgeSearchTool()
    ctx = ToolContext(solar=_FakeSolar(), qdrant=_FakeQdrant([]))  # type: ignore[arg-type]

    result = await tool.run({"query": "x", "source_types": ["UNKNOWN"]}, ctx)

    assert result.status == "failed"
    assert result.error and result.error.code == "INVALID_SOURCE_TYPE"
