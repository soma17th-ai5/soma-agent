"""RAG 인덱서 단위 테스트.

- chunk_text는 순수 함수 → 직접 검증.
- index_chunks는 Qdrant in-memory + Solar mock으로 결합 검증.
"""
from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest
from qdrant_client import QdrantClient

from app.adapters.qdrant_client import QdrantAdapter
from app.domain.contracts.knowledge import KnowledgeSourceType
from app.services.rag_indexer import (
    _deterministic_chunk_id,
    chunk_text,
    index_chunks,
)

TEST_VECTOR_SIZE = 8


@pytest.fixture
def qdrant() -> QdrantAdapter:
    raw = QdrantClient(":memory:")
    adapter = QdrantAdapter(
        client=raw, collection="rag_test", vector_size=TEST_VECTOR_SIZE
    )
    adapter.ensure_collection()
    return adapter


@pytest.fixture
def solar_mock() -> MagicMock:
    mock = MagicMock()
    # 호출마다 input 길이만큼 결정적 벡터 반환.
    mock.embed_passages.side_effect = lambda texts: [
        [float(i) + 0.01 * j for j in range(TEST_VECTOR_SIZE)]
        for i, _ in enumerate(texts)
    ]
    return mock


# --- chunk_text -------------------------------------------------------


def test_should_returnEmptyList_when_chunkTextOnBlank() -> None:
    assert chunk_text("") == []
    assert chunk_text("   \n\t") == []


def test_should_returnSingleChunk_when_textShorterThanMaxChars() -> None:
    chunks = chunk_text("짧은 텍스트", max_chars=100)
    assert chunks == ["짧은 텍스트"]


def test_should_splitWithOverlap_when_textExceedsMaxChars() -> None:
    text = "가" * 150
    chunks = chunk_text(text, max_chars=50, overlap=10)

    # step = 40, 첫 청크 [0:50], 둘째 [40:90], 셋째 [80:130], 넷째 [120:150]
    assert len(chunks) == 4
    for c in chunks:
        assert len(c) <= 50
    # overlap이 실제 적용되었는지: 둘째 청크 시작이 첫째 끝보다 앞에 있음
    # (단순 길이 sanity)
    assert sum(len(c) for c in chunks) > len(text)


def test_should_raise_when_overlapInvalid() -> None:
    with pytest.raises(ValueError):
        chunk_text("abc" * 100, max_chars=10, overlap=10)
    with pytest.raises(ValueError):
        chunk_text("abc", max_chars=0, overlap=0)


# --- _deterministic_chunk_id -----------------------------------------


def test_should_returnSameId_when_sameInputs() -> None:
    a = _deterministic_chunk_id("NOTICE", "n1", 0)
    b = _deterministic_chunk_id("NOTICE", "n1", 0)
    assert a == b


def test_should_returnDifferentIds_when_differentChunkIdx() -> None:
    a = _deterministic_chunk_id("NOTICE", "n1", 0)
    b = _deterministic_chunk_id("NOTICE", "n1", 1)
    assert a != b


# --- index_chunks ----------------------------------------------------


def test_should_upsertAllChunks_when_indexChunksCalled(
    qdrant: QdrantAdapter, solar_mock: MagicMock
) -> None:
    count = index_chunks(
        qdrant,
        solar_mock,
        KnowledgeSourceType.NOTICE,
        source_id="n1",
        title="공지 1번",
        texts=["청크 A", "청크 B", "청크 C"],
        official=True,
        source_url="https://example.com/notice/1",
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
    )

    assert count == 3
    solar_mock.embed_passages.assert_called_once_with(["청크 A", "청크 B", "청크 C"])

    results = qdrant.search([0.0] * TEST_VECTOR_SIZE, k=10)
    payloads = [r.payload for r in results if r.payload]
    assert len(payloads) == 3
    titles = {p["title"] for p in payloads}
    assert titles == {"공지 1번"}
    types = {p["source_type"] for p in payloads}
    assert types == {"NOTICE"}
    # source_url이 페이로드에 보존되었는지
    assert all(p.get("source_url") == "https://example.com/notice/1" for p in payloads)


def test_should_replaceExistingChunks_when_reindexingSameSource(
    qdrant: QdrantAdapter, solar_mock: MagicMock
) -> None:
    # 1차 인덱싱: 청크 3개
    index_chunks(
        qdrant,
        solar_mock,
        KnowledgeSourceType.NOTICE,
        source_id="n1",
        title="v1",
        texts=["a", "b", "c"],
        official=True,
    )
    # 2차 인덱싱: 같은 source_id, 청크 2개 — 기존이 모두 삭제되고 2개만 남아야 함
    index_chunks(
        qdrant,
        solar_mock,
        KnowledgeSourceType.NOTICE,
        source_id="n1",
        title="v2",
        texts=["x", "y"],
        official=True,
    )

    results = qdrant.search([0.0] * TEST_VECTOR_SIZE, k=10)
    payloads = [r.payload for r in results if r.payload]
    assert len(payloads) == 2
    assert all(p["title"] == "v2" for p in payloads)


def test_should_returnZeroAndDelete_when_textsEmpty(
    qdrant: QdrantAdapter, solar_mock: MagicMock
) -> None:
    # 사전 인덱싱
    index_chunks(
        qdrant,
        solar_mock,
        KnowledgeSourceType.NOTICE,
        source_id="n1",
        title="v1",
        texts=["a", "b"],
        official=True,
    )
    # 빈 입력 — 기존만 삭제, 임베딩 호출 없음
    solar_mock.embed_passages.reset_mock()
    count = index_chunks(
        qdrant,
        solar_mock,
        KnowledgeSourceType.NOTICE,
        source_id="n1",
        title="v2",
        texts=[],
        official=True,
    )

    assert count == 0
    solar_mock.embed_passages.assert_not_called()
    results = qdrant.search([0.0] * TEST_VECTOR_SIZE, k=10)
    assert results == []


def test_should_setRoomName_when_indexingWebexMessage(
    qdrant: QdrantAdapter, solar_mock: MagicMock
) -> None:
    index_chunks(
        qdrant,
        solar_mock,
        KnowledgeSourceType.WEBEX_MESSAGE,
        source_id="msg-1",
        title="대화",
        texts=["webex 한 줄"],
        official=False,
        room_name="ai5-general",
    )

    results = qdrant.search([0.0] * TEST_VECTOR_SIZE, k=10)
    assert len(results) == 1
    payload = results[0].payload
    assert payload is not None
    assert payload["room_name"] == "ai5-general"
    assert payload["official"] is False
