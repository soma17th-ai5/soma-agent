"""router 노드. SPEC §5.2.

사용자 메시지 + 후보 컨텍스트 + 최근 N턴(기본 5)을 LLM에 보내 함수 호출 형식의
tool_plan(≤2)을 받는다. 본 노드는 *결정*만 한다 — 실제 tool 실행은 tool_executor.
"""
from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from typing import Any

from app.adapters.solar_chat_client import SolarChatClient, SolarChatError
from app.agent.memory import ChatTurn
from app.agent.prompts import ROUTER_SYSTEM_PROMPT
from app.agent.tool_catalog import build_function_specs
from app.tools.registry import ToolRegistry

log = logging.getLogger("app.agent.router")

DEFAULT_RECENT_TURNS = 5
MAX_TOOLS_PER_TURN = 2


@dataclass(frozen=True)
class PlannedToolCall:
    tool_name: str
    params: dict[str, Any]


@dataclass(frozen=True)
class RouterDecision:
    """router 결과.

    - calls: 실행할 tool 계획 (executor가 추가로 ≤2 강제).
    - direct_answer: tool 호출 없이 모델이 바로 답변한 경우의 텍스트.
    - error: LLM 호출 자체가 실패한 경우의 메시지 (synthesizer가 사용자 안내로 변환).
    """

    calls: list[PlannedToolCall] = field(default_factory=list)
    direct_answer: str | None = None
    error: str | None = None


def _build_messages(
    user_message: str,
    memory_turns: list[ChatTurn],
    candidates_context: list[dict[str, Any]] | None,
    recent_turns: int,
) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": ROUTER_SYSTEM_PROMPT},
    ]
    for turn in memory_turns[-recent_turns:]:
        messages.append({"role": "user", "content": turn.user_message})
        messages.append({"role": "assistant", "content": turn.assistant_message})
    if candidates_context:
        # 직전 응답에서 노출된 후보 목록 — 라우터가 "1번", "그거" 같은 지시어를 해석할 때 사용.
        messages.append(
            {
                "role": "system",
                "content": (
                    "직전 응답에서 사용자에게 보여준 후보 목록 (참조용):\n"
                    + json.dumps(candidates_context, ensure_ascii=False)
                ),
            }
        )
    messages.append({"role": "user", "content": user_message})
    return messages


async def route(
    *,
    user_message: str,
    memory_turns: list[ChatTurn],
    candidates_context: list[dict[str, Any]] | None,
    registry: ToolRegistry,
    chat_client: SolarChatClient,
    recent_turns: int = DEFAULT_RECENT_TURNS,
) -> RouterDecision:
    """LLM에 plan을 요청한다. 실패는 RouterDecision(error=...)로 흡수."""
    messages = _build_messages(user_message, memory_turns, candidates_context, recent_turns)
    tools_spec = build_function_specs(registry)
    tool_choice: str | None = "auto" if tools_spec else None

    try:
        # SolarChatClient.chat은 sync httpx → 별도 스레드로 비동기 실행.
        response = await asyncio.to_thread(
            chat_client.chat, messages, tools=tools_spec, tool_choice=tool_choice
        )
    except SolarChatError as e:
        log.warning("router.llm_failed status=%s message=%s", e.status, e.message)
        return RouterDecision(error=f"LLM 호출 실패: {e.message}")

    calls: list[PlannedToolCall] = []
    for tc in response.tool_calls:
        if tc.name not in registry:
            # 카탈로그에 없는 tool 이름은 환각 — 무시.
            log.info("router.unknown_tool name=%s", tc.name)
            continue
        calls.append(PlannedToolCall(tool_name=tc.name, params=tc.arguments))

    # SPEC §5.2 — 최대 2개. 라우터에서 1차 절단 (executor에서 partial 표시 책임).
    truncated = calls[:MAX_TOOLS_PER_TURN]

    return RouterDecision(
        calls=truncated,
        direct_answer=response.content,
    )
