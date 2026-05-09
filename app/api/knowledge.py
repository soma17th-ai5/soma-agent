"""Knowledge RAG endpoints."""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.api.deps import QdrantDep, SolarChatDep, SolarDep
from app.domain.contracts.knowledge import KnowledgeSourceType, SearchHit
from app.services import knowledge_qa

router = APIRouter(prefix="/api/v1/knowledge", tags=["knowledge"])


class KnowledgeAskRequest(BaseModel):
    query: str = Field(min_length=1, description="질문")
    source_types: list[KnowledgeSourceType] | None = Field(
        default=None,
        description="검색 대상. 예: MENTORING, NOTICE, WEBEX_MESSAGE",
    )
    official_only: bool = False
    room_name: str | None = None
    k: int = Field(default=5, ge=1, le=20)


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


class KnowledgeAskResponse(BaseModel):
    answer: str
    sources: list[KnowledgeSource]
    llm_used: bool
    llm_error: str | None = None


@router.post("/ask", response_model=KnowledgeAskResponse)
def ask_knowledge(
    body: KnowledgeAskRequest,
    qdrant: QdrantDep,
    solar: SolarDep,
    chat: SolarChatDep,
) -> KnowledgeAskResponse:
    result = knowledge_qa.ask(
        qdrant,
        solar,
        chat,
        body.query,
        source_types=body.source_types,
        official_only=body.official_only,
        room_name=body.room_name,
        k=body.k,
    )
    return KnowledgeAskResponse(
        answer=result.answer,
        sources=[_source_from_hit(hit) for hit in result.hits],
        llm_used=result.llm_used,
        llm_error=result.llm_error,
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
