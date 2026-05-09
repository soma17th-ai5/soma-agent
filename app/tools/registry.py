"""Tool 등록·조회 레지스트리. router가 카탈로그를 만들 때, executor가 호출할 때 사용."""
from __future__ import annotations

from app.tools.base import Tool


class ToolRegistry:
    """이름→Tool 인스턴스 매핑.

    중복 등록은 즉시 에러로 발생시켜 이름 충돌을 조기 발견한다 (SPEC §4 — tool 이름은
    `domain.operation` 규약상 유일해야 함).
    """

    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        if tool.name in self._tools:
            raise ValueError(f"tool already registered: {tool.name}")
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def all(self) -> list[Tool]:
        return list(self._tools.values())

    def __contains__(self, name: str) -> bool:
        return name in self._tools

    def __len__(self) -> int:
        return len(self._tools)
