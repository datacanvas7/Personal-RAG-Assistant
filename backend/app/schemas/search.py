import uuid
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

MAX_QUERY_CHARS = 2000


class SearchRequest(BaseModel):
    # The query is a POST body, not a URL parameter: URLs end up in access logs and browser
    # history, and what someone searches their private documents for is private.
    query: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=MAX_QUERY_CHARS)
    ]
    top_k: int = Field(default=5, ge=1, le=50)
    # Restrict the search to these documents. Ids that are not the caller's match nothing.
    document_ids: list[uuid.UUID] | None = Field(default=None, max_length=100)


class SearchHit(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    chunk_id: uuid.UUID
    document_id: uuid.UUID
    filename: str
    page_number: int | None
    chunk_index: int
    content: str
    # Cosine similarity of the chunk to the query, higher is closer.
    score: float


class SearchResponse(BaseModel):
    results: list[SearchHit]
