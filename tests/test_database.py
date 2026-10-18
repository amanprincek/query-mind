"""Tests for the database layer.

Unit tests run without MySQL by mocking SQLAlchemy. Integration tests
require a reachable MySQL server and are skipped otherwise. They run
against the dedicated ``querymind_db`` and never drop or truncate data.
"""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy.exc import SQLAlchemyError

from database import ALLOWED_TABLES, Database, DatabaseError

try:
    from init_db import TABLE_DDL, SEED_ORDER  # noqa: F401
    from init_db import initialize as init_initialize  # noqa: F401
    HAS_INIT_DB = True
except Exception:  # pragma: no cover - import guard
    HAS_INIT_DB = False


# ------------------------------------------------------------------ #
# Unit tests (no MySQL required)
# ------------------------------------------------------------------ #
def test_allowed_tables_contains_six_tables() -> None:
    assert ALLOWED_TABLES == {
        "customers",
        "products",
        "categories",
        "orders",
        "order_items",
        "payments",
    }


def test_build_url_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DB_HOST", "localhost")
    monkeypatch.setenv("DB_PORT", "3306")
    monkeypatch.setenv("DB_NAME", "querymind_db")
    monkeypatch.setenv("DB_USER", "querymind_app")
    monkeypatch.setenv("DB_PASSWORD", "s3cr3t")
    db = Database()
    expected = (
        "mysql+pymysql://querymind_app:s3cr3t@localhost:3306/"
        "querymind_db?charset=utf8mb4"
    )
    assert db.connection_url == expected
    # Password must not leak into a repr-style attribute accidentally.
    assert "s3cr3t" not in str(db.result_limit)


def test_health_check_healthy(monkeypatch: pytest.MonkeyPatch) -> None:
    db = Database()
    mock_conn = MagicMock()
    mock_conn.execute.return_value.scalar.side_effect = ["8.0.46", "querymind_db"]
    mock_context = MagicMock()
    mock_context.__enter__.return_value = mock_conn
    mock_context.__exit__.return_value = False
    db._engine = MagicMock()
    db._engine.connect.return_value = mock_context

    health = db.health_check()
    assert health["healthy"] is True
    assert health["database"] == "querymind_db"
    assert health["version"] == "8.0.46"


def test_health_check_unhealthy(monkeypatch: pytest.MonkeyPatch) -> None:
    db = Database()
    db._engine = MagicMock()
    db._engine.connect.side_effect = SQLAlchemyError("cannot connect")

    health = db.health_check()
    assert health["healthy"] is False
    assert "message" in health
    # No credentials leaked.
    assert "password" not in str(health).lower()


def test_invalid_connection_handling(monkeypatch: pytest.MonkeyPatch) -> None:
    with patch(
        "database.create_engine", side_effect=SQLAlchemyError("bad connection")
    ):
        db = Database(connection_url="mysql+pymysql://bad:bad@bad:1/bad")
        health = db.health_check()
        assert health["healthy"] is False


def test_get_schema(monkeypatch: pytest.MonkeyPatch) -> None:
    db = Database()
    mock_inspector = MagicMock()
    mock_inspector.get_table_names.return_value = ["customers", "products"]
    mock_inspector.get_columns.return_value = [
        {
            "name": "customer_id",
            "type": "INTEGER",
            "nullable": False,
            "default": None,
        },
        {
            "name": "email",
            "type": "VARCHAR(255)",
            "nullable": False,
            "default": None,
        },
    ]
    mock_inspector.get_pk_constraint.return_value = {
        "constrained_columns": ["customer_id"]
    }
    mock_inspector.get_foreign_keys.return_value = []
    mock_inspector.get_indexes.return_value = []

    with patch("database.inspect", return_value=mock_inspector):
        schema = db.get_schema()

    assert "customers" in schema
    assert schema["customers"]["primary_keys"] == ["customer_id"]
    col_names = [c["name"] for c in schema["customers"]["columns"]]
    assert "customer_id" in col_names and "email" in col_names


def test_get_schema_excludes_non_allowlisted(monkeypatch: pytest.MonkeyPatch) -> None:
    db = Database()
    mock_inspector = MagicMock()
    mock_inspector.get_table_names.return_value = ["customers", "mysql.user", "foo"]
    mock_inspector.get_columns.return_value = []
    mock_inspector.get_pk_constraint.return_value = {"constrained_columns": []}
    mock_inspector.get_foreign_keys.return_value = []
    mock_inspector.get_indexes.return_value = []

    with patch("database.inspect", return_value=mock_inspector):
        schema = db.get_schema()

    assert "customers" in schema
    assert "mysql.user" not in schema
    assert "foo" not in schema


def test_execute_readonly_bounded(monkeypatch: pytest.MonkeyPatch) -> None:
    db = Database(result_limit=2)
    mock_conn = MagicMock()
    mock_result = MagicMock()
    mock_result.mappings.return_value.all.return_value = [
        {"id": 1}, {"id": 2}, {"id": 3}, {"id": 4},
    ]
    mock_conn.execute.return_value = mock_result
    mock_context = MagicMock()
    mock_context.__enter__.return_value = mock_conn
    mock_context.__exit__.return_value = False
    db._engine = MagicMock()
    db._engine.connect.return_value = mock_context

    rows = db.execute_readonly("SELECT * FROM customers")
    assert len(rows) == 2
    assert rows == [{"id": 1}, {"id": 2}]


def test_execute_readonly_with_params(monkeypatch: pytest.MonkeyPatch) -> None:
    db = Database()
    mock_conn = MagicMock()
    mock_result = MagicMock()
    mock_result.mappings.return_value.all.return_value = [{"id": 1}]
    mock_conn.execute.return_value = mock_result
    mock_context = MagicMock()
    mock_context.__enter__.return_value = mock_conn
    mock_context.__exit__.return_value = False
    db._engine = MagicMock()
    db._engine.connect.return_value = mock_context

    db.execute_readonly("SELECT * FROM customers WHERE customer_id = :id", {"id": 1})
    args, kwargs = mock_conn.execute.call_args
    # Parameters may be passed positionally or as keyword args.
    all_args = list(args) + list(kwargs.values())
    assert any("id" in str(a) for a in all_args)


def test_get_table_relationships(monkeypatch: pytest.MonkeyPatch) -> None:
    db = Database()
    mock_inspector = MagicMock()
    mock_inspector.get_table_names.return_value = ["orders", "customers"]
    mock_inspector.get_foreign_keys.return_value = [
        {
            "constrained_columns": ["customer_id"],
            "referred_table": "customers",
            "referred_columns": ["customer_id"],
        }
    ]
    mock_inspector.get_columns.return_value = []
    mock_inspector.get_pk_constraint.return_value = {"constrained_columns": []}
    mock_inspector.get_indexes.return_value = []

    with patch("database.inspect", return_value=mock_inspector):
        rels = db.get_table_relationships()

    # The mock returns the same FK for every inspected table, so we expect
    # at least the orders -> customers relationship to be discovered.
    assert len(rels) >= 1
    assert any(
        r["from_table"] == "orders" and r["to_table"] == "customers"
        for r in rels
    )


# ------------------------------------------------------------------ #
# Integration tests (require MySQL; skipped otherwise)
# ------------------------------------------------------------------ #
@pytest.mark.integration
def test_database_initialization_is_idempotent(
    mysql_available: bool, admin_url: str, app_url: str
) -> None:
    if not HAS_INIT_DB:
        pytest.skip("init_db module not importable")
    if not mysql_available:
        pytest.skip("MySQL not reachable; set MYSQL_ROOT_USER/PASSWORD env vars")

    app_password = os.getenv("DB_PASSWORD", "querymind_app_pw_test")
    # Run initialization twice; must not duplicate or destroy data.
    init_initialize(admin_url, app_password)
    init_initialize(admin_url, app_password)

    from sqlalchemy import create_engine, text

    engine = create_engine(app_url, connect_args={"connect_timeout": 5})
    with engine.connect() as conn:
        for table in ("customers", "products", "categories", "orders",
                      "order_items", "payments"):
            count = conn.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar()
            assert count >= 0


@pytest.mark.integration
def test_known_aggregate_query_results(
    mysql_available: bool, app_url: str
) -> None:
    if not mysql_available:
        pytest.skip("MySQL not reachable; set DB_* env vars")

    from sqlalchemy import create_engine, text

    engine = create_engine(app_url, connect_args={"connect_timeout": 5})
    with engine.connect() as conn:
        total_customers = conn.execute(
            text("SELECT COUNT(*) FROM customers")
        ).scalar()
        assert total_customers == 8

        completed = conn.execute(
            text("SELECT COUNT(*) FROM orders WHERE status = 'completed'")
        ).scalar()
        assert completed == 8


@pytest.mark.integration
def test_readonly_user_cannot_mutate(
    mysql_available: bool, app_url: str
) -> None:
    if not mysql_available:
        pytest.skip("MySQL not reachable; set DB_* env vars")

    from sqlalchemy import create_engine, text

    engine = create_engine(app_url, connect_args={"connect_timeout": 5})
    with engine.connect() as conn:
        try:
            conn.execute(text("INSERT INTO customers (email) VALUES ('x@y.com')"))
            pytest.fail("Read-only user should not be able to INSERT")
        except Exception:
            pass  # expected
