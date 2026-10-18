"""Unit tests for deterministic query templates.

No database required; tests the matching logic and template SQL strings.
"""

from __future__ import annotations

import pytest

from query_templates import (
    match_template,
    list_templates,
    get_template,
    QueryTemplate,
)


def test_list_templates_returns_all() -> None:
    templates = list_templates()
    names = {t.name for t in templates}
    expected = {
        "total_customers",
        "recent_orders",
        "highest_selling_products",
        "sales_by_category",
        "total_orders_by_status",
        "customers_by_completed_purchases",
    }
    assert expected.issubset(names)
    for t in templates:
        assert isinstance(t, QueryTemplate)
        assert t.sql.strip().upper().startswith("SELECT")


def test_get_template_by_name() -> None:
    t = get_template("total_customers")
    assert t is not None
    assert t.name == "total_customers"
    assert "COUNT(*)" in t.sql


def test_match_total_customers() -> None:
    assert match_template("How many customers are there in total?") is not None
    assert match_template("total customers") is not None


def test_match_recent_orders() -> None:
    t = match_template("Show recent orders.")
    assert t is not None
    assert t.name == "recent_orders"
    assert "DATE_SUB" in t.sql and "MAX(order_date)" in t.sql


def test_match_highest_selling_products() -> None:
    t = match_template("Which five products generated the highest sales?")
    assert t is not None
    assert t.name == "highest_selling_products"
    assert "order_items" in t.sql and "products" in t.sql


def test_match_sales_by_category() -> None:
    t = match_template("Sales by product category.")
    assert t is not None
    assert t.name == "sales_by_category"


def test_match_orders_by_status() -> None:
    t = match_template("Show total orders by status.")
    assert t is not None
    assert t.name == "total_orders_by_status"


def test_match_customers_completed_purchases() -> None:
    t = match_template("Customers ranked by total completed purchases.")
    assert t is not None
    assert t.name == "customers_by_completed_purchases"


def test_ambiguous_question_no_template(engine_check=None) -> None:
    # "best customers" without metric -> no template (AI/clarification handles it)
    assert match_template("Show me the best customers.") is None


def test_unrelated_question_no_template() -> None:
    assert match_template("What is the weather like?") is None


def test_highest_selling_products_uses_sales_value_not_order_total() -> None:
    t = get_template("highest_selling_products")
    assert t is not None
    # sales value = quantity * price, not orders.total_amount
    assert "quantity * p.price" in t.sql
    assert "orders.total_amount" not in t.sql


def test_templates_no_mutation_ddl() -> None:
    forbidden = {"INSERT", "UPDATE", "DELETE", "DROP", "ALTER", "CREATE",
                 "TRUNCATE", "REPLACE"}
    for t in list_templates():
        upper = t.sql.upper()
        for kw in forbidden:
            assert kw not in upper, f"Template {t.name} contains {kw}"
