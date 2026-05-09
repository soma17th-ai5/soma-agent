"""멘토링 액션 Request 스키마. Response는 schemas/action.py 의 ActionProposal/ActionResult 공용."""
from __future__ import annotations

from pydantic import BaseModel, Field


class ApplyReq(BaseModel):
    confirmed: bool = Field(default=False)
    soma_user_id: str = Field(min_length=1)


class CancelReq(BaseModel):
    apply_sn: int = Field(gt=0)
    qustnr_sn: int = Field(gt=0)
    confirmed: bool = Field(default=False)
    soma_user_id: str = Field(min_length=1)
