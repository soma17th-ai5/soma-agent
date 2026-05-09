"""ToolRegistry 등록·조회·중복 방어 검증."""
from __future__ import annotations

from typing import Any

import pytest

from app.domain.contracts.tool_result import ToolResult
from app.tools.base import Tool, ToolContext
from app.tools.registry import ToolRegistry


class _FakeTool(Tool):
    name = "fake.test"
    domain = "system"
    operation = "test"
    requires_auth = False

    async def run(self, params: dict[str, Any], ctx: ToolContext) -> ToolResult:
        return ToolResult(
            tool=self.name,
            domain=self.domain,
            operation=self.operation,
            status="success",
            data=params,
        )


class _OtherFake(Tool):
    name = "fake.other"
    domain = "system"
    operation = "other"
    requires_auth = False

    async def run(self, params: dict[str, Any], ctx: ToolContext) -> ToolResult:
        return ToolResult(
            tool=self.name,
            domain=self.domain,
            operation=self.operation,
            status="success",
        )


def test_should_returnRegisteredTool_when_lookupByName() -> None:
    reg = ToolRegistry()
    tool = _FakeTool()

    reg.register(tool)

    assert reg.get("fake.test") is tool
    assert "fake.test" in reg


def test_should_returnNone_when_unknownName() -> None:
    reg = ToolRegistry()
    assert reg.get("missing") is None
    assert "missing" not in reg


def test_should_listAll_when_multipleRegistered() -> None:
    reg = ToolRegistry()
    reg.register(_FakeTool())
    reg.register(_OtherFake())

    assert len(reg) == 2
    assert {t.name for t in reg.all()} == {"fake.test", "fake.other"}


def test_should_raise_when_duplicateRegistration() -> None:
    reg = ToolRegistry()
    reg.register(_FakeTool())

    with pytest.raises(ValueError, match="already registered"):
        reg.register(_FakeTool())


@pytest.mark.asyncio
async def test_should_executeRunMethod_when_invokedDirectly() -> None:
    tool = _FakeTool()

    result = await tool.run({"q": "x"}, ToolContext(session_id="s-1"))

    assert result.status == "success"
    assert result.tool == "fake.test"
    assert result.data == {"q": "x"}
