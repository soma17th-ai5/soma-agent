"""synthesizer 노드. SPEC §5.4, §6.1, §6.2.

ToolResult[] → ChatMessage 변환.
- LLM은 *요약문 생성*에만 사용. 사실 데이터는 ToolResult를 그대로 ChatMessage에 옮긴다.
- Source dedup, ActionProposal 분리, UI 블록 매핑.
- 모든 결과가 failed면 사용자에게 일시적 장애를 알리는 답변.
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass

from app.adapters.solar_chat_client import SolarChatClient, SolarChatError
from app.agent.prompts import SYNTHESIZER_SYSTEM_PROMPT
from app.domain.contracts.action import ActionProposal
from app.domain.contracts.chat import ChatMessage, ChatUIBlock
from app.domain.contracts.source import Source
from app.domain.contracts.tool_result import ToolResult, ToolStatus

log = logging.getLogger("app.agent.synthesizer")


@dataclass(frozen=True)
class SynthesisInput:
    user_message: str
    results: list[ToolResult]
    direct_answer_from_router: str | None = None
    truncated: bool = False
    trace_id: str | None = None


def _aggregate_status(results: list[ToolResult], truncated: bool) -> ToolStatus:
    if truncated:
        return "partial"
    if not results:
        return "success"  # 직접 답변(라우터가 tool 안 부른 경우)
    statuses = {r.status for r in results}
    if statuses == {"failed"}:
        return "failed"
    if "needs_confirmation" in statuses:
        return "needs_confirmation"
    if "failed" in statuses or "partial" in statuses:
        return "partial"
    return "success"


def _dedup_sources(results: list[ToolResult]) -> list[Source]:
    seen: dict[tuple[str, str], Source] = {}
    for r in results:
        for src in r.sources:
            key = (src.type, src.id or src.title)
            if key in seen:
                continue
            seen[key] = src
    return list(seen.values())


def _collect_actions(results: list[ToolResult]) -> list[ActionProposal]:
    """needs_confirmation ToolResult의 ActionProposal만 사용자에 노출 (SPEC §5.4)."""
    proposals: list[ActionProposal] = []
    for r in results:
        if r.status == "needs_confirmation" and isinstance(r.action, ActionProposal):
            proposals.append(r.action)
    return proposals


def _build_ui_blocks(results: list[ToolResult], sources: list[Source]) -> list[ChatUIBlock]:
    blocks: list[ChatUIBlock] = []
    if sources:
        blocks.append(
            ChatUIBlock(type="source_list", title="출처", items=[s.model_dump() for s in sources])
        )
    for r in results:
        if r.status != "success":
            continue
        if r.tool == "opensoma.mentoring.list" and r.data:
            blocks.append(ChatUIBlock(type="mentoring_cards", title="멘토링", items=list(r.data)))
        elif r.tool == "opensoma.notice.get" and r.data:
            blocks.append(ChatUIBlock(type="notice_list", title="공지", items=[r.data]))
    return blocks


async def _llm_summary(
    *,
    user_message: str,
    results: list[ToolResult],
    chat_client: SolarChatClient | None,
) -> str | None:
    if chat_client is None:
        return None
    facts = [
        {
            "tool": r.tool,
            "status": r.status,
            "data": r.data,
            "sources": [s.model_dump() for s in r.sources],
        }
        for r in results
    ]
    messages = [
        {"role": "system", "content": SYNTHESIZER_SYSTEM_PROMPT},
        {"role": "user", "content": user_message},
        {
            "role": "tool",
            "tool_call_id": "facts",
            "content": str(facts),
        },
    ]
    try:
        response = await asyncio.to_thread(chat_client.chat, messages)
        return response.content
    except SolarChatError as e:
        log.warning("synthesizer.llm_failed status=%s message=%s", e.status, e.message)
        return None


def _fallback_answer(results: list[ToolResult], truncated: bool) -> str:
    if truncated:
        return "한 번에 처리할 수 있는 도구 수가 초과되어 일부만 처리했습니다."
    if not results:
        return "어떤 작업을 도와드릴까요?"
    if all(r.status == "failed" for r in results):
        return "일시적인 오류로 정보를 가져오지 못했습니다. 잠시 후 다시 시도해주세요."
    successes = [r for r in results if r.status == "success"]
    if successes:
        return f"{len(successes)}개의 결과를 가져왔습니다. 자세한 내용은 카드를 확인해주세요."
    return "처리 결과를 확인해주세요."


async def synthesize(
    payload: SynthesisInput,
    *,
    chat_client: SolarChatClient | None = None,
) -> ChatMessage:
    status = _aggregate_status(payload.results, payload.truncated)
    sources = _dedup_sources(payload.results)
    actions = _collect_actions(payload.results)
    ui = _build_ui_blocks(payload.results, sources)

    if payload.direct_answer_from_router and not payload.results:
        # router가 tool 없이 바로 답변한 경우 — 그대로 사용.
        answer = payload.direct_answer_from_router
    else:
        answer = await _llm_summary(
            user_message=payload.user_message,
            results=payload.results,
            chat_client=chat_client,
        ) or _fallback_answer(payload.results, payload.truncated)

    return ChatMessage(
        answer=answer,
        status=status,
        sources=sources,
        ui=ui,
        actions=actions,
        trace_id=payload.trace_id or uuid.uuid4().hex,
    )
