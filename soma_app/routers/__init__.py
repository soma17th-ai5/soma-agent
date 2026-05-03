from fastapi import APIRouter

from soma_app.routers.chat import router as chat_router
from soma_app.routers.embedding import router as embedding_router

v1_router = APIRouter(prefix="/api/v1")

v1_router.include_router(chat_router, tags=["chat"])
v1_router.include_router(embedding_router, tags=["embedding"])
