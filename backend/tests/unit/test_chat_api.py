"""The chat API end to end with in-memory stores and a scripted language model.

The SQL-level behavior (user filters, cascades, ordering, the one-transaction save) is covered
against PostgreSQL in tests/integration/test_chat.py; here we test validation, auth, ownership,
the saved history, the SSE protocol and error mapping through the real services.
"""

import json
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

import httpx2
import pytest

from app.api.deps import get_auth_service, get_chat_service, get_embedder
from app.core.config import Settings
from app.llm.base import LLMError, LLMUnavailableError
from app.main import create_app
from app.rag.prompt_builder import NOT_FOUND_ANSWER
from app.rag.service import RagService
from app.retrieval.service import SearchService
from app.services.auth import AuthService
from app.services.chat import ChatService
from tests.fakes import (
    FakeChatStore,
    FakeDocumentStore,
    FakeEmbedder,
    FakeLLM,
    FakeTokenStore,
    FakeTransaction,
    FakeUserStore,
)
from tests.unit.test_search_api import Env as SearchEnv
from tests.unit.test_search_api import InMemoryVectorStore, _document, _login

CONVERSATIONS = "/api/v1/chat/conversations"
CHUNK = "Passwords must be reset every ninety days."
QUESTION = "How often must passwords be reset?"
ANSWER = "Every ninety days [1]."


@dataclass
class ChatEnv(SearchEnv):
    llm: FakeLLM
    store: FakeChatStore
    tx: FakeTransaction
    # Flip to False to simulate a server without a configured model.
    model: dict[str, bool]


@pytest.fixture
async def env() -> AsyncIterator[ChatEnv]:
    settings = Settings()
    users, tokens = FakeUserStore(), FakeTokenStore()
    documents, embedder = FakeDocumentStore(), FakeEmbedder()
    vectors = InMemoryVectorStore(embedder)
    store, tx, llm = FakeChatStore(), FakeTransaction(), FakeLLM()
    model = {"configured": True}

    def chat_service() -> ChatService:
        rag = RagService(
            searcher=SearchService(embedder=embedder, vectors=vectors, documents=documents),
            llm=llm if model["configured"] else None,
            top_k=settings.retrieval_top_k,
            score_threshold=settings.retrieval_score_threshold,
            max_context_chars=settings.max_context_chars,
            history_max_messages=settings.chat_history_max_messages,
            release_connection=tx.commit,
        )
        return ChatService(
            conversations=store,
            messages=store,
            rag=rag,
            transaction=tx,
            history_max_messages=settings.chat_history_max_messages,
        )

    app = create_app()
    app.dependency_overrides[get_auth_service] = lambda: AuthService(
        users=users, tokens=tokens, transaction=FakeTransaction(), settings=settings
    )
    app.dependency_overrides[get_embedder] = lambda: embedder
    app.dependency_overrides[get_chat_service] = chat_service
    transport = httpx2.ASGITransport(app=app)
    async with httpx2.AsyncClient(transport=transport, base_url="http://test") as client:
        yield ChatEnv(client, users, documents, vectors, embedder, llm, store, tx, model)


async def _conversation(env: ChatEnv, headers: dict[str, str], title: str | None = None) -> str:
    response = await env.client.post(
        CONVERSATIONS, headers=headers, json={} if title is None else {"title": title}
    )
    assert response.status_code == 201, response.text
    return str(response.json()["id"])


async def _ask(
    env: ChatEnv, headers: dict[str, str], conversation_id: str, content: str = QUESTION
) -> httpx2.Response:
    return await env.client.post(
        f"/api/v1/chat/{conversation_id}/messages", headers=headers, json={"content": content}
    )


def _sse(text: str) -> list[tuple[str, dict[str, Any]]]:
    events = []
    for block in text.strip().split("\n\n"):
        lines = block.splitlines()
        assert lines[0].startswith("event: ") and lines[1].startswith("data: "), block
        events.append(
            (lines[0].removeprefix("event: "), json.loads(lines[1].removeprefix("data: ")))
        )
    return events


async def _stream(
    env: ChatEnv, headers: dict[str, str], conversation_id: str, content: str = QUESTION
) -> httpx2.Response:
    return await env.client.post(
        f"/api/v1/chat/{conversation_id}/stream", headers=headers, json={"content": content}
    )


async def _saved(env: ChatEnv, headers: dict[str, str], conversation_id: str) -> dict[str, Any]:
    response = await env.client.get(f"{CONVERSATIONS}/{conversation_id}/messages", headers=headers)
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


# --- authentication --------------------------------------------------------------------


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("POST", CONVERSATIONS),
        ("GET", CONVERSATIONS),
        ("GET", f"{CONVERSATIONS}/{uuid.uuid4()}"),
        ("PATCH", f"{CONVERSATIONS}/{uuid.uuid4()}"),
        ("DELETE", f"{CONVERSATIONS}/{uuid.uuid4()}"),
        ("GET", f"{CONVERSATIONS}/{uuid.uuid4()}/messages"),
        ("POST", f"/api/v1/chat/{uuid.uuid4()}/messages"),
        ("POST", f"/api/v1/chat/{uuid.uuid4()}/stream"),
    ],
)
async def test_every_chat_route_requires_authentication(
    env: ChatEnv, method: str, path: str
) -> None:
    response = await env.client.request(method, path, json={"content": "hi", "title": "x"})

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthorized"
    assert env.llm.calls == []


# --- conversations ---------------------------------------------------------------------


async def test_a_conversation_gets_a_default_or_a_given_title(env: ChatEnv) -> None:
    headers, _ = await _login(env, "ada@example.com")

    untitled = await env.client.post(CONVERSATIONS, headers=headers, json={})
    titled = await env.client.post(CONVERSATIONS, headers=headers, json={"title": "  Tax  "})

    assert untitled.status_code == titled.status_code == 201
    assert untitled.json()["title"] == "New conversation"
    assert titled.json()["title"] == "Tax"
    assert set(titled.json()) == {"id", "title", "created_at", "updated_at"}


@pytest.mark.parametrize("title", ["", "   ", "x" * 201])
async def test_blank_or_overlong_titles_are_rejected(env: ChatEnv, title: str) -> None:
    headers, _ = await _login(env, "ada@example.com")
    conversation_id = await _conversation(env, headers)

    created = await env.client.post(CONVERSATIONS, headers=headers, json={"title": title})
    renamed = await env.client.patch(
        f"{CONVERSATIONS}/{conversation_id}", headers=headers, json={"title": title}
    )

    assert created.status_code == renamed.status_code == 422


async def test_conversations_are_paged_most_recently_active_first(env: ChatEnv) -> None:
    headers, user_id = await _login(env, "ada@example.com")
    _document(env, user_id, "handbook.txt", [CHUNK])
    first = await _conversation(env, headers, "first")
    second = await _conversation(env, headers, "second")
    third = await _conversation(env, headers, "third")
    await _ask(env, headers, first)  # activity moves "first" to the top

    page_one = (await env.client.get(CONVERSATIONS, headers=headers, params={"limit": 2})).json()
    page_two = (
        await env.client.get(CONVERSATIONS, headers=headers, params={"limit": 2, "offset": 2})
    ).json()

    assert [c["id"] for c in page_one["items"]] == [first, third]
    assert [c["id"] for c in page_two["items"]] == [second]
    assert page_one["total"] == page_two["total"] == 3
    assert (page_one["limit"], page_one["offset"], page_two["offset"]) == (2, 0, 2)


@pytest.mark.parametrize("params", [{"limit": 0}, {"limit": 101}, {"offset": -1}])
async def test_bad_paging_parameters_are_rejected(env: ChatEnv, params: dict[str, int]) -> None:
    headers, _ = await _login(env, "ada@example.com")

    assert (await env.client.get(CONVERSATIONS, headers=headers, params=params)).status_code == 422


async def test_a_conversation_can_be_read_renamed_and_deleted(env: ChatEnv) -> None:
    headers, user_id = await _login(env, "ada@example.com")
    _document(env, user_id, "handbook.txt", [CHUNK])
    conversation_id = await _conversation(env, headers, "Old name")
    await _ask(env, headers, conversation_id)
    url = f"{CONVERSATIONS}/{conversation_id}"

    assert (await env.client.get(url, headers=headers)).json()["title"] == "Old name"
    renamed = await env.client.patch(url, headers=headers, json={"title": "New name"})
    assert renamed.status_code == 200
    assert renamed.json()["title"] == "New name"
    assert (await env.client.delete(url, headers=headers)).status_code == 204

    assert (await env.client.get(url, headers=headers)).status_code == 404
    assert (await env.client.delete(url, headers=headers)).status_code == 404
    assert env.store.messages == []  # the saved messages went with it


# --- ownership -------------------------------------------------------------------------


async def test_another_users_conversation_is_reported_as_not_found(env: ChatEnv) -> None:
    ada, ada_id = await _login(env, "ada@example.com")
    bob, _ = await _login(env, "bob@example.com")
    _document(env, ada_id, "handbook.txt", [CHUNK])
    conversation_id = await _conversation(env, ada, "Ada's")
    await _ask(env, ada, conversation_id)
    url = f"{CONVERSATIONS}/{conversation_id}"
    calls_before = len(env.llm.calls)

    attempts = [
        await env.client.get(url, headers=bob),
        await env.client.patch(url, headers=bob, json={"title": "mine now"}),
        await env.client.delete(url, headers=bob),
        await env.client.get(f"{url}/messages", headers=bob),
        await _ask(env, bob, conversation_id),
        await _stream(env, bob, conversation_id),
    ]

    for response in attempts:
        assert response.status_code == 404, response.text
        assert response.json()["error"]["code"] == "not_found"
    # Same answer as for an id that never existed, nothing leaked, nothing changed.
    assert (await _ask(env, bob, str(uuid.uuid4()))).status_code == 404
    assert len(env.llm.calls) == calls_before
    assert (await env.client.get(CONVERSATIONS, headers=bob)).json()["items"] == []
    assert (await env.client.get(url, headers=ada)).json()["title"] == "Ada's"
    assert (await _saved(env, ada, conversation_id))["total"] == 2


async def test_a_users_documents_do_not_answer_another_users_question(env: ChatEnv) -> None:
    _, ada_id = await _login(env, "ada@example.com")
    bob, _ = await _login(env, "bob@example.com")
    _document(env, ada_id, "secret.txt", ["The launch code is swordfish."])
    conversation_id = await _conversation(env, bob)

    response = await _ask(env, bob, conversation_id, "What is the launch code swordfish?")

    assert response.status_code == 201
    assert response.json()["assistant_message"]["content"] == NOT_FOUND_ANSWER
    assert response.json()["assistant_message"]["sources"] == []
    assert env.llm.calls == []
    assert "launch code is swordfish" not in response.text


# --- non-streaming messages -------------------------------------------------------------


async def test_a_question_is_answered_with_sources_and_both_messages_are_saved(
    env: ChatEnv,
) -> None:
    headers, user_id = await _login(env, "ada@example.com")
    document_id = _document(env, user_id, "handbook.txt", [CHUNK])
    conversation_id = await _conversation(env, headers)
    env.llm.replies.append(ANSWER)

    response = await _ask(env, headers, conversation_id)

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["grounded"] is True
    assert body["user_message"]["role"] == "user"
    assert body["user_message"]["content"] == QUESTION
    assert body["user_message"]["sources"] == []
    answer = body["assistant_message"]
    assert (answer["role"], answer["content"]) == ("assistant", ANSWER)
    [source] = answer["sources"]
    assert source["number"] == 1
    assert source["document_id"] == str(document_id)
    assert source["filename"] == "handbook.txt"
    assert 0.45 <= source["score"] <= 1.0
    assert "excerpt" not in source  # passage text is not stored with a message
    saved = await _saved(env, headers, conversation_id)
    assert saved["total"] == 2
    assert [m["role"] for m in saved["items"]] == ["user", "assistant"]
    assert saved["items"][1] == answer
    assert env.tx.commits >= 1


async def test_an_untitled_conversation_is_named_after_its_first_question(env: ChatEnv) -> None:
    headers, user_id = await _login(env, "ada@example.com")
    _document(env, user_id, "handbook.txt", [CHUNK])
    untitled = await _conversation(env, headers)
    titled = await _conversation(env, headers, "Security")
    long_question = QUESTION + " " + "Please be thorough. " * 10

    await _ask(env, headers, untitled)
    await _ask(env, headers, titled)
    await _ask(env, headers, untitled, long_question)  # only the first question names it

    assert (await env.client.get(f"{CONVERSATIONS}/{untitled}", headers=headers)).json()[
        "title"
    ] == QUESTION
    assert (await env.client.get(f"{CONVERSATIONS}/{titled}", headers=headers)).json()[
        "title"
    ] == "Security"
    other = await _conversation(env, headers)
    await _ask(env, headers, other, long_question)
    title = (await env.client.get(f"{CONVERSATIONS}/{other}", headers=headers)).json()["title"]
    assert len(title) <= 60
    assert title.endswith("…")


async def test_follow_up_questions_see_the_earlier_turns_but_only_a_window_of_them(
    env: ChatEnv,
) -> None:
    headers, user_id = await _login(env, "ada@example.com")
    _document(env, user_id, "handbook.txt", [CHUNK])
    conversation_id = await _conversation(env, headers)
    env.llm.replies.append(ANSWER)
    await _ask(env, headers, conversation_id)

    await _ask(env, headers, conversation_id, "And how often must passwords be reset again?")

    second_prompt = env.llm.calls[1]
    assert [m.role for m in second_prompt[1:-1]] == ["user", "assistant"]
    assert second_prompt[1].content == QUESTION
    assert second_prompt[2].content == "Every ninety days."  # old [n] markers are stripped
    # Many turns later the prompt still carries at most the configured window.
    for _ in range(6):
        await _ask(env, headers, conversation_id)
    window = Settings().chat_history_max_messages
    assert len(env.llm.calls[-1]) <= window + 2  # + system message + the new question


async def test_a_question_the_documents_cannot_answer_is_saved_as_not_found(
    env: ChatEnv,
) -> None:
    headers, user_id = await _login(env, "ada@example.com")
    _document(env, user_id, "handbook.txt", [CHUNK])
    conversation_id = await _conversation(env, headers)

    response = await _ask(env, headers, conversation_id, "Who won the football match?")

    assert response.status_code == 201
    body = response.json()
    assert body["grounded"] is False
    assert body["assistant_message"]["content"] == NOT_FOUND_ANSWER
    assert body["assistant_message"]["sources"] == []
    assert env.llm.calls == []
    assert (await _saved(env, headers, conversation_id))["total"] == 2


async def test_the_document_filter_limits_what_the_answer_is_built_from(env: ChatEnv) -> None:
    headers, user_id = await _login(env, "ada@example.com")
    _document(env, user_id, "old-policy.txt", [CHUNK])
    new = _document(env, user_id, "new-policy.txt", [CHUNK])
    conversation_id = await _conversation(env, headers)

    response = await env.client.post(
        f"/api/v1/chat/{conversation_id}/messages",
        headers=headers,
        json={"content": QUESTION, "document_ids": [str(new)]},
    )

    [source] = response.json()["assistant_message"]["sources"]
    assert source["filename"] == "new-policy.txt"


async def test_a_failing_model_is_a_503_and_nothing_is_saved(env: ChatEnv) -> None:
    headers, user_id = await _login(env, "ada@example.com")
    _document(env, user_id, "handbook.txt", [CHUNK])
    conversation_id = await _conversation(env, headers)
    env.llm.replies.append(LLMUnavailableError("429 secret-provider-detail"))

    response = await _ask(env, headers, conversation_id)

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "service_unavailable"
    assert "secret-provider-detail" not in response.text
    assert (await _saved(env, headers, conversation_id))["total"] == 0  # a clean retry is possible
    assert (await env.client.get(f"{CONVERSATIONS}/{conversation_id}", headers=headers)).json()[
        "title"
    ] == "New conversation"


async def test_without_a_configured_model_chat_is_a_503_and_conversations_still_work(
    env: ChatEnv,
) -> None:
    env.model["configured"] = False
    headers, _ = await _login(env, "ada@example.com")
    conversation_id = await _conversation(env, headers)

    asked = await _ask(env, headers, conversation_id)
    streamed = await _stream(env, headers, conversation_id)

    assert asked.status_code == streamed.status_code == 503
    assert asked.json()["error"]["code"] == "service_unavailable"
    assert (await env.client.get(CONVERSATIONS, headers=headers)).status_code == 200


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"content": ""},
        {"content": "   "},
        {"content": "x" * 2001},
        {"content": "ok", "document_ids": ["not-a-uuid"]},
        {"content": "ok", "document_ids": [str(uuid.uuid4())] * 101},
    ],
    ids=["missing", "empty", "blank", "too-long", "bad-id", "too-many-ids"],
)
async def test_invalid_messages_are_rejected_before_any_work(
    env: ChatEnv, body: dict[str, Any]
) -> None:
    headers, _ = await _login(env, "ada@example.com")
    conversation_id = await _conversation(env, headers)

    for route in ("messages", "stream"):
        response = await env.client.post(
            f"/api/v1/chat/{conversation_id}/{route}", headers=headers, json=body
        )
        assert response.status_code == 422
    assert env.llm.calls == []
    assert env.embedder.calls == 0


async def test_a_malformed_conversation_id_is_a_422(env: ChatEnv) -> None:
    headers, _ = await _login(env, "ada@example.com")

    response = await _ask(env, headers, "not-a-uuid")

    assert response.status_code == 422


async def test_messages_are_listed_oldest_first_and_paged(env: ChatEnv) -> None:
    headers, user_id = await _login(env, "ada@example.com")
    _document(env, user_id, "handbook.txt", [CHUNK])
    conversation_id = await _conversation(env, headers)
    for _ in range(3):
        await _ask(env, headers, conversation_id)

    everything = await _saved(env, headers, conversation_id)
    second_page = (
        await env.client.get(
            f"{CONVERSATIONS}/{conversation_id}/messages",
            headers=headers,
            params={"limit": 4, "offset": 4},
        )
    ).json()

    assert everything["total"] == 6
    assert [m["role"] for m in everything["items"]] == ["user", "assistant"] * 3
    stamps = [m["created_at"] for m in everything["items"]]
    assert stamps == sorted(stamps)
    assert [m["id"] for m in second_page["items"]] == [m["id"] for m in everything["items"][4:]]
    assert (second_page["total"], second_page["limit"], second_page["offset"]) == (6, 4, 4)


async def test_the_database_connection_is_released_before_the_model_is_called(
    env: ChatEnv,
) -> None:
    headers, user_id = await _login(env, "ada@example.com")
    _document(env, user_id, "handbook.txt", [CHUNK])
    conversation_id = await _conversation(env, headers)
    commits_when_model_called: list[int] = []
    env.llm.on_call = lambda: commits_when_model_called.append(env.tx.commits)
    commits_before = env.tx.commits

    await _ask(env, headers, conversation_id)
    await _stream(env, headers, conversation_id)

    # Retrieval ended its transaction (one commit) before each model call.
    assert commits_when_model_called[0] == commits_before + 1
    assert commits_when_model_called[1] == env.tx.commits - 1


# --- streaming --------------------------------------------------------------------------


async def test_a_stream_sends_tokens_then_the_saved_messages(env: ChatEnv) -> None:
    headers, user_id = await _login(env, "ada@example.com")
    document_id = _document(env, user_id, "handbook.txt", [CHUNK])
    conversation_id = await _conversation(env, headers)
    env.llm.replies.append("Every ninety days [1].")

    response = await _stream(env, headers, conversation_id)

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    # no-transform keeps a compressing proxy (Next's gzip layer) from buffering the stream.
    assert response.headers["cache-control"] == "no-cache, no-transform"
    events = _sse(response.text)
    assert [name for name, _ in events] == ["token"] * 4 + ["done"]
    assert "".join(data["text"] for name, data in events if name == "token") == ANSWER
    done = events[-1][1]
    assert done["grounded"] is True
    assert done["user_message"]["content"] == QUESTION
    assert done["assistant_message"]["content"] == ANSWER
    assert done["assistant_message"]["sources"][0]["document_id"] == str(document_id)
    saved = await _saved(env, headers, conversation_id)
    assert saved["items"][1] == done["assistant_message"]  # what was streamed is what was saved
    assert saved["items"][0] == done["user_message"]
    assert (await env.client.get(f"{CONVERSATIONS}/{conversation_id}", headers=headers)).json()[
        "title"
    ] == QUESTION


async def test_the_final_text_drops_citations_the_model_invented(env: ChatEnv) -> None:
    headers, user_id = await _login(env, "ada@example.com")
    _document(env, user_id, "handbook.txt", [CHUNK])
    conversation_id = await _conversation(env, headers)
    env.llm.replies.append("Every ninety days [1] and also yearly [7].")

    events = _sse((await _stream(env, headers, conversation_id)).text)

    streamed = "".join(data["text"] for name, data in events if name == "token")
    assert "[7]" in streamed  # the live preview cannot know yet
    done = events[-1][1]
    assert "[7]" not in done["assistant_message"]["content"]
    assert [s["number"] for s in done["assistant_message"]["sources"]] == [1]
    assert "[7]" not in (await _saved(env, headers, conversation_id))["items"][1]["content"]


async def test_a_stream_without_relevant_documents_never_calls_the_model(env: ChatEnv) -> None:
    headers, user_id = await _login(env, "ada@example.com")
    _document(env, user_id, "handbook.txt", [CHUNK])
    conversation_id = await _conversation(env, headers)

    events = _sse((await _stream(env, headers, conversation_id, "Who won the match?")).text)

    assert [name for name, _ in events] == ["token", "done"]
    assert events[0][1]["text"] == NOT_FOUND_ANSWER
    assert events[1][1]["grounded"] is False
    assert events[1][1]["assistant_message"]["sources"] == []
    assert env.llm.calls == []
    assert (await _saved(env, headers, conversation_id))["total"] == 2


async def test_problems_found_before_the_first_token_are_ordinary_http_errors(
    env: ChatEnv,
) -> None:
    headers, user_id = await _login(env, "ada@example.com")
    _document(env, user_id, "handbook.txt", [CHUNK])
    conversation_id = await _conversation(env, headers)

    unknown = await _stream(env, headers, str(uuid.uuid4()))
    env.llm.replies.append(LLMError("rejected"))
    rejected = await _stream(env, headers, conversation_id)
    env.llm.replies.append(LLMUnavailableError("busy"))
    busy = await _stream(env, headers, conversation_id)

    assert unknown.status_code == 404
    assert rejected.status_code == busy.status_code == 503
    for response in (unknown, rejected, busy):
        assert response.headers["content-type"].startswith("application/json")
        assert set(response.json()["error"]) == {"code", "message"}
    assert (await _saved(env, headers, conversation_id))["total"] == 0


async def test_a_failure_midway_ends_the_stream_with_an_error_event_and_saves_nothing(
    env: ChatEnv,
) -> None:
    headers, user_id = await _login(env, "ada@example.com")
    _document(env, user_id, "handbook.txt", [CHUNK])
    conversation_id = await _conversation(env, headers)
    env.llm.replies.append("Every ninety days [1].")
    env.llm.fail_after_first_piece = LLMUnavailableError("connection reset secret-detail")

    response = await _stream(env, headers, conversation_id)

    assert response.status_code == 200  # the status was already sent with the first token
    events = _sse(response.text)
    assert [name for name, _ in events] == ["token", "error"]
    error = events[-1][1]["error"]
    assert error["code"] == "service_unavailable"
    assert "secret-detail" not in response.text
    assert (await _saved(env, headers, conversation_id))["total"] == 0
    assert (await env.client.get(f"{CONVERSATIONS}/{conversation_id}", headers=headers)).json()[
        "title"
    ] == "New conversation"
