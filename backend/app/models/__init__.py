"""Importing this package registers every model on ``Base.metadata`` (Alembic needs that)."""

from app.models.conversation import Conversation, Message, MessageRole, MessageSource
from app.models.document import Document, DocumentChunk, DocumentStatus
from app.models.user import RefreshToken, User
from app.models.user_settings import Theme, UserSettings

__all__ = [
    "Conversation",
    "Document",
    "DocumentChunk",
    "DocumentStatus",
    "Message",
    "MessageRole",
    "MessageSource",
    "RefreshToken",
    "Theme",
    "User",
    "UserSettings",
]
