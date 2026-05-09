"""헬스 체크 서비스. DB 연결 상태 등 인프라 점검을 라우터에서 분리.

라우터에서 try/except를 두지 않기 위해 어댑터 예외 → 도메인 예외 변환을 여기서 수행.
"""
from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.errors.exceptions import DatabaseUnavailable
from app.observability.logging import get_logger

log = get_logger("app.services.health")


def check_db(db: Session) -> None:
    """`SELECT 1`로 DB 도달 가능성 확인. 실패 시 DatabaseUnavailable raise.

    내부 진단 정보는 로그로만 남기고, 응답엔 일반화된 503을 노출한다.
    """
    try:
        db.execute(text("SELECT 1"))
    except Exception as exc:
        log.error("readyz.db_unavailable", error=str(exc), exc_info=exc)
        raise DatabaseUnavailable() from exc
