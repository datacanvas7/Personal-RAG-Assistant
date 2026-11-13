"""Properties the database itself must guarantee, independent of application code."""

import uuid

import pytest
from sqlalchemy import Connection, Engine, text
from sqlalchemy.exc import DataError, IntegrityError

from app.core.config import get_settings


def _user(conn: Connection, email: str = "a@example.com") -> uuid.UUID:
    new_id: uuid.UUID = conn.execute(
        text("INSERT INTO users (email, password_hash) VALUES (:e, 'x') RETURNING id"),
        {"e": email},
    ).scalar_one()
    return new_id


def _document(conn: Connection, user_id: uuid.UUID) -> uuid.UUID:
    new_id: uuid.UUID = conn.execute(
        text(
            "INSERT INTO documents (user_id, filename, content_type, size_bytes, storage_path,"
            " content_sha256) VALUES (:u, 'f.txt', 'text/plain', 1, 'p', 'h') RETURNING id"
        ),
        {"u": user_id},
    ).scalar_one()
    return new_id


def _conversation(conn: Connection, user_id: uuid.UUID) -> uuid.UUID:
    new_id: uuid.UUID = conn.execute(
        text("INSERT INTO conversations (user_id, title) VALUES (:u, 't') RETURNING id"),
        {"u": user_id},
    ).scalar_one()
    return new_id


def test_email_must_be_lowercase(migrated_engine: Engine) -> None:
    with (
        pytest.raises(IntegrityError, match="ck_users_email_lowercase"),
        migrated_engine.begin() as c,
    ):
        _user(c, "Mixed@Example.com")


def test_email_is_unique(migrated_engine: Engine) -> None:
    with pytest.raises(IntegrityError, match="uq_users_email"), migrated_engine.begin() as c:
        _user(c)
        _user(c)


def test_document_status_is_restricted(migrated_engine: Engine) -> None:
    with pytest.raises(IntegrityError, match="ck_documents_status"), migrated_engine.begin() as c:
        user = _user(c)
        c.execute(
            text(
                "INSERT INTO documents (user_id, filename, content_type, size_bytes,"
                " storage_path, content_sha256, status)"
                " VALUES (:u, 'f', 't', 1, 'p', 'h', 'bogus')"
            ),
            {"u": user},
        )


def test_chunk_cannot_belong_to_a_different_user_than_its_document(
    migrated_engine: Engine,
) -> None:
    with (
        pytest.raises(IntegrityError, match="fk_document_chunks_document_id_documents"),
        migrated_engine.begin() as c,
    ):
        owner = _user(c, "owner@example.com")
        intruder = _user(c, "intruder@example.com")
        document = _document(c, owner)
        c.execute(
            text(
                "INSERT INTO document_chunks (user_id, document_id, chunk_index, content)"
                " VALUES (:u, :d, 0, 'x')"
            ),
            {"u": intruder, "d": document},
        )


def test_message_cannot_be_added_to_another_users_conversation(migrated_engine: Engine) -> None:
    with (
        pytest.raises(IntegrityError, match="fk_messages_conversation_id_conversations"),
        migrated_engine.begin() as c,
    ):
        owner = _user(c, "owner@example.com")
        intruder = _user(c, "intruder@example.com")
        conversation = _conversation(c, owner)
        c.execute(
            text(
                "INSERT INTO messages (user_id, conversation_id, role, content)"
                " VALUES (:u, :c, 'user', 'hi')"
            ),
            {"u": intruder, "c": conversation},
        )


def test_embedding_dimension_is_enforced(migrated_engine: Engine) -> None:
    dimension = get_settings().embedding_dimension
    insert = text(
        "INSERT INTO document_chunks (user_id, document_id, chunk_index, content, embedding)"
        " VALUES (:u, :d, :i, 'x', CAST(:v AS vector))"
    )
    with migrated_engine.begin() as c:
        user = _user(c)
        document = _document(c, user)
        c.execute(insert, {"u": user, "d": document, "i": 0, "v": str([0.1] * dimension)})

    with pytest.raises(DataError), migrated_engine.begin() as c:
        c.execute(
            insert,
            {"u": user, "d": document, "i": 1, "v": str([0.1] * (dimension + 1))},
        )


def test_deleting_a_user_removes_everything_they_own(migrated_engine: Engine) -> None:
    with migrated_engine.begin() as c:
        user = _user(c)
        document = _document(c, user)
        conversation = _conversation(c, user)
        c.execute(
            text(
                "INSERT INTO document_chunks (user_id, document_id, chunk_index, content)"
                " VALUES (:u, :d, 0, 'x')"
            ),
            {"u": user, "d": document},
        )
        c.execute(
            text(
                "INSERT INTO messages (user_id, conversation_id, role, content)"
                " VALUES (:u, :c, 'user', 'hi')"
            ),
            {"u": user, "c": conversation},
        )
        c.execute(
            text(
                "INSERT INTO refresh_tokens (user_id, family_id, token_hash, expires_at)"
                " VALUES (:u, gen_random_uuid(), 'h', now())"
            ),
            {"u": user},
        )

        c.execute(text("DELETE FROM users WHERE id = :u"), {"u": user})

        tables = ("documents", "document_chunks", "conversations", "messages", "refresh_tokens")
        for table in tables:
            assert c.execute(text(f"SELECT count(*) FROM {table}")).scalar_one() == 0  # noqa: S608


def test_deleting_a_document_keeps_the_citation_snapshot(migrated_engine: Engine) -> None:
    with migrated_engine.begin() as c:
        user = _user(c)
        document = _document(c, user)
        conversation = _conversation(c, user)
        chunk = c.execute(
            text(
                "INSERT INTO document_chunks (user_id, document_id, chunk_index, content)"
                " VALUES (:u, :d, 0, 'x') RETURNING id"
            ),
            {"u": user, "d": document},
        ).scalar_one()
        message = c.execute(
            text(
                "INSERT INTO messages (user_id, conversation_id, role, content)"
                " VALUES (:u, :c, 'assistant', 'answer') RETURNING id"
            ),
            {"u": user, "c": conversation},
        ).scalar_one()
        c.execute(
            text(
                "INSERT INTO message_sources (user_id, message_id, chunk_id, document_id,"
                " position, document_filename, page_number, score)"
                " VALUES (:u, :m, :ch, :d, 1, 'f.txt', 3, 0.9)"
            ),
            {"u": user, "m": message, "ch": chunk, "d": document},
        )

        c.execute(text("DELETE FROM documents WHERE id = :d"), {"d": document})

        row = c.execute(
            text(
                "SELECT chunk_id, document_id, document_filename, page_number FROM message_sources"
            )
        ).one()
        assert tuple(row) == (None, None, "f.txt", 3)
        assert c.execute(text("SELECT count(*) FROM document_chunks")).scalar_one() == 0
