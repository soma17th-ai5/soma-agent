"""OpenSoma 멘토링 tool 4종. SPEC §4.2.

- list/get: 라이브 조회 (현재 상태가 중요한 의도일 때만).
- apply/cancel: SPEC §4.4 — `/chat` 라우터는 호출하지 않는다. `/actions/execute`에서만
  호출. 본 tool은 confirmed=True 경로(=실제 실행)를 노출한다.
"""
from __future__ import annotations

from typing import Any

from app.adapters.opensoma_client import OpenSomaClientError
from app.domain.contracts.action import ActionResult
from app.domain.contracts.tool_result import Artifact, ToolResult
from app.services import mentoring as mentoring_service
from app.tools._helpers import failed_result, require_param
from app.tools.base import Tool, ToolContext


def _missing_auth(tool_name: str, operation: str) -> ToolResult:
    return failed_result(
        tool=tool_name,
        domain="opensoma",
        operation=operation,
        code="SOMA_AUTH_REQUIRED",
        message="X-Soma-Session is required for this tool",
    )


def _wrap_opensoma_error(
    *, tool: str, operation: str, e: OpenSomaClientError
) -> ToolResult:
    return failed_result(
        tool=tool,
        domain="opensoma",
        operation=operation,
        code=e.code or "OPENSOMA_ERROR",
        message=e.message,
        recoverable=e.status >= 500,
    )


class MentoringListTool(Tool):
    """라이브 멘토링 목록. 현재 상태가 정확해야 하는 의도일 때만 사용."""

    name = "opensoma.mentoring.list"
    domain = "opensoma"
    operation = "list"
    requires_auth = True

    async def run(self, params: dict[str, Any], ctx: ToolContext) -> ToolResult:
        if not ctx.soma_session or ctx.opensoma is None:
            return _missing_auth(self.name, self.operation)

        try:
            payload = ctx.opensoma.mentoring_list(ctx.soma_session)
        except OpenSomaClientError as e:
            return _wrap_opensoma_error(tool=self.name, operation=self.operation, e=e)

        items = payload.get("items") or payload.get("data") or []
        return ToolResult(
            tool=self.name,
            domain=self.domain,
            operation=self.operation,
            status="success",
            data=items,
            artifacts=[Artifact(type="list", title="멘토링 목록", items=items)],
        )


class MentoringGetTool(Tool):
    """라이브 멘토링 상세."""

    name = "opensoma.mentoring.get"
    domain = "opensoma"
    operation = "get"
    requires_auth = True

    async def run(self, params: dict[str, Any], ctx: ToolContext) -> ToolResult:
        if not ctx.soma_session or ctx.opensoma is None:
            return _missing_auth(self.name, self.operation)

        mid, err = require_param(params, "mentoring_id")
        if err:
            return failed_result(
                tool=self.name,
                domain=self.domain,
                operation=self.operation,
                code="INVALID_PARAM",
                message=err,
            )

        try:
            mid_int = int(mid)
        except (TypeError, ValueError):
            return failed_result(
                tool=self.name,
                domain=self.domain,
                operation=self.operation,
                code="INVALID_PARAM",
                message=f"mentoring_id must be int-like, got {mid!r}",
            )

        try:
            detail = ctx.opensoma.mentoring_get(ctx.soma_session, mid_int)
        except OpenSomaClientError as e:
            return _wrap_opensoma_error(tool=self.name, operation=self.operation, e=e)

        return ToolResult(
            tool=self.name,
            domain=self.domain,
            operation=self.operation,
            status="success",
            data=detail,
            artifacts=[Artifact(type="card", title="멘토링 상세", content=str(detail.get("title", "")))],
        )


class MentoringApplyTool(Tool):
    """멘토링 신청 *실제 실행*. SPEC §4.4 — `/actions/execute`에서만 호출.

    confirmed=True 경로 — services.mentoring.apply에 위임. 결과는 ActionResult.
    """

    name = "opensoma.mentoring.apply"
    domain = "opensoma"
    operation = "apply"
    requires_auth = True

    async def run(self, params: dict[str, Any], ctx: ToolContext) -> ToolResult:
        if not ctx.soma_session or ctx.opensoma is None or ctx.db is None:
            return _missing_auth(self.name, self.operation)
        if not ctx.soma_user_id:
            return failed_result(
                tool=self.name,
                domain=self.domain,
                operation=self.operation,
                code="MISSING_USER_ID",
                message="soma_user_id required to invalidate applications cache",
            )

        mid, err = require_param(params, "mentoring_id")
        if err:
            return failed_result(
                tool=self.name,
                domain=self.domain,
                operation=self.operation,
                code="INVALID_PARAM",
                message=err,
            )

        try:
            mid_int = int(mid)
        except (TypeError, ValueError):
            return failed_result(
                tool=self.name,
                domain=self.domain,
                operation=self.operation,
                code="INVALID_PARAM",
                message=f"mentoring_id must be int-like, got {mid!r}",
            )

        try:
            outcome = mentoring_service.apply(
                ctx.db,
                ctx.opensoma,
                ctx.soma_session,
                ctx.soma_user_id,
                mid_int,
                confirmed=True,
            )
        except mentoring_service.MentoringNotApplicableError as e:
            return failed_result(
                tool=self.name,
                domain=self.domain,
                operation=self.operation,
                code="MENTORING_NOT_APPLICABLE",
                message=str(e),
            )
        except OpenSomaClientError as e:
            return _wrap_opensoma_error(tool=self.name, operation=self.operation, e=e)

        if not isinstance(outcome, ActionResult):
            # confirmed=True 경로는 ActionResult를 반환해야 함 — 방어.
            return failed_result(
                tool=self.name,
                domain=self.domain,
                operation=self.operation,
                code="UNEXPECTED_PROPOSAL",
                message="apply tool received ActionProposal in confirmed path",
            )

        return ToolResult(
            tool=self.name,
            domain=self.domain,
            operation=self.operation,
            status="success" if outcome.status == "success" else "failed",
            data=outcome.payload,
            action=outcome,
        )


class MentoringCancelTool(Tool):
    """멘토링 신청 취소 *실제 실행*. SPEC §4.4 — `/actions/execute`에서만 호출."""

    name = "opensoma.mentoring.cancel"
    domain = "opensoma"
    operation = "cancel"
    requires_auth = True

    async def run(self, params: dict[str, Any], ctx: ToolContext) -> ToolResult:
        if not ctx.soma_session or ctx.opensoma is None or ctx.db is None:
            return _missing_auth(self.name, self.operation)
        if not ctx.soma_user_id:
            return failed_result(
                tool=self.name,
                domain=self.domain,
                operation=self.operation,
                code="MISSING_USER_ID",
                message="soma_user_id required",
            )

        for required in ("apply_sn", "qustnr_sn"):
            _, err = require_param(params, required)
            if err:
                return failed_result(
                    tool=self.name,
                    domain=self.domain,
                    operation=self.operation,
                    code="INVALID_PARAM",
                    message=err,
                )

        try:
            apply_sn = int(params["apply_sn"])
            qustnr_sn = int(params["qustnr_sn"])
        except (TypeError, ValueError) as e:
            return failed_result(
                tool=self.name,
                domain=self.domain,
                operation=self.operation,
                code="INVALID_PARAM",
                message=f"apply_sn/qustnr_sn must be int-like: {e}",
            )

        try:
            outcome = mentoring_service.cancel(
                ctx.db,
                ctx.opensoma,
                ctx.soma_session,
                ctx.soma_user_id,
                apply_sn,
                qustnr_sn,
                confirmed=True,
            )
        except OpenSomaClientError as e:
            return _wrap_opensoma_error(tool=self.name, operation=self.operation, e=e)

        if not isinstance(outcome, ActionResult):
            return failed_result(
                tool=self.name,
                domain=self.domain,
                operation=self.operation,
                code="UNEXPECTED_PROPOSAL",
                message="cancel tool received ActionProposal in confirmed path",
            )

        return ToolResult(
            tool=self.name,
            domain=self.domain,
            operation=self.operation,
            status="success" if outcome.status == "success" else "failed",
            data=outcome.payload,
            action=outcome,
        )
