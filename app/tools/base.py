"""Tool 추상 + ToolContext. SPEC §4.

각 tool은 `Tool` 추상 클래스를 상속하며 클래스 변수로 메타데이터를 선언하고
`run()`만 구현한다. router가 LLM에 노출하는 카탈로그는 메타데이터로 자동 생성된다.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, ClassVar

from app.domain.contracts.tool_result import DomainType, ToolResult


@dataclass
class ToolContext:
    """Tool 실행 시 함께 전달되는 호출자 컨텍스트.

    - session_id: 채팅 세션 ID (대화 메모리 키). `/chat`에서 X-Session-Id 헤더로 받음.
    - soma_session: OpenSoma 세션 토큰. `requires_auth=True` tool은 이 값이 없으면
      실행 전에 router/executor에서 차단해야 한다.
    - soma_user_id: 인증된 사용자 식별자. application/mentoring tool에서 캐시 키로 사용.
    """

    session_id: str | None = None
    soma_session: str | None = None
    soma_user_id: str | None = None


class Tool(ABC):
    """Agent에 노출되는 단위 호출.

    Subclass 규칙:
    - 클래스 변수 `name`, `domain`, `operation`, `requires_auth`를 선언한다.
    - 인스턴스 메서드 `run(params, ctx)`만 구현한다.
    - 인스턴스 단위로 `ToolRegistry`에 등록한다 (싱글턴).
    """

    name: ClassVar[str]
    domain: ClassVar[DomainType]
    operation: ClassVar[str]
    requires_auth: ClassVar[bool]

    @abstractmethod
    async def run(self, params: dict[str, Any], ctx: ToolContext) -> ToolResult:
        """Tool 본체 호출. 실패는 예외 대신 `ToolResult{status:"failed"}`로 흡수."""
