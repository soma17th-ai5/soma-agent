"""공지 첨부 anchor 파서 단위 테스트.

`parse_attachments`는 순수 함수 (BeautifulSoup만 사용) → 직접 검증.
"""
from __future__ import annotations

import pytest

from app.services.notice_attachment import AttachmentRef, parse_attachments


def test_should_returnEmpty_when_contentIsBlank() -> None:
    assert parse_attachments("") == []
    assert parse_attachments("   \n\t") == []


def test_should_returnEmpty_when_noAnchorMatchesAttachmentPattern() -> None:
    # 단순 본문, 외부 링크는 첨부가 아님.
    html = '<p>안녕하세요</p><a href="https://example.com/blog">참고</a>'

    assert parse_attachments(html) == []


def test_should_extractPdfAnchor_when_extensionInHref() -> None:
    html = '<a href="https://www.swmaestro.ai/sw/files/notice-2025.pdf">2025 공지.pdf</a>'

    refs = parse_attachments(html)

    assert refs == [
        AttachmentRef(
            href="https://www.swmaestro.ai/sw/files/notice-2025.pdf",
            name="2025 공지.pdf",
            file_type="pdf",
        )
    ]


def test_should_extractAnchor_when_downloadDoMarkerPresent() -> None:
    # OpenSoma 다운로드 핸들러는 보통 download.do?atchFileId=... 형태.
    html = (
        '<p>첨부:</p>'
        '<a href="https://www.swmaestro.ai/sw/cmm/fms/FileDown.do?atchFileId=ABC&fileSn=0">'
        '안내문.pdf</a>'
    )

    refs = parse_attachments(html)

    assert len(refs) == 1
    assert refs[0].name == "안내문.pdf"
    assert "FileDown.do" in refs[0].href.lower() or "filedown" in refs[0].href.lower()
    # 파일명 안에 .pdf 가 있어 file_type 추론 성공.
    assert refs[0].file_type == "pdf"


def test_should_dedupeByHref_when_sameUrlAppearsTwice() -> None:
    html = (
        '<a href="https://www.swmaestro.ai/sw/file.pdf">file.pdf</a>'
        '<a href="https://www.swmaestro.ai/sw/file.pdf">동일첨부</a>'
    )

    refs = parse_attachments(html)

    # 같은 href 는 첫 anchor만 채택.
    assert len(refs) == 1
    assert refs[0].name == "file.pdf"


def test_should_classifyFileType_forVariousExtensions() -> None:
    html = (
        '<a href="https://www.swmaestro.ai/sw/x.hwp">계획.hwp</a>'
        '<a href="https://www.swmaestro.ai/sw/y.docx">설명.docx</a>'
        '<a href="https://www.swmaestro.ai/sw/z.zip">자료.zip</a>'
    )

    refs = parse_attachments(html)

    types = [r.file_type for r in refs]
    assert types == ["hwp", "docx", "zip"]


def test_should_skipAnchorWithoutHref() -> None:
    html = '<a>이름만 있음</a><a href="">빈 href</a>'

    assert parse_attachments(html) == []


def test_should_fallbackName_when_anchorTextEmpty() -> None:
    # 이미지 anchor 등 텍스트가 비어있는 경우 path tail을 이름으로 사용.
    html = '<a href="https://www.swmaestro.ai/sw/upload/file-123.pdf"></a>'

    refs = parse_attachments(html)

    assert len(refs) == 1
    assert refs[0].name == "file-123.pdf"
    assert refs[0].file_type == "pdf"


@pytest.mark.parametrize("ext", ["pdf", "hwp", "hwpx", "docx", "xlsx", "pptx", "zip"])
def test_should_recognizeSupportedExtensions(ext: str) -> None:
    html = f'<a href="https://www.swmaestro.ai/sw/x.{ext}">file.{ext}</a>'

    refs = parse_attachments(html)

    assert len(refs) == 1
    assert refs[0].file_type == ext
