"""Scheduler job entrypoints.

Each job creates its own DB session and adapter instances because APScheduler runs
jobs outside the request dependency-injection lifecycle.
"""

from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import asdict, is_dataclass
from typing import Any

from sqlalchemy.orm import Session

from app.adapters.opensoma_client import OpenSomaClient
from app.adapters.qdrant_client import QdrantAdapter
from app.adapters.solar_client import SolarClient
from app.adapters.webex_client import WebexClient
from app.config import get_settings
from app.db.session import session_scope
from app.scheduler import state
from app.services import mentoring as mentoring_service
from app.services import notice as notice_service
from app.services import webex as webex_service

NOTICES_SYNC = "notices_sync"
MENTORINGS_SYNC = "mentorings_sync"
WEBEX_SYNC = "webex_sync"
JOB_NAMES = (NOTICES_SYNC, MENTORINGS_SYNC, WEBEX_SYNC)

SessionFactory = Callable[[], AbstractContextManager[Session]]


def run_job(job_name: str, *, session_factory: SessionFactory = session_scope) -> dict[str, Any]:
    if job_name == NOTICES_SYNC:
        return run_notices_sync(session_factory=session_factory)
    if job_name == MENTORINGS_SYNC:
        return run_mentorings_sync(session_factory=session_factory)
    if job_name == WEBEX_SYNC:
        return run_webex_sync(session_factory=session_factory)
    raise ValueError(f"unknown scheduler job: {job_name}")


def run_notices_sync(*, session_factory: SessionFactory = session_scope) -> dict[str, Any]:
    with session_factory() as db:
        return _run_with_state(db, NOTICES_SYNC, lambda: _run_opensoma_notice_sync(db))


def run_mentorings_sync(*, session_factory: SessionFactory = session_scope) -> dict[str, Any]:
    with session_factory() as db:
        return _run_with_state(db, MENTORINGS_SYNC, lambda: _run_opensoma_mentoring_sync(db))


def run_webex_sync(*, session_factory: SessionFactory = session_scope) -> dict[str, Any]:
    with session_factory() as db:
        return _run_with_state(db, WEBEX_SYNC, lambda: _run_webex_sync(db))


def _run_with_state(
    db: Session,
    job_name: str,
    fn: Callable[[], Any],
) -> dict[str, Any]:
    state.mark_started(db, job_name)
    try:
        stats = fn()
    except Exception as exc:
        state.mark_error(db, job_name, exc)
        raise
    state.mark_success(db, job_name)
    return _stats_to_dict(stats)


def _run_opensoma_notice_sync(db: Session) -> Any:
    with _ManagedClients() as (opensoma, qdrant, solar):
        session_id = opensoma.operator_session().session_id
        qdrant.ensure_collection()
        return notice_service.run_sync(db, opensoma, session_id, qdrant=qdrant, solar=solar)


def _run_opensoma_mentoring_sync(db: Session) -> Any:
    with _ManagedClients() as (opensoma, qdrant, solar):
        session_id = opensoma.operator_session().session_id
        qdrant.ensure_collection()
        return mentoring_service.run_sync(db, opensoma, session_id, qdrant=qdrant, solar=solar)


def _run_webex_sync(db: Session) -> Any:
    settings = get_settings()
    with WebexClient(settings.operator_webex_token) as webex:
        qdrant = QdrantAdapter()
        solar = SolarClient()
        try:
            qdrant.ensure_collection()
            return webex_service.run_sync(db, webex, qdrant=qdrant, solar=solar)
        finally:
            qdrant.close()
            solar.close()


class _ManagedClients:
    def __enter__(self) -> tuple[OpenSomaClient, QdrantAdapter, SolarClient]:
        self.opensoma = OpenSomaClient()
        self.qdrant = QdrantAdapter()
        self.solar = SolarClient()
        return self.opensoma, self.qdrant, self.solar

    def __exit__(self, *_: object) -> None:
        self.opensoma.close()
        self.qdrant.close()
        self.solar.close()


def _stats_to_dict(stats: Any) -> dict[str, Any]:
    if is_dataclass(stats) and not isinstance(stats, type):
        return asdict(stats)
    if isinstance(stats, dict):
        return stats
    return {"result": str(stats)}
