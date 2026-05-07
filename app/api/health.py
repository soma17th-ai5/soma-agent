from fastapi import APIRouter

from app.api.deps import DbSession
from app.services import health as health_service

router = APIRouter(tags=["health"])


@router.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/readyz")
def readyz(db: DbSession) -> dict[str, str]:
    health_service.check_db(db)
    return {"status": "ready"}
