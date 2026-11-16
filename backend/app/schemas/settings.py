from typing import Annotated, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.core.config import Settings
from app.models import Theme
from app.services.settings import UserPreferences

TopK = Annotated[int, Field(ge=1, le=20)]
Threshold = Annotated[float, Field(ge=0, le=1)]


class RetrievalDefaults(BaseModel):
    top_k: int
    score_threshold: float


class ServerInfo(BaseModel):
    """Decided by whoever runs the server; shown read-only."""

    llm_model: str
    llm_configured: bool = Field(description="False until an LLM_API_KEY is set.")
    embedding_provider: str
    embedding_model: str
    chunk_size_chars: int
    chunk_overlap_chars: int
    max_upload_bytes: int


class SettingsRead(BaseModel):
    theme: Theme
    retrieval_top_k: int | None = Field(description="Your own value; null = the server default.")
    retrieval_score_threshold: float | None = Field(
        description="Your own value; null = the server default."
    )
    defaults: RetrievalDefaults
    server: ServerInfo

    @classmethod
    def build(cls, preferences: UserPreferences, settings: Settings) -> "SettingsRead":
        return cls(
            theme=Theme(preferences.theme),
            retrieval_top_k=preferences.retrieval_top_k,
            retrieval_score_threshold=preferences.retrieval_score_threshold,
            defaults=RetrievalDefaults(
                top_k=settings.retrieval_top_k,
                score_threshold=settings.retrieval_score_threshold,
            ),
            server=ServerInfo(
                llm_model=settings.llm_model,
                llm_configured=bool(
                    settings.llm_api_key and settings.llm_api_key.get_secret_value()
                ),
                embedding_provider=settings.embedding_provider,
                embedding_model=settings.resolved_embedding_model,
                chunk_size_chars=settings.chunk_size_chars,
                chunk_overlap_chars=settings.chunk_overlap_chars,
                max_upload_bytes=settings.max_upload_bytes,
            ),
        )


class SettingsUpdate(BaseModel):
    """A partial update: send only what changes. ``null`` for a retrieval value goes back
    to the server default."""

    model_config = ConfigDict(extra="forbid")

    theme: Theme | None = None
    retrieval_top_k: TopK | None = None
    retrieval_score_threshold: Threshold | None = None

    @model_validator(mode="after")
    def _theme_cannot_be_cleared(self) -> Self:
        if "theme" in self.model_fields_set and self.theme is None:
            raise ValueError("theme cannot be null")
        return self

    def changes(self) -> dict[str, object]:
        """Only the fields the client sent (so ``null`` can mean "reset")."""
        values = self.model_dump(exclude_unset=True)
        if isinstance(values.get("theme"), Theme):
            values["theme"] = values["theme"].value
        return values
