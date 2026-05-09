from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, Request
from pydantic import BaseModel

from app.api.deps import DbSession
from app.config import get_settings
from app.errors.exceptions import InvalidRequest
from app.scheduler.runner import SchedulerManager

router = APIRouter(prefix="/api/v1/scheduler", tags=["scheduler"])


class SchedulerJobResponse(BaseModel):
    name: str
    cron: str
    next_run_at: str | None
    last_run_at: str | None
    last_success_at: str | None
    last_error: str | None


class SchedulerStatusResponse(BaseModel):
    running: bool
    jobs: list[SchedulerJobResponse]


class RunJobResponse(BaseModel):
    job_name: str
    status: str
    stats: dict[str, Any]


def _manager(request: Request) -> SchedulerManager:
    manager = getattr(request.app.state, "scheduler_manager", None)
    if not isinstance(manager, SchedulerManager):
        raise InvalidRequest("scheduler is not configured")
    return manager


def _require_admin_token(
    x_scheduler_token: Annotated[str | None, Header()] = None,
) -> None:
    expected = get_settings().scheduler_admin_token
    if expected and x_scheduler_token != expected:
        raise InvalidRequest("invalid scheduler admin token")


@router.get("/status", response_model=SchedulerStatusResponse)
def status(request: Request, db: DbSession) -> SchedulerStatusResponse:
    manager = _manager(request)
    return SchedulerStatusResponse(
        running=manager.running,
        jobs=[
            SchedulerJobResponse(**job.__dict__)
            for job in manager.statuses(db)
        ],
    )


@router.post("/jobs/{job_name}/run", response_model=RunJobResponse)
def run_job(
    job_name: str,
    request: Request,
    _: Annotated[None, Depends(_require_admin_token)],
) -> RunJobResponse:
    manager = _manager(request)
    try:
        stats = manager.run_now(job_name)
    except ValueError as exc:
        raise InvalidRequest(str(exc)) from exc
    return RunJobResponse(job_name=job_name, status="success", stats=stats)
