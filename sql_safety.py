"""SQL safety validation using SQLGlot with the MySQL dialect.

Only a single, read-only SELECT statement against the application's
allowlisted tables is permitted. Mutations, DDL, multiple statements,
file operations, stored-procedure execution, and administrative
commands are rejected.

SQLGlot is a parsing/validation aid, not a complete security boundary.
Defense in depth (restricted DB user, statement timeouts, read-only
sessions, result bounding) is also applied.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import sqlglot
from sqlglot import exp

DEFAULT_MAX_RESULT_COUNT = 500

APPLICATION_TABLES = frozenset({
    "customers",
    "products",
    "categories",
    "orders",
    "order_items",
    "payments",
})

SYSTEM_SCHEMA_PREFIXES = frozenset({
    "mysql",
    "information_schema",
    "performance_schema",
    "sys",
})


@dataclass
class SafetyResult:
    safe: bool
    errors: list[str] = field(default_factory=list)
    sql: str | None = None


class SqlSafetyValidator:
    """Validates that a SQL string is a single safe read-only SELECT."""

    def __init__(
        self,
        allowed_tables: frozenset[str] | None = None,
        max_result_count: int = DEFAULT_MAX_RESULT_COUNT,
        dialect: str = "mysql",
    ) -> None:
        self.allowed_tables = allowed_tables or APPLICATION_TABLES
        self.max_result_count = max_result_count
        self.dialect = dialect
        self._allowed_lower = {t.lower() for t in self.allowed_tables}

    def validate(self, sql: str) -> SafetyResult:
        stripped = sql.strip()

        if not stripped:
            return SafetyResult(safe=False, errors=["Empty SQL query."])

        # Reject multiple SQL statements.
        try:
            statements = sqlglot.parse(stripped, read=self.dialect)
        except Exception as exc:  # noqa: BLE001 - validation failure
            return SafetyResult(
                safe=False,
                errors=[f"Unable to parse SQL: {exc}"],
            )

        if len(statements) > 1:
            return SafetyResult(
                safe=False,
                errors=[
                    f"Multiple SQL statements are not allowed "
                    f"(found {len(statements)})."
                ],
            )

        parsed = statements[0]

        # Only a top-level SELECT is permitted.
        if not isinstance(parsed, exp.Select):
            return SafetyResult(
                safe=False,
                errors=[
                    "Only a single read-only SELECT statement is permitted. "
                    "Mutations, DDL, and administrative commands are rejected."
                ],
            )

        errors: list[str] = []
        self._reject_file_operations(parsed, errors)
        self._reject_stored_procedure_calls(parsed, errors)

        # Table allowlist enforcement.
        referenced_tables = self._referenced_tables(parsed)
        for table in referenced_tables:
            name_lower = (table or "").lower()
            if not name_lower:
                continue
            if any(
                name_lower.startswith(prefix) for prefix in SYSTEM_SCHEMA_PREFIXES
            ):
                errors.append(f"Access to system schema '{table}' is not allowed.")
            elif name_lower not in self._allowed_lower:
                errors.append(f"Table '{table}' is not in the allowed table list.")

        # Result-limit enforcement (preserves SQL correctness: the query is
        # not modified; an over-large explicit LIMIT is rejected).
        self._enforce_result_limit(parsed, errors)

        if errors:
            return SafetyResult(safe=False, errors=errors)

        return SafetyResult(safe=True, sql=parsed.sql(dialect=self.dialect))

    # ------------------------------------------------------------------ #
    # Internal helpers
    # ------------------------------------------------------------------ #
    @staticmethod
    def _reject_file_operations(parsed: exp.Expression, errors: list[str]) -> None:
        for node in parsed.walk():
            if isinstance(node, exp.Select) and node.args.get("into"):
                errors.append("SELECT INTO / file output operations are not allowed.")
            if isinstance(node, exp.Anonymous):
                if "LOAD_FILE" in node.sql(dialect="mysql").upper():
                    errors.append("File operations (LOAD_FILE) are not allowed.")

    @staticmethod
    def _reject_stored_procedure_calls(
        parsed: exp.Expression, errors: list[str]
    ) -> None:
        for node in parsed.walk():
            if isinstance(node, exp.Command):
                errors.append("Stored procedure execution is not allowed.")

    @staticmethod
    def _referenced_tables(parsed: exp.Expression) -> list[str]:
        tables: list[str] = []
        for node in parsed.walk():
            if isinstance(node, exp.Table):
                tables.append(node.name or "")
        return tables

    def _enforce_result_limit(
        self, parsed: exp.Expression, errors: list[str]
    ) -> None:
        limit_node = parsed.args.get("limit")
        if limit_node is None:
            # No explicit LIMIT: bounding is applied at execution time.
            return
        try:
            raw = getattr(limit_node.expression, "this", limit_node.expression)
            limit_value = int(raw)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            errors.append("LIMIT clause must contain a numeric value.")
            return
        if limit_value > self.max_result_count:
            errors.append(
                f"LIMIT {limit_value} exceeds the configured maximum of "
                f"{self.max_result_count} rows."
            )
