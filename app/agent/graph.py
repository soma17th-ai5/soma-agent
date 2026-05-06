"""Agent StateGraph. SPEC §5.

router → tool_executor → synthesizer 직선 그래프. LangGraph StateGraph는 노드 간
TypedDict state를 자동 머지한다. 본 그래프는 분기가 없으므로 LangGraph의 라우팅
기능을 적극 사용하지 않지만, 향후 retry/clarify 노드 추가를 위한 구조 보존.
"""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph

from app.adapters.solar_chat_client import SolarChatClient
from app.agent.memory import AgentMemory, ChatTurn
from app.agent.nodes.router import RouterDecision, route
from app.agent.nodes.synthesizer import SynthesisInput, synthesize
from app.agent.nodes.tool_executor import ExecutionOutcome, execute
from app.domain.contracts.chat import ChatMessage
from app.domain.contracts.tool_result import ToolResult
from app.tools.base import ToolContext
from app.tools.registry import ToolRegistry

log = logging.getLogger("app.agent.graph")


class GraphState(TypedDict, total=False):
    user_message: str
    candidates_context: list[dict[str, Any]] | None
    decision: RouterDecision
    results: list[ToolResult]
    truncated: bool
    final: ChatMessage


@dataclass
class AgentDeps:
    """그래프 노드들이 의존하는 클라이언트 묶음. 매 요청마다 새로 만든다."""

    registry: ToolRegistry
    chat_client: SolarChatClient
    memory: AgentMemory
    tool_ctx: ToolContext


async def run_chat(
    *,
    user_message: str,
    session_id: str,
    candidates_context: list[dict[str, Any]] | None,
    deps: AgentDeps,
) -> ChatMessage:
    """단일 채팅 턴 실행 — 메모리 갱신 포함.

    LangGraph StateGraph 인스턴스를 매번 빌드하지 않고 노드 함수를 직접 호출. 그래프
    형태가 단순한 직선이라 오버헤드를 줄이고, 통합 테스트에서 노드별 단위 호출을
    그대로 재사용할 수 있다. (분기/clarify 추가 시 build_graph()로 전환.)
    """
    trace_id = uuid.uuid4().hex
    memory_turns = deps.memory.recent(session_id)

    decision = await route(
        user_message=user_message,
        memory_turns=memory_turns,
        candidates_context=candidates_context,
        registry=deps.registry,
        chat_client=deps.chat_client,
    )

    if decision.error:
        log.warning("graph.router_error trace=%s msg=%s", trace_id, decision.error)
        # router 실패 → 빈 결과로 합성 (synthesizer가 일시적 장애 메시지 생성).
        outcome = ExecutionOutcome(results=[], truncated=False)
    elif not decision.calls:
        # 직접 답변 의도 — tool 호출 없이 진행.
        outcome = ExecutionOutcome(results=[], truncated=False)
    else:
        outcome = await execute(
            plan=decision.calls,
            registry=deps.registry,
            ctx=deps.tool_ctx,
        )

    final = await synthesize(
        SynthesisInput(
            user_message=user_message,
            results=outcome.results,
            direct_answer_from_router=decision.direct_answer,
            truncated=outcome.truncated,
            trace_id=trace_id,
        ),
        chat_client=deps.chat_client,
    )

    deps.memory.append(
        session_id, ChatTurn(user_message=user_message, assistant_message=final.answer)
    )
    return final


def build_graph() -> StateGraph:
    """LangGraph StateGraph 빌더 — 향후 분기/retry 노드 추가용 자리."""
    g = StateGraph(GraphState)
    # 노드는 run_chat이 직접 호출 — 본 빌더는 그래프 토폴로지 보존만 한다.
    g.add_node("router", lambda s: s)
    g.add_node("executor", lambda s: s)
    g.add_node("synthesizer", lambda s: s)
    g.add_edge(START, "router")
    g.add_edge("router", "executor")
    g.add_edge("executor", "synthesizer")
    g.add_edge("synthesizer", END)
    return g.compile()
