"""Pytest configuration and fixtures for QueryMind tests.

Integration fixtures that require a real MySQL connection are guarded so
unit tests run without any database credentials.
"""

from __future__ import annotations

import os

import pytest
from sqlalchemy import create_engine, text


def _admin_url() -> str:
    host = os.getenv("MYSQL_HOST", "localhost")
    port = os.getenv("MYSQL_PORT", "3306")
    user = os.getenv("MYSQL_ROOT_USER", "root")
    password = os.getenv("MYSQL_ROOT_PASSWORD", "")
    return f"mysql+pymysql://{user}:{password}@{host}:{port}/"


@pytest.fixture
def admin_url() -> str:
    return _admin_url()


@pytest.fixture
def mysql_available(admin_url: str) -> bool:
    """True if a MySQL server is reachable with the configured admin creds."""
    try:
        engine = create_engine(admin_url, connect_args={"connect_timeout": 3})
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


@pytest.fixture
def app_url() -> str:
    host = os.getenv("DB_HOST", "localhost")
    port = os.getenv("DB_PORT", "3306")
    user = os.getenv("DB_USER", "querymind_app")
    password = os.getenv("DB_PASSWORD", "")
    name = os.getenv("DB_NAME", "querymind_db")
    return f"mysql+pymysql://{user}:{password}@{host}:{port}/{name}"
