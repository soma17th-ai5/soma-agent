"""사용자 접수 내역 — TTL 캐시 (5분) + 신청/취소 후 즉시 무효화. SPEC §3.1, §7.2.

흐름:
  api/agent → services.application.get_history(user, opensoma, session_id)
            → cached_at < now-5min 이면 sidecar history 조회 → applications 갱신 → 반환
            → else applications 그대로 반환
  apply/cancel 직후 → invalidate(user) 로 행 삭제 → 다음 조회 시 강제 재조회
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.adapters.opensoma_client import OpenSomaClient
from app.domain.models.application import Application

log = logging.getLogger("app.services.application")

CACHE_TTL = timedelta(minutes=5)


@dataclass
class HistoryResult:
    items: list[Application]
    cached_at: datetime
    refreshed: bool


def _extract_qustnr_sn(url: str | None) -> int | None:
    if not url:
        return None
    m = re.search(r"qustnrSn=(\d+)", url)
    return int(m.group(1)) if m else None


def _is_fresh(rows: list[Application]) -> bool:
    """모든 행의 cached_at 이 TTL 이내면 캐시 유효."""
    if not rows:
        return False
    cutoff = datetime.utcnow() - CACHE_TTL
    return all(r.cached_at >= cutoff for r in rows)


def get_history(
    db: Session,
    opensoma: OpenSomaClient,
    session_id: str,
    soma_user_id: str,
    *,
    force_refresh: bool = False,
    max_pages: int = 10,
) -> HistoryResult:
    """사용자 접수 내역 — 캐시 우선, 만료/강제 시 sidecar 호출."""
    rows = (
        db.execute(select(Application).where(Application.soma_user_id == soma_user_id))
        .scalars()
        .all()
    )
    if not force_refresh and _is_fresh(rows):
        cached_at = max((r.cached_at for r in rows), default=datetime.utcnow())
        return HistoryResult(items=list(rows), cached_at=cached_at, refreshed=False)

    # cache miss → sidecar 호출 + 갱신
    db.execute(delete(Application).where(Application.soma_user_id == soma_user_id))
    new_rows: list[Application] = []
    for page in range(1, max_pages + 1):
        payload = opensoma.application_history(session_id, page=page)
        for item in payload.get("items", []) or []:
            new_rows.append(_to_row(item, soma_user_id))
        pagination = payload.get("pagination") or {}
        total_pages = pagination.get("totalPages") or page
        if page >= total_pages:
            break
    db.add_all(new_rows)
    db.commit()
    log.info("application.history.refreshed", user=soma_user_id, count=len(new_rows))
    cached_at = datetime.utcnow()
    return HistoryResult(items=new_rows, cached_at=cached_at, refreshed=True)


def invalidate(db: Session, soma_user_id: str) -> int:
    """해당 user 의 모든 applications 행 삭제 (apply/cancel 직후 호출)."""
    result = db.execute(delete(Application).where(Application.soma_user_id == soma_user_id))
    db.commit()
    count = result.rowcount or 0
    log.info("application.history.invalidated", user=soma_user_id, removed=count)
    return count


def _to_row(item: dict[str, Any], soma_user_id: str) -> Application:
    """sidecar history item → Application ORM. url 의 qustnrSn 추출."""
    return Application(
        soma_user_id=soma_user_id,
        apply_sn=int(item["id"]),
        qustnr_sn=_extract_qustnr_sn(item.get("url")),
        category=item.get("category"),
        title=item.get("title"),
        target_url=item.get("url"),
        author=item.get("author"),
        session_date_text=item.get("sessionDate"),
        applied_at_text=item.get("appliedAt"),
        application_status=item.get("applicationStatus"),
        approval_status=item.get("approvalStatus"),
        application_detail=item.get("applicationDetail"),
        note=item.get("note"),
    )
