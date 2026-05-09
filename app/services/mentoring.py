"""멘토링 동기화 서비스. SPEC §7.3.

mentoring_list (운영자 세션) → content_hash 비교 → 변경분만 detail 조회 →
MySQL upsert (mentorings + mentoring_applicants HMAC) → Qdrant 인덱싱.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import re
from dataclasses import dataclass, field
from datetime import date, datetime, time
from typing import Any

from bs4 import BeautifulSoup
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.adapters.opensoma_client import OpenSomaClient
from app.adapters.qdrant_client import QdrantAdapter
from app.adapters.solar_client import SolarClient
from app.config import get_settings
from app.domain.contracts.knowledge import KnowledgeSourceType
from app.domain.models.mentoring import Mentoring, MentoringApplicant
from app.services.rag_indexer import index_chunks

log = logging.getLogger("app.services.mentoring")


@dataclass
class MentoringSyncStats:
    fetched: int = 0
    inserted: int = 0
    updated: int = 0
    skipped: int = 0
    applicants_persisted: int = 0
    indexed: int = 0
    errors: list[str] = field(default_factory=list)


def _hash_applicant_name(name: str) -> str:
    """멘토링 신청자 실명 익명화. WEBEX_SENDER_SALT 공유 (단일 시크릿 정책)."""
    salt = get_settings().webex_sender_salt
    if not salt:
        raise ValueError("WEBEX_SENDER_SALT must be set for applicant name anonymization")
    digest = hmac.new(salt.encode("utf-8"), name.encode("utf-8"), hashlib.sha256)
    return digest.hexdigest()[:32]


def _compute_content_hash(item: dict[str, Any]) -> str:
    """목록 응답의 핵심 필드 기반 해시. detail 변경 감지에는 별도."""
    raw = json.dumps(
        {
            "id": item.get("id"),
            "title": item.get("title"),
            "type": item.get("type"),
            "registrationPeriod": item.get("registrationPeriod"),
            "sessionDate": item.get("sessionDate"),
            "sessionTime": item.get("sessionTime"),
            "attendees": item.get("attendees"),
            "approved": item.get("approved"),
            "status": item.get("status"),
            "author": item.get("author"),
            "createdAt": item.get("createdAt"),
        },
        sort_keys=True,
        ensure_ascii=False,
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _parse_iso_date(s: str | None) -> date | None:
    if not s:
        return None
    try:
        return datetime.strptime(s.strip(), "%Y-%m-%d").date()
    except ValueError:
        return None


def _parse_iso_datetime(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.strptime(s.strip(), "%Y-%m-%d")
    except ValueError:
        return None


def _parse_time(s: str | None) -> time | None:
    if not s:
        return None
    try:
        return datetime.strptime(s.strip(), "%H:%M").time()
    except ValueError:
        return None


def _strip_html(html: str | None) -> str:
    if not html:
        return ""
    text = BeautifulSoup(html, "html.parser").get_text(separator="\n")
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def run_sync(
    db: Session,
    opensoma: OpenSomaClient,
    session_id: str,
    *,
    qdrant: QdrantAdapter | None = None,
    solar: SolarClient | None = None,
    max_pages: int = 50,
) -> MentoringSyncStats:
    stats = MentoringSyncStats()

    for page in range(1, max_pages + 1):
        payload = opensoma.mentoring_list(session_id, page=page)
        items = payload.get("items", []) or []
        pagination = payload.get("pagination") or {}

        if not items:
            break

        for item in items:
            stats.fetched += 1
            try:
                _process_item(item, db, opensoma, session_id, qdrant, solar, stats)
            except Exception as exc:
                log.exception("mentoring.sync_item_failed id=%s", item.get("id"))
                stats.errors.append(f"mentoring_id={item.get('id')}: {exc}")

        total_pages = pagination.get("totalPages") or page
        if page >= total_pages:
            break

    db.commit()
    return stats


def _process_item(
    item: dict[str, Any],
    db: Session,
    opensoma: OpenSomaClient,
    session_id: str,
    qdrant: QdrantAdapter | None,
    solar: SolarClient | None,
    stats: MentoringSyncStats,
) -> None:
    mentoring_id = int(item["id"])
    new_hash = _compute_content_hash(item)

    existing = db.execute(
        select(Mentoring).where(Mentoring.mentoring_id == mentoring_id)
    ).scalar_one_or_none()

    if existing and existing.content_hash == new_hash:
        stats.skipped += 1
        return

    # 변경 감지 → detail 조회
    detail = opensoma.mentoring_get(session_id, mentoring_id)
    fields = _flatten_fields(item, detail)

    if existing is None:
        mentoring = Mentoring(mentoring_id=mentoring_id, content_hash=new_hash, **fields)
        db.add(mentoring)
        stats.inserted += 1
    else:
        for k, v in fields.items():
            setattr(existing, k, v)
        existing.content_hash = new_hash
        existing.is_active = True
        mentoring = existing
        stats.updated += 1

    db.flush()

    # applicants 갱신: 항상 전체 교체
    db.execute(
        delete(MentoringApplicant).where(MentoringApplicant.mentoring_id == mentoring_id)
    )
    for applicant in detail.get("applicants") or []:
        name = applicant.get("name") or ""
        if not name:
            continue
        db.add(
            MentoringApplicant(
                mentoring_id=mentoring_id,
                applicant_name_hash=_hash_applicant_name(name),
                applied_at_text=applicant.get("appliedAt"),
                cancelled_at_text=applicant.get("cancelledAt"),
                applicant_status=applicant.get("status"),
            )
        )
        stats.applicants_persisted += 1

    if qdrant is not None and solar is not None:
        text = _searchable_text(item, detail)
        if text:
            index_chunks(
                qdrant,
                solar,
                source_type=KnowledgeSourceType.MENTORING,
                source_id=str(mentoring_id),
                title=item["title"],
                texts=[text],
                official=True,
                source_url=item.get("url"),
                created_at=_parse_iso_datetime(item.get("createdAt")),
            )
            stats.indexed += 1


def _flatten_fields(item: dict[str, Any], detail: dict[str, Any]) -> dict[str, Any]:
    """list item + detail의 객체 필드를 우리 컬럼으로 평탄화."""
    reg = item.get("registrationPeriod") or {}
    session_t = item.get("sessionTime") or {}
    att = item.get("attendees") or {}
    session_date_v = _parse_iso_date(item.get("sessionDate"))
    session_start_t = _parse_time(session_t.get("start") if isinstance(session_t, dict) else None)
    session_end_t = _parse_time(session_t.get("end") if isinstance(session_t, dict) else None)
    session_started_at = (
        datetime.combine(session_date_v, session_start_t)
        if session_date_v and session_start_t
        else None
    )
    return {
        "title": item["title"],
        "mentoring_type": item.get("type"),
        "registration_start_at": _parse_iso_datetime(reg.get("start") if isinstance(reg, dict) else None),
        "registration_end_at": _parse_iso_datetime(reg.get("end") if isinstance(reg, dict) else None),
        "session_date": session_date_v,
        "session_start_time": session_start_t,
        "session_end_time": session_end_t,
        "session_started_at": session_started_at,
        "attendees_current": att.get("current") if isinstance(att, dict) else None,
        "attendees_max": att.get("max") if isinstance(att, dict) else None,
        "approved": item.get("approved"),
        "mentoring_status": item.get("status"),
        "author": item.get("author"),
        "created_at_text": item.get("createdAt"),
        "content_html": detail.get("content"),
        "venue": detail.get("venue"),
    }


def _searchable_text(item: dict[str, Any], detail: dict[str, Any]) -> str:
    """RAG 인덱싱용 합성 텍스트."""
    parts = [
        item.get("title") or "",
        item.get("type") or "",
        item.get("author") or "",
        detail.get("venue") or "",
        item.get("sessionDate") or "",
        _strip_html(detail.get("content")),
    ]
    return "\n".join(p for p in parts if p)


# =====================================================================
# 액션: apply / cancel  (SPEC §4.4 needs_confirmation)
# =====================================================================

from app.domain.contracts.action import ActionProposal, ActionResult  # noqa: E402
from app.errors.exceptions import MentoringNotOpen  # noqa: E402
from app.services import application as application_service  # noqa: E402

_OPEN_STATUSES = {"접수중", "open", "OPEN"}


def apply(
    db: Session,
    opensoma: OpenSomaClient,
    session_id: str,
    soma_user_id: str,
    mentoring_id: int,
    *,
    confirmed: bool = False,
) -> ActionProposal | ActionResult:
    """1차(confirmed=False): 직전 detail 재검증 + ActionProposal 반환 (실행 X).
    2차(confirmed=True):     sidecar apply 호출 → applications 캐시 무효화 → ActionResult.

    raises MentoringNotOpen: 현재 status 가 접수중이 아닐 때
    """
    detail = opensoma.mentoring_get(session_id, mentoring_id)
    status = detail.get("status")
    if status not in _OPEN_STATUSES:
        # status 컨텍스트는 응답 본문 message에 포함시켜 클라이언트에 전달.
        raise MentoringNotOpen(
            f"멘토링이 신청 가능 상태가 아닙니다 (현재: {status!r})",
        )

    if not confirmed:
        return ActionProposal(
            type="opensoma.mentoring.apply",
            label=f"멘토링 신청: {detail.get('title', '?')}",
            payload={
                "mentoring_id": mentoring_id,
                "title": detail.get("title"),
                "session_date": detail.get("sessionDate"),
                "session_time": detail.get("sessionTime"),
                "venue": detail.get("venue"),
                "current_status": status,
                "attendees": detail.get("attendees"),
            },
        )

    result = opensoma.mentoring_apply(session_id, mentoring_id)
    application_service.invalidate(db, soma_user_id)
    return ActionResult(
        type="opensoma.mentoring.apply",
        status="success",
        message=f"신청 완료: {result.get('title', detail.get('title', '?'))}",
        payload={
            "apply_sn": result.get("apply_sn"),
            "qustnr_sn": result.get("qustnr_sn"),
            "mentoring_id": result.get("mentoring_id", mentoring_id),
            "applied_at": result.get("applied_at"),
            "application_status": result.get("application_status"),
            "approval_status": result.get("approval_status"),
        },
    )


def cancel(
    db: Session,
    opensoma: OpenSomaClient,
    session_id: str,
    soma_user_id: str,
    apply_sn: int,
    qustnr_sn: int,
    *,
    confirmed: bool = False,
) -> ActionProposal | ActionResult:
    """1차(confirmed=False): ActionProposal 반환.
    2차(confirmed=True):     sidecar cancel → applications 캐시 무효화.
    """
    if not confirmed:
        return ActionProposal(
            type="opensoma.mentoring.cancel",
            label=f"멘토링 신청 취소 (apply_sn={apply_sn})",
            payload={
                "apply_sn": apply_sn,
                "qustnr_sn": qustnr_sn,
            },
        )

    opensoma.mentoring_cancel(session_id, apply_sn=apply_sn, qustnr_sn=qustnr_sn)
    application_service.invalidate(db, soma_user_id)
    return ActionResult(
        type="opensoma.mentoring.cancel",
        status="success",
        message="신청 취소 완료",
        payload={"apply_sn": apply_sn, "qustnr_sn": qustnr_sn},
    )
