"""Unit tests for SQLGlot-based SQL safety validation.

No database or API credentials are required.
"""

from __future__ import annotations

import pytest

from sql_safety import SqlSafetyValidator, SafetyResult, DEFAULT_MAX_RESULT_COUNT


@pytest.fixture
def validator() -> SqlSafetyValidator:
    return SqlSafetyValidator(max_result_count=DEFAULT_MAX_RESULT_COUNT)


def test_valid_select_accepted(validator: SqlSafetyValidator) -> None:
    result = validator.validate("SELECT * FROM customers LIMIT 10")
    assert isinstance(result, SafetyResult)
    assert result.safe is True
    assert result.sql is not None
    assert "SELECT" in result.sql.upper()


def test_valid_select_with_join_accepted(validator: SqlSafetyValidator) -> None:
    sql = (
        "SELECT p.name, SUM(oi.quantity * p.price) AS sales_value "
        "FROM order_items oi JOIN products p ON p.product_id = oi.product_id "
        "GROUP BY p.name ORDER BY sales_value DESC LIMIT 5"
    )
    result = validator.validate(sql)
    assert result.safe is True


def test_insert_rejected(validator: SqlSafetyValidator) -> None:
    result = validator.validate("INSERT INTO customers (email) VALUES ('x@y.com')")
    assert result.safe is False
    assert result.sql is None


def test_update_rejected(validator: SqlSafetyValidator) -> None:
    result = validator.validate("UPDATE orders SET status = 'cancelled' WHERE order_id = 1")
    assert result.safe is False


def test_delete_rejected(validator: SqlSafetyValidator) -> None:
    result = validator.validate("DELETE FROM order_items WHERE order_id = 1")
    assert result.safe is False


def test_drop_rejected(validator: SqlSafetyValidator) -> None:
    result = validator.validate("DROP TABLE customers")
    assert result.safe is False


def test_alter_rejected(validator: SqlSafetyValidator) -> None:
    result = validator.validate("ALTER TABLE orders ADD COLUMN note TEXT")
    assert result.safe is False


def test_create_rejected(validator: SqlSafetyValidator) -> None:
    result = validator.validate("CREATE TABLE temp (id INT)")
    assert result.safe is False


def test_truncate_rejected(validator: SqlSafetyValidator) -> None:
    result = validator.validate("TRUNCATE TABLE order_items")
    assert result.safe is False


def test_replace_rejected(validator: SqlSafetyValidator) -> None:
    result = validator.validate("REPLACE INTO customers (email) VALUES ('x@y.com')")
    assert result.safe is False


def test_multiple_statements_rejected(validator: SqlSafetyValidator) -> None:
    result = validator.validate(
        "SELECT * FROM customers; SELECT * FROM orders;"
    )
    assert result.safe is False
    assert result.sql is None
    assert any("statement" in e.lower() for e in result.errors)


def test_multiple_statements_with_mutation_rejected(
    validator: SqlSafetyValidator,
) -> None:
    result = validator.validate(
        "SELECT * FROM customers; DROP TABLE customers;"
    )
    assert result.safe is False


def test_select_into_rejected(validator: SqlSafetyValidator) -> None:
    result = validator.validate("SELECT * FROM customers INTO OUTFILE '/tmp/x.csv'")
    assert result.safe is False
    assert any("file" in e.lower() or "into" in e.lower() for e in result.errors)


def test_stored_procedure_call_rejected(validator: SqlSafetyValidator) -> None:
    result = validator.validate("CALL some_procedure()")
    assert result.safe is False


def test_table_allowlist_enforcement(validator: SqlSafetyValidator) -> None:
    result = validator.validate("SELECT * FROM mysql.user")
    assert result.safe is False
    joined = " ".join(result.errors).lower()
    assert "system schema" in joined or "allowed table" in joined


def test_information_schema_rejected(validator: SqlSafetyValidator) -> None:
    result = validator.validate("SELECT * FROM information_schema.tables")
    assert result.safe is False


def test_performance_schema_rejected(validator: SqlSafetyValidator) -> None:
    result = validator.validate("SELECT * FROM performance_schema.tables")
    assert result.safe is False


def test_limit_exceeding_max_rejected(validator: SqlSafetyValidator) -> None:
    result = validator.validate(f"SELECT * FROM customers LIMIT {DEFAULT_MAX_RESULT_COUNT + 1}")
    assert result.safe is False
    assert any("limit" in e.lower() for e in result.errors)


def test_limit_at_max_accepted(validator: SqlSafetyValidator) -> None:
    result = validator.validate(f"SELECT * FROM customers LIMIT {DEFAULT_MAX_RESULT_COUNT}")
    assert result.safe is True


def test_no_limit_is_fine(validator: SqlSafetyValidator) -> None:
    # No explicit LIMIT: result bounding happens at execution time.
    result = validator.validate("SELECT * FROM customers")
    assert result.safe is True


def test_empty_sql_rejected(validator: SqlSafetyValidator) -> None:
    result = validator.validate("")
    assert result.safe is False

    result = validator.validate("   ")
    assert result.safe is False


def test_unparseable_sql_rejected(validator: SqlSafetyValidator) -> None:
    result = validator.validate("SELECT * FROM")
    assert result.safe is False


def test_non_select_rejected(validator: SqlSafetyValidator) -> None:
    result = validator.validate("SHOW TABLES")
    assert result.safe is False


def test_sanitized_sql_is_valid_mysql(validator: SqlSafetyValidator) -> None:
    result = validator.validate("select c.name from customers c limit 3")
    assert result.safe is True
    assert result.sql is not None
    assert result.sql.strip().upper().startswith("SELECT")
