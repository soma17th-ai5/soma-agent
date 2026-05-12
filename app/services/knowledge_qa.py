"""Knowledge RAG answer generation service."""
from __future__ import annotations

import json
from dataclasses import dataclass

from app.adapters.qdrant_client import QdrantAdapter
from app.adapters.solar_chat_client import SolarChatClient, SolarChatError
from app.adapters.solar_client import SolarClient
from app.domain.contracts.knowledge import KnowledgeSourceType, SearchHit
from app.services import knowledge as knowledge_service

_ROUTER_SYSTEM_PROMPT = """\
당신은 SomaAgent의 검색 라우터입니다.
사용자 메시지를 보고 검색에 사용할 query와 source_types를 결정하세요.
반드시 JSON 객체만 답하세요.

가능한 source_types:
- MENTORING: 멘토링, 특강, 멘토, 신청 가능한 프로그램
- NOTICE: 공지사항, 안내, 모집, 제출
- NOTICE_PDF: 공지 첨부 PDF 내용
- WEBEX_MESSAGE: Webex, 회의, 채팅, 대화 내용

형식:
{"query":"검색에 사용할 짧은 문장","source_types":["MENTORING"],"official_only":false,"k":5}

애매하면 여러 source_types를 고르거나 빈 배열을 반환하세요.
official_only는 사용자가 공식/소마 기준을 요구하면 true, Webex/대화까지 포함하면 false입니다.
k는 1~20 사이 정수입니다. 사용자가 개수를 말하지 않으면 5입니다.
"""

_SYSTEM_PROMPT = """\
당신은 SomaAgent의 검색 기반 응답 작성자입니다.
주어진 검색 결과 컨텍스트에 있는 사실만 사용해서 한국어로 답하세요.
컨텍스트에 없는 내용은 추측하지 말고, 부족하면 부족하다고 말하세요.
답변은 2~5문장으로 간결하게 작성하세요.
"""


@dataclass(frozen=True)
class KnowledgeAnswer:
    answer: str
    hits: list[SearchHit]
    llm_used: bool
    resolved_query: str
    source_types: list[KnowledgeSourceType] | None
    official_only: bool
    k: int
    router_used: bool
    router_error: str | None = None
    llm_error: str | None = None


@dataclass(frozen=True)
class RouteDecision:
    query: str
    source_types: list[KnowledgeSourceType] | None
    official_only: bool
    k: int
    router_used: bool
    router_error: str | None = None


def ask(
    qdrant: QdrantAdapter,
    solar: SolarClient,
    chat: SolarChatClient,
    message: str,
) -> KnowledgeAnswer:
    route = _route_message(chat, message)
    hits = knowledge_service.search(
        qdrant,
        solar,
        route.query,
        source_types=route.source_types,
        official_only=route.official_only,
        k=route.k,
    )
    if not hits:
        return KnowledgeAnswer(
            answer="관련 결과를 찾지 못했습니다.",
            hits=[],
            llm_used=False,
            resolved_query=route.query,
            source_types=route.source_types,
            official_only=route.official_only,
            k=route.k,
            router_used=route.router_used,
            router_error=route.router_error,
        )

    context = [
        {
            "source_type": hit.source_type.value,
            "source_id": hit.source_id,
            "title": hit.title,
            "text": hit.text,
            "score": hit.score,
            "created_at": hit.created_at.isoformat() if hit.created_at else None,
            "source_url": hit.source_url,
            "room_name": hit.room_name,
        }
        for hit in hits
    ]
    messages = [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                f"질문: {message.strip()}\n"
                f"검색 query: {route.query}\n\n"
                "검색 결과 컨텍스트(JSON):\n"
                f"{json.dumps(context, ensure_ascii=False)}"
            ),
        },
    ]

    try:
        response = chat.chat(messages, temperature=0.0)
    except SolarChatError as exc:
        return KnowledgeAnswer(
            answer="검색 결과는 찾았지만 LLM 답변 생성에 실패했습니다.",
            hits=hits,
            llm_used=False,
            resolved_query=route.query,
            source_types=route.source_types,
            official_only=route.official_only,
            k=route.k,
            router_used=route.router_used,
            router_error=route.router_error,
            llm_error=exc.message,
        )

    return KnowledgeAnswer(
        answer=response.content or "검색 결과는 찾았지만 답변을 생성하지 못했습니다.",
        hits=hits,
        llm_used=True,
        resolved_query=route.query,
        source_types=route.source_types,
        official_only=route.official_only,
        k=route.k,
        router_used=route.router_used,
        router_error=route.router_error,
    )


def _route_message(chat: SolarChatClient, message: str) -> RouteDecision:
    fallback = RouteDecision(
        query=message.strip(),
        source_types=None,
        official_only=False,
        k=5,
        router_used=False,
        router_error=None,
    )
    try:
        response = chat.chat(
            [
                {"role": "system", "content": _ROUTER_SYSTEM_PROMPT},
                {"role": "user", "content": message.strip()},
            ],
            temperature=0.0,
        )
    except SolarChatError as exc:
        return RouteDecision(
            query=fallback.query,
            source_types=None,
            official_only=fallback.official_only,
            k=fallback.k,
            router_used=False,
            router_error=exc.message,
        )

    if not response.content:
        return RouteDecision(
            query=fallback.query,
            source_types=None,
            official_only=fallback.official_only,
            k=fallback.k,
            router_used=False,
            router_error="empty router response",
        )

    try:
        raw = json.loads(response.content)
        query = str(raw.get("query") or fallback.query).strip() or fallback.query
        raw_types = raw.get("source_types") or []
        source_types = [KnowledgeSourceType(t) for t in raw_types] if raw_types else None
        official_only = bool(raw.get("official_only", fallback.official_only))
        k = _normalize_k(raw.get("k"), fallback.k)
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        return RouteDecision(
            query=fallback.query,
            source_types=None,
            official_only=fallback.official_only,
            k=fallback.k,
            router_used=False,
            router_error=str(exc),
        )

    return RouteDecision(
        query=query,
        source_types=source_types,
        official_only=official_only,
        k=k,
        router_used=True,
    )


def _normalize_k(value: object, default: int) -> int:
    try:
        k = int(value)
    except (TypeError, ValueError):
        return default
    return min(max(k, 1), 20)
