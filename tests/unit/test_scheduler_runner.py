from __future__ import annotations

from typing import Any

import pytest
from apscheduler.schedulers.background import BackgroundScheduler
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api import deps
from app.api.scheduler import router
from app.config import Settings, get_settings
from app.domain.models import Base
from app.errors import BaseAPIException
from app.errors.handlers import api_error_handler, validation_error_handler
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


def test_should_returnStatusAndRunJob_when_schedulerApiCalled() -> None:
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

    def override_db() -> Any:
        db = SessionLocal()
        try:
            yield db
        finally:
            db.close()

    calls: list[str] = []
    manager = SchedulerManager(
        settings=_settings(),
        scheduler=BackgroundScheduler(timezone="Asia/Seoul"),
        run_job=lambda name: calls.append(name) or {"done": True},
    )
    manager.start()

    app = FastAPI()
    app.state.scheduler_manager = manager
    app.add_exception_handler(BaseAPIException, api_error_handler)
    from fastapi.exceptions import RequestValidationError

    app.add_exception_handler(RequestValidationError, validation_error_handler)
    app.dependency_overrides[deps.get_db] = override_db
    app.include_router(router)

    try:
        with TestClient(app) as client:
            status_res = client.get("/api/v1/scheduler/status")
            assert status_res.status_code == 200
            body = status_res.json()
            assert body["running"] is True
            assert {job["name"] for job in body["jobs"]} == {
                "notices_sync",
                "mentorings_sync",
                "webex_sync",
            }

            run_res = client.post("/api/v1/scheduler/jobs/webex_sync/run")
            assert run_res.status_code == 200
            assert run_res.json()["stats"] == {"done": True}
            assert calls == ["webex_sync"]
    finally:
        manager.shutdown()


def test_should_rejectRunJob_when_adminTokenConfiguredAndHeaderMissing(monkeypatch: Any) -> None:
    monkeypatch.setenv("SCHEDULER_ADMIN_TOKEN", "secret")
    get_settings.cache_clear()

    app = FastAPI()
    app.state.scheduler_manager = SchedulerManager(
        settings=_settings(),
        scheduler=BackgroundScheduler(timezone="Asia/Seoul"),
        run_job=lambda _: {"done": True},
    )
    app.add_exception_handler(BaseAPIException, api_error_handler)
    app.include_router(router)

    try:
        with TestClient(app) as client:
            res = client.post("/api/v1/scheduler/jobs/webex_sync/run")
            assert res.status_code == 422
            assert res.json()["code"] == "INVALID_REQUEST"
    finally:
        monkeypatch.delenv("SCHEDULER_ADMIN_TOKEN", raising=False)
        get_settings.cache_clear()
