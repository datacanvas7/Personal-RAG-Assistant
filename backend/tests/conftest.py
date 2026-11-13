"""Shared test configuration.

Environment variables are set *before* the application is imported, because the
settings object is created at import time and the database password has no default.
Tests never connect to a real PostgreSQL, Redis or LLM.
"""

import os

os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("POSTGRES_PASSWORD", "test-password")
