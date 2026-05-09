"""LLM에 노출할 Tool JSON Schema 카탈로그.

각 tool의 *런타임* 책임은 `app/tools/*` 가, *LLM 인터페이스* 책임은 본 모듈이 진다.
변경이 잦은 부분(설명 문구·필드 설명)을 분리해 tool 코드는 안정적으로 둔다.

SPEC §4.2의 8개 tool에 대한 OpenAI Chat Completions 호환 function spec.
"""
from __future__ import annotations

from typing import Any

from app.tools.registry import ToolRegistry

TOOL_DESCRIPTIONS: dict[str, dict[str, Any]] = {
    "knowledge.search": {
        "description": (
            "공지/멘토링/Webex 메시지를 통합 RAG로 의미 검색한다. "
            "현재 상태가 중요한 라이브 조회는 opensoma.* tool을 우선 사용하고, "
            "본 tool은 의미 검색·요약·아카이브 조회용."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "자연어 검색어"},
                "source_types": {
                    "type": "array",
                    "items": {
                        "type": "string",
                        "enum": ["NOTICE", "NOTICE_PDF", "MENTORING", "WEBEX_MESSAGE"],
                    },
                    "description": "검색 대상 원천 필터 (생략 시 전체)",
                },
                "official_only": {
                    "type": "boolean",
                    "description": "공식 출처만 (예: 공지/PDF)",
                    "default": False,
                },
                "room_name": {
                    "type": "string",
                    "description": "Webex 룸 이름 필터 (선택)",
                },
                "k": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 20,
                    "default": 5,
                    "description": "반환 개수",
                },
            },
            "required": ["query"],
        },
    },
    "opensoma.mentoring.list": {
        "description": "현재 신청 가능한 멘토링 라이브 목록. 정원/상태가 정확해야 할 때만 사용.",
        "parameters": {
            "type": "object",
            "properties": {},
        },
    },
    "opensoma.mentoring.get": {
        "description": (
            "단일 멘토링 라이브 상세 — 신청 직전 재검증, 또는 사용자가 특정 ID의 자세한 정보를 요청할 때. "
            "본 tool은 신청·취소를 *수행하지 않는다*. 신청 의도라도 본 tool로 상태만 확인하면 충분."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "mentoring_id": {"type": "integer", "description": "멘토링 ID"},
            },
            "required": ["mentoring_id"],
        },
    },
    "opensoma.mentoring.apply": {
        "description": (
            "멘토링 신청을 *실제 실행* (확인 완료 후 /actions/execute 경로 전용). "
            "라우터는 본 tool을 호출하지 마세요 — 액션 의도는 mentoring.get만 호출."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "mentoring_id": {"type": "integer"},
            },
            "required": ["mentoring_id"],
        },
    },
    "opensoma.mentoring.cancel": {
        "description": "멘토링 신청 취소 *실제 실행* (/actions/execute 전용). 라우터에서 호출 금지.",
        "parameters": {
            "type": "object",
            "properties": {
                "apply_sn": {"type": "integer"},
                "qustnr_sn": {"type": "integer"},
            },
            "required": ["apply_sn", "qustnr_sn"],
        },
    },
    "opensoma.application.history": {
        "description": "현재 사용자의 멘토링 신청/취소 내역 (TTL 5분 캐시).",
        "parameters": {
            "type": "object",
            "properties": {
                "force_refresh": {"type": "boolean", "default": False},
            },
        },
    },
    "opensoma.notice.get": {
        "description": "단일 공지 정확 조회 (첨부 포함). 사용자가 공지 N번을 명시적으로 지칭할 때.",
        "parameters": {
            "type": "object",
            "properties": {
                "notice_id": {"type": "integer"},
            },
            "required": ["notice_id"],
        },
    },
    "calendar.invite.create": {
        "description": "캘린더 초대 생성 (mock). 사용자가 명시적으로 일정 생성을 요청할 때만 사용.",
        "parameters": {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "start_at": {"type": "string", "description": "ISO 8601"},
                "end_at": {"type": "string", "description": "ISO 8601"},
                "description": {"type": "string"},
                "location": {"type": "string"},
            },
            "required": ["title", "start_at", "end_at"],
        },
    },
}


def build_function_specs(registry: ToolRegistry) -> list[dict[str, Any]]:
    """등록된 tool들에 대한 OpenAI/Solar function spec 목록.

    카탈로그에 정의된 tool만 LLM에 노출 — 신규 tool 추가 시 본 모듈에도 등록 필수.
    """
    specs: list[dict[str, Any]] = []
    for tool in registry.all():
        meta = TOOL_DESCRIPTIONS.get(tool.name)
        if meta is None:
            continue
        specs.append(
            {
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": meta["description"],
                    "parameters": meta["parameters"],
                },
            }
        )
    return specs
