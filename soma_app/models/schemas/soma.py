from datetime import datetime
from enum import Enum
from typing import List, Optional, Any, Dict
from pydantic import BaseModel, Field

class SomaSourceType(str, Enum):
    OPEN_SOMA = "OpenSoma"
    WEBEX = "Webex"
    SYSTEM = "System"

class SomaIntent(str, Enum):
    NOTICE = "NOTICE"                   # 공지사항 확인
    MENTORING_SEARCH = "MENTORING_SEARCH" # 멘토링 탐색
    MENTORING_APPLY = "MENTORING_APPLY"   # 멘토링 신청
    MENTORING_CANCEL = "MENTORING_CANCEL" # 멘토링 취소
    WEBEX_SUMMARY = "WEBEX_SUMMARY"       # Webex 메시지 요약
    MY_STATUS = "MY_STATUS"             # 내 접수 내역 확인
    UNKNOWN = "UNKNOWN"                 # 분류 불가

class MentoringStatus(str, Enum):
    AVAILABLE = "신청 가능"
    CLOSED = "마감"
    APPLIED = "신청 완료"

class Notice(BaseModel):
    id: str
    title: str
    content: str
    date: str
    url: Optional[str] = None
    is_important: bool = False

class Mentoring(BaseModel):
    id: str
    title: str
    mentor_name: str
    category: str
    start_at: datetime
    status: MentoringStatus
    description: Optional[str] = None
    url: Optional[str] = None

class WebexMessage(BaseModel):
    id: str
    room_name: str
    sender: str
    text: str
    created_at: datetime
    url: Optional[str] = None

class SomaActionType(str, Enum):
    APPLY = "MENTORING_APPLY"
    CANCEL = "MENTORING_CANCEL"
    CALENDAR_ADD = "CALENDAR_ADD"

class SomaActionResponse(BaseModel):
    success: bool
    action: SomaActionType
    message: str
    data: Optional[dict] = None

class SomaSource(BaseModel):
    title: str
    url: Optional[str] = None
    mentoring_id: Optional[str] = Field(None, alias="mentoringId")
    date: Optional[str] = None
    time: Optional[str] = None

    class Config:
        populate_by_name = True

class SomaSuggestedAction(BaseModel):
    action_type: SomaActionType = Field(..., alias="actionType")
    label: str
    payload: Dict[str, Any]

    class Config:
        populate_by_name = True

class SomaAgentResponse(BaseModel):
    answer: str
    sources: List[SomaSource] = Field(default_factory=list)
    suggested_actions: List[SomaSuggestedAction] = Field(default_factory=list, alias="suggestedActions")
    source_type: Optional[SomaSourceType] = None # 내부 참조용

    class Config:
        populate_by_name = True

class SomaChatRequest(BaseModel):
    message: str = Field(..., description="사용자 질문")
    chat_session_id: Optional[str] = Field(None, alias="chatSessionId", description="채팅 세션 ID")
