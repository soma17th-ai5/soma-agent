"""tool_executor 노드. SPEC §5.3.

router의 plan을 받아 순차 실행. 핵심 책임:
1. plan 길이 > 2면 잘라내고 partial ToolResult로 안내.
2. 각 tool 실패는 ToolResult{status:"failed"}로 흡수, 그래프는 끝까지 진행.
3. 등록되지 않은 tool 이름은 failed로 즉시 응답 (router가 1차 검증, 본 노드가 2차).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from app.agent.nodes.router import MAX_TOOLS_PER_TURN, PlannedToolCall
from app.domain.contracts.tool_result import Artifact, ToolError, ToolResult
from app.tools.base import ToolContext
from app.tools.registry import ToolRegistry

log = logging.getLogger("app.agent.tool_executor")


@dataclass(frozen=True)
class ExecutionOutcome:
    results: list[ToolResult]
    truncated: bool  # plan이 MAX 초과로 잘렸는지


def _partial_truncation_notice(dropped: int) -> ToolResult:
    return ToolResult(
        tool="system.partial",
        domain="system",
        operation="truncate",
        status="partial",
        artifacts=[
            Artifact(
                type="markdown",
                content=(
                    f"한 번에 처리 가능한 호출 수(2개)를 초과해 {dropped}건을 생략했습니다. "
                    "필요하면 나누어 다시 요청해주세요."
                ),
            )
        ],
    )


def _unknown_tool_result(name: str) -> ToolResult:
    return ToolResult(
        tool=name,
        domain="system",
        operation="unknown",
        status="failed",
        error=ToolError(
            code="UNKNOWN_TOOL",
            message=f"tool not registered: {name}",
            recoverable=False,
        ),
    )


async def execute(
    *,
    plan: list[PlannedToolCall],
    registry: ToolRegistry,
    ctx: ToolContext,
) -> ExecutionOutcome:
    truncated = False
    dropped_count = 0
    if len(plan) > MAX_TOOLS_PER_TURN:
        dropped_count = len(plan) - MAX_TOOLS_PER_TURN
        plan = plan[:MAX_TOOLS_PER_TURN]
        truncated = True
        log.info("tool_executor.truncated dropped=%s", dropped_count)

    results: list[ToolResult] = []
    for call in plan:
        tool = registry.get(call.tool_name)
        if tool is None:
            results.append(_unknown_tool_result(call.tool_name))
            continue
        try:
            result = await tool.run(call.params, ctx)
        except Exception as e:  # 어떤 tool도 그래프를 죽이지 않는다.
            log.exception("tool_executor.tool_raised name=%s", call.tool_name)
            results.append(
                ToolResult(
                    tool=tool.name,
                    domain=tool.domain,
                    operation=tool.operation,
                    status="failed",
                    error=ToolError(
                        code="TOOL_RAISED",
                        message=str(e),
                        recoverable=False,
                    ),
                )
            )
            continue
        results.append(result)

    if truncated:
        # 절단 안내는 사용자 답변에 partial 표시로 합성된다 (synthesizer가 처리).
        results.append(_partial_truncation_notice(dropped=dropped_count))

    return ExecutionOutcome(results=results, truncated=truncated)
