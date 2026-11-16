"""User settings against real PostgreSQL: the upsert, the constraints, isolation, the cascade,
and that a saved preference really changes what /ask retrieves."""

from sqlalchemy import text

from app.api.deps import get_llm
from app.rag.prompt_builder import NOT_FOUND_ANSWER
from tests.fakes import FakeLLM
from tests.integration.test_documents_flow import Stack, _login, _upload, stack  # noqa: F401

SETTINGS = "/api/v1/settings"
ASK = "/api/v1/ask"


def _rows(stack: Stack) -> list[tuple[str, str, int | None, float | None]]:  # noqa: F811
    with stack.engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT u.email, s.theme, s.retrieval_top_k, s.retrieval_score_threshold "
                "FROM user_settings s JOIN users u ON u.id = s.user_id ORDER BY u.email"
            )
        ).all()
    return [(r.email, r.theme, r.retrieval_top_k, r.retrieval_score_threshold) for r in rows]


async def test_first_and_later_saves_share_one_row_and_keep_other_fields(stack: Stack) -> None:  # noqa: F811
    ada = await _login(stack.client, "ada@example.com")

    assert _rows(stack) == []  # reading creates nothing
    await stack.client.get(SETTINGS, headers=ada)
    assert _rows(stack) == []

    await stack.client.patch(SETTINGS, headers=ada, json={"theme": "dark"})
    await stack.client.patch(SETTINGS, headers=ada, json={"retrieval_top_k": 7})
    await stack.client.patch(SETTINGS, headers=ada, json={"retrieval_score_threshold": 0.0})

    assert _rows(stack) == [("ada@example.com", "dark", 7, 0.0)]
    body = (await stack.client.get(SETTINGS, headers=ada)).json()
    assert (body["theme"], body["retrieval_top_k"], body["retrieval_score_threshold"]) == (
        "dark",
        7,
        0.0,
    )

    await stack.client.patch(SETTINGS, headers=ada, json={"retrieval_top_k": None})
    assert _rows(stack) == [("ada@example.com", "dark", None, 0.0)]


async def test_each_user_has_their_own_row(stack: Stack) -> None:  # noqa: F811
    ada = await _login(stack.client, "ada@example.com")
    bob = await _login(stack.client, "bob@example.com")

    await stack.client.patch(SETTINGS, headers=ada, json={"theme": "dark"})
    await stack.client.patch(SETTINGS, headers=bob, json={"theme": "light"})

    assert _rows(stack) == [
        ("ada@example.com", "dark", None, None),
        ("bob@example.com", "light", None, None),
    ]
    assert (await stack.client.get(SETTINGS, headers=ada)).json()["theme"] == "dark"


async def test_the_database_itself_refuses_out_of_range_values(stack: Stack) -> None:  # noqa: F811
    await _login(stack.client, "ada@example.com")
    bad_rows = [
        "theme = 'purple'",
        "retrieval_top_k = 0",
        "retrieval_top_k = 21",
        "retrieval_score_threshold = 1.5",
        "retrieval_score_threshold = -0.5",
    ]
    for assignment in bad_rows:
        with stack.engine.connect() as conn:
            try:
                conn.execute(
                    text(
                        "INSERT INTO user_settings (user_id) SELECT id FROM users "
                        "ON CONFLICT DO NOTHING"
                    )
                )
                conn.execute(text(f"UPDATE user_settings SET {assignment}"))  # noqa: S608
            except Exception as error:  # noqa: BLE001
                assert "violates check constraint" in str(error), assignment
            else:
                raise AssertionError(f"accepted: {assignment}")


async def test_deleting_the_user_deletes_their_settings(stack: Stack) -> None:  # noqa: F811
    ada = await _login(stack.client, "ada@example.com")
    await stack.client.patch(SETTINGS, headers=ada, json={"theme": "dark"})

    with stack.engine.begin() as conn:
        conn.execute(text("DELETE FROM users WHERE email = 'ada@example.com'"))

    assert _rows(stack) == []


async def test_a_saved_threshold_changes_what_ask_finds(stack: Stack) -> None:  # noqa: F811
    llm = FakeLLM("Every ninety days [1].")
    stack.app.dependency_overrides[get_llm] = lambda: llm
    ada = await _login(stack.client, "ada@example.com")
    chunk = "Passwords must be reset every ninety days. " * 12
    await _upload(stack, ada, "policy.txt", chunk.encode())
    # Shares most, but not all, words with the passage: relevant by default, never a perfect match.
    question = {"question": "How often must passwords be reset?"}

    before = await stack.client.post(ASK, headers=ada, json=question)
    await stack.client.patch(SETTINGS, headers=ada, json={"retrieval_score_threshold": 0.99})
    strict = await stack.client.post(ASK, headers=ada, json=question)
    await stack.client.patch(SETTINGS, headers=ada, json={"retrieval_score_threshold": None})
    after = await stack.client.post(ASK, headers=ada, json=question)

    assert before.json()["grounded"] is True
    assert strict.json()["answer"] == NOT_FOUND_ANSWER
    assert after.json()["grounded"] is True
