"""Knowledge(통합 RAG) 도메인 컨트랙트.

`knowledge.search` tool과 인덱서가 주고받는 내부 데이터 구조 정의.
SPEC §3.2 (Qdrant 컬렉션) / §4.2 (`knowledge.search` tool) 참고.

이 모듈은 외부 라이브러리(qdrant-client, httpx)에 의존하지 않는다 — 어댑터/서비스
경계를 가로지르는 *순수 데이터 컨트랙트*만 둔다.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class KnowledgeSourceType(StrEnum):
    """RAG 인덱싱 대상 원천 타입. SPEC §3.2 payload `source_type` 참고.

    str 상속으로 Qdrant payload·로깅·외부 직렬화에서 그대로 사용 가능.
    """

    NOTICE = "NOTICE"
    NOTICE_PDF = "NOTICE_PDF"
    MENTORING = "MENTORING"
    WEBEX_MESSAGE = "WEBEX_MESSAGE"


@dataclass(frozen=True)
class SearchHit:
    """`knowledge.search`의 단일 매치 결과.

    Qdrant 검색 결과(payload + score)를 도메인 친화적 형태로 변환한 값 객체.
    `source_url` 또는 `created_at`은 원천에 따라 누락될 수 있다 (예: Webex 메시지).
    """

    chunk_id: str
    source_type: KnowledgeSourceType
    source_id: str
    title: str
    text: str
    official: bool
    score: float
    created_at: datetime | None = None
    source_url: str | None = None
    room_name: str | None = None
