"""SPEC §6.1, §6.2 contract 모델 직렬화/필수 필드 검증."""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.domain.contracts.action import ActionProposal
from app.domain.contracts.chat import ChatMessage, ChatUIBlock
from app.domain.contracts.source import Source
from app.domain.contracts.tool_result import (
    Artifact,
    ToolError,
    ToolResult,
)


class TestSource:
    def test_should_serializeRequiredFields_when_minimalInputGiven(self) -> None:
        src = Source(type="notice", title="공지 제목", official=True)
        dumped = src.model_dump()

        assert dumped["type"] == "notice"
        assert dumped["title"] == "공지 제목"
        assert dumped["official"] is True
        # 선택 필드 기본값
        assert dumped["id"] is None
        assert dumped["url"] is None

    def test_should_rejectUnknownType_when_invalidSourceType(self) -> None:
        with pytest.raises(ValidationError):
            Source(type="bogus", title="x", official=True)  # type: ignore[arg-type]


class TestToolResult:
    def test_should_acceptSpecDomains_when_validDomain(self) -> None:
        for domain in ("opensoma", "rag", "webex", "calendar", "system"):
            ToolResult(
                tool=f"{domain}.x",
                domain=domain,  # type: ignore[arg-type]
                operation="x",
                status="success",
            )

    def test_should_rejectUnknownDomain_when_invalidDomain(self) -> None:
        with pytest.raises(ValidationError):
            ToolResult(
                tool="x.y",
                domain="knowledge",  # type: ignore[arg-type]
                operation="y",
                status="success",
            )

    def test_should_carryArtifactsAndError_when_failedToolStatus(self) -> None:
        result = ToolResult(
            tool="opensoma.mentoring.list",
            domain="opensoma",
            operation="list",
            status="failed",
            artifacts=[Artifact(type="markdown", content="외부 호출 실패")],
            error=ToolError(code="UPSTREAM_UNAVAILABLE", message="503", recoverable=True),
        )

        assert result.status == "failed"
        assert result.artifacts[0].content == "외부 호출 실패"
        assert result.error is not None
        assert result.error.recoverable is True


class TestChatMessage:
    def test_should_requireTraceId_when_constructing(self) -> None:
        # SPEC §6.2: trace_id는 required.
        with pytest.raises(ValidationError):
            ChatMessage(answer="hello", status="success")  # type: ignore[call-arg]

    def test_should_acceptOnlyActionProposals_when_actionsListGiven(self) -> None:
        proposal = ActionProposal(
            type="MENTORING_APPLY",
            label="신청",
            payload={"mentoringId": "M-1"},
            requiresConfirmation=True,
        )
        msg = ChatMessage(
            answer="신청하시겠어요?",
            status="needs_confirmation",
            actions=[proposal],
            ui=[ChatUIBlock(type="mentoring_cards", title="추천", items=[])],
            trace_id="trace-abc",
        )

        assert len(msg.actions) == 1
        assert msg.actions[0].type == "MENTORING_APPLY"
        assert msg.ui[0].type == "mentoring_cards"
