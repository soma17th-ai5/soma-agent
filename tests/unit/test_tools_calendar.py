"""calendar.invite.create tool 검증."""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from app.adapters.calendar_mock import CalendarMock
from app.tools.base import ToolContext
from app.tools.calendar import CalendarInviteCreateTool


@pytest.mark.asyncio
async def test_should_returnSuccess_when_validParamsAndCalendarSucceeds() -> None:
    tool = CalendarInviteCreateTool()
    ctx = ToolContext(calendar=CalendarMock(fail_rate=0.0, seed=1))
    start = datetime(2026, 6, 1, 10, 0)

    result = await tool.run(
        {
            "title": "멘토링 A",
            "start_at": start.isoformat(),
            "end_at": (start + timedelta(hours=1)).isoformat(),
        },
        ctx,
    )

    assert result.status == "success"
    assert result.data is not None
    assert result.data["status"] == "success"
    assert result.data["invite_id"]


@pytest.mark.asyncio
async def test_should_returnFailed_when_calendarMockMissing() -> None:
    tool = CalendarInviteCreateTool()

    result = await tool.run({"title": "x"}, ToolContext())

    assert result.status == "failed"
    assert result.error is not None
    assert result.error.code == "MISSING_DEPS"


@pytest.mark.asyncio
async def test_should_returnFailed_when_invalidIsoDate() -> None:
    tool = CalendarInviteCreateTool()
    ctx = ToolContext(calendar=CalendarMock(fail_rate=0.0))

    result = await tool.run(
        {"title": "x", "start_at": "not-a-date", "end_at": "2026-06-01T10:00"}, ctx
    )

    assert result.status == "failed"
    assert result.error is not None
    assert result.error.code == "INVALID_PARAM"


@pytest.mark.asyncio
async def test_should_returnFailed_when_titleMissing() -> None:
    tool = CalendarInviteCreateTool()
    ctx = ToolContext(calendar=CalendarMock(fail_rate=0.0))

    result = await tool.run({}, ctx)

    assert result.status == "failed"
    assert result.error is not None
    assert "title" in result.error.message
