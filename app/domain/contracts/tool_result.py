"""Tool 호출 결과 contract. SPEC §6.1.

- ToolResult: 백엔드 내부 통합 형식 (Tool 단위 1개 결과)
- Artifact: 프론트가 카드/리스트/표로 그릴 수 있는 표시 데이터
- ActionProposal/ActionResult는 contracts/action.py
- ToolError: 실패 시 detail
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel

from app.domain.contracts.action import ActionProposal, ActionResult
from app.domain.contracts.source import Source

ToolStatus = Literal["success", "partial", "failed", "needs_confirmation"]
ArtifactType = Literal["card", "list", "table", "markdown", "confirmation"]
# SPEC §6.1 verbatim. knowledge.search 도메인은 "rag" (검색 카테고리),
# webex 메시지 요약 결과는 "webex" — Tool 이름과 별개의 분류 축이다.
DomainType = Literal["opensoma", "rag", "webex", "calendar", "system"]


class Artifact(BaseModel):
    type: ArtifactType
    title: str | None = None
    items: list[Any] | None = None
    content: str | None = None


class ToolError(BaseModel):
    code: str
    message: str
    recoverable: bool = False


class ToolResult(BaseModel):
    tool: str
    domain: DomainType
    operation: str
    status: ToolStatus
    data: Any | None = None
    sources: list[Source] = []
    artifacts: list[Artifact] = []
    action: ActionProposal | ActionResult | None = None
    error: ToolError | None = None
    metadata: dict[str, Any] = {}
