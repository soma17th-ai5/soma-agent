"""사용자 확인이 필요한 액션 (apply/cancel)에 대한 contract.

SPEC §6.1 ActionProposal/ActionResult 정의 그대로. 1차 호출 시 ActionProposal,
2차 호출(confirmed=true) 시 ActionResult 반환.
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class ActionProposal(BaseModel):
    """확인 대기 — 사용자가 confirmed=true 로 다시 호출하면 실행."""

    type: str
    label: str
    payload: dict[str, Any]
    requires_confirmation: bool = Field(default=True, alias="requiresConfirmation")

    model_config = {"populate_by_name": True}


class ActionResult(BaseModel):
    """실제 액션 실행 결과."""

    type: str
    status: Literal["success", "failed"]
    message: str
    payload: dict[str, Any] | None = None
