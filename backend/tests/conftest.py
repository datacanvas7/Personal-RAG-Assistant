"""Shared test configuration.

Environment variables are set *before* the application is imported, because settings are
read on first use and the secrets have no defaults.

Unit tests never connect to PostgreSQL, Redis or an LLM. Tests under ``tests/integration``
need a real database and run only when ``POSTGRES_DB`` names a throwaway ``*_test``
database (CI does; see ``tests/integration/conftest.py``).
"""

import os
import sys

import pytest

os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("POSTGRES_PASSWORD", "test-password")
os.environ.setdefault("JWT_SECRET_KEY", "test-only-secret-key-not-for-real-use-0123456789")


@pytest.fixture(autouse=True)
def _no_embedding_index_check_on_startup(monkeypatch: pytest.MonkeyPatch) -> None:
    """Starting the app in a test must not read whatever database the environment points at.

    In CI the integration tests leave rows behind (embedded with a fake model), and the real
    startup guard would rightly refuse them. The guard itself is covered by
    ``test_embedding_guard.py`` and ``tests/integration/test_search.py``.
    """

    async def _skip() -> None:
        return None

    monkeypatch.setattr("app.main._check_embedding_index", _skip)


def _annotate(title: str, details: str) -> None:
    """Emit a GitHub Actions error annotation, visible on the run page without raw logs.

    Written to the real stdout: pytest captures ``sys.stdout`` while a test runs, so a plain
    ``print`` from inside a hook would never reach the log.
    """
    tail = "\n".join(details.strip().splitlines()[-40:])[-4000:]
    tail = tail.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
    sys.__stdout__.write(f"\n::error title={title}::{tail}\n")  # type: ignore[union-attr]
    sys.__stdout__.flush()  # type: ignore[union-attr]


def pytest_runtest_logreport(report: pytest.TestReport) -> None:
    if report.failed and os.environ.get("GITHUB_ACTIONS") == "true":
        _annotate(f"{report.nodeid} ({report.when})", report.longreprtext)


def pytest_collectreport(report: pytest.CollectReport) -> None:
    if report.failed and os.environ.get("GITHUB_ACTIONS") == "true":
        _annotate(f"{report.nodeid} (collection)", report.longreprtext)
