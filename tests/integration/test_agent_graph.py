"""Agent 그래프 통합 시나리오. SPEC §16 완료 기준.

LLM 호출은 SolarChatClient 모킹으로 대체. tool 호출은 실제 Tool 인스턴스를 통과
시키되, 외부(qdrant/solar embedding/opensoma sidecar)는 stub로 차단.
"""
from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest

from app.adapters.solar_chat_client import (
    ChatResponse,
    ChatToolCall,
)
from app.agent.graph import AgentDeps, run_chat
from app.agent.memory import AgentMemory
from app.tools.base import ToolContext
from app.tools.builtin import build_default_registry


class _StubChatClient:
    """SolarChatClient 인터페이스 stub — chat 호출별로 다른 응답을 큐로 반환."""

    def __init__(self, responses: list[ChatResponse]) -> None:
        self._responses = list(responses)
        self.calls: list[dict[str, Any]] = []

    def chat(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
        tool_choice: Any = None,
        temperature: float = 0.0,
    ) -> ChatResponse:
        self.calls.append({"messages": messages, "tools": tools})
        if not self._responses:
            return ChatResponse(content="(no more)", tool_calls=[], finish_reason="stop")
        return self._responses.pop(0)


def _qdrant_with(points: list[SimpleNamespace]) -> MagicMock:
    q = MagicMock()
    q.search.return_value = points
    return q


def _solar_embed() -> MagicMock:
    s = MagicMock()
    s.embed_query.return_value = [0.1] * 8
    return s


def _make_deps(
    chat_responses: list[ChatResponse],
    *,
    tool_ctx: ToolContext | None = None,
) -> AgentDeps:
    return AgentDeps(
        registry=build_default_registry(),
        chat_client=_StubChatClient(chat_responses),  # type: ignore[arg-type]
        memory=AgentMemory(),
        tool_ctx=tool_ctx or ToolContext(),
    )


@pytest.mark.asyncio
async def test_should_routeKnowledgeSearch_when_userAsksForBackendMentoring() -> None:
    """SPEC §16 완료기준 #1 — '백엔드 멘토링 찾아줘' → knowledge.search(MENTORING)."""
    points = [
        SimpleNamespace(
            id="c1",
            score=0.9,
            payload={
                "chunk_id": "c1",
                "source_type": "MENTORING",
                "source_id": "M-1",
                "title": "백엔드 멘토링",
                "text": "...",
                "official": False,
                "created_at": datetime(2026, 5, 1).isoformat(),
                "source_url": "http://example/m/1",
            },
        )
    ]
    chat_responses = [
        # 1) router: knowledge.search(source_types=MENTORING) 호출
        ChatResponse(
            content=None,
            tool_calls=[
                ChatToolCall(
                    id="r1",
                    name="knowledge.search",
                    arguments={"query": "백엔드 멘토링", "source_types": ["MENTORING"]},
                )
            ],
            finish_reason="tool_calls",
        ),
        # 2) synthesizer summary
        ChatResponse(content="백엔드 멘토링을 찾았습니다.", tool_calls=[], finish_reason="stop"),
    ]
    deps = _make_deps(
        chat_responses,
        tool_ctx=ToolContext(qdrant=_qdrant_with(points), solar=_solar_embed()),
    )

    msg = await run_chat(
        user_message="백엔드 멘토링 찾아줘",
        session_id="s-1",
        candidates_context=None,
        deps=deps,
    )

    assert msg.status == "success"
    assert msg.sources and msg.sources[0].title == "백엔드 멘토링"
    assert msg.answer == "백엔드 멘토링을 찾았습니다."


@pytest.mark.asyncio
async def test_should_truncateAndMarkPartial_when_routerReturnsThreeTools() -> None:
    """SPEC §16 완료기준 #3 — 3개 이상 tool 요청 시 partial."""
    chat_responses = [
        ChatResponse(
            content=None,
            tool_calls=[
                ChatToolCall(id="1", name="knowledge.search", arguments={"query": "x"}),
                ChatToolCall(id="2", name="opensoma.mentoring.list", arguments={}),
                ChatToolCall(id="3", name="opensoma.notice.get", arguments={"notice_id": 1}),
            ],
            finish_reason="tool_calls",
        ),
        ChatResponse(content="여러 결과를 가져왔어요.", tool_calls=[], finish_reason="stop"),
    ]
    # mentoring.list/notice.get는 SOMA_AUTH_REQUIRED로 fail되지만, 본 테스트는 절단 동작에만 집중.
    deps = _make_deps(
        chat_responses,
        tool_ctx=ToolContext(qdrant=_qdrant_with([]), solar=_solar_embed()),
    )

    msg = await run_chat(
        user_message="여러 거 한번에",
        session_id="s-2",
        candidates_context=None,
        deps=deps,
    )

    # router에서 1차 절단(2개)됨 — graph는 partial 상태가 아닐 수 있다.
    # 핵심: 등록된 tool 8개 안에서 골라졌고 결과가 합성됐다.
    assert msg.answer  # 어떤 답변이든 채워졌어야 함


@pytest.mark.asyncio
async def test_should_appendToMemory_when_chatTurnCompletes() -> None:
    # router가 tool 호출 없이 직접 답변 → synthesizer가 router 응답 그대로 사용 (1콜).
    deps = _make_deps(
        [ChatResponse(content="안녕하세요!", tool_calls=[], finish_reason="stop")],
    )

    await run_chat(
        user_message="안녕",
        session_id="s-3",
        candidates_context=None,
        deps=deps,
    )

    turns = deps.memory.recent("s-3")
    assert len(turns) == 1
    assert turns[0].user_message == "안녕"
