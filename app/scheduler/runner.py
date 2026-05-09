"""APScheduler integration for FastAPI lifespan."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.domain.models.sync_state import SyncState
from app.observability.logging import get_logger
from app.scheduler import jobs

log = get_logger("app.scheduler.runner")


@dataclass(frozen=True)
class SchedulerJobStatus:
    name: str
    cron: str
    next_run_at: str | None
    last_run_at: str | None
    last_success_at: str | None
    last_error: str | None


class SchedulerManager:
    def __init__(
        self,
        *,
        settings: Settings | None = None,
        scheduler: BackgroundScheduler | None = None,
        run_job: Callable[[str], dict[str, Any]] | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._scheduler = scheduler or BackgroundScheduler(
            timezone=self._settings.scheduler_timezone
        )
        self._run_job = run_job or (lambda job_name: jobs.run_job(job_name))
        self._cron_by_job = {
            jobs.NOTICES_SYNC: self._settings.sync_notices_cron,
            jobs.MENTORINGS_SYNC: self._settings.sync_mentorings_cron,
            jobs.WEBEX_SYNC: self._settings.sync_webex_cron,
        }

    @property
    def running(self) -> bool:
        return self._scheduler.running

    def start(self) -> None:
        if not self._settings.scheduler_enabled:
            log.info("scheduler.disabled")
            return
        if self._scheduler.running:
            return
        for job_name, cron_expr in self._cron_by_job.items():
            self._scheduler.add_job(
                self._run_job,
                trigger=CronTrigger.from_crontab(
                    cron_expr,
                    timezone=self._settings.scheduler_timezone,
                ),
                args=[job_name],
                id=job_name,
                name=job_name,
                replace_existing=True,
                max_instances=1,
                coalesce=True,
                misfire_grace_time=300,
            )
        self._scheduler.start()
        log.info("scheduler.started", jobs=list(self._cron_by_job))

    def shutdown(self) -> None:
        if self._scheduler.running:
            self._scheduler.shutdown(wait=False)
            log.info("scheduler.stopped")

    def run_now(self, job_name: str) -> dict[str, Any]:
        if job_name not in self._cron_by_job:
            raise ValueError(f"unknown scheduler job: {job_name}")
        return self._run_job(job_name)

    def statuses(self, db: Session) -> list[SchedulerJobStatus]:
        rows = {
            row.job_name: row
            for row in db.execute(select(SyncState)).scalars().all()
        }
        return [
            self._status_for(job_name, rows.get(job_name))
            for job_name in self._cron_by_job
        ]

    def _status_for(
        self,
        job_name: str,
        row: SyncState | None,
    ) -> SchedulerJobStatus:
        scheduled_job = self._scheduler.get_job(job_name)
        next_run_at = scheduled_job.next_run_time if scheduled_job else None
        return SchedulerJobStatus(
            name=job_name,
            cron=self._cron_by_job[job_name],
            next_run_at=next_run_at.isoformat() if next_run_at else None,
            last_run_at=row.last_run_at.isoformat() if row and row.last_run_at else None,
            last_success_at=(
                row.last_success_at.isoformat() if row and row.last_success_at else None
            ),
            last_error=row.last_error if row else None,
        )


def create_scheduler_manager() -> SchedulerManager:
    return SchedulerManager()
