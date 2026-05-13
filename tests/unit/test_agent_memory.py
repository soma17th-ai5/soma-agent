"""AgentMemory deque 동작 검증."""
from __future__ import annotations

import pytest

from app.agent.memory import AgentMemory, ChatTurn


def test_should_returnEmpty_when_sessionUnknown() -> None:
    mem = AgentMemory()
    assert mem.recent("missing") == []
    assert len(mem) == 0


def test_should_appendAndReturnTurns_when_sessionExists() -> None:
    mem = AgentMemory()
    mem.append("s-1", ChatTurn(user_message="hi", assistant_message="hello"))
    mem.append("s-1", ChatTurn(user_message="bye", assistant_message="see you"))

    turns = mem.recent("s-1")
    assert len(turns) == 2
    assert turns[0].user_message == "hi"
    assert turns[1].user_message == "bye"


def test_should_dropOldestTurn_when_overMaxTurns() -> None:
    mem = AgentMemory(max_turns=3)
    for i in range(5):
        mem.append("s-1", ChatTurn(user_message=f"u{i}", assistant_message=f"a{i}"))

    turns = mem.recent("s-1")
    assert [t.user_message for t in turns] == ["u2", "u3", "u4"]


def test_should_returnLastN_when_recentNGiven() -> None:
    mem = AgentMemory(max_turns=10)
    for i in range(5):
        mem.append("s-1", ChatTurn(user_message=f"u{i}", assistant_message=f"a{i}"))

    turns = mem.recent("s-1", n=2)
    assert [t.user_message for t in turns] == ["u3", "u4"]


def test_should_isolateSessions_when_multipleSessionIds() -> None:
    mem = AgentMemory()
    mem.append("a", ChatTurn(user_message="a-msg", assistant_message="a-resp"))
    mem.append("b", ChatTurn(user_message="b-msg", assistant_message="b-resp"))

    assert [t.user_message for t in mem.recent("a")] == ["a-msg"]
    assert [t.user_message for t in mem.recent("b")] == ["b-msg"]


def test_should_clearSession_when_clearCalled() -> None:
    mem = AgentMemory()
    mem.append("s", ChatTurn(user_message="x", assistant_message="y"))
    mem.clear("s")
    assert mem.recent("s") == []


def test_should_raise_when_maxTurnsZeroOrNegative() -> None:
    with pytest.raises(ValueError):
        AgentMemory(max_turns=0)
