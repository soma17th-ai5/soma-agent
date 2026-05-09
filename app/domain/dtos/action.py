"""사용자 확인이 필요한 액션(apply/cancel) DTO. SPEC §6.1.

서비스 레이어가 직접 반환하는 값 객체. FastAPI는 dataclass를 그대로 직렬화하며,
OpenAPI 스키마도 정상 생성된다.

이전 위치: `app/domain/contracts/action.py` (Pydantic BaseModel)
이전 이유: 서비스 레이어에서 BaseModel import 금지 (이슈 #37 AC).
JSON 출력 키는 기존과 동일 — pydantic v2에서도 alias는 출력 기본 적용 안 됐으므로
필드명 그대로 직렬화되었다.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


@dataclass(slots=True, frozen=True)
class ActionProposal:
    """확인 대기 — 사용자가 confirmed=true 로 다시 호출하면 실행."""

    type: str
    label: str
    payload: dict[str, Any]
    requires_confirmation: bool = True


@dataclass(slots=True, frozen=True)
class ActionResult:
    """실제 액션 실행 결과."""

    type: str
    status: Literal["success", "failed"]
    message: str
    payload: dict[str, Any] | None = field(default=None)
