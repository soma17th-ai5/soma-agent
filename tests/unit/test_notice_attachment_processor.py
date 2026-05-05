"""notice_attachment.process_notice_attachments 통합 단위 테스트.

다운로드는 mock callable, qdrant는 in-memory, solar는 MagicMock.
- PDF 첨부: 다운로드 → 텍스트 추출 → 인덱싱 (chunk_count > 0).
- 비-PDF 첨부 (hwp/zip): 인덱싱 skip, 결과 행만 기록.
- 다운로드 실패: extracted_text=None, chunk_count=0 (예외 안 던짐).
- 첨부 없음: 빈 결과.
"""
from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest
from qdrant_client import QdrantClient

from app.adapters.qdrant_client import QdrantAdapter
from app.services.notice_attachment import (
    AttachmentRef,
    process_notice_attachments,
)

TEST_VECTOR_SIZE = 8


# 한 페이지 "Hello SOMA" 만 들어있는 최소 PDF (test_pdf_extract와 동일 페이로드).
_MINIMAL_PDF = (
    b"%PDF-1.4\n"
    b"1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
    b"2 0 obj<</Type/Pages/Count 1/Kids[3 0 R]>>endobj\n"
    b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 612 792]/Contents 4 0 R"
    b"/Resources<</Font<</F1 5 0 R>>>>>>endobj\n"
    b"4 0 obj<</Length 44>>stream\n"
    b"BT\n/F1 24 Tf\n100 700 Td\n(Hello SOMA) Tj\nET\n"
    b"endstream\nendobj\n"
    b"5 0 obj<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>endobj\n"
    b"xref\n0 6\n0000000000 65535 f \n"
    b"0000000009 00000 n \n0000000054 00000 n \n0000000099 00000 n \n"
    b"0000000188 00000 n \n0000000280 00000 n \n"
    b"trailer<</Size 6/Root 1 0 R>>\nstartxref\n338\n%%EOF\n"
)


@pytest.fixture
def qdrant() -> QdrantAdapter:
    raw = QdrantClient(":memory:")
    adapter = QdrantAdapter(
        client=raw, collection="rag_test", vector_size=TEST_VECTOR_SIZE
    )
    adapter.ensure_collection()
    return adapter


@pytest.fixture
def solar_mock() -> MagicMock:
    mock = MagicMock()
    mock.embed_passages.side_effect = lambda texts: [
        [float(i) + 0.01 * j for j in range(TEST_VECTOR_SIZE)]
        for i, _ in enumerate(texts)
    ]
    return mock


def test_should_returnEmptyList_when_contentHasNoAttachments(
    qdrant: QdrantAdapter, solar_mock: MagicMock
) -> None:
    download_calls: list[AttachmentRef] = []

    results = process_notice_attachments(
        notice_id=1,
        content_html="<p>본문만 있음</p>",
        qdrant=qdrant,
        solar=solar_mock,
        download=lambda ref: download_calls.append(ref) or b"",
        title="제목",
    )

    assert results == []
    assert download_calls == []
    solar_mock.embed_passages.assert_not_called()


def test_should_indexPdf_when_pdfAttachmentProvided(
    qdrant: QdrantAdapter, solar_mock: MagicMock
) -> None:
    html = '<a href="https://www.swmaestro.ai/sw/notice.pdf">notice.pdf</a>'
    download_mock = MagicMock(return_value=_MINIMAL_PDF)

    results = process_notice_attachments(
        notice_id=42,
        content_html=html,
        qdrant=qdrant,
        solar=solar_mock,
        download=download_mock,
        title="공지 제목",
        source_url="https://www.swmaestro.ai/sw/notice/view.do?id=42",
        created_at=datetime(2026, 5, 1, tzinfo=UTC),
    )

    assert len(results) == 1
    processed = results[0]
    assert processed.ref.file_type == "pdf"
    assert processed.extracted_text is not None
    assert "Hello SOMA" in processed.extracted_text
    assert processed.extracted_at is not None
    assert processed.chunk_count == 1
    download_mock.assert_called_once()

    # Qdrant에 NOTICE_PDF 페이로드로 적재되었는지 확인.
    hits = qdrant.search([0.0] * TEST_VECTOR_SIZE, k=10)
    payloads = [h.payload for h in hits if h.payload]
    assert len(payloads) == 1
    payload = payloads[0]
    assert payload["source_type"] == "NOTICE_PDF"
    assert payload["source_id"] == "42::0"
    assert payload["official"] is True
    # source_ref에 첨부 URL이 보존되어야 — DB 행과 cross-link 가능.
    assert payload["source_ref"] == "https://www.swmaestro.ai/sw/notice.pdf"


def test_should_skipIndexing_when_attachmentIsNotPdf(
    qdrant: QdrantAdapter, solar_mock: MagicMock
) -> None:
    html = '<a href="https://www.swmaestro.ai/sw/x.hwp">계획.hwp</a>'
    download_mock = MagicMock()

    results = process_notice_attachments(
        notice_id=1,
        content_html=html,
        qdrant=qdrant,
        solar=solar_mock,
        download=download_mock,
        title="제목",
    )

    # hwp는 v1에서 인덱싱 skip.
    assert len(results) == 1
    assert results[0].chunk_count == 0
    assert results[0].extracted_text is None
    download_mock.assert_not_called()
    solar_mock.embed_passages.assert_not_called()


def test_should_recordRowWithoutCrash_when_downloadRaises(
    qdrant: QdrantAdapter, solar_mock: MagicMock
) -> None:
    html = '<a href="https://www.swmaestro.ai/sw/notice.pdf">notice.pdf</a>'

    def boom(_ref: AttachmentRef) -> bytes:
        raise RuntimeError("download failed")

    results = process_notice_attachments(
        notice_id=1,
        content_html=html,
        qdrant=qdrant,
        solar=solar_mock,
        download=boom,
        title="제목",
    )

    assert len(results) == 1
    assert results[0].chunk_count == 0
    assert results[0].extracted_text is None
    solar_mock.embed_passages.assert_not_called()


def test_should_recordRowWithoutCrash_when_pdfTextExtractionFails(
    qdrant: QdrantAdapter, solar_mock: MagicMock
) -> None:
    # 잘못된 PDF 바이트는 extract_pdf_text에서 빈 문자열을 반환.
    html = '<a href="https://www.swmaestro.ai/sw/notice.pdf">notice.pdf</a>'
    download_mock = MagicMock(return_value=b"NOT A REAL PDF")

    results = process_notice_attachments(
        notice_id=1,
        content_html=html,
        qdrant=qdrant,
        solar=solar_mock,
        download=download_mock,
        title="제목",
    )

    assert len(results) == 1
    assert results[0].chunk_count == 0
    assert results[0].extracted_text is None
    solar_mock.embed_passages.assert_not_called()


def test_should_indexEachPdfWithUniqueSourceId_when_multipleAttachments(
    qdrant: QdrantAdapter, solar_mock: MagicMock
) -> None:
    html = (
        '<a href="https://www.swmaestro.ai/sw/a.pdf">a.pdf</a>'
        '<a href="https://www.swmaestro.ai/sw/b.pdf">b.pdf</a>'
    )
    download_mock = MagicMock(return_value=_MINIMAL_PDF)

    results = process_notice_attachments(
        notice_id=99,
        content_html=html,
        qdrant=qdrant,
        solar=solar_mock,
        download=download_mock,
        title="제목",
    )

    assert len(results) == 2
    assert all(r.chunk_count == 1 for r in results)

    hits = qdrant.search([0.0] * TEST_VECTOR_SIZE, k=10)
    source_ids = {h.payload["source_id"] for h in hits if h.payload}
    assert source_ids == {"99::0", "99::1"}
