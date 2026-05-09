"""CalendarMock 결정론·실패 주입 검증."""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from app.adapters.calendar_mock import CalendarMock


def test_should_returnSuccess_when_failRateZero() -> None:
    mock = CalendarMock(fail_rate=0.0, seed=42)
    start = datetime(2026, 6, 1, 10, 0)
    end = start + timedelta(hours=1)

    result = mock.create_invite(title="멘토링 A", start_at=start, end_at=end)

    assert result.status == "success"
    assert result.invite_id and result.invite_id.startswith("mock-")
    assert result.error is None


def test_should_returnFailed_when_failRateOne() -> None:
    mock = CalendarMock(fail_rate=1.0)
    start = datetime(2026, 6, 1, 10, 0)
    end = start + timedelta(hours=1)

    result = mock.create_invite(title="멘토링 B", start_at=start, end_at=end)

    assert result.status == "failed"
    assert result.invite_id is None
    assert result.error == "mock_fail_injected"


def test_should_returnFailed_when_endBeforeStart() -> None:
    mock = CalendarMock(fail_rate=0.0)
    start = datetime(2026, 6, 1, 10, 0)
    end = start - timedelta(minutes=1)

    result = mock.create_invite(title="잘못된 일정", start_at=start, end_at=end)

    assert result.status == "failed"
    assert "end_at must be after start_at" in (result.error or "")


def test_should_raiseValueError_when_failRateOutOfRange() -> None:
    with pytest.raises(ValueError):
        CalendarMock(fail_rate=1.5)
