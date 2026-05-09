"""tool_executor — 절단·실패 흡수·미등록 tool 검증."""
from __future__ import annotations

from typing import Any

import pytest

from app.agent.nodes.router import PlannedToolCall
from app.agent.nodes.tool_executor import execute
from app.domain.contracts.tool_result import ToolResult
from app.tools.base import Tool, ToolContext
from app.tools.registry import ToolRegistry


class _OkTool(Tool):
    name = "test.ok"
    domain = "system"
    operation = "ok"
    requires_auth = False

    async def run(self, params: dict[str, Any], ctx: ToolContext) -> ToolResult:
        return ToolResult(
            tool=self.name, domain="system", operation="ok", status="success", data=params
        )


class _RaiseTool(Tool):
    name = "test.raise"
    domain = "system"
    operation = "raise"
    requires_auth = False

    async def run(self, params: dict[str, Any], ctx: ToolContext) -> ToolResult:
        raise RuntimeError("boom")


def _registry() -> ToolRegistry:
    reg = ToolRegistry()
    reg.register(_OkTool())
    reg.register(_RaiseTool())
    return reg


@pytest.mark.asyncio
async def test_should_runEachTool_when_planFitsLimit() -> None:
    plan = [
        PlannedToolCall(tool_name="test.ok", params={"a": 1}),
        PlannedToolCall(tool_name="test.ok", params={"a": 2}),
    ]
    out = await execute(plan=plan, registry=_registry(), ctx=ToolContext())

    assert len(out.results) == 2
    assert out.truncated is False
    assert all(r.status == "success" for r in out.results)


@pytest.mark.asyncio
async def test_should_truncateAndAppendNotice_when_planExceedsTwo() -> None:
    plan = [
        PlannedToolCall(tool_name="test.ok", params={}),
        PlannedToolCall(tool_name="test.ok", params={}),
        PlannedToolCall(tool_name="test.ok", params={}),
    ]
    out = await execute(plan=plan, registry=_registry(), ctx=ToolContext())

    assert out.truncated is True
    # 2개 실행 + 1개 partial 안내 = 3개
    assert len(out.results) == 3
    statuses = [r.status for r in out.results]
    assert statuses.count("success") == 2
    assert statuses[-1] == "partial"


@pytest.mark.asyncio
async def test_should_absorbException_when_toolRaises() -> None:
    plan = [PlannedToolCall(tool_name="test.raise", params={})]
    out = await execute(plan=plan, registry=_registry(), ctx=ToolContext())

    assert out.results[0].status == "failed"
    assert out.results[0].error is not None
    assert out.results[0].error.code == "TOOL_RAISED"


@pytest.mark.asyncio
async def test_should_returnUnknownTool_when_notRegistered() -> None:
    plan = [PlannedToolCall(tool_name="missing.tool", params={})]
    out = await execute(plan=plan, registry=_registry(), ctx=ToolContext())

    assert out.results[0].status == "failed"
    assert out.results[0].error is not None
    assert out.results[0].error.code == "UNKNOWN_TOOL"
