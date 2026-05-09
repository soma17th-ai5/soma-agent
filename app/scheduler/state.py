"""`sync_state` persistence helpers for scheduler jobs."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.models.sync_state import SyncState


def utc_now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def mark_started(db: Session, job_name: str, *, now: datetime | None = None) -> SyncState:
    row = _get_or_create(db, job_name)
    row.last_run_at = now or utc_now()
    db.commit()
    db.refresh(row)
    return row


def mark_success(db: Session, job_name: str, *, now: datetime | None = None) -> SyncState:
    row = _get_or_create(db, job_name)
    current = now or utc_now()
    row.last_run_at = row.last_run_at or current
    row.last_success_at = current
    row.last_error = None
    db.commit()
    db.refresh(row)
    return row


def mark_error(
    db: Session,
    job_name: str,
    error: BaseException | str,
    *,
    now: datetime | None = None,
) -> SyncState:
    row = _get_or_create(db, job_name)
    current = now or utc_now()
    row.last_run_at = row.last_run_at or current
    row.last_error = _error_message(error)
    db.commit()
    db.refresh(row)
    return row


def _get_or_create(db: Session, job_name: str) -> SyncState:
    row = db.execute(select(SyncState).where(SyncState.job_name == job_name)).scalar_one_or_none()
    if row is None:
        row = SyncState(job_name=job_name)
        db.add(row)
        db.flush()
    return row


def _error_message(error: BaseException | str) -> str:
    message = str(error)
    return message[:2000]
