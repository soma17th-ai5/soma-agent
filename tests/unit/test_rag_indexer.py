"""RAG 인덱서 단위 테스트.

- chunk_text는 순수 함수 → 직접 검증.
- index_chunks는 Qdrant in-memory + Solar mock으로 결합 검증.
"""
from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest
from qdrant_client import QdrantClient
from qdrant_client.http import models as qm

from app.adapters.qdrant_client import QdrantAdapter
from app.domain.contracts.knowledge import KnowledgeSourceType
from app.domain.models.webex import WebexMessage
from app.services.rag_indexer import (
    _deterministic_chunk_id,
    chunk_text,
    index_chunks,
    index_webex_messages,
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


def test_should_skipBotAndExtractPriorityContent_when_indexingWebexMessages(
    qdrant: QdrantAdapter, solar_mock: MagicMock
) -> None:
    # 1. 봇 메시지 (스킵 대상)
    bot_msg = WebexMessage(
        message_id="BOT1",
        is_bot_sender=True,
        text="이것은 봇이 보내는 아주 긴 메시지입니다. 30자가 넘지만 봇이라서 스킵되어야 합니다.",
        created_at=datetime(2026, 5, 5, tzinfo=UTC),
        collected_at=datetime(2026, 5, 5, tzinfo=UTC),
    )
    # 2. 일반 메시지 (text 우선)
    text_msg = WebexMessage(
        message_id="MSG1",
        is_bot_sender=False,
        text="안녕하세요. 30자가 넘는 일반 텍스트 메시지입니다. 아주 아주 아주 아주 깁니다.",
        markdown="# 마크다운",
        created_at=datetime(2026, 5, 5, tzinfo=UTC),
        collected_at=datetime(2026, 5, 5, tzinfo=UTC),
    )
    # 3. 마크다운 메시지 (text 없고 markdown만)
    md_msg = WebexMessage(
        message_id="MSG2",
        is_bot_sender=False,
        text=None,
        markdown="이것은 마크다운 메시지입니다. 역시 30자가 넘어야 인덱싱이 됩니다. 룰루랄라.",
        created_at=datetime(2026, 5, 5, tzinfo=UTC),
        collected_at=datetime(2026, 5, 5, tzinfo=UTC),
    )
    # 4. HTML 메시지 (태그 제거 확인)
    html_msg = WebexMessage(
        message_id="MSG3",
        is_bot_sender=False,
        text=None,
        markdown=None,
        html="<p>이것은 <b>HTML</b> 메시지입니다. 태그를 제거하면 순수 텍스트만 남아야 하며 30자 기준을 통과해야 합니다.</p>",
        created_at=datetime(2026, 5, 5, tzinfo=UTC),
        collected_at=datetime(2026, 5, 5, tzinfo=UTC),
    )
    # 5. 짧은 메시지 (스킵 대상)
    short_msg = WebexMessage(
        message_id="MSG4",
        is_bot_sender=False,
        text="너무 짧아요",
        created_at=datetime(2026, 5, 5, tzinfo=UTC),
        collected_at=datetime(2026, 5, 5, tzinfo=UTC),
    )

    messages = [
        (bot_msg, "RoomA"),
        (text_msg, "RoomA"),
        (md_msg, "RoomB"),
        (html_msg, "RoomC"),
        (short_msg, "RoomA"),
    ]

    count = index_webex_messages(qdrant, solar_mock, messages)

    # MSG1, MSG2, MSG3 만 인덱싱되어야 함
    assert count == 3

    # MSG1 검증
    res1 = qdrant.search([0.0] * TEST_VECTOR_SIZE, k=10, room_name="RoomA")
    # RoomA 에는 MSG1 만 인덱싱됨 (short_msg 는 스킵되었으므로)
    assert len(res1) == 1
    assert "일반 텍스트 메시지" in res1[0].payload["text"]

    # MSG2 검증
    res2 = qdrant.search([0.0] * TEST_VECTOR_SIZE, k=10, room_name="RoomB")
    assert len(res2) == 1
    assert "마크다운 메시지" in res2[0].payload["text"]

    # MSG3 검증 (HTML 태그 제거 확인)
    res3 = qdrant.search([0.0] * TEST_VECTOR_SIZE, k=10, room_name="RoomC")
    assert len(res3) == 1
    assert "<b>" not in res3[0].payload["text"]
    # BeautifulSoup separator="\n"으로 인해 "HTML" 주변에 개행이 생길 수 있음
    assert "HTML" in res3[0].payload["text"]
    assert "메시지입니다" in res3[0].payload["text"]
