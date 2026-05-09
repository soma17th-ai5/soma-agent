"""opensoma.notice.get tool. SPEC §4.2 — 단일 공지 정확 조회 (첨부 포함)."""
from __future__ import annotations

from typing import Any

from app.adapters.opensoma_client import OpenSomaClientError
from app.domain.contracts.tool_result import Artifact, ToolResult
from app.tools._helpers import failed_result, require_param
from app.tools.base import Tool, ToolContext


class NoticeGetTool(Tool):
    name = "opensoma.notice.get"
    domain = "opensoma"
    operation = "get"
    requires_auth = True

    async def run(self, params: dict[str, Any], ctx: ToolContext) -> ToolResult:
        if not ctx.soma_session or ctx.opensoma is None:
            return failed_result(
                tool=self.name,
                domain=self.domain,
                operation=self.operation,
                code="SOMA_AUTH_REQUIRED",
                message="X-Soma-Session is required",
            )

        nid, err = require_param(params, "notice_id")
        if err:
            return failed_result(
                tool=self.name,
                domain=self.domain,
                operation=self.operation,
                code="INVALID_PARAM",
                message=err,
            )
        try:
            nid_int = int(nid)
        except (TypeError, ValueError):
            return failed_result(
                tool=self.name,
                domain=self.domain,
                operation=self.operation,
                code="INVALID_PARAM",
                message=f"notice_id must be int-like, got {nid!r}",
            )

        try:
            detail = ctx.opensoma.notice_get(ctx.soma_session, nid_int)
        except OpenSomaClientError as e:
            return failed_result(
                tool=self.name,
                domain=self.domain,
                operation=self.operation,
                code=e.code or "OPENSOMA_ERROR",
                message=e.message,
                recoverable=e.status >= 500,
            )

        return ToolResult(
            tool=self.name,
            domain=self.domain,
            operation=self.operation,
            status="success",
            data=detail,
            artifacts=[Artifact(type="card", title=detail.get("title", "공지"), content=detail.get("content"))],
        )
