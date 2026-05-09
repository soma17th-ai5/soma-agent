from __future__ import annotations

from datetime import datetime

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.domain.models import Base
from app.domain.models.sync_state import SyncState
from app.scheduler import state


def _session() -> sessionmaker:
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def test_should_createAndUpdateSyncState_when_jobSucceeds() -> None:
    SessionLocal = _session()
    with SessionLocal() as db:
        started_at = datetime(2026, 5, 9, 10, 0, 0)
        succeeded_at = datetime(2026, 5, 9, 10, 1, 0)

        state.mark_started(db, "webex_sync", now=started_at)
        state.mark_success(db, "webex_sync", now=succeeded_at)

        row = db.execute(select(SyncState)).scalar_one()
        assert row.job_name == "webex_sync"
        assert row.last_run_at == started_at
        assert row.last_success_at == succeeded_at
        assert row.last_error is None


def test_should_recordErrorAndTruncateMessage_when_jobFails() -> None:
    SessionLocal = _session()
    with SessionLocal() as db:
        state.mark_error(db, "notices_sync", "x" * 3000)

        row = db.execute(select(SyncState)).scalar_one()
        assert row.job_name == "notices_sync"
        assert row.last_error == "x" * 2000
