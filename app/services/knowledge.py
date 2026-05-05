"""통합 RAG 검색 서비스.

SPEC §4.2 — 공지/멘토링/Webex 검색은 이 한 함수로 통합. Tool 레이어
(`app/tools/knowledge.py`, #16에서 작성)는 본 모듈을 얇게 감싼다.
"""
from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from app.domain.contracts.knowledge import KnowledgeSourceType, SearchHit

if TYPE_CHECKING:
    from app.adapters.qdrant_client import QdrantAdapter
    from app.adapters.solar_client import SolarClient


def search(
    qdrant: QdrantAdapter,
    solar: SolarClient,
    query: str,
    *,
    source_types: list[KnowledgeSourceType] | None = None,
    official_only: bool = False,
    room_name: str | None = None,
    k: int = 5,
) -> list[SearchHit]:
    """질의에 대한 상위 k개 청크를 반환.

    - 공백/빈 query는 빈 리스트로 즉시 반환 (불필요한 API 호출·검색 방지).
    - 결과는 Qdrant score 내림차순 (Qdrant 기본 정렬 그대로).
    """
    if not query or not query.strip():
        return []

    vector = solar.embed_query(query.strip())
    raw_filter_types = [t.value for t in source_types] if source_types else None
    points = qdrant.search(
        vector,
        source_types=raw_filter_types,
        official_only=official_only,
        room_name=room_name,
        k=k,
    )

    hits: list[SearchHit] = []
    for p in points:
        payload = p.payload or {}
        try:
            source_type = KnowledgeSourceType(payload.get("source_type"))
        except ValueError:
            # 알 수 없는 source_type은 결과에서 제외 — 컬렉션 오염 방어.
            continue

        hits.append(
            SearchHit(
                chunk_id=str(payload.get("chunk_id") or p.id),
                source_type=source_type,
                source_id=str(payload.get("source_id") or ""),
                title=str(payload.get("title") or ""),
                text=str(payload.get("text") or ""),
                official=bool(payload.get("official", False)),
                score=float(p.score or 0.0),
                created_at=_parse_dt(payload.get("created_at")),
                source_url=_as_optional_str(payload.get("source_url")),
                room_name=_as_optional_str(payload.get("room_name")),
            )
        )
    return hits


def _parse_dt(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _as_optional_str(value: object) -> str | None:
    if value is None:
        return None
    return str(value) if value != "" else None
