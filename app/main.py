from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api import auth, health
from app.config import get_settings
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
    app.include_router(health.router)
    app.include_router(auth.router)
    return app


app = create_app()
