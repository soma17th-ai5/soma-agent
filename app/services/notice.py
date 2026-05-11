"""공지 동기화 서비스. SPEC §7.2.

흐름:
  opensoma.notice.list (운영자 세션) → content_hash 비교 →
  변경 또는 신규만 detail 조회 → MySQL upsert →
  Qdrant 재인덱싱 (source_type=NOTICE, official=True)
"""
from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from bs4 import BeautifulSoup
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.adapters.opensoma_client import OpenSomaClient
from app.adapters.qdrant_client import QdrantAdapter
from app.adapters.solar_client import SolarClient
from app.domain.contracts.knowledge import KnowledgeSourceType
from app.domain.models.notice import Notice
from app.services.rag_indexer import index_chunks

log = logging.getLogger("app.services.notice")


@dataclass
class NoticeSyncStats:
    fetched: int = 0
    inserted: int = 0
    updated: int = 0
    skipped: int = 0
    indexed: int = 0
    errors: list[str] = field(default_factory=list)


def _compute_content_hash(*, title: str, author: str | None, created_at_text: str | None) -> str:
    """목록 응답 필드 기반 단순 해시. 본문 변경 감지는 detail 조회 후 별도 처리."""
    raw = f"{title}{author or ''}{created_at_text or ''}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _parse_posted_at(created_at_text: str | None) -> datetime | None:
    """공지 createdAt 포맷 'YYYY.MM.DD HH:MM:SS' (점 구분, KST 추정)."""
    if not created_at_text:
        return None
    try:
        return datetime.strptime(created_at_text.strip(), "%Y.%m.%d %H:%M:%S")
    except ValueError:
        return None


def _strip_html(html: str | None) -> str:
    if not html:
        return ""
    text = BeautifulSoup(html, "html.parser").get_text(separator="\n")
    # 연속 공백·개행 정리
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def run_sync(
    db: Session,
    opensoma: OpenSomaClient,
    session_id: str,
    *,
    qdrant: QdrantAdapter | None = None,
    solar: SolarClient | None = None,
    max_pages: int = 50,
) -> NoticeSyncStats:
    """운영자 세션으로 공지 목록 페이지를 순회. 변경분만 detail 조회·인덱싱.

    qdrant/solar 가 None 이면 RDB 동기화만, 인덱싱은 skip (테스트 격리용).
    """
    stats = NoticeSyncStats()

    for page in range(1, max_pages + 1):
        payload = opensoma.notice_list(session_id, page=page)
        items = payload.get("items", []) or []
        pagination = payload.get("pagination") or {}

        if not items:
            break

        for item in items:
            stats.fetched += 1
            try:
                _process_item(item, db, opensoma, session_id, qdrant, solar, stats)
            except Exception as exc:
                log.exception("notice.sync_item_failed notice_id=%s", item.get("id"))
                stats.errors.append(f"notice_id={item.get('id')}: {exc}")

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
    stats: NoticeSyncStats,
) -> None:
    notice_id = int(item["id"])
    title = item["title"]
    author = item.get("author")
    created_at_text = item.get("createdAt")
    new_hash = _compute_content_hash(
        title=title, author=author, created_at_text=created_at_text
    )

    existing = db.execute(
        select(Notice).where(Notice.notice_id == notice_id)
    ).scalar_one_or_none()

    if existing and existing.content_hash == new_hash:
        stats.skipped += 1
        return

    detail = opensoma.notice_get(session_id, notice_id)
    content_html = detail.get("content")
    content_text = _strip_html(content_html)

    if existing is None:
        notice = Notice(
            notice_id=notice_id,
            title=title,
            author=author,
            created_at_text=created_at_text,
            posted_at=_parse_posted_at(created_at_text),
            content_html=content_html,
            content_text=content_text,
            content_hash=new_hash,
            is_active=True,
        )
        db.add(notice)
        stats.inserted += 1
    else:
        existing.title = title
        existing.author = author
        existing.created_at_text = created_at_text
        existing.posted_at = _parse_posted_at(created_at_text)
        existing.content_html = content_html
        existing.content_text = content_text
        existing.content_hash = new_hash
        existing.is_active = True
        stats.updated += 1

    if qdrant is not None and solar is not None and content_text:
        index_chunks(
            qdrant,
            solar,
            source_type=KnowledgeSourceType.NOTICE,
            source_id=str(notice_id),
            title=title,
            texts=[content_text],
            official=True,
            source_url=item.get("url"),
            created_at=_parse_posted_at(created_at_text),
        )
        stats.indexed += 1
