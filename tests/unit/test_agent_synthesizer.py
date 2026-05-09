"""synthesizer — ToolResult[] → ChatMessage 매핑 검증."""
from __future__ import annotations

import pytest

from app.agent.nodes.synthesizer import SynthesisInput, synthesize
from app.domain.contracts.action import ActionProposal
from app.domain.contracts.source import Source
from app.domain.contracts.tool_result import (
    Artifact,
    ToolError,
    ToolResult,
)


def _result(
    *,
    tool="x.y",
    domain="system",
    operation="y",
    status="success",
    sources=None,
    data=None,
    action=None,
):  # type: ignore[no-untyped-def]
    return ToolResult(
        tool=tool,
        domain=domain,
        operation=operation,
        status=status,
        sources=sources or [],
        data=data,
        action=action,
    )


@pytest.mark.asyncio
async def test_should_dedupSources_when_multipleResultsShareSourceId() -> None:
    src1 = Source(id="n-1", type="notice", title="공지 A", official=True)
    src2 = Source(id="n-1", type="notice", title="공지 A", official=True)  # dup
    src3 = Source(id="n-2", type="notice", title="공지 B", official=True)

    payload = SynthesisInput(
        user_message="공지",
        results=[_result(sources=[src1]), _result(sources=[src2, src3])],
    )
    msg = await synthesize(payload, chat_client=None)

    assert len(msg.sources) == 2
    titles = {s.title for s in msg.sources}
    assert titles == {"공지 A", "공지 B"}


@pytest.mark.asyncio
async def test_should_aggregateStatusFailed_when_allFailed() -> None:
    msg = await synthesize(
        SynthesisInput(
            user_message="x",
            results=[
                _result(status="failed"),
                _result(status="failed"),
            ],
        ),
        chat_client=None,
    )

    assert msg.status == "failed"


@pytest.mark.asyncio
async def test_should_aggregatePartial_when_truncated() -> None:
    msg = await synthesize(
        SynthesisInput(
            user_message="x",
            results=[_result(status="success")],
            truncated=True,
        ),
        chat_client=None,
    )

    assert msg.status == "partial"


@pytest.mark.asyncio
async def test_should_exposeOnlyActionProposals_when_needsConfirmation() -> None:
    proposal = ActionProposal(
        type="MENTORING_APPLY",
        label="신청",
        payload={"mentoringId": "M-1"},
        requiresConfirmation=True,
    )
    msg = await synthesize(
        SynthesisInput(
            user_message="신청해",
            results=[
                _result(status="needs_confirmation", action=proposal),
            ],
        ),
        chat_client=None,
    )

    assert len(msg.actions) == 1
    assert msg.actions[0].type == "MENTORING_APPLY"
    assert msg.status == "needs_confirmation"


@pytest.mark.asyncio
async def test_should_buildMentoringCardsBlock_when_listToolSucceeded() -> None:
    items = [{"id": 1, "title": "M-1"}]
    msg = await synthesize(
        SynthesisInput(
            user_message="멘토링 목록",
            results=[
                ToolResult(
                    tool="opensoma.mentoring.list",
                    domain="opensoma",
                    operation="list",
                    status="success",
                    data=items,
                    artifacts=[Artifact(type="list", items=items)],
                )
            ],
        ),
        chat_client=None,
    )

    block_types = [b.type for b in msg.ui]
    assert "mentoring_cards" in block_types


@pytest.mark.asyncio
async def test_should_useRouterDirectAnswer_when_noToolResults() -> None:
    msg = await synthesize(
        SynthesisInput(
            user_message="안녕",
            results=[],
            direct_answer_from_router="안녕하세요!",
        ),
        chat_client=None,
    )

    assert msg.answer == "안녕하세요!"
    assert msg.status == "success"


@pytest.mark.asyncio
async def test_should_returnFallback_when_chatClientUnavailable() -> None:
    msg = await synthesize(
        SynthesisInput(
            user_message="검색",
            results=[
                ToolResult(
                    tool="x", domain="system", operation="x", status="failed",
                    error=ToolError(code="X", message="boom"),
                )
            ],
        ),
        chat_client=None,
    )

    assert "다시 시도" in msg.answer
