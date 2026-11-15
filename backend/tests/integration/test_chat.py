"""Chat and analytics against real PostgreSQL + pgvector, with a scripted language model.

What only a real database can prove: ownership is enforced by the SQL itself (another user's
conversation is a 404 and its rows are untouched), a question and its answer are saved together
with their sources in one transaction, deleting a conversation cascades, deleting a document
keeps the citation text but nulls the links, and the analytics counts add up.
"""

import json
from typing import Any

from sqlalchemy import Engine, text

from app.api.deps import get_llm
from app.llm.base import LLMUnavailableError
from app.rag.prompt_builder import NOT_FOUND_ANSWER
from tests.fakes import FakeLLM
from tests.integration.test_documents_flow import Stack, _login, _upload, stack  # noqa: F401

CHAT = "/api/v1/chat"
CONVERSATIONS = f"{CHAT}/conversations"
TEXT = "Passwords must be reset every ninety days. " * 12
QUESTION = "Passwords must be reset every ninety days?"


def _count(engine: Engine, table: str) -> int:
    with engine.connect() as conn:
        return int(conn.execute(text(f"SELECT count(*) FROM {table}")).scalar_one())  # noqa: S608


def _sse(body: str) -> list[tuple[str, dict[str, Any]]]:
    events = []
    for block in body.strip().split("\n\n"):
        name, data = block.splitlines()
        events.append((name.removeprefix("event: "), json.loads(data.removeprefix("data: "))))
    return events


async def _new_conversation(stack: Stack, headers: dict[str, str]) -> str:  # noqa: F811
    response = await stack.client.post(CONVERSATIONS, headers=headers, json={})
    assert response.status_code == 201, response.text
    return str(response.json()["id"])


async def _setup(stack: Stack, llm: FakeLLM) -> tuple[dict[str, str], str]:  # noqa: F811
    stack.app.dependency_overrides[get_llm] = lambda: llm
    ada = await _login(stack.client, "ada@example.com")
    await _upload(stack, ada, "security.txt", TEXT.encode())
    return ada, await _new_conversation(stack, ada)


async def test_conversation_crud_and_paging(stack: Stack) -> None:  # noqa: F811
    ada = await _login(stack.client, "ada@example.com")
    ids = []
    for title in ("one", "two", "three"):
        created = await stack.client.post(CONVERSATIONS, headers=ada, json={"title": title})
        ids.append(created.json()["id"])

    first_page = (await stack.client.get(f"{CONVERSATIONS}?limit=2", headers=ada)).json()
    second_page = (await stack.client.get(f"{CONVERSATIONS}?limit=2&offset=2", headers=ada)).json()

    assert first_page["total"] == 3
    assert len(first_page["items"]) == 2
    assert len(second_page["items"]) == 1
    seen = [c["id"] for c in first_page["items"] + second_page["items"]]
    assert sorted(seen) == sorted(ids)

    renamed = await stack.client.patch(
        f"{CONVERSATIONS}/{ids[0]}", headers=ada, json={"title": "x"}
    )
    assert renamed.json()["title"] == "x"
    deleted = await stack.client.delete(f"{CONVERSATIONS}/{ids[0]}", headers=ada)
    assert deleted.status_code == 204
    assert (await stack.client.get(f"{CONVERSATIONS}/{ids[0]}", headers=ada)).status_code == 404


async def test_another_users_conversation_is_invisible_and_untouched(stack: Stack) -> None:  # noqa: F811
    llm = FakeLLM("Passwords are reset every ninety days [1].")
    ada, conversation = await _setup(stack, llm)
    sent = await stack.client.post(
        f"{CHAT}/{conversation}/messages", headers=ada, json={"content": QUESTION}
    )
    assert sent.status_code == 201, sent.text
    bob = await _login(stack.client, "bob@example.com")
    before = (_count(stack.engine, "messages"), _count(stack.engine, "message_sources"))

    attempts = [
        await stack.client.get(f"{CONVERSATIONS}/{conversation}", headers=bob),
        await stack.client.get(f"{CONVERSATIONS}/{conversation}/messages", headers=bob),
        await stack.client.patch(
            f"{CONVERSATIONS}/{conversation}", headers=bob, json={"title": "x"}
        ),
        await stack.client.post(
            f"{CHAT}/{conversation}/messages", headers=bob, json={"content": QUESTION}
        ),
        await stack.client.post(
            f"{CHAT}/{conversation}/stream", headers=bob, json={"content": QUESTION}
        ),
        await stack.client.delete(f"{CONVERSATIONS}/{conversation}", headers=bob),
    ]

    assert [r.status_code for r in attempts] == [404] * 6
    assert (await stack.client.get(CONVERSATIONS, headers=bob)).json()["total"] == 0
    assert len(llm.calls) == 1  # only Ada's own question ever reached the model
    assert (_count(stack.engine, "messages"), _count(stack.engine, "message_sources")) == before
    assert (
        await stack.client.get(f"{CONVERSATIONS}/{conversation}", headers=ada)
    ).status_code == 200


async def test_send_saves_question_answer_and_sources_together(stack: Stack) -> None:  # noqa: F811
    llm = FakeLLM("Passwords are reset every ninety days [1].")
    ada, conversation = await _setup(stack, llm)

    sent = await stack.client.post(
        f"{CHAT}/{conversation}/messages", headers=ada, json={"content": QUESTION}
    )

    assert sent.status_code == 201, sent.text
    assert sent.json()["grounded"] is True
    history = (
        await stack.client.get(f"{CONVERSATIONS}/{conversation}/messages", headers=ada)
    ).json()
    assert [m["role"] for m in history["items"]] == ["user", "assistant"]
    assert history["items"][0]["content"] == QUESTION
    [source] = history["items"][1]["sources"]
    assert source["number"] == 1
    assert source["filename"] == "security.txt"
    assert source["document_id"] is not None
    assert (await stack.client.get(f"{CONVERSATIONS}/{conversation}", headers=ada)).json()[
        "title"
    ] == QUESTION[:200]


async def test_a_failed_model_call_saves_nothing(stack: Stack) -> None:  # noqa: F811
    llm = FakeLLM(LLMUnavailableError("down"))
    ada, conversation = await _setup(stack, llm)

    sent = await stack.client.post(
        f"{CHAT}/{conversation}/messages", headers=ada, json={"content": QUESTION}
    )

    assert sent.status_code == 503
    assert _count(stack.engine, "messages") == 0
    assert _count(stack.engine, "message_sources") == 0


async def test_stream_saves_after_the_last_token(stack: Stack) -> None:  # noqa: F811
    llm = FakeLLM("Passwords are reset every ninety days [1].")
    ada, conversation = await _setup(stack, llm)

    response = await stack.client.post(
        f"{CHAT}/{conversation}/stream", headers=ada, json={"content": QUESTION}
    )

    assert response.status_code == 200
    events = _sse(response.text)
    assert [name for name, _ in events[:-1]] == ["token"] * (len(events) - 1)
    name, done = events[-1]
    assert name == "done"
    assert "".join(data["text"] for _, data in events[:-1]) == done["assistant_message"]["content"]
    assert _count(stack.engine, "messages") == 2
    assert _count(stack.engine, "message_sources") == 1


async def test_stream_failure_after_the_first_token_saves_nothing(stack: Stack) -> None:  # noqa: F811
    llm = FakeLLM("Passwords are reset every ninety days [1].")
    llm.fail_after_first_piece = LLMUnavailableError("dropped")
    ada, conversation = await _setup(stack, llm)

    response = await stack.client.post(
        f"{CHAT}/{conversation}/stream", headers=ada, json={"content": QUESTION}
    )

    assert response.status_code == 200
    names = [name for name, _ in _sse(response.text)]
    assert names[0] == "token"
    assert names[-1] == "error"
    assert _count(stack.engine, "messages") == 0


async def test_unanswerable_question_is_saved_as_not_found_without_sources(stack: Stack) -> None:  # noqa: F811
    llm = FakeLLM()
    ada, conversation = await _setup(stack, llm)

    sent = await stack.client.post(
        f"{CHAT}/{conversation}/messages", headers=ada, json={"content": "zebra quantum banana?"}
    )

    assert sent.status_code == 201
    assert sent.json()["assistant_message"]["content"] == NOT_FOUND_ANSWER
    assert sent.json()["grounded"] is False
    assert llm.calls == []
    assert _count(stack.engine, "message_sources") == 0


async def test_deleting_a_conversation_removes_its_messages_and_sources(stack: Stack) -> None:  # noqa: F811
    llm = FakeLLM("Passwords are reset every ninety days [1].")
    ada, conversation = await _setup(stack, llm)
    await stack.client.post(
        f"{CHAT}/{conversation}/messages", headers=ada, json={"content": QUESTION}
    )
    assert _count(stack.engine, "messages") == 2

    await stack.client.delete(f"{CONVERSATIONS}/{conversation}", headers=ada)

    assert _count(stack.engine, "messages") == 0
    assert _count(stack.engine, "message_sources") == 0


async def test_deleting_a_document_keeps_the_citation_but_unlinks_it(stack: Stack) -> None:  # noqa: F811
    llm = FakeLLM("Passwords are reset every ninety days [1].")
    ada, conversation = await _setup(stack, llm)
    await stack.client.post(
        f"{CHAT}/{conversation}/messages", headers=ada, json={"content": QUESTION}
    )
    [document] = (await stack.client.get("/api/v1/documents", headers=ada)).json()["items"]

    deleted = await stack.client.delete(f"/api/v1/documents/{document['id']}", headers=ada)

    assert deleted.status_code == 204
    history = (
        await stack.client.get(f"{CONVERSATIONS}/{conversation}/messages", headers=ada)
    ).json()
    [source] = history["items"][1]["sources"]
    assert source["filename"] == "security.txt"
    assert source["document_id"] is None
    assert source["chunk_id"] is None


async def test_analytics_overview_counts_only_the_callers_data(stack: Stack) -> None:  # noqa: F811
    llm = FakeLLM("Passwords are reset every ninety days [1].")
    ada, conversation = await _setup(stack, llm)
    await stack.client.post(
        f"{CHAT}/{conversation}/messages", headers=ada, json={"content": QUESTION}
    )
    bob = await _login(stack.client, "bob@example.com")
    await _upload(stack, bob, "bobs.txt", b"Bob's notes are long enough to chunk. " * 12)
    await _new_conversation(stack, bob)

    ada_view = (await stack.client.get("/api/v1/analytics/overview", headers=ada)).json()
    bob_view = (await stack.client.get("/api/v1/analytics/overview", headers=bob)).json()

    assert ada_view["documents"] == {"total": 1, "ready": 1, "processing": 0, "failed": 0}
    assert ada_view["conversations"] == 1
    assert ada_view["messages"] == 2
    assert (ada_view["questions"], ada_view["answers"], ada_view["cited_answers"]) == (1, 1, 1)
    assert ada_view["chunks"] > 0
    assert ada_view["recent_activity"]["documents_uploaded"] == 1
    assert ada_view["recent_activity"]["questions_asked"] == 1
    assert bob_view["documents"]["total"] == 1
    assert bob_view["messages"] == 0
    assert bob_view["chunks"] != 0
