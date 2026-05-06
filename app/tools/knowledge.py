"""knowledge.search tool. SPEC §4.2 — 모든 RAG 진입점."""
from __future__ import annotations

from dataclasses import asdict
from typing import Any

from app.domain.contracts.knowledge import KnowledgeSourceType, SearchHit
from app.domain.contracts.source import Source
from app.domain.contracts.tool_result import Artifact, ToolResult
from app.services import knowledge as knowledge_service
from app.tools._helpers import failed_result
from app.tools.base import Tool, ToolContext


def _hit_dict(hit: SearchHit) -> dict[str, Any]:
    """SearchHit는 frozen dataclass → JSON 호환 dict로 변환. datetime은 ISO 문자열."""
    raw = asdict(hit)
    if hit.created_at is not None:
        raw["created_at"] = hit.created_at.isoformat()
    raw["source_type"] = hit.source_type.value
    return raw


def _hit_to_source(hit: SearchHit) -> Source:
    """SearchHit → SPEC §6.1 Source. source_type 매핑은 contracts 일치."""
    type_map: dict[KnowledgeSourceType, str] = {
        KnowledgeSourceType.NOTICE: "notice",
        KnowledgeSourceType.NOTICE_PDF: "notice_pdf",
        KnowledgeSourceType.MENTORING: "mentoring",
        KnowledgeSourceType.WEBEX_MESSAGE: "webex_message",
    }
    return Source(
        id=hit.source_id or hit.chunk_id,
        type=type_map.get(hit.source_type, "other"),  # type: ignore[arg-type]
        title=hit.title,
        url=hit.source_url,
        created_at=hit.created_at.isoformat() if hit.created_at else None,
        official=hit.official,
        raw_ref=hit.chunk_id,
    )


class KnowledgeSearchTool(Tool):
    """통합 RAG 검색. 공지/멘토링/Webex 모두 단일 컬렉션·단일 tool."""

    name = "knowledge.search"
    domain = "rag"
    operation = "search"
    requires_auth = False

    async def run(self, params: dict[str, Any], ctx: ToolContext) -> ToolResult:
        if ctx.qdrant is None or ctx.solar is None:
            return failed_result(
                tool=self.name,
                domain=self.domain,
                operation=self.operation,
                code="MISSING_DEPS",
                message="qdrant/solar dependencies not provided",
            )

        query = (params.get("query") or "").strip()
        if not query:
            # 빈 query는 즉시 success(빈 결과). LLM이 잘못 호출해도 비용 0.
            return ToolResult(
                tool=self.name,
                domain=self.domain,
                operation=self.operation,
                status="success",
                data=[],
            )

        try:
            raw_types = params.get("source_types") or []
            source_types = [KnowledgeSourceType(t) for t in raw_types] if raw_types else None
        except ValueError as e:
            return failed_result(
                tool=self.name,
                domain=self.domain,
                operation=self.operation,
                code="INVALID_SOURCE_TYPE",
                message=str(e),
            )

        try:
            hits = knowledge_service.search(
                ctx.qdrant,
                ctx.solar,
                query,
                source_types=source_types,
                official_only=bool(params.get("official_only", False)),
                room_name=params.get("room_name"),
                k=int(params.get("k", 5)),
            )
        except Exception as e:  # 외부 호출 실패는 흡수 — 그래프는 끝까지 진행.
            return failed_result(
                tool=self.name,
                domain=self.domain,
                operation=self.operation,
                code="KNOWLEDGE_SEARCH_FAILED",
                message=str(e),
                recoverable=True,
            )

        sources = [_hit_to_source(h) for h in hits]
        artifacts = [
            Artifact(
                type="list",
                title="검색 결과",
                items=[_hit_dict(h) for h in hits],
            )
        ]
        return ToolResult(
            tool=self.name,
            domain=self.domain,
            operation=self.operation,
            status="success",
            data=[_hit_dict(h) for h in hits],
            sources=sources,
            artifacts=artifacts,
        )
