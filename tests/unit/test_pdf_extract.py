"""PDF 텍스트 추출 단위 테스트.

외부 PDF 파일 fixture 없이 *최소 PDF* 바이트를 인-소스로 구성해 격리.
- 정상 PDF → text 추출 성공.
- 손상된 PDF / 빈 입력 → 빈 문자열 (예외 던지지 않음).
"""
from __future__ import annotations

from app.services.notice_attachment import extract_pdf_text

# 한 페이지에 "Hello SOMA" 텍스트만 있는 최소 PDF 1.4.
# pypdf가 읽을 수 있는 단순 컨텐츠 스트림(BT...ET, F1 폰트, 1줄)으로 손수 구성.
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


def test_should_returnEmpty_when_emptyBytes() -> None:
    assert extract_pdf_text(b"") == ""


def test_should_returnEmpty_when_inputIsNotValidPdf() -> None:
    # 잘못된 PDF는 예외 대신 빈 문자열로 처리 — 호출부에서 chunk_count=0으로 흘러간다.
    assert extract_pdf_text(b"not a pdf at all") == ""


def test_should_extractText_when_minimalPdfProvided() -> None:
    text = extract_pdf_text(_MINIMAL_PDF)

    assert "Hello SOMA" in text


def test_should_returnNonEmpty_when_pdfHasText() -> None:
    # 결과가 strip 후에도 의미 있는지 sanity check.
    text = extract_pdf_text(_MINIMAL_PDF)

    assert text.strip() != ""
