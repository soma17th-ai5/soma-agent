"""Qdrant 어댑터 단위 테스트. qdrant-client의 in-memory 모드 사용 (실 네트워크 X)."""
from __future__ import annotations

import pytest
from qdrant_client import QdrantClient
from qdrant_client.http import models as qm

from app.adapters.qdrant_client import QdrantAdapter

# 테스트 속도 위해 작은 차원 사용. 실제 운영은 4096차원 (SPEC §3.2).
TEST_VECTOR_SIZE = 8


@pytest.fixture
def adapter() -> QdrantAdapter:
    raw = QdrantClient(":memory:")
    return QdrantAdapter(
        client=raw,
        collection="test_chunks",
        vector_size=TEST_VECTOR_SIZE,
    )


def _vec(seed: float) -> list[float]:
    """간단한 결정적 벡터 생성기. cosine 유사도 비교 가능하게 다양화."""
    return [seed + i * 0.01 for i in range(TEST_VECTOR_SIZE)]


def _point(
    pid: str,
    *,
    source_type: str,
    source_id: str,
    text: str,
    official: bool = True,
    room_name: str | None = None,
    seed: float = 0.1,
) -> qm.PointStruct:
    payload: dict[str, object] = {
        "chunk_id": pid,
        "source_type": source_type,
        "source_id": source_id,
        "title": f"title-{source_id}",
        "text": text,
        "official": official,
    }
    if room_name is not None:
        payload["room_name"] = room_name
    return qm.PointStruct(id=pid, vector=_vec(seed), payload=payload)


def test_should_beIdempotent_when_ensureCollectionCalledTwice(
    adapter: QdrantAdapter,
) -> None:
    adapter.ensure_collection()
    adapter.ensure_collection()  # 두 번째 호출에도 예외 없이 통과해야 함

    collections = {c.name for c in adapter.raw.get_collections().collections}
    assert "test_chunks" in collections


def test_should_returnUpsertedPoint_when_searchAfterUpsert(
    adapter: QdrantAdapter,
) -> None:
    adapter.ensure_collection()
    pid = "11111111-1111-1111-1111-111111111111"
    adapter.upsert([_point(pid, source_type="NOTICE", source_id="n1", text="hello")])

    results = adapter.search(_vec(0.1), k=5)

    assert len(results) == 1
    assert str(results[0].id) == pid
    assert results[0].payload is not None
    assert results[0].payload["source_id"] == "n1"


def test_should_filterBySourceType_when_searchWithSourceTypes(
    adapter: QdrantAdapter,
) -> None:
    adapter.ensure_collection()
    adapter.upsert(
        [
            _point(
                "11111111-1111-1111-1111-111111111111",
                source_type="NOTICE",
                source_id="n1",
                text="공지",
            ),
            _point(
                "22222222-2222-2222-2222-222222222222",
                source_type="MENTORING",
                source_id="m1",
                text="멘토링",
                seed=0.11,
            ),
            _point(
                "33333333-3333-3333-3333-333333333333",
                source_type="WEBEX_MESSAGE",
                source_id="w1",
                text="webex",
                official=False,
                room_name="room-A",
                seed=0.12,
            ),
        ]
    )

    results = adapter.search(_vec(0.1), source_types=["NOTICE", "MENTORING"], k=10)

    types = {r.payload["source_type"] for r in results if r.payload}
    assert types == {"NOTICE", "MENTORING"}


def test_should_filterOfficialOnly_when_searchWithOfficialFlag(
    adapter: QdrantAdapter,
) -> None:
    adapter.ensure_collection()
    adapter.upsert(
        [
            _point(
                "11111111-1111-1111-1111-111111111111",
                source_type="NOTICE",
                source_id="n1",
                text="공식",
                official=True,
            ),
            _point(
                "22222222-2222-2222-2222-222222222222",
                source_type="WEBEX_MESSAGE",
                source_id="w1",
                text="비공식",
                official=False,
                room_name="room-A",
                seed=0.11,
            ),
        ]
    )

    results = adapter.search(_vec(0.1), official_only=True, k=10)

    assert len(results) == 1
    assert results[0].payload is not None
    assert results[0].payload["official"] is True


def test_should_removeAllChunks_when_deleteBySource(
    adapter: QdrantAdapter,
) -> None:
    adapter.ensure_collection()
    adapter.upsert(
        [
            _point(
                "11111111-1111-1111-1111-111111111111",
                source_type="NOTICE",
                source_id="n1",
                text="청크1",
            ),
            _point(
                "22222222-2222-2222-2222-222222222222",
                source_type="NOTICE",
                source_id="n1",
                text="청크2",
                seed=0.11,
            ),
            _point(
                "33333333-3333-3333-3333-333333333333",
                source_type="NOTICE",
                source_id="n2",
                text="다른 공지",
                seed=0.12,
            ),
        ]
    )

    adapter.delete_by_source("NOTICE", "n1")

    results = adapter.search(_vec(0.1), k=10)
    remaining_ids = {r.payload["source_id"] for r in results if r.payload}
    assert remaining_ids == {"n2"}


def test_should_beNoOp_when_deleteBySourceWithUnknownId(
    adapter: QdrantAdapter,
) -> None:
    adapter.ensure_collection()
    # 매칭 없는 삭제는 예외 없이 통과해야 함 (멱등성).
    adapter.delete_by_source("NOTICE", "nonexistent")
