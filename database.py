"""Database layer for QueryMind.

Secure SQLAlchemy connection management, schema introspection,
foreign-key discovery, connection health checks, and safe read-only
query execution against MySQL.

Credentials are never logged, printed, or returned to the UI.
"""

from __future__ import annotations

import os
from typing import Any
from urllib.parse import quote_plus

from dotenv import load_dotenv
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError

load_dotenv()

# Six application tables that may be queried. MySQL system schemas are
# explicitly excluded.
ALLOWED_TABLES: frozenset[str] = frozenset({
    "customers",
    "products",
    "categories",
    "orders",
    "order_items",
    "payments",
})

DEFAULT_RESULT_LIMIT = 500
DEFAULT_STATEMENT_TIMEOUT_SECONDS = 5


class DatabaseError(Exception):
    """Raised when a database operation fails."""


class Database:
    """Manages a MySQL connection for read-only QueryMind operations."""

    def __init__(
        self,
        connection_url: str | None = None,
        result_limit: int = DEFAULT_RESULT_LIMIT,
        statement_timeout_seconds: int = DEFAULT_STATEMENT_TIMEOUT_SECONDS,
    ) -> None:
        self.connection_url = connection_url or self._build_url_from_env()
        self.result_limit = result_limit
        self.statement_timeout_seconds = statement_timeout_seconds
        self._engine: Engine | None = None

    @staticmethod
    def _build_url_from_env() -> str:
        host = os.getenv("DB_HOST", "localhost")
        port = os.getenv("DB_PORT", "3306")
        name = os.getenv("DB_NAME", "querymind_db")
        user = quote_plus(os.getenv("DB_USER", "querymind_app"))
        password = quote_plus(os.getenv("DB_PASSWORD", ""))
        return (
            f"mysql+pymysql://{user}:{password}@{host}:{port}/{name}"
            f"?charset=utf8mb4"
        )

    @property
    def engine(self) -> Engine:
        if self._engine is None:
            self._engine = create_engine(
                self.connection_url,
                pool_pre_ping=True,
                connect_args={"connect_timeout": 10},
            )
        return self._engine

    def dispose(self) -> None:
        if self._engine is not None:
            self._engine.dispose()
            self._engine = None

    @staticmethod
    def build_url(db_name: str) -> str:
        """Build a connection URL for a specific database name."""
        host = os.getenv("DB_HOST", "localhost")
        port = os.getenv("DB_PORT", "3306")
        user = quote_plus(os.getenv("DB_USER", "querymind_app"))
        password = quote_plus(os.getenv("DB_PASSWORD", ""))
        return (
            f"mysql+pymysql://{user}:{password}@{host}:{port}/{db_name}"
            f"?charset=utf8mb4"
        )

    def switch_database(self, db_name: str) -> None:
        """Switch to a different database by recreating the engine.

        Disposes the current engine and builds a new one for ``db_name``.
        Credentials come from environment variables (host, port, user,
        password); only the database name changes.
        """
        self.connection_url = self.build_url(db_name)
        self.dispose()

    @staticmethod
    def list_databases(admin_url: str | None = None) -> list[str]:
        """Return a list of database names on the MySQL server.

        Requires an admin connection URL (root or user with SHOW DATABASES
        privilege). Returns an empty list if the admin URL is not provided
        or the query fails.
        """
        if not admin_url:
            return []
        try:
            engine = create_engine(
                admin_url,
                pool_pre_ping=True,
                connect_args={"connect_timeout": 10},
            )
            with engine.connect() as conn:
                result = conn.execute(text("SHOW DATABASES"))
                return [row[0] for row in result.fetchall()]
        except SQLAlchemyError:
            return []
        finally:
            try:
                engine.dispose()
            except Exception:  # noqa: BLE001
                pass

    # ------------------------------------------------------------------ #
    # Health checks
    # ------------------------------------------------------------------ #
    def health_check(self) -> dict[str, Any]:
        """Return connection health information without leaking credentials."""
        try:
            with self.engine.connect() as conn:
                version = conn.execute(text("SELECT VERSION()")).scalar()
                current_db = conn.execute(text("SELECT DATABASE()")).scalar()
            return {
                "healthy": True,
                "database": str(current_db) if current_db else None,
                "version": str(version) if version else None,
            }
        except SQLAlchemyError as exc:
            return {
                "healthy": False,
                "error": type(exc).__name__,
                "message": "Unable to connect to the database. Check your .env "
                "configuration and confirm MySQL is running.",
            }
        except Exception as exc:  # noqa: BLE001 - surface to UI generically
            return {
                "healthy": False,
                "error": type(exc).__name__,
                "message": "Unable to connect to the database.",
            }

    # ------------------------------------------------------------------ #
    # Schema introspection
    # ------------------------------------------------------------------ #
    def get_schema(self) -> dict[str, Any]:
        """Introspect schema for the allowlisted application tables.

        Returns a dict keyed by table name with columns, primary keys,
        foreign keys, and indexes. Unknown/missing tables are omitted.
        """
        inspector = inspect(self.engine)
        available = set(inspector.get_table_names())
        schema: dict[str, Any] = {}

        for table in sorted(ALLOWED_TABLES):
            if table not in available:
                continue
            columns = []
            for col in inspector.get_columns(table):
                columns.append(
                    {
                        "name": col["name"],
                        "type": str(col["type"]),
                        "nullable": bool(col.get("nullable", True)),
                        "default": col.get("default"),
                    }
                )
            pk_constraint = inspector.get_pk_constraint(table) or {}
            fks = []
            for fk in inspector.get_foreign_keys(table):
                fks.append(
                    {
                        "columns": fk.get("constrained_columns", []),
                        "referred_table": fk.get("referred_table"),
                        "referred_columns": fk.get("referred_columns", []),
                    }
                )
            indexes = inspector.get_indexes(table) or []
            schema[table] = {
                "columns": columns,
                "primary_keys": pk_constraint.get("constrained_columns", []),
                "foreign_keys": fks,
                "indexes": indexes,
            }
        return schema

    def get_table_relationships(self) -> list[dict[str, Any]]:
        """Return discovered foreign-key relationships between tables."""
        inspector = inspect(self.engine)
        available = set(inspector.get_table_names())
        relationships: list[dict[str, Any]] = []
        for table in sorted(ALLOWED_TABLES):
            if table not in available:
                continue
            for fk in inspector.get_foreign_keys(table):
                referred = fk.get("referred_table")
                if referred in ALLOWED_TABLES:
                    relationships.append(
                        {
                            "from_table": table,
                            "from_columns": fk.get("constrained_columns", []),
                            "to_table": referred,
                            "to_columns": fk.get("referred_columns", []),
                        }
                    )
        return relationships

    # ------------------------------------------------------------------ #
    # Safe read-only query execution
    # ------------------------------------------------------------------ #
    def execute_readonly(
        self, sql: str, params: dict[str, Any] | None = None
    ) -> list[dict[str, Any]]:
        """Execute a parameterized read-only SELECT and return bounded rows.

        The query itself is not modified (SQL correctness is preserved).
        Result rows are bounded at the application layer to ``result_limit``.
        A read-only session and a statement timeout are attempted where the
        server supports them; these are non-fatal if unsupported.
        """
        with self.engine.connect() as conn:
            # Attempt read-only session (non-fatal if unsupported).
            try:
                conn.execute(text("SET SESSION transaction_read_only = ON"))
            except SQLAlchemyError:
                pass

            # Attempt a statement timeout (non-fatal if unsupported).
            try:
                conn.execute(
                    text(
                        f"SET SESSION max_statement_time = "
                        f"{self.statement_timeout_seconds}"
                    )
                )
            except SQLAlchemyError:
                pass

            result = conn.execute(text(sql), params or {})
            rows = result.mappings().all()

        return [dict(row) for row in rows[: self.result_limit]]


def get_database() -> Database:
    """Factory returning a configured :class:`Database` instance."""
    return Database()
