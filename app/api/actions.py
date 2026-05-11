"""도메인 액션 실행 엔드포인트. SPEC §6.1 ActionResult 처리.

채팅/카드 UI를 통해 수신된 ActionExecutionRequest를 해당 핸들러로 라우팅한다.
"""
from __future__ import annotations

from fastapi import APIRouter, Request
from pydantic import Field

from app.api.deps import DbSession, SessionId, SomaClient
from app.domain.contracts.action import ActionExecutionRequest, ActionExecutionResponse
from app.observability.logging import get_logger
from app.services.actions import action_service

router = APIRouter(prefix="/api/v1/actions", tags=["actions"])
log = get_logger("app.api.actions")


@router.post("/execute", response_model=ActionExecutionResponse)
def execute_action(
    request: Request,
    body: ActionExecutionRequest,
    session_id: SessionId,
    db: DbSession,
    client: SomaClient,
) -> ActionExecutionResponse:
    """ActionProposal/카드 액션을 실제로 수행한다."""
    trace_id = getattr(request.state, "trace_id", "unknown")
    
    log.info(
        "action.execute_requested",
        action_type=body.action_type,
        user_id=body.soma_user_id,
        trace_id=trace_id,
    )
    
    return action_service.execute(
        db,
        client,
        session_id,
        body.soma_user_id,
        body.action_type,
        body.payload,
        trace_id,
    )
