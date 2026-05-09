from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError

from app.adapters.opensoma_client import OpenSomaClientError
from app.api import application, auth, health, mentoring
from app.config import get_settings
from app.errors.exceptions import BaseAPIException
from app.errors.handlers import (
    api_error_handler,
    opensoma_error_handler,
    validation_error_handler,
)
from app.observability.logging import configure_logging, get_logger
from app.observability.tracing import TraceIdMiddleware


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    configure_logging()
    settings = get_settings()
    log = get_logger("app.main")
    log.info("app.startup", env=settings.app_env, port=settings.app_port)
    yield
    log.info("app.shutdown")


def create_app() -> FastAPI:
    app = FastAPI(title="SomaAgent", version="0.1.0", lifespan=lifespan)
    app.add_middleware(TraceIdMiddleware)

    # 도메인 예외는 라우터/서비스에서 raise만 하면 핸들러가 표준 응답으로 변환한다.
    app.add_exception_handler(BaseAPIException, api_error_handler)
    app.add_exception_handler(OpenSomaClientError, opensoma_error_handler)
    app.add_exception_handler(RequestValidationError, validation_error_handler)

    app.include_router(health.router)
    app.include_router(auth.router)
    app.include_router(mentoring.router)
    app.include_router(application.router)
    return app


app = create_app()
