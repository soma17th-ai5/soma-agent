"""Qdrant 벡터 DB 어댑터.

SPEC §3.2 — 단일 컬렉션(`soma_chunks`)에 4096차원 cosine 벡터로 저장,
`source_type`/`official`/`room_name` 페이로드 필터로 도메인 분리.

본 어댑터는 *얇은 래퍼*로, 실제 chunking·embedding은 `services/rag_indexer.py`,
검색 결과의 `SearchHit` 변환은 `services/knowledge.py`에서 담당.
"""
from __future__ import annotations

import contextlib
from typing import Any

from qdrant_client import QdrantClient as _RawQdrantClient
from qdrant_client.http import models as qm

from app.config import get_settings

# SPEC §3.2 명시 — Solar embedding 차원 (passage·query 동일).
DEFAULT_VECTOR_SIZE = 4096
DEFAULT_DISTANCE = qm.Distance.COSINE

# Qdrant payload 인덱스. SPEC §3.2 schema의 keyword/text 구분과 일치.
_KEYWORD_FIELDS = (
    "chunk_id",
    "source_type",
    "source_id",
    "official",
    "room_name",
    "source_url",
    "source_ref",
)


class QdrantAdapter:
    """Qdrant 클라이언트 래퍼.

    프로덕션: `host`/`port`를 settings에서 읽어 HTTP 모드로 연결.
    테스트: 생성자에 `client=QdrantClient(":memory:")`를 주입해 in-memory 모드 사용.
    """

    def __init__(
        self,
        *,
        client: _RawQdrantClient | None = None,
        host: str | None = None,
        port: int | None = None,
        collection: str | None = None,
        vector_size: int = DEFAULT_VECTOR_SIZE,
    ) -> None:
        settings = get_settings()
        self._collection = collection or settings.qdrant_collection
        self._vector_size = vector_size
        if client is not None:
            self._client = client
        else:
            self._client = _RawQdrantClient(
                host=host or settings.qdrant_host,
                port=port or settings.qdrant_port,
            )

    @property
    def collection(self) -> str:
        return self._collection

    @property
    def raw(self) -> _RawQdrantClient:
        """저수준 클라이언트 노출 (테스트·고급 사용에 한정)."""
        return self._client

    def close(self) -> None:
        self._client.close()

    # --- 컬렉션 -----------------------------------------------------------

    def ensure_collection(self) -> None:
        """컬렉션이 없으면 생성. 멱등성 보장.

        - 벡터: cosine, 4096차원
        - 페이로드 인덱스: keyword/bool 필드는 명시적으로 색인 → 필터 성능 확보
        """
        existing = {c.name for c in self._client.get_collections().collections}
        if self._collection not in existing:
            self._client.create_collection(
                collection_name=self._collection,
                vectors_config=qm.VectorParams(
                    size=self._vector_size, distance=DEFAULT_DISTANCE
                ),
            )

        # 페이로드 인덱스 생성 — 이미 있으면 Qdrant가 멱등 처리.
        for field in _KEYWORD_FIELDS:
            self._safe_create_payload_index(field, qm.PayloadSchemaType.KEYWORD)
        # `created_at`/`collected_at`은 datetime → 문자열 keyword로 저장한다고 가정.
        # 범위 필터가 필요해지면 후속 마이그레이션에서 datetime 인덱스로 전환 (#10/#15).

    def _safe_create_payload_index(
        self, field_name: str, schema: qm.PayloadSchemaType
    ) -> None:
        # 이미 존재하는 인덱스는 무시 (멱등성).
        with contextlib.suppress(Exception):
            self._client.create_payload_index(
                collection_name=self._collection,
                field_name=field_name,
                field_schema=schema,
            )

    # --- Upsert / Delete --------------------------------------------------

    def upsert(self, points: list[qm.PointStruct]) -> None:
        """청크 포인트 일괄 저장. 빈 리스트는 no-op."""
        if not points:
            return
        self._client.upsert(collection_name=self._collection, points=points)

    def delete_by_source(self, source_type: str, source_id: str) -> None:
        """재인덱싱을 위해 (source_type, source_id) 조합의 모든 청크 삭제.

        멱등 — 매칭 포인트가 없어도 예외 없음.
        """
        flt = qm.Filter(
            must=[
                qm.FieldCondition(
                    key="source_type", match=qm.MatchValue(value=source_type)
                ),
                qm.FieldCondition(
                    key="source_id", match=qm.MatchValue(value=source_id)
                ),
            ]
        )
        self._client.delete(
            collection_name=self._collection,
            points_selector=qm.FilterSelector(filter=flt),
        )

    # --- Search -----------------------------------------------------------

    def search(
        self,
        vector: list[float],
        *,
        source_types: list[str] | None = None,
        official_only: bool = False,
        room_name: str | None = None,
        k: int = 5,
    ) -> list[qm.ScoredPoint]:
        """벡터 유사도 검색 + 메타데이터 필터.

        - `source_types`: 비어있지 않으면 OR 매칭(`MatchAny`)
        - `official_only`: True면 `official == true`만
        - `room_name`: 주어지면 정확 매칭 (Webex 메시지 분리용)
        """
        flt = _build_search_filter(
            source_types=source_types,
            official_only=official_only,
            room_name=room_name,
        )
        # qdrant-client >=1.10에서 `search`는 deprecated. `query_points` 사용 (universal API).
        response = self._client.query_points(
            collection_name=self._collection,
            query=vector,
            query_filter=flt,
            limit=k,
            with_payload=True,
        )
        return list(response.points)


def _build_search_filter(
    *,
    source_types: list[str] | None,
    official_only: bool,
    room_name: str | None,
) -> qm.Filter | None:
    must: list[Any] = []
    if source_types:
        must.append(
            qm.FieldCondition(
                key="source_type", match=qm.MatchAny(any=list(source_types))
            )
        )
    if official_only:
        must.append(
            qm.FieldCondition(key="official", match=qm.MatchValue(value=True))
        )
    if room_name:
        must.append(
            qm.FieldCondition(key="room_name", match=qm.MatchValue(value=room_name))
        )
    if not must:
        return None
    return qm.Filter(must=must)
