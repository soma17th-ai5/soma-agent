"""Knowledge RAG answer generation service."""
from __future__ import annotations

import json
from dataclasses import dataclass

from app.adapters.qdrant_client import QdrantAdapter
from app.adapters.solar_chat_client import SolarChatClient, SolarChatError
from app.adapters.solar_client import SolarClient
from app.domain.contracts.knowledge import KnowledgeSourceType, SearchHit
from app.services import knowledge as knowledge_service

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
    llm_error: str | None = None


def ask(
    qdrant: QdrantAdapter,
    solar: SolarClient,
    chat: SolarChatClient,
    query: str,
    *,
    source_types: list[KnowledgeSourceType] | None = None,
    official_only: bool = False,
    room_name: str | None = None,
    k: int = 5,
) -> KnowledgeAnswer:
    hits = knowledge_service.search(
        qdrant,
        solar,
        query,
        source_types=source_types,
        official_only=official_only,
        room_name=room_name,
        k=k,
    )
    if not hits:
        return KnowledgeAnswer(answer="관련 결과를 찾지 못했습니다.", hits=[], llm_used=False)

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
                f"질문: {query.strip()}\n\n"
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
            llm_error=exc.message,
        )

    return KnowledgeAnswer(
        answer=response.content or "검색 결과는 찾았지만 답변을 생성하지 못했습니다.",
        hits=hits,
        llm_used=True,
    )
