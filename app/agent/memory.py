"""세션별 대화 메모리. SPEC §5.5.

`dict[session_id, deque[ChatTurn]]`로 최근 N턴(기본 10)만 유지. 서버 재시작 시 유실
허용. 동시성: 단일 프로세스 가정 (멀티 워커 시 외부 저장소로 교체 필요).
"""
from __future__ import annotations

from collections import deque
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime

DEFAULT_MAX_TURNS = 10


@dataclass(frozen=True)
class ChatTurn:
    """1턴 = (user 메시지, assistant 최종 응답).

    중간 ToolResult/UI 블록은 메모리에 담지 않는다 — 다음 턴 라우팅에 필요한 것은
    *대화 흐름*이지 *원천 데이터*가 아니므로. 후보 목록 같은 컨텍스트는 클라가 매
    요청에 재전송하는 책임을 진다 (SPEC §5.2).
    """

    user_message: str
    assistant_message: str
    created_at: datetime = field(default_factory=datetime.utcnow)


class AgentMemory:
    """세션별 ChatTurn 보관소.

    `append`/`recent`/`clear` 만 노출. 내부 자료구조 deque는 max_turns로 자동 제한.
    """

    def __init__(self, max_turns: int = DEFAULT_MAX_TURNS) -> None:
        if max_turns <= 0:
            raise ValueError(f"max_turns must be positive, got {max_turns}")
        self._max_turns = max_turns
        self._turns: dict[str, deque[ChatTurn]] = {}

    def append(self, session_id: str, turn: ChatTurn) -> None:
        bucket = self._turns.setdefault(session_id, deque(maxlen=self._max_turns))
        bucket.append(turn)

    def recent(self, session_id: str, n: int | None = None) -> list[ChatTurn]:
        """최근 n턴(기본 전체) 반환. 오래된 → 최신 순."""
        bucket = self._turns.get(session_id)
        if not bucket:
            return []
        items = list(bucket)
        return items if n is None else items[-n:]

    def clear(self, session_id: str) -> None:
        self._turns.pop(session_id, None)

    def session_ids(self) -> Iterable[str]:
        return list(self._turns.keys())

    def __len__(self) -> int:
        return sum(len(b) for b in self._turns.values())
