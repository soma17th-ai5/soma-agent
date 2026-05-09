"""opensoma.* tool 검증 — OpenSomaClient/services 모킹."""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from app.adapters.opensoma_client import OpenSomaClientError
from app.domain.contracts.action import ActionResult
from app.tools.application import ApplicationHistoryTool
from app.tools.base import ToolContext
from app.tools.mentoring import (
    MentoringApplyTool,
    MentoringCancelTool,
    MentoringGetTool,
    MentoringListTool,
)
from app.tools.notice import NoticeGetTool


def _ctx(*, soma_session: str = "sess", soma_user_id: str = "u-1", **kw):  # type: ignore[no-untyped-def]
    return ToolContext(
        soma_session=soma_session,
        soma_user_id=soma_user_id,
        opensoma=kw.get("opensoma"),
        db=kw.get("db"),
    )


@pytest.mark.asyncio
async def test_mentoringList_should_returnItems_when_clientSucceeds() -> None:
    client = MagicMock()
    client.mentoring_list.return_value = {"items": [{"id": 1, "title": "A"}]}

    result = await MentoringListTool().run({}, _ctx(opensoma=client))

    assert result.status == "success"
    assert result.data == [{"id": 1, "title": "A"}]
    client.mentoring_list.assert_called_once_with("sess")


@pytest.mark.asyncio
async def test_mentoringList_should_returnFailed_when_authMissing() -> None:
    result = await MentoringListTool().run({}, ToolContext())

    assert result.status == "failed"
    assert result.error and result.error.code == "SOMA_AUTH_REQUIRED"


@pytest.mark.asyncio
async def test_mentoringList_should_wrapClientError_when_upstreamFails() -> None:
    client = MagicMock()
    client.mentoring_list.side_effect = OpenSomaClientError(
        503, "UPSTREAM_UNAVAILABLE", "down"
    )

    result = await MentoringListTool().run({}, _ctx(opensoma=client))

    assert result.status == "failed"
    assert result.error and result.error.code == "UPSTREAM_UNAVAILABLE"
    assert result.error.recoverable is True


@pytest.mark.asyncio
async def test_mentoringGet_should_rejectInvalidId() -> None:
    result = await MentoringGetTool().run(
        {"mentoring_id": "abc"}, _ctx(opensoma=MagicMock())
    )

    assert result.status == "failed"
    assert result.error and result.error.code == "INVALID_PARAM"


@pytest.mark.asyncio
async def test_mentoringApply_should_returnSuccess_when_serviceReturnsActionResult() -> None:
    client = MagicMock()
    db = MagicMock()
    apply_outcome = ActionResult(
        type="opensoma.mentoring.apply",
        status="success",
        message="신청 완료",
        payload={"apply_sn": 123, "qustnr_sn": 456},
    )

    import app.tools.mentoring as tools_mentoring

    monkey_called: dict[str, object] = {}

    def _fake_apply(db_arg, opensoma_arg, sess, user_id, mid, *, confirmed):  # type: ignore[no-untyped-def]
        monkey_called["confirmed"] = confirmed
        monkey_called["mid"] = mid
        return apply_outcome

    original_apply = tools_mentoring.mentoring_service.apply
    tools_mentoring.mentoring_service.apply = _fake_apply  # type: ignore[assignment]
    try:
        result = await MentoringApplyTool().run(
            {"mentoring_id": 7}, _ctx(opensoma=client, db=db)
        )
    finally:
        tools_mentoring.mentoring_service.apply = original_apply  # type: ignore[assignment]

    assert result.status == "success"
    assert monkey_called["confirmed"] is True
    assert monkey_called["mid"] == 7
    assert result.action == apply_outcome


@pytest.mark.asyncio
async def test_mentoringCancel_should_validateBothIds() -> None:
    result = await MentoringCancelTool().run(
        {"apply_sn": 1}, _ctx(opensoma=MagicMock(), db=MagicMock())
    )

    assert result.status == "failed"
    assert result.error and "qustnr_sn" in result.error.message


@pytest.mark.asyncio
async def test_applicationHistory_should_returnItems_when_serviceSucceeds() -> None:
    from datetime import datetime

    import app.tools.application as tools_application

    fake_row = MagicMock(
        apply_sn=1,
        qustnr_sn=2,
        category="mentoring",
        title="A",
        target_url="http://x",
        session_date_text=None,
        applied_at_text="2026-05-01",
        application_status="신청완료",
        approval_status="승인",
    )
    fake_result = MagicMock(items=[fake_row], cached_at=datetime(2026, 5, 6), refreshed=True)

    original = tools_application.application_service.get_history
    tools_application.application_service.get_history = MagicMock(return_value=fake_result)  # type: ignore[assignment]
    try:
        result = await ApplicationHistoryTool().run(
            {}, _ctx(opensoma=MagicMock(), db=MagicMock())
        )
    finally:
        tools_application.application_service.get_history = original  # type: ignore[assignment]

    assert result.status == "success"
    assert isinstance(result.data, list) and len(result.data) == 1
    assert result.data[0]["apply_sn"] == 1
    assert result.metadata["refreshed"] is True


@pytest.mark.asyncio
async def test_noticeGet_should_returnDetail_when_clientSucceeds() -> None:
    client = MagicMock()
    client.notice_get.return_value = {"id": 5, "title": "공지 5", "content": "..."}

    result = await NoticeGetTool().run({"notice_id": 5}, _ctx(opensoma=client))

    assert result.status == "success"
    assert result.data["title"] == "공지 5"
    client.notice_get.assert_called_once_with("sess", 5)


@pytest.mark.asyncio
async def test_noticeGet_should_failOnAuthMissing() -> None:
    result = await NoticeGetTool().run({"notice_id": 1}, ToolContext())

    assert result.status == "failed"
    assert result.error and result.error.code == "SOMA_AUTH_REQUIRED"
