"""RAG 인덱싱 헬퍼.

청킹 → 임베딩 → Qdrant upsert까지 묶는 *공용* 헬퍼. 도메인별 sync 잡(공지/멘토링/Webex)이
이 모듈을 호출해 동일한 형식의 청크를 단일 컬렉션에 적재하도록 한다.

설계 메모:
- 함수 위주, 의존성은 인자로 주입(테스트 용이성).
- chunking은 v1에서 단순 char 기반. 토큰 기반 청킹은 v2 (#10/#15에서 평가).
- point ID는 (source_type, source_id, chunk_idx) 해시로 결정성 보장 →
  같은 입력 재인덱싱 시 같은 ID가 나와 멱등.
"""
from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from qdrant_client.http import models as qm

from app.domain.contracts.knowledge import KnowledgeSourceType

if TYPE_CHECKING:
    from app.adapters.qdrant_client import QdrantAdapter
    from app.adapters.solar_client import SolarClient


# 단순 문자 기반 청킹 기본값. 한국어 평균을 고려해 ~800자 청크에 ~80자 overlap.
DEFAULT_MAX_CHARS = 800
DEFAULT_OVERLAP = 80


def chunk_text(
    text: str,
    *,
    max_chars: int = DEFAULT_MAX_CHARS,
    overlap: int = DEFAULT_OVERLAP,
) -> list[str]:
    """문자 기반 sliding window 청킹.

    - 빈 문자열/공백만 입력 시 빈 리스트 반환.
    - `max_chars` 이하면 단일 청크로 그대로 반환.
    - overlap이 max_chars 이상이면 ValueError — 무한 루프 방지.
    """
    if max_chars <= 0:
        raise ValueError("max_chars must be positive")
    if overlap < 0 or overlap >= max_chars:
        raise ValueError("overlap must be in [0, max_chars)")

    cleaned = text.strip()
    if not cleaned:
        return []
    if len(cleaned) <= max_chars:
        return [cleaned]

    step = max_chars - overlap
    chunks: list[str] = []
    start = 0
    while start < len(cleaned):
        end = start + max_chars
        chunk = cleaned[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= len(cleaned):
            break
        start += step
    return chunks


def index_chunks(
    qdrant: QdrantAdapter,
    solar: SolarClient,
    source_type: KnowledgeSourceType,
    source_id: str,
    *,
    title: str,
    texts: list[str],
    official: bool,
    source_url: str | None = None,
    room_name: str | None = None,
    created_at: datetime | None = None,
    collected_at: datetime | None = None,
    source_ref: str | None = None,
) -> int:
    """청크 리스트를 Qdrant에 적재. 같은 (source_type, source_id) 기존 청크는 선삭제.

    Args:
        texts: 사전에 청킹된 텍스트 목록. 호출자가 `chunk_text`로 분할하거나 도메인별
            특수 청킹(예: 공지의 첨부 PDF별)을 적용한 결과를 그대로 전달.
        official: OpenSoma 출처면 True, Webex면 False (SPEC §3.2).

    Returns:
        실제로 인덱싱된 청크 수. `texts`가 비어있으면 0과 함께 *기존 청크는 삭제*만 수행
        — "원천이 비워졌다"를 표현 가능.
    """
    # 재인덱싱: 항상 먼저 삭제. 입력이 비어있어도 "원천 삭제" 시나리오를 지원.
    qdrant.delete_by_source(source_type.value, source_id)

    if not texts:
        return 0

    vectors = solar.embed_passages(texts)
    if len(vectors) != len(texts):
        raise RuntimeError(
            f"embedding count mismatch: got {len(vectors)} for {len(texts)} texts"
        )

    now = collected_at or datetime.now(UTC)
    points: list[qm.PointStruct] = []
    for idx, (chunk, vector) in enumerate(zip(texts, vectors, strict=True)):
        chunk_uuid = _deterministic_chunk_id(source_type.value, source_id, idx)
        payload: dict[str, object] = {
            "chunk_id": chunk_uuid,
            "source_type": source_type.value,
            "source_id": source_id,
            "title": title,
            "text": chunk,
            "official": official,
            "collected_at": now.isoformat(),
        }
        if created_at is not None:
            payload["created_at"] = created_at.isoformat()
        if source_url is not None:
            payload["source_url"] = source_url
        if room_name is not None:
            payload["room_name"] = room_name
        if source_ref is not None:
            payload["source_ref"] = source_ref

        points.append(
            qm.PointStruct(id=chunk_uuid, vector=vector, payload=payload)
        )

    qdrant.upsert(points)
    return len(points)


def _deterministic_chunk_id(source_type: str, source_id: str, chunk_idx: int) -> str:
    """동일 (source_type, source_id, chunk_idx)에서 같은 UUID를 생성.

    Qdrant point ID는 UUID 또는 int여야 하므로, sha1 해시를 16바이트로 잘라 UUID로 변환.
    deterministic이므로 재인덱싱 시 멱등하다.
    """
    raw = f"{source_type}|{source_id}|{chunk_idx}".encode()
    digest = hashlib.sha1(raw, usedforsecurity=False).digest()[:16]
    return str(uuid.UUID(bytes=digest))
