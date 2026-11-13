"""Shared test configuration.

Environment variables are set *before* the application is imported, because settings are
read on first use and the secrets have no defaults.

Unit tests never connect to PostgreSQL, Redis or an LLM. Tests under ``tests/integration``
need a real database and run only when ``POSTGRES_DB`` names a throwaway ``*_test``
database (CI does; see ``tests/integration/conftest.py``).
"""

import os
from collections.abc import Generator
from typing import Any

import pytest

os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("POSTGRES_PASSWORD", "test-password")
os.environ.setdefault("JWT_SECRET_KEY", "test-only-secret-key-not-for-real-use-0123456789")


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item: pytest.Item, call: pytest.CallInfo[None]) -> Generator[None]:
    """On GitHub Actions, turn a failing test into an inline annotation on the run page,
    so the cause is visible without opening the raw log."""
    outcome: Any = yield
    report = outcome.get_result()
    if report.failed and os.environ.get("GITHUB_ACTIONS") == "true":
        message = (call.excinfo.exconly() if call.excinfo else "failed").splitlines()[0]
        # Workflow-command values must escape %, CR and LF.
        message = message.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
        print(f"::error title={item.nodeid}::{message}")
