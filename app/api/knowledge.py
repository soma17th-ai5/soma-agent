"""Chat/RAG endpoints."""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.api.deps import QdrantDep, SolarChatDep, SolarDep
from app.domain.contracts.knowledge import KnowledgeSourceType, SearchHit
from app.services import knowledge_qa

router = APIRouter(prefix="/api/v1", tags=["chat"])


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, description="사용자 메시지")


class KnowledgeSource(BaseModel):
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


class ChatResponse(BaseModel):
    answer: str
    sources: list[KnowledgeSource]
    llm_used: bool
    llm_error: str | None = None
    metadata: dict[str, object]


@router.post("/chat", response_model=ChatResponse)
def chat(
    body: ChatRequest,
    qdrant: QdrantDep,
    solar: SolarDep,
    chat: SolarChatDep,
) -> ChatResponse:
    result = knowledge_qa.ask(
        qdrant,
        solar,
        chat,
        body.message,
    )
    return ChatResponse(
        answer=result.answer,
        sources=[_source_from_hit(hit) for hit in result.hits],
        llm_used=result.llm_used,
        llm_error=result.llm_error,
        metadata={
            "resolved_query": result.resolved_query,
            "source_types": [source_type.value for source_type in result.source_types]
            if result.source_types
            else [],
            "official_only": result.official_only,
            "k": result.k,
            "router": "llm" if result.router_used else "fallback",
            "router_error": result.router_error,
        },
    )


def _source_from_hit(hit: SearchHit) -> KnowledgeSource:
    return KnowledgeSource(
        chunk_id=hit.chunk_id,
        source_type=hit.source_type,
        source_id=hit.source_id,
        title=hit.title,
        text=hit.text,
        official=hit.official,
        score=hit.score,
        created_at=hit.created_at,
        source_url=hit.source_url,
        room_name=hit.room_name,
    )
