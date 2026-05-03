from fastapi import FastAPI

from contextlib import asynccontextmanager
from soma_app.core.logger import logger

from soma_app.core.db import get_chrome_client

@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        logger.info("Starting FastAPI application")
        async with get_chrome_client() as client:
            try:
                await client.heartbeat()
            except Exception as e:
                logger.error(f"Failed to ping Chroma: {e}")
                raise
            logger.info("Chroma is ready")

        yield
    finally:
        logger.info("Stopping FastAPI application")
