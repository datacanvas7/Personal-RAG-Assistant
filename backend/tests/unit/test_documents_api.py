"""HTTP behavior of the document endpoints, with the service wired to in-memory fakes."""

import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass

import httpx2
import pytest

from app.api.deps import get_auth_service, get_document_service
from app.core.config import Settings
from app.main import create_app
from app.models import DocumentStatus
from app.services.auth import AuthService
from app.services.documents import DocumentService
from tests.fakes import (
    FakeDocumentStore,
    FakeFileStorage,
    FakeQueue,
    FakeTokenStore,
    FakeTransaction,
    FakeUserStore,
)
from tests.samples import make_pdf

PASSWORD = "a-reasonable-passphrase"
BASE = "/api/v1/documents"
SMALL_LIMIT = 2048


@dataclass
class Env:
    client: httpx2.AsyncClient
    store: FakeDocumentStore
    storage: FakeFileStorage
    queue: FakeQueue
    tx: FakeTransaction


@pytest.fixture
async def env() -> AsyncIterator[Env]:
    settings = Settings(max_upload_bytes=SMALL_LIMIT)
    store, storage, queue = FakeDocumentStore(), FakeFileStorage(), FakeQueue()
    doc_tx = FakeTransaction()
    users, tokens = FakeUserStore(), FakeTokenStore()
    app = create_app()
    app.dependency_overrides[get_auth_service] = lambda: AuthService(
        users=users, tokens=tokens, transaction=FakeTransaction(), settings=settings
    )
    app.dependency_overrides[get_document_service] = lambda: DocumentService(
        documents=store, storage=storage, queue=queue, transaction=doc_tx, settings=settings
    )
    transport = httpx2.ASGITransport(app=app)
    async with httpx2.AsyncClient(transport=transport, base_url="http://test") as client:
        yield Env(client, store, storage, queue, doc_tx)


async def _login(client: httpx2.AsyncClient, email: str) -> dict[str, str]:
    credentials = {"email": email, "password": PASSWORD}
    await client.post("/api/v1/auth/register", json=credentials)
    response = await client.post("/api/v1/auth/login", json=credentials)
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


async def _upload(
    env: Env,
    headers: dict[str, str],
    *,
    name: str = "notes.txt",
    data: bytes = b"some notes",
) -> httpx2.Response:
    return await env.client.post(
        f"{BASE}/upload", headers=headers, files={"file": (name, data, "application/octet-stream")}
    )


async def test_every_endpoint_requires_authentication(env: Env) -> None:
    some_id = uuid.uuid4()
    calls = [
        env.client.post(f"{BASE}/upload", files={"file": ("a.txt", b"x")}),
        env.client.get(BASE),
        env.client.get(f"{BASE}/{some_id}"),
        env.client.get(f"{BASE}/{some_id}/status"),
        env.client.post(f"{BASE}/{some_id}/retry"),
        env.client.delete(f"{BASE}/{some_id}"),
    ]
    for call in calls:
        response = await call
        assert response.status_code == 401


async def test_upload_accepts_the_file_and_queues_it(env: Env) -> None:
    headers = await _login(env.client, "ada@example.com")

    response = await _upload(env, headers, name="My Notes.txt")

    assert response.status_code == 202
    body = response.json()
    assert body["filename"] == "My Notes.txt"
    assert body["status"] == "pending"
    assert body["content_type"] == "text/plain"
    assert body["size_bytes"] == len(b"some notes")
    assert body["total_chunks"] is None
    assert env.queue.enqueued == [uuid.UUID(body["id"])]
    assert len(env.storage.files) == 1


async def test_responses_never_expose_the_storage_path_or_hash(env: Env) -> None:
    headers = await _login(env.client, "ada@example.com")

    body = (await _upload(env, headers)).json()

    assert set(body) == {
        "id",
        "filename",
        "content_type",
        "size_bytes",
        "status",
        "error_message",
        "total_pages",
        "total_chunks",
        "created_at",
        "updated_at",
    }


async def test_upload_of_a_pdf_works(env: Env) -> None:
    headers = await _login(env.client, "ada@example.com")

    response = await _upload(env, headers, name="doc.pdf", data=make_pdf(["hello"]))

    assert response.status_code == 202
    assert response.json()["content_type"] == "application/pdf"


@pytest.mark.parametrize(
    ("name", "data", "status", "code"),
    [
        ("virus.exe", b"MZ", 415, "unsupported_file_type"),
        ("empty.txt", b"", 400, "invalid_file"),
        ("fake.pdf", b"this is not a pdf", 400, "invalid_file"),
        ("big.txt", b"x" * (SMALL_LIMIT + 1), 413, "file_too_large"),
    ],
)
async def test_invalid_uploads_are_rejected_and_nothing_is_stored(
    env: Env, name: str, data: bytes, status: int, code: str
) -> None:
    headers = await _login(env.client, "ada@example.com")

    response = await _upload(env, headers, name=name, data=data)

    assert response.status_code == status
    assert response.json()["error"]["code"] == code
    assert env.storage.files == {}
    assert env.store.documents == {}
    assert env.queue.enqueued == []


async def test_upload_without_a_file_is_a_validation_error(env: Env) -> None:
    headers = await _login(env.client, "ada@example.com")

    response = await env.client.post(f"{BASE}/upload", headers=headers)

    assert response.status_code == 422


async def test_uploading_the_same_file_twice_is_a_conflict(env: Env) -> None:
    headers = await _login(env.client, "ada@example.com")
    await _upload(env, headers, name="a.txt", data=b"identical content")

    response = await _upload(env, headers, name="renamed.txt", data=b"identical content")

    assert response.status_code == 409
    assert len(env.store.documents) == 1
    assert len(env.storage.files) == 1


async def test_two_users_may_upload_the_same_file(env: Env) -> None:
    ada = await _login(env.client, "ada@example.com")
    bob = await _login(env.client, "bob@example.com")

    assert (await _upload(env, ada, data=b"same bytes")).status_code == 202
    assert (await _upload(env, bob, data=b"same bytes")).status_code == 202


async def test_a_lost_upload_race_cleans_up_and_reports_a_conflict(env: Env) -> None:
    headers = await _login(env.client, "ada@example.com")
    first = (await _upload(env, headers, data=b"racing content")).json()
    # Simulate the other request winning between our duplicate check and our insert.
    real_get_by_hash = env.store.get_by_hash

    async def blind(user_id: uuid.UUID, content_sha256: str) -> None:
        return None

    env.store.get_by_hash = blind  # type: ignore[method-assign]
    try:
        response = await _upload(env, headers, data=b"racing content")
    finally:
        env.store.get_by_hash = real_get_by_hash  # type: ignore[method-assign]

    assert response.status_code == 409
    assert env.tx.rollbacks == 1
    assert len(env.storage.files) == 1
    assert next(iter(env.storage.files)).endswith(f"{first['id']}.txt")


async def test_broker_outage_marks_the_document_failed_and_retry_recovers(env: Env) -> None:
    headers = await _login(env.client, "ada@example.com")
    env.queue.fail = True

    response = await _upload(env, headers)

    assert response.status_code == 202
    document_id = response.json()["id"]
    status = (await env.client.get(f"{BASE}/{document_id}/status", headers=headers)).json()
    assert status["status"] == "failed"
    assert "retry" in status["error_message"].lower()

    env.queue.fail = False
    retried = await env.client.post(f"{BASE}/{document_id}/retry", headers=headers)

    assert retried.status_code == 202
    assert retried.json()["status"] == "pending"
    assert retried.json()["error_message"] is None
    assert env.queue.enqueued == [uuid.UUID(document_id)]


async def test_only_failed_documents_can_be_retried(env: Env) -> None:
    headers = await _login(env.client, "ada@example.com")
    document_id = (await _upload(env, headers)).json()["id"]

    response = await env.client.post(f"{BASE}/{document_id}/retry", headers=headers)

    assert response.status_code == 409
    assert len(env.queue.enqueued) == 1  # only the original upload


async def test_status_endpoint_reports_progress_fields(env: Env) -> None:
    headers = await _login(env.client, "ada@example.com")
    document_id = (await _upload(env, headers)).json()["id"]
    document = env.store.documents[uuid.UUID(document_id)]
    document.status = DocumentStatus.READY
    document.total_pages = 4
    document.total_chunks = 9

    response = await env.client.get(f"{BASE}/{document_id}/status", headers=headers)

    assert response.json() == {
        "id": document_id,
        "status": "ready",
        "error_message": None,
        "total_pages": 4,
        "total_chunks": 9,
    }


async def test_list_is_paged_and_newest_first(env: Env) -> None:
    headers = await _login(env.client, "ada@example.com")
    for n in range(3):
        await _upload(env, headers, name=f"n{n}.txt", data=f"content {n}".encode())

    page = (await env.client.get(BASE, headers=headers, params={"limit": 2})).json()
    rest = (await env.client.get(BASE, headers=headers, params={"limit": 2, "offset": 2})).json()

    assert page["total"] == 3
    assert [d["filename"] for d in page["items"]] == ["n2.txt", "n1.txt"]
    assert [d["filename"] for d in rest["items"]] == ["n0.txt"]
    assert (page["limit"], page["offset"]) == (2, 0)


@pytest.mark.parametrize("params", [{"limit": 0}, {"limit": 101}, {"offset": -1}])
async def test_list_rejects_bad_paging(env: Env, params: dict[str, int]) -> None:
    headers = await _login(env.client, "ada@example.com")

    response = await env.client.get(BASE, headers=headers, params=params)

    assert response.status_code == 422


async def test_users_cannot_see_or_touch_each_others_documents(env: Env) -> None:
    ada = await _login(env.client, "ada@example.com")
    bob = await _login(env.client, "bob@example.com")
    document_id = (await _upload(env, ada)).json()["id"]

    attempts = [
        await env.client.get(f"{BASE}/{document_id}", headers=bob),
        await env.client.get(f"{BASE}/{document_id}/status", headers=bob),
        await env.client.post(f"{BASE}/{document_id}/retry", headers=bob),
        await env.client.delete(f"{BASE}/{document_id}", headers=bob),
    ]

    # "Not found", not "forbidden": the response must not reveal that the id exists.
    assert [r.status_code for r in attempts] == [404, 404, 404, 404]
    assert all(r.json()["error"]["code"] == "not_found" for r in attempts)
    assert (await env.client.get(BASE, headers=bob)).json()["items"] == []
    assert (await env.client.get(f"{BASE}/{document_id}", headers=ada)).status_code == 200
    assert len(env.storage.files) == 1


async def test_unknown_and_malformed_ids(env: Env) -> None:
    headers = await _login(env.client, "ada@example.com")

    missing = await env.client.get(f"{BASE}/{uuid.uuid4()}", headers=headers)
    malformed = await env.client.get(f"{BASE}/not-a-uuid", headers=headers)

    assert missing.status_code == 404
    assert malformed.status_code == 422


async def test_delete_removes_the_record_and_the_file(env: Env) -> None:
    headers = await _login(env.client, "ada@example.com")
    document_id = (await _upload(env, headers)).json()["id"]

    response = await env.client.delete(f"{BASE}/{document_id}", headers=headers)

    assert response.status_code == 204
    assert env.store.documents == {}
    assert env.storage.files == {}
    assert (await env.client.get(f"{BASE}/{document_id}", headers=headers)).status_code == 404


async def test_delete_succeeds_even_if_the_file_cannot_be_removed(env: Env) -> None:
    headers = await _login(env.client, "ada@example.com")
    document_id = (await _upload(env, headers)).json()["id"]
    env.storage.fail_delete = True

    response = await env.client.delete(f"{BASE}/{document_id}", headers=headers)

    assert response.status_code == 204
    assert env.store.documents == {}
