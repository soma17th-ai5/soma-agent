"""calendar.invite.create tool — mock 캘린더. SPEC §4.2.

SPEC §6.4 부분 실패 정책: 멘토링 신청 성공 + 캘린더 실패는 신청을 롤백하지 않고
ChatMessage `data.calendarInvite.status="failed"`로 표기한다. 본 tool 자체는
ToolResult.status를 캘린더 결과에 그대로 매핑한다 (executor가 partial로 합성).
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from app.domain.contracts.tool_result import Artifact, ToolResult
from app.tools._helpers import failed_result, require_param
from app.tools.base import Tool, ToolContext


def _parse_iso(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


class CalendarInviteCreateTool(Tool):
    name = "calendar.invite.create"
    domain = "calendar"
    operation = "create"
    requires_auth = False

    async def run(self, params: dict[str, Any], ctx: ToolContext) -> ToolResult:
        if ctx.calendar is None:
            return failed_result(
                tool=self.name,
                domain=self.domain,
                operation=self.operation,
                code="MISSING_DEPS",
                message="calendar mock not provided",
            )

        title, err = require_param(params, "title")
        if err:
            return failed_result(
                tool=self.name,
                domain=self.domain,
                operation=self.operation,
                code="INVALID_PARAM",
                message=err,
            )

        start_at = _parse_iso(params.get("start_at"))
        end_at = _parse_iso(params.get("end_at"))
        if start_at is None or end_at is None:
            return failed_result(
                tool=self.name,
                domain=self.domain,
                operation=self.operation,
                code="INVALID_PARAM",
                message="start_at/end_at must be ISO 8601 datetime",
            )

        result = ctx.calendar.create_invite(
            title=title,
            start_at=start_at,
            end_at=end_at,
            description=params.get("description"),
            location=params.get("location"),
        )

        payload = {
            "status": result.status,
            "invite_id": result.invite_id,
            "title": result.title,
            "start_at": result.start_at.isoformat(),
            "end_at": result.end_at.isoformat(),
            "description": result.description,
            "location": result.location,
            "error": result.error,
        }
        return ToolResult(
            tool=self.name,
            domain=self.domain,
            operation=self.operation,
            status="success" if result.status == "success" else "failed",
            data=payload,
            artifacts=[Artifact(type="card", title=f"캘린더 초대: {title}", content=result.error)],
        )
