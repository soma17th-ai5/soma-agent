"""ToolResult/ChatMessage 가 참조하는 출처 메타데이터. SPEC §6.1."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

SourceType = Literal[
    "notice",
    "notice_pdf",
    "mentoring",
    "application",
    "webex_message",
    "webex_summary",
    "calendar",
    "other",
]


class Source(BaseModel):
    id: str | None = None
    type: SourceType
    title: str
    url: str | None = None
    created_at: str | None = None
    collected_at: str | None = None
    official: bool
    raw_ref: str | None = None
