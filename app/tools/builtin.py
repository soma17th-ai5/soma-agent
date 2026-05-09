"""기본 8개 tool을 등록한 ToolRegistry 팩토리.

Agent 그래프는 시작 시 `build_default_registry()`로 카탈로그를 만든다.
테스트는 자체 registry를 만들어 일부 tool만 등록할 수 있다.
"""
from __future__ import annotations

from app.tools.application import ApplicationHistoryTool
from app.tools.calendar import CalendarInviteCreateTool
from app.tools.knowledge import KnowledgeSearchTool
from app.tools.mentoring import (
    MentoringApplyTool,
    MentoringCancelTool,
    MentoringGetTool,
    MentoringListTool,
)
from app.tools.notice import NoticeGetTool
from app.tools.registry import ToolRegistry


def build_default_registry() -> ToolRegistry:
    reg = ToolRegistry()
    reg.register(KnowledgeSearchTool())
    reg.register(MentoringListTool())
    reg.register(MentoringGetTool())
    reg.register(MentoringApplyTool())
    reg.register(MentoringCancelTool())
    reg.register(ApplicationHistoryTool())
    reg.register(NoticeGetTool())
    reg.register(CalendarInviteCreateTool())
    return reg
