"""ChatMessage — 프론트 응답 형식. SPEC §6.2."""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel

from app.domain.contracts.action import ActionProposal
from app.domain.contracts.source import Source
from app.domain.contracts.tool_result import ToolStatus


class ChatUIBlock(BaseModel):
    type: Literal[
        "source_list",
        "mentoring_cards",
        "notice_list",
        "webex_summary",
        "action_result",
    ]
    title: str | None = None
    items: list[Any] | None = None


class ChatMessage(BaseModel):
    answer: str
    status: ToolStatus
    sources: list[Source] = []
    ui: list[ChatUIBlock] = []
    # SPEC §6.2: actions는 ActionProposal[]만 노출한다. ActionResult는 /actions/execute 응답.
    actions: list[ActionProposal] = []
    trace_id: str
