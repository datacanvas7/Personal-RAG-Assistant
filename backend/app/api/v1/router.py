from fastapi import APIRouter

from app.api.v1 import analytics, ask, auth, chat, documents, health, search, users

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(auth.router)
api_router.include_router(users.router)
api_router.include_router(documents.router)
api_router.include_router(search.router)
api_router.include_router(ask.router)
api_router.include_router(chat.router)
api_router.include_router(analytics.router)
