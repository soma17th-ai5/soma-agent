"""도메인 액션 디스패처 서비스. SPEC §6.1 ActionResult 처리.

사용자의 발화나 카드 UI를 통해 생성된 ActionProposal을 실제로 수행하고,
OpenSoma 상태 재검증, 캐시 무효화, 캘린더 초대(mock) 등 후속 처리를 담당한다.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from app.adapters.calendar_mock import CalendarMock
from app.adapters.opensoma_client import OpenSomaClient
from app.domain.contracts.action import ActionExecutionResponse
from app.errors.exceptions import ActionConflict, InvalidActionType, InvalidRequest
from app.observability.logging import get_logger
from app.services import application as application_service

log = get_logger("app.services.actions")

_OPEN_STATUSES = {"접수중", "open"}


class ActionHandler(ABC):
    @abstractmethod
    def execute(
        self,
        db: Session,
        opensoma: OpenSomaClient,
        session_id: str,
        soma_user_id: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        """액션 수행 후 Response에 포함될 payload 반환."""
        pass


class MentoringApplyHandler(ActionHandler):
    def execute(
        self,
        db: Session,
        opensoma: OpenSomaClient,
        session_id: str,
        soma_user_id: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        mentoring_id = payload.get("mentoringId") or payload.get("mentoring_id")
        if not mentoring_id:
            raise InvalidRequest("mentoringId is required for MENTORING_APPLY")

        # 1. 상태 재검증
        detail = opensoma.mentoring_get(session_id, mentoring_id)
        status = (detail.get("status") or "").lower()
        if status not in _OPEN_STATUSES:
            raise ActionConflict(
                f"멘토링 신청이 불가능한 상태입니다 (현재: {detail.get('status')!r})",
            )

        # 2. 신청 수행
        result = opensoma.mentoring_apply(session_id, mentoring_id)

        # 3. 캘린더 초대 (mock) — 실패해도 신청 결과는 유지
        try:
            # OpenSoma 응답에서 일시 추출 (PoC 실측 기반)
            # sessionDate: "2026-05-31", sessionTime: {"start": "20:00", "end": "22:00"}
            date_str = detail.get("sessionDate")
            time_obj = detail.get("sessionTime") or {}
            start_t = time_obj.get("start")
            end_t = time_obj.get("end")

            if date_str and start_t and end_t:
                start_dt = datetime.fromisoformat(f"{date_str}T{start_t}")
                end_dt = datetime.fromisoformat(f"{date_str}T{end_t}")

                cal = CalendarMock()
                cal_res = cal.create_invite(
                    title=f"[Soma] {detail.get('title')}",
                    start_at=start_dt,
                    end_at=end_dt,
                    location=detail.get("venue"),
                )
                result["calendarInvite"] = {
                    "status": cal_res.status,
                    "inviteId": cal_res.invite_id,
                    "error": cal_res.error,
                }
        except Exception as e:
            log.warning("action.calendar_invite_failed", error=str(e), mentoring_id=mentoring_id)

        # 4. 캐시 무효화
        application_service.invalidate(db, soma_user_id)

        return {
            "apply_sn": result.get("apply_sn"),
            "qustnr_sn": result.get("qustnr_sn"),
            "mentoring_id": mentoring_id,
            "calendarInvite": result.get("calendarInvite"),
        }


class MentoringCancelHandler(ActionHandler):
    def execute(
        self,
        db: Session,
        opensoma: OpenSomaClient,
        session_id: str,
        soma_user_id: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        apply_sn = payload.get("applySn") or payload.get("apply_sn")
        qustnr_sn = payload.get("qustnrSn") or payload.get("qustnr_sn")
        mentoring_id = payload.get("mentoringId") or payload.get("mentoring_id")

        # applySn 또는 qustnrSn 하나만 존재하면 INVALID_REQUEST (SPEC 충실)
        if (apply_sn is not None and qustnr_sn is None) or (apply_sn is None and qustnr_sn is not None):
            raise InvalidRequest("Both applySn and qustnrSn must be provided together")

        if not apply_sn or not qustnr_sn:
            if not mentoring_id:
                raise InvalidRequest("applySn/qustnrSn or mentoringId is required")

            # 매핑 시도
            apply_sn, qustnr_sn = self._map_mentoring_to_apply(
                db, opensoma, session_id, soma_user_id, mentoring_id
            )

        # 취소 수행
        opensoma.mentoring_cancel(session_id, apply_sn=apply_sn, qustnr_sn=qustnr_sn)

        # 캐시 무효화
        application_service.invalidate(db, soma_user_id)

        return {"apply_sn": apply_sn, "qustnr_sn": qustnr_sn}

    def _map_mentoring_to_apply(
        self,
        db: Session,
        opensoma: OpenSomaClient,
        session_id: str,
        soma_user_id: str,
        mentoring_id: int,
    ) -> tuple[int, int]:
        """mentoringId 를 기반으로 사용자의 신청 내역(applySn, qustnrSn)을 찾는다."""
        detail = opensoma.mentoring_get(session_id, mentoring_id)
        target_title = detail.get("title")
        if not target_title:
            raise ActionConflict("대상 멘토링의 제목을 확인할 수 없어 취소할 수 없습니다.")

        # 1. 캐시 우선 조회
        history = application_service.get_history(db, opensoma, session_id, soma_user_id, force_refresh=False)
        for item in history.items:
            if item.title == target_title:
                return item.apply_sn, item.qustnr_sn or mentoring_id

        # 2. 캐시 미스 시 강제 재조회
        history = application_service.get_history(db, opensoma, session_id, soma_user_id, force_refresh=True)
        for item in history.items:
            if item.title == target_title:
                return item.apply_sn, item.qustnr_sn or mentoring_id

        raise ActionConflict(
            f"신청 내역에서 해당 멘토링을 찾을 수 없습니다: {target_title!r}. 이미 취소되었거나 신청한 적이 없는 것 같습니다.",
        )


class ActionExecutionService:
    def __init__(self) -> None:
        self._handlers: dict[str, ActionHandler] = {
            "MENTORING_APPLY": MentoringApplyHandler(),
            "MENTORING_CANCEL": MentoringCancelHandler(),
        }

    def execute(
        self,
        db: Session,
        opensoma: OpenSomaClient,
        session_id: str,
        soma_user_id: str,
        action_type: str,
        payload: dict[str, Any],
        trace_id: str,
    ) -> ActionExecutionResponse:
        handler = self._handlers.get(action_type)
        if not handler:
            raise InvalidActionType(f"Unsupported action type: {action_type}")

        result_payload = handler.execute(db, opensoma, session_id, soma_user_id, payload)
        return ActionExecutionResponse(
            actionType=action_type,
            status="success",
            message="요청하신 액션을 성공적으로 완료했습니다.",
            payload=result_payload,
            traceId=trace_id,
        )


# 싱글톤 인스턴스
action_service = ActionExecutionService()
