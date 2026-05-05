"""knowledge.search 서비스 통합 테스트.

Qdrant in-memory + Solar mock으로 인덱싱→검색 라운드트립 검증.
"""
from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest
from qdrant_client import QdrantClient

from app.adapters.qdrant_client import QdrantAdapter
from app.domain.contracts.knowledge import KnowledgeSourceType, SearchHit
from app.services.knowledge import search
from app.services.rag_indexer import index_chunks

TEST_VECTOR_SIZE = 8


@pytest.fixture
def qdrant() -> QdrantAdapter:
    raw = QdrantClient(":memory:")
    adapter = QdrantAdapter(
        client=raw, collection="search_test", vector_size=TEST_VECTOR_SIZE
    )
    adapter.ensure_collection()
    return adapter


@pytest.fixture
def solar_mock() -> MagicMock:
    """결정적 임베딩: 텍스트별로 인덱스 기반 벡터를 반환.

    검색 시 query 임베딩이 특정 청크와 가깝도록 측정 가능.
    """
    mock = MagicMock()
    mock.embed_passages.side_effect = lambda texts: [
        [float(i + 1)] + [0.0] * (TEST_VECTOR_SIZE - 1) for i, _ in enumerate(texts)
    ]
    return mock


def test_should_returnSearchHits_when_querySucceeds(
    qdrant: QdrantAdapter, solar_mock: MagicMock
) -> None:
    index_chunks(
        qdrant,
        solar_mock,
        KnowledgeSourceType.NOTICE,
        source_id="n1",
        title="중간발표 안내",
        texts=["중간발표 일정은 다음과 같습니다."],
        official=True,
        source_url="https://example.com/n1",
        created_at=datetime(2026, 5, 1, tzinfo=UTC),
    )
    # query 벡터: 첫 청크와 같은 방향 → 가장 유사
    solar_mock.embed_query.return_value = [1.0] + [0.0] * (TEST_VECTOR_SIZE - 1)

    hits = search(qdrant, solar_mock, "중간발표 언제예요?", k=5)

    assert len(hits) == 1
    hit = hits[0]
    assert isinstance(hit, SearchHit)
    assert hit.source_type == KnowledgeSourceType.NOTICE
    assert hit.source_id == "n1"
    assert hit.title == "중간발표 안내"
    assert hit.text == "중간발표 일정은 다음과 같습니다."
    assert hit.official is True
    assert hit.source_url == "https://example.com/n1"
    assert hit.created_at == datetime(2026, 5, 1, tzinfo=UTC)
    assert hit.score > 0


def test_should_returnEmpty_when_queryIsBlank(
    qdrant: QdrantAdapter, solar_mock: MagicMock
) -> None:
    hits = search(qdrant, solar_mock, "   ")

    assert hits == []
    solar_mock.embed_query.assert_not_called()


def test_should_filterBySourceType_when_specified(
    qdrant: QdrantAdapter, solar_mock: MagicMock
) -> None:
    index_chunks(
        qdrant,
        solar_mock,
        KnowledgeSourceType.NOTICE,
        source_id="n1",
        title="공지",
        texts=["공지 본문"],
        official=True,
    )
    index_chunks(
        qdrant,
        solar_mock,
        KnowledgeSourceType.MENTORING,
        source_id="m1",
        title="멘토링",
        texts=["멘토링 본문"],
        official=True,
    )
    solar_mock.embed_query.return_value = [1.0] + [0.0] * (TEST_VECTOR_SIZE - 1)

    hits = search(
        qdrant,
        solar_mock,
        "검색",
        source_types=[KnowledgeSourceType.MENTORING],
        k=5,
    )

    assert len(hits) == 1
    assert hits[0].source_type == KnowledgeSourceType.MENTORING


def test_should_returnOnlyOfficial_when_officialOnly(
    qdrant: QdrantAdapter, solar_mock: MagicMock
) -> None:
    index_chunks(
        qdrant,
        solar_mock,
        KnowledgeSourceType.NOTICE,
        source_id="n1",
        title="공식",
        texts=["공식 본문"],
        official=True,
    )
    index_chunks(
        qdrant,
        solar_mock,
        KnowledgeSourceType.WEBEX_MESSAGE,
        source_id="msg-1",
        title="비공식",
        texts=["비공식 본문"],
        official=False,
        room_name="room",
    )
    solar_mock.embed_query.return_value = [1.0] + [0.0] * (TEST_VECTOR_SIZE - 1)

    hits = search(qdrant, solar_mock, "검색", official_only=True, k=10)

    assert len(hits) == 1
    assert hits[0].official is True
    assert hits[0].source_type == KnowledgeSourceType.NOTICE


def test_should_filterByRoomName_when_specified(
    qdrant: QdrantAdapter, solar_mock: MagicMock
) -> None:
    index_chunks(
        qdrant,
        solar_mock,
        KnowledgeSourceType.WEBEX_MESSAGE,
        source_id="msg-1",
        title="방A",
        texts=["방A 메시지"],
        official=False,
        room_name="room-A",
    )
    index_chunks(
        qdrant,
        solar_mock,
        KnowledgeSourceType.WEBEX_MESSAGE,
        source_id="msg-2",
        title="방B",
        texts=["방B 메시지"],
        official=False,
        room_name="room-B",
    )
    solar_mock.embed_query.return_value = [1.0] + [0.0] * (TEST_VECTOR_SIZE - 1)

    hits = search(qdrant, solar_mock, "검색", room_name="room-A", k=10)

    assert len(hits) == 1
    assert hits[0].room_name == "room-A"


def test_should_useQueryModel_when_searching(
    qdrant: QdrantAdapter, solar_mock: MagicMock
) -> None:
    """검색 시에는 embed_query만 호출, embed_passages는 인덱싱에서만."""
    solar_mock.embed_query.return_value = [0.5] * TEST_VECTOR_SIZE

    search(qdrant, solar_mock, "쿼리")

    solar_mock.embed_query.assert_called_once_with("쿼리")
