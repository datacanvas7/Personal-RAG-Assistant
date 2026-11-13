"""Local embeddings with a SentenceTransformers model (default: BAAI/bge-small-en-v1.5).

Needs no API key and sends no data anywhere, at the cost of PyTorch in the image. The
library is an optional extra (``local-embeddings``), imported only when the model is first
used, so an installation that uses OpenAI never loads it.
"""

import logging
import threading
from collections.abc import Callable, Sequence
from typing import Any, Protocol, cast

from app.embeddings.base import EmbeddingError, EmbeddingUnavailableError

logger = logging.getLogger(__name__)


class _Encoder(Protocol):
    """The part of ``SentenceTransformer`` this adapter uses (and tests can fake)."""

    def encode(self, sentences: list[str], **kwargs: Any) -> Any: ...

    def get_embedding_dimension(self) -> int | None: ...


def load_sentence_transformer(model_name: str) -> _Encoder:
    try:
        from sentence_transformers import SentenceTransformer
    except ImportError as error:
        raise EmbeddingError(
            "EMBEDDING_PROVIDER=sentence_transformers needs the 'local-embeddings' extra "
            "(uv sync --extra local-embeddings). Install it or set EMBEDDING_PROVIDER=openai."
        ) from error
    # cast: the library's overloaded ``encode`` is richer than the slice we declare above,
    # and its type information exists only when the optional extra is installed.
    return cast(_Encoder, SentenceTransformer(model_name, device="cpu"))


class SentenceTransformerProvider:
    def __init__(
        self,
        *,
        model_name: str,
        dimension: int,
        query_prefix: str = "",
        batch_size: int = 32,
        loader: Callable[[str], _Encoder] = load_sentence_transformer,
    ) -> None:
        self._model_name = model_name
        self._dimension = dimension
        self._query_prefix = query_prefix
        self._batch_size = batch_size
        self._loader = loader
        self._model: _Encoder | None = None
        self._lock = threading.Lock()

    @property
    def model_id(self) -> str:
        return f"sentence-transformers:{self._model_name}:{self._dimension}"

    @property
    def dimension(self) -> int:
        return self._dimension

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        return self._encode(list(texts))

    def embed_query(self, text: str) -> list[float]:
        # BGE models retrieve better when the *query* (not the documents) carries an
        # instruction prefix.
        return self._encode([self._query_prefix + text])[0]

    def _encode(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        model = self._loaded_model()
        try:
            # Normalised vectors make cosine distance and dot product agree.
            vectors = model.encode(
                texts,
                batch_size=self._batch_size,
                normalize_embeddings=True,
                convert_to_numpy=True,
                show_progress_bar=False,
            )
        except Exception as error:
            raise EmbeddingError(f"embedding with {self._model_name} failed") from error
        result: list[list[float]] = vectors.tolist()
        return result

    def _loaded_model(self) -> _Encoder:
        # Loading takes seconds and may download the weights, so it happens on first use,
        # once per process, and not at import time.
        with self._lock:
            if self._model is None:
                self._model = self._load()
            return self._model

    def _load(self) -> _Encoder:
        logger.info("loading embedding model %s", self._model_name)
        try:
            model = self._loader(self._model_name)
        except EmbeddingError:
            raise
        except Exception as error:
            # Typically a failed download (offline, Hugging Face outage): worth retrying.
            raise EmbeddingUnavailableError(
                f"could not load embedding model {self._model_name}"
            ) from error
        actual = model.get_embedding_dimension()
        if actual != self._dimension:
            raise EmbeddingError(
                f"{self._model_name} produces {actual}-dimensional vectors but "
                f"EMBEDDING_DIMENSION is {self._dimension}"
            )
        return model
