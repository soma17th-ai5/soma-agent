"""공지 첨부 파일 처리 서비스.

OpenSoma 공지 상세(NoticeDetail.content)는 HTML 문자열로 첨부 anchor를 포함한다.
실측(#8 PoC)에 따르면 첨부는 다음 패턴 중 하나로 등장:

- `<a href="https://www.swmaestro.ai/sw/.../download.do?...">파일명.pdf</a>`
- `<a href="...filename.pdf">filename.pdf</a>` (확장자 직접 포함)

이 모듈은:
1. content HTML에서 첨부 anchor를 추출 (`parse_attachments`).
2. PDF 바이트에서 텍스트를 추출 (`extract_pdf_text`).
3. 위 두 단계를 묶어 sidecar 경유 다운로드 + RAG 인덱싱까지 수행
   (`process_notice_attachments`).

설계 메모:
- 다운로드 함수는 의존성 주입(`download`). 운영에서는 sidecar의
  `/notice/:id/attachment` 엔드포인트를 호출하고, 테스트에서는 mock 사용.
- 텍스트 추출 실패는 치명적이지 않다(이미지 PDF, 손상 파일 등) → 로그 + extracted_text=None.
- chunking은 `rag_indexer.chunk_text` 재사용. 각 첨부는 단일 source_id 컬럼에
  `f"{notice_id}::{idx}"` 형태로 저장 → notice 본문(NOTICE)과 첨부(NOTICE_PDF)가 분리.

SPEC §3.1 notice_attachments / §3.2 NOTICE_PDF / §12 미해결 #2.
"""
from __future__ import annotations

import io
import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING

from bs4 import BeautifulSoup

from app.domain.contracts.knowledge import KnowledgeSourceType
from app.services.rag_indexer import chunk_text, index_chunks

if TYPE_CHECKING:
    from app.adapters.qdrant_client import QdrantAdapter
    from app.adapters.solar_client import SolarClient

logger = logging.getLogger(__name__)


# 첨부 후보로 인식할 파일 확장자. 소문자 비교.
SUPPORTED_EXTENSIONS = (".pdf", ".hwp", ".hwpx", ".docx", ".doc", ".xlsx", ".xls", ".pptx", ".ppt", ".zip", ".txt")

# OpenSoma 첨부 다운로드 URL 시그니처. 확장자가 없는 다운로드 핸들러 대응.
DOWNLOAD_URL_MARKERS = ("download.do", "fileDownload", "/download/", "filedownload.do")


@dataclass(frozen=True)
class AttachmentRef:
    """공지 본문에서 추출된 첨부 anchor.

    `file_type`은 URL 확장자에서 유추 (소문자, 점 없음). 추론 실패 시 None.
    """

    href: str
    name: str
    file_type: str | None


@dataclass(frozen=True)
class ProcessedAttachment:
    """첨부 1건 처리 결과. notice_attachments 행 + 인덱싱 메타.

    Caller는 이 구조를 보고 DB upsert(`notice_attachments`)를 수행한다.
    `chunk_count == 0`이면 인덱싱이 skip된 것 (텍스트 추출 실패 또는 비-PDF).
    """

    ref: AttachmentRef
    extracted_text: str | None
    extracted_at: datetime | None
    chunk_count: int


def _infer_file_type(href: str, name: str) -> str | None:
    """URL 또는 파일명에서 확장자를 추출. 둘 다 없으면 None.

    download.do 형태는 보통 query에 fileNm이 있어 거기서 우선 추출.
    """
    candidates = [name, href]
    for raw in candidates:
        if not raw:
            continue
        lower = raw.lower()
        # 점 이후 마지막 토큰을 확장자 후보로 사용. 길이 5자 이하만 허용해
        # 도메인 일부가 잘못 매치되는 케이스(예: .swmaestro)를 방지.
        if "." not in lower:
            continue
        ext = lower.rsplit(".", 1)[-1]
        # 쿼리스트링·앵커가 붙은 경우 제거.
        ext = ext.split("?", 1)[0].split("#", 1)[0]
        if 1 <= len(ext) <= 5 and ext.isalpha():
            return ext
    return None


def _looks_like_attachment(href: str, name: str) -> bool:
    """anchor 가 첨부 다운로드인지 판별.

    - 알려진 확장자가 URL 또는 텍스트에 포함되거나
    - URL 에 download 마커가 있음
    """
    if not href:
        return False
    lower_href = href.lower()
    lower_name = name.lower() if name else ""
    if any(marker in lower_href for marker in DOWNLOAD_URL_MARKERS):
        return True
    return any(ext in lower_href or ext in lower_name for ext in SUPPORTED_EXTENSIONS)


def parse_attachments(content_html: str) -> list[AttachmentRef]:
    """공지 content HTML에서 첨부 anchor를 추출.

    - `<a>` 태그만 검사. `<a href="...">텍스트</a>` 형태.
    - href가 없거나 빈 anchor는 무시.
    - file_name은 anchor 텍스트 → 비어있으면 href 마지막 segment에서 추론.
    - 빈/공백 입력 시 빈 리스트.
    """
    if not content_html or not content_html.strip():
        return []

    soup = BeautifulSoup(content_html, "html.parser")
    refs: list[AttachmentRef] = []
    seen_hrefs: set[str] = set()

    for anchor in soup.find_all("a"):
        href = (anchor.get("href") or "").strip()
        if not href:
            continue
        # 동일 URL이 여러 번 등장하는 경우 dedupe (앵커 텍스트 변종 무시).
        if href in seen_hrefs:
            continue

        # 텍스트는 visible 텍스트만 사용. 공백 정규화.
        name = anchor.get_text(strip=True)
        if not name:
            # 이미지 alt 등 fallback. 마지막 path segment에서 유추.
            tail = href.rsplit("/", 1)[-1]
            name = tail.split("?", 1)[0] or href

        if not _looks_like_attachment(href, name):
            continue

        seen_hrefs.add(href)
        refs.append(
            AttachmentRef(
                href=href,
                name=name,
                file_type=_infer_file_type(href, name),
            )
        )

    return refs


def extract_pdf_text(content: bytes) -> str:
    """PDF 바이트에서 추출 가능한 텍스트를 평문으로 반환.

    - 페이지 사이는 줄바꿈 2개로 구분.
    - 추출 실패(스캔본·암호화·손상) 시 빈 문자열 반환 — 호출자는 chunk_count == 0 으로 처리.
    - pypdf는 import 시 무거운 부수 효과가 없어 함수 내부 import 안 함 (모듈 레벨).
    """
    if not content:
        return ""

    # pypdf는 일부 환경에서 import 비용이 있어 lazy 로드.
    from pypdf import PdfReader

    try:
        reader = PdfReader(io.BytesIO(content))
    except Exception:
        logger.warning("pypdf failed to open document", exc_info=True)
        return ""

    parts: list[str] = []
    for page in reader.pages:
        try:
            text = page.extract_text() or ""
        except Exception:
            logger.warning("pypdf failed to extract a page", exc_info=True)
            text = ""
        text = text.strip()
        if text:
            parts.append(text)

    return "\n\n".join(parts)


def process_notice_attachments(
    notice_id: int | str,
    content_html: str,
    qdrant: QdrantAdapter,
    solar: SolarClient,
    *,
    download: Callable[[AttachmentRef], bytes],
    title: str,
    source_url: str | None = None,
    created_at: datetime | None = None,
    official: bool = True,
    now: Callable[[], datetime] = datetime.utcnow,
) -> list[ProcessedAttachment]:
    """공지 본문 HTML을 받아 첨부를 다운로드·추출·인덱싱.

    Args:
        notice_id: 우리 시스템의 notice_id (BIGINT). source_id 구성에 사용.
        content_html: NoticeDetail.content (HTML 원본).
        download: AttachmentRef → bytes. sidecar 경유 다운로드 함수 주입.
            테스트에서는 mock; 운영에서는 OpenSomaClient 메소드.
        title: notice title — RAG 페이로드에 사용.
        source_url: notice 상세 URL — RAG payload `source_url`. 첨부 자체 URL은 별도.
        official: NOTICE_PDF는 OpenSoma 출처 → 기본 True. SPEC §3.2 official 필드.
        now: 테스트 주입용 — 처리 시각 기록.

    Returns:
        첨부별 처리 결과. caller는 이를 사용해 `notice_attachments` upsert 수행.
        다운로드 또는 텍스트 추출 실패 시 `extracted_text=None`, `chunk_count=0`.
    """
    refs = parse_attachments(content_html)
    if not refs:
        return []

    notice_key = str(notice_id)
    results: list[ProcessedAttachment] = []
    for idx, ref in enumerate(refs):
        if (ref.file_type or "").lower() != "pdf":
            # PDF 외 형식(hwp, zip 등)은 v1에서 인덱싱 skip.
            # extracted_text는 None — caller가 notice_attachments 행만 기록.
            results.append(
                ProcessedAttachment(
                    ref=ref, extracted_text=None, extracted_at=None, chunk_count=0
                )
            )
            continue

        try:
            content = download(ref)
        except Exception:
            logger.warning(
                "attachment download failed: notice=%s href=%s", notice_key, ref.href, exc_info=True
            )
            results.append(
                ProcessedAttachment(
                    ref=ref, extracted_text=None, extracted_at=None, chunk_count=0
                )
            )
            continue

        text = extract_pdf_text(content)
        extracted_at = now() if text else None
        chunks = chunk_text(text) if text else []
        chunk_count = 0
        if chunks:
            source_id = f"{notice_key}::{idx}"
            chunk_count = index_chunks(
                qdrant,
                solar,
                KnowledgeSourceType.NOTICE_PDF,
                source_id=source_id,
                title=f"{title} / {ref.name}",
                texts=chunks,
                official=official,
                source_url=source_url,
                created_at=created_at,
                source_ref=ref.href,
            )

        results.append(
            ProcessedAttachment(
                ref=ref,
                extracted_text=text or None,
                extracted_at=extracted_at,
                chunk_count=chunk_count,
            )
        )

    return results
