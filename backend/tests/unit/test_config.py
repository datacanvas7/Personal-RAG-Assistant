from app.core.config import Settings
from app.workers.tasks import ping


def test_database_url_escapes_special_characters_in_the_password() -> None:
    settings = Settings(postgres_password="p@ss/w:rd#1")

    rendered = settings.database_url.render_as_string(hide_password=False)

    assert rendered.startswith("postgresql+psycopg://rag:")
    # Exactly one unescaped "@" must remain: the one separating credentials from host.
    assert rendered.count("@") == 1
    assert settings.database_url.password == "p@ss/w:rd#1"


def test_password_is_not_exposed_by_repr() -> None:
    settings = Settings(postgres_password="super-secret")

    assert "super-secret" not in repr(settings)


def test_cors_origins_are_parsed_and_trimmed() -> None:
    settings = Settings(
        postgres_password="x",
        backend_cors_origins=" http://localhost:3000 ,https://example.com,, ",
    )

    assert settings.cors_origins == ["http://localhost:3000", "https://example.com"]


def test_cors_is_disabled_by_default() -> None:
    assert Settings(postgres_password="x").cors_origins == []


def test_ping_task_returns_pong() -> None:
    assert ping() == "pong"
