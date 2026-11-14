"""POST /ask against real PostgreSQL + pgvector, with a scripted language model.

The point: whatever the model is told is built only from the caller's own chunks, and a user
with no relevant documents gets "not found" without the model being called at all.
"""

from app.api.deps import get_llm
from app.rag.prompt_builder import NOT_FOUND_ANSWER
from tests.fakes import FakeLLM
from tests.integration.test_documents_flow import Stack, _login, _upload, stack  # noqa: F401

ASK = "/api/v1/ask"


async def test_ask_answers_from_the_owners_documents_with_sources(stack: Stack) -> None:  # noqa: F811
    llm = FakeLLM("Passwords are reset every ninety days [1].")
    stack.app.dependency_overrides[get_llm] = lambda: llm
    ada = await _login(stack.client, "ada@example.com")
    text = "Passwords must be reset every ninety days. " * 12
    await _upload(stack, ada, "security.txt", text.encode())

    response = await stack.client.post(
        ASK, headers=ada, json={"question": "Passwords must be reset every ninety days?"}
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["grounded"] is True
    assert body["answer"] == "Passwords are reset every ninety days [1]."
    assert body["sources"][0]["filename"] == "security.txt"
    assert body["sources"][0]["number"] == 1
    assert "reset every ninety days" in llm.calls[0][-1].content


async def test_another_users_documents_never_reach_the_model(stack: Stack) -> None:  # noqa: F811
    llm = FakeLLM()
    stack.app.dependency_overrides[get_llm] = lambda: llm
    ada = await _login(stack.client, "ada@example.com")
    bob = await _login(stack.client, "bob@example.com")
    secret = "The launch code is swordfish. " * 12
    await _upload(stack, ada, "secret.txt", secret.encode())

    as_bob = await stack.client.post(
        ASK, headers=bob, json={"question": "The launch code is swordfish?"}
    )

    assert as_bob.status_code == 200
    assert as_bob.json()["answer"] == NOT_FOUND_ANSWER
    assert as_bob.json()["sources"] == []
    assert llm.calls == []
    assert "swordfish" not in as_bob.text
