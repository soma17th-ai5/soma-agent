"""router 노드 — function-calling plan 정규화 검증."""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from app.adapters.solar_chat_client import (
    ChatResponse,
    ChatToolCall,
    SolarChatError,
)
from app.agent.memory import ChatTurn
from app.agent.nodes.router import MAX_TOOLS_PER_TURN, route
from app.tools.builtin import build_default_registry


def _chat_client_with(response: ChatResponse) -> MagicMock:
    client = MagicMock()
    client.chat.return_value = response
    return client


@pytest.mark.asyncio
async def test_should_returnPlannedCalls_when_modelInvokesKnownTool() -> None:
    response = ChatResponse(
        content=None,
        tool_calls=[
            ChatToolCall(
                id="c1",
                name="knowledge.search",
                arguments={"query": "백엔드 멘토링", "source_types": ["MENTORING"]},
            )
        ],
        finish_reason="tool_calls",
    )
    decision = await route(
        user_message="백엔드 멘토링 찾아줘",
        memory_turns=[],
        candidates_context=None,
        registry=build_default_registry(),
        chat_client=_chat_client_with(response),
    )

    assert len(decision.calls) == 1
    assert decision.calls[0].tool_name == "knowledge.search"
    assert decision.calls[0].params["source_types"] == ["MENTORING"]


@pytest.mark.asyncio
async def test_should_dropUnknownTool_when_modelHallucinates() -> None:
    response = ChatResponse(
        content=None,
        tool_calls=[
            ChatToolCall(id="c1", name="bogus.tool", arguments={}),
            ChatToolCall(id="c2", name="opensoma.notice.get", arguments={"notice_id": 1}),
        ],
        finish_reason="tool_calls",
    )
    decision = await route(
        user_message="공지 1번",
        memory_turns=[],
        candidates_context=None,
        registry=build_default_registry(),
        chat_client=_chat_client_with(response),
    )

    assert [c.tool_name for c in decision.calls] == ["opensoma.notice.get"]


@pytest.mark.asyncio
async def test_should_truncateToTwo_when_modelProposesThreeOrMore() -> None:
    response = ChatResponse(
        content=None,
        tool_calls=[
            ChatToolCall(id="c1", name="knowledge.search", arguments={"query": "x"}),
            ChatToolCall(id="c2", name="opensoma.mentoring.list", arguments={}),
            ChatToolCall(id="c3", name="opensoma.notice.get", arguments={"notice_id": 1}),
        ],
        finish_reason="tool_calls",
    )
    decision = await route(
        user_message="multi",
        memory_turns=[],
        candidates_context=None,
        registry=build_default_registry(),
        chat_client=_chat_client_with(response),
    )

    assert len(decision.calls) == MAX_TOOLS_PER_TURN


@pytest.mark.asyncio
async def test_should_passDirectAnswer_when_noToolCalls() -> None:
    response = ChatResponse(content="안녕하세요", tool_calls=[], finish_reason="stop")
    decision = await route(
        user_message="안녕",
        memory_turns=[],
        candidates_context=None,
        registry=build_default_registry(),
        chat_client=_chat_client_with(response),
    )

    assert decision.calls == []
    assert decision.direct_answer == "안녕하세요"


@pytest.mark.asyncio
async def test_should_returnError_when_llmFails() -> None:
    client = MagicMock()
    client.chat.side_effect = SolarChatError(503, "down")

    decision = await route(
        user_message="뭐해",
        memory_turns=[],
        candidates_context=None,
        registry=build_default_registry(),
        chat_client=client,
    )

    assert decision.error is not None
    assert decision.calls == []


@pytest.mark.asyncio
async def test_should_includeMemoryAndCandidates_in_chatMessages() -> None:
    captured: dict[str, object] = {}

    def _capture(messages, **kwargs):  # type: ignore[no-untyped-def]
        captured["messages"] = messages
        return ChatResponse(content="ok", tool_calls=[], finish_reason="stop")

    client = MagicMock()
    client.chat.side_effect = _capture

    await route(
        user_message="그거 신청해줘",
        memory_turns=[ChatTurn(user_message="멘토링 추천", assistant_message="3개 있어요")],
        candidates_context=[{"id": 1, "title": "Backend"}],
        registry=build_default_registry(),
        chat_client=client,
    )

    msgs = captured["messages"]
    assert isinstance(msgs, list)
    roles = [m["role"] for m in msgs]
    # system(prompt) → user(prev) → assistant(prev) → system(candidates) → user(current)
    assert roles[0] == "system"
    assert "후보" in str(msgs[-2]["content"])
    assert msgs[-1]["role"] == "user"
    assert msgs[-1]["content"] == "그거 신청해줘"
    # 직전 턴이 메시지에 포함되었는지
    assert any(m["role"] == "user" and m["content"] == "멘토링 추천" for m in msgs)
