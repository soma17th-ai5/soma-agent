"""동기화 잡 상태. SPEC §3.1 sync_state 매핑."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.domain.models import Base


class SyncState(Base):
    __tablename__ = "sync_state"

    job_name: Mapped[str] = mapped_column(String(100), primary_key=True)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
