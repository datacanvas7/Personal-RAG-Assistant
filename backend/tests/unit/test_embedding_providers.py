"""The two embedding adapters, with the OpenAI client and the local model faked."""

from types import SimpleNamespace
from typing import Any

import httpx2
import openai
import pytest

from app.embeddings.base import EmbeddingError, EmbeddingUnavailableError
from app.embeddings.openai import OpenAIEmbeddingProvider
from app.embeddings.sentence_transformers import SentenceTransformerProvider

DIM = 4


# --- OpenAI ---------------------------------------------------------------------------------


class FakeOpenAIClient:
    """Mimics ``client.embeddings.create``; records calls and can raise or misbehave."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.error: Exception | None = None
        self.vector_size = DIM
        self.shuffle = False
        self.embeddings = SimpleNamespace(create=self._create)

    def _create(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        data = [
            SimpleNamespace(index=i, embedding=[float(len(text))] * self.vector_size)
            for i, text in enumerate(kwargs["input"])
        ]
        if self.shuffle:
            data.reverse()
        return SimpleNamespace(data=data)


def _openai(
    client: FakeOpenAIClient, model: str = "text-embedding-3-small", batch_size: int = 100
) -> OpenAIEmbeddingProvider:
    return OpenAIEmbeddingProvider(
        api_key="sk-test", model=model, dimension=DIM, batch_size=batch_size, client=client
    )


def _status_error(cls: type[openai.APIStatusError], status: int) -> openai.APIStatusError:
    request = httpx2.Request("POST", "https://api.openai.com/v1/embeddings")
    return cls(
        "secret provider message", response=httpx2.Response(status, request=request), body=None
    )


def test_openai_model_id_names_provider_model_and_dimension() -> None:
    assert _openai(FakeOpenAIClient()).model_id == f"openai:text-embedding-3-small:{DIM}"


def test_openai_requests_the_configured_dimension_from_text_embedding_3() -> None:
    client = FakeOpenAIClient()

    vectors = _openai(client).embed_documents(["a", "bb"])

    assert client.calls[0]["dimensions"] == DIM
    assert [len(v) for v in vectors] == [DIM, DIM]


def test_openai_omits_dimensions_for_models_that_do_not_support_it() -> None:
    client = FakeOpenAIClient()

    _openai(client, model="text-embedding-ada-002").embed_query("hello")

    assert "dimensions" not in client.calls[0]


def test_openai_batches_large_inputs_and_keeps_order() -> None:
    client = FakeOpenAIClient()
    texts = ["a" * n for n in range(1, 6)]

    vectors = _openai(client, batch_size=2).embed_documents(texts)

    assert [len(call["input"]) for call in client.calls] == [2, 2, 1]
    assert [v[0] for v in vectors] == [1.0, 2.0, 3.0, 4.0, 5.0]


def test_openai_reorders_a_response_that_arrives_out_of_order() -> None:
    client = FakeOpenAIClient()
    client.shuffle = True

    vectors = _openai(client).embed_documents(["a", "bb", "ccc"])

    assert [v[0] for v in vectors] == [1.0, 2.0, 3.0]


@pytest.mark.parametrize(
    "error",
    [
        openai.APIConnectionError(request=httpx2.Request("POST", "https://api.openai.com")),
        openai.APITimeoutError(request=httpx2.Request("POST", "https://api.openai.com")),
        _status_error(openai.RateLimitError, 429),
        _status_error(openai.InternalServerError, 503),
    ],
    ids=["connection", "timeout", "rate-limit", "server-error"],
)
def test_openai_transient_failures_are_retryable(error: Exception) -> None:
    client = FakeOpenAIClient()
    client.error = error

    with pytest.raises(EmbeddingUnavailableError):
        _openai(client).embed_query("hello")


@pytest.mark.parametrize(
    ("cls", "status"),
    [(openai.AuthenticationError, 401), (openai.BadRequestError, 400), (openai.NotFoundError, 404)],
)
def test_openai_client_errors_are_permanent_and_do_not_leak_provider_text(
    cls: type[openai.APIStatusError], status: int
) -> None:
    client = FakeOpenAIClient()
    client.error = _status_error(cls, status)

    with pytest.raises(EmbeddingError) as raised:
        _openai(client).embed_query("hello")

    assert not isinstance(raised.value, EmbeddingUnavailableError)
    assert "secret provider message" not in str(raised.value)
    assert str(status) in str(raised.value)


def test_openai_rejects_vectors_of_the_wrong_size() -> None:
    client = FakeOpenAIClient()
    client.vector_size = DIM + 1

    with pytest.raises(EmbeddingError, match="EMBEDDING_DIMENSION"):
        _openai(client).embed_query("hello")


# --- SentenceTransformers -------------------------------------------------------------------


class FakeArray:
    def __init__(self, rows: list[list[float]]) -> None:
        self._rows = rows

    def tolist(self) -> list[list[float]]:
        return self._rows


class FakeEncoder:
    def __init__(self, dimension: int = DIM) -> None:
        self.dimension = dimension
        self.encoded: list[list[str]] = []
        self.kwargs: dict[str, Any] = {}
        self.fail = False

    def encode(self, sentences: list[str], **kwargs: Any) -> FakeArray:
        if self.fail:
            raise RuntimeError("CUDA exploded at /secret/path")
        self.encoded.append(sentences)
        self.kwargs = kwargs
        return FakeArray([[1.0] + [0.0] * (self.dimension - 1) for _ in sentences])

    def get_embedding_dimension(self) -> int:
        return self.dimension


def _local(encoder: FakeEncoder, **overrides: Any) -> tuple[SentenceTransformerProvider, list[str]]:
    loads: list[str] = []

    def loader(name: str) -> FakeEncoder:
        loads.append(name)
        return encoder

    options: dict[str, Any] = {
        "model_name": "org/model",
        "dimension": DIM,
        "query_prefix": "Represent this query: ",
        "loader": loader,
    }
    return SentenceTransformerProvider(**(options | overrides)), loads


def test_local_model_id_names_provider_model_and_dimension() -> None:
    provider, _ = _local(FakeEncoder())

    assert provider.model_id == f"sentence-transformers:org/model:{DIM}"


def test_local_model_is_loaded_lazily_and_only_once() -> None:
    provider, loads = _local(FakeEncoder())
    assert loads == []  # constructing the provider must not load a model

    provider.embed_documents(["a"])
    provider.embed_query("b")

    assert loads == ["org/model"]


def test_local_query_prefix_applies_to_queries_only() -> None:
    encoder = FakeEncoder()
    provider, _ = _local(encoder)

    provider.embed_documents(["the doc"])
    provider.embed_query("the question")

    assert encoder.encoded == [["the doc"], ["Represent this query: the question"]]


def test_local_vectors_are_requested_normalized() -> None:
    encoder = FakeEncoder()
    provider, _ = _local(encoder)

    vectors = provider.embed_documents(["a", "b"])

    assert encoder.kwargs["normalize_embeddings"] is True
    assert len(vectors) == 2
    assert len(vectors[0]) == DIM


def test_local_empty_input_does_not_load_the_model() -> None:
    provider, loads = _local(FakeEncoder())

    assert provider.embed_documents([]) == []
    assert loads == []


def test_local_dimension_mismatch_is_a_permanent_error() -> None:
    provider, _ = _local(FakeEncoder(dimension=DIM * 2))

    with pytest.raises(EmbeddingError, match="EMBEDDING_DIMENSION") as raised:
        provider.embed_query("x")

    assert not isinstance(raised.value, EmbeddingUnavailableError)


def test_local_load_failure_is_retryable() -> None:
    def loader(_name: str) -> FakeEncoder:
        raise OSError("offline")

    provider = SentenceTransformerProvider(model_name="m", dimension=DIM, loader=loader)

    with pytest.raises(EmbeddingUnavailableError):
        provider.embed_query("x")


def test_local_encoding_failure_does_not_leak_internals() -> None:
    encoder = FakeEncoder()
    provider, _ = _local(encoder)
    provider.embed_query("warm up")
    encoder.fail = True

    with pytest.raises(EmbeddingError) as raised:
        provider.embed_query("x")

    assert "/secret/path" not in str(raised.value)
