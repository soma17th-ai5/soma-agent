from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.observability.logging import get_logger

router = APIRouter(tags=["health"])
log = get_logger("app.api.health")


@router.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/readyz")
def readyz(db: Session = Depends(get_db)) -> dict[str, str]:
    try:
        db.execute(text("SELECT 1"))
    except Exception as exc:
        log.error("readyz.db_unavailable", error=str(exc), exc_info=exc)
        # 응답에는 내부 연결 정보를 노출하지 않는다. 자세한 진단은 로그.
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "DATABASE_UNAVAILABLE", "message": "Database is unavailable"},
        ) from exc
    return {"status": "ready"}
