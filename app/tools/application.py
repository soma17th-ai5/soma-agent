"""opensoma.application.history tool. SPEC §4.2 — TTL 5분 캐시."""
from __future__ import annotations

from typing import Any

from app.adapters.opensoma_client import OpenSomaClientError
from app.domain.contracts.tool_result import Artifact, ToolResult
from app.services import application as application_service
from app.tools._helpers import failed_result
from app.tools.base import Tool, ToolContext


class ApplicationHistoryTool(Tool):
    """현재 사용자의 멘토링 신청/취소 내역. force_refresh 미지정 시 캐시 우선."""

    name = "opensoma.application.history"
    domain = "opensoma"
    operation = "history"
    requires_auth = True

    async def run(self, params: dict[str, Any], ctx: ToolContext) -> ToolResult:
        if not ctx.soma_session or ctx.opensoma is None or ctx.db is None:
            return failed_result(
                tool=self.name,
                domain=self.domain,
                operation=self.operation,
                code="SOMA_AUTH_REQUIRED",
                message="X-Soma-Session and db required",
            )
        if not ctx.soma_user_id:
            return failed_result(
                tool=self.name,
                domain=self.domain,
                operation=self.operation,
                code="MISSING_USER_ID",
                message="soma_user_id required as cache key",
            )

        force_refresh = bool(params.get("force_refresh", False))

        try:
            result = application_service.get_history(
                ctx.db,
                ctx.opensoma,
                ctx.soma_session,
                ctx.soma_user_id,
                force_refresh=force_refresh,
            )
        except OpenSomaClientError as e:
            return failed_result(
                tool=self.name,
                domain=self.domain,
                operation=self.operation,
                code=e.code or "OPENSOMA_ERROR",
                message=e.message,
                recoverable=e.status >= 500,
            )

        items = [
            {
                "apply_sn": r.apply_sn,
                "qustnr_sn": r.qustnr_sn,
                "category": r.category,
                "title": r.title,
                "url": r.target_url,
                "session_date": r.session_date_text,
                "applied_at": r.applied_at_text,
                "application_status": r.application_status,
                "approval_status": r.approval_status,
            }
            for r in result.items
        ]
        return ToolResult(
            tool=self.name,
            domain=self.domain,
            operation=self.operation,
            status="success",
            data=items,
            artifacts=[Artifact(type="list", title="신청 내역", items=items)],
            metadata={"refreshed": result.refreshed, "cached_at": result.cached_at.isoformat()},
        )
