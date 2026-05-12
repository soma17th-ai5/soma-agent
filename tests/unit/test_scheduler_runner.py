from __future__ import annotations

import pytest
from apscheduler.schedulers.background import BackgroundScheduler

from app.config import Settings
from app.scheduler.runner import SchedulerManager


def _settings() -> Settings:
    return Settings(
        scheduler_enabled=True,
        sync_notices_cron="*/30 * * * *",
        sync_mentorings_cron="*/30 * * * *",
        sync_webex_cron="0 * * * *",
    )


def test_should_registerConfiguredJobs_when_schedulerStarts() -> None:
    manager = SchedulerManager(
        settings=_settings(),
        scheduler=BackgroundScheduler(timezone="Asia/Seoul"),
        run_job=lambda _: {},
    )
    try:
        manager.start()

        assert manager.running is True
        assert manager._scheduler.get_job("notices_sync") is not None
        assert manager._scheduler.get_job("mentorings_sync") is not None
        assert manager._scheduler.get_job("webex_sync") is not None
    finally:
        manager.shutdown()


def test_should_runRequestedJob_when_runNowCalled() -> None:
    calls: list[str] = []
    manager = SchedulerManager(
        settings=_settings(),
        scheduler=BackgroundScheduler(timezone="Asia/Seoul"),
        run_job=lambda name: calls.append(name) or {"ok": True},
    )

    result = manager.run_now("webex_sync")

    assert calls == ["webex_sync"]
    assert result == {"ok": True}


def test_should_raiseValueError_when_jobNameUnknown() -> None:
    manager = SchedulerManager(settings=_settings(), run_job=lambda _: {})

    with pytest.raises(ValueError):
        manager.run_now("unknown")
