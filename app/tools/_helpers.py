"""Tool 구현 공용 헬퍼.

- _failed_result: 실패 응답을 일관 형태로 만든다 (예외/누락 deps).
- _require_*: 필수 의존성·필수 파라미터 검증. 실패 시 ToolResult(failed) 반환.
"""
from __future__ import annotations

from typing import Any

from app.domain.contracts.tool_result import (
    DomainType,
    ToolError,
    ToolResult,
)


def failed_result(
    *,
    tool: str,
    domain: DomainType,
    operation: str,
    code: str,
    message: str,
    recoverable: bool = False,
) -> ToolResult:
    return ToolResult(
        tool=tool,
        domain=domain,
        operation=operation,
        status="failed",
        error=ToolError(code=code, message=message, recoverable=recoverable),
    )


def require_param(params: dict[str, Any], key: str) -> tuple[Any, str | None]:
    """필수 파라미터 추출. 부재/None이면 에러 메시지 반환."""
    value = params.get(key)
    if value is None or (isinstance(value, str) and not value.strip()):
        return None, f"missing required param: {key}"
    return value, None
