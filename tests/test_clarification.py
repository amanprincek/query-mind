"""Unit tests for the clarification engine.

Deterministic behavior; no database or API credentials required.
"""

from __future__ import annotations

import pytest

from clarification import Clarification, ClarificationEngine


@pytest.fixture
def engine() -> ClarificationEngine:
    return ClarificationEngine(default_time_window_days=30)


def test_clear_question_no_clarification(engine: ClarificationEngine) -> None:
    result = engine.assess("How many customers are there in total?")
    assert result.needed is False
    assert result.question is None


def test_recent_orders_uses_default_window_no_clarification(
    engine: ClarificationEngine,
) -> None:
    result = engine.assess("Show recent orders.")
    assert result.needed is False


def test_best_customers_ambiguous_metric(engine: ClarificationEngine) -> None:
    result = engine.assess("Show me the best customers.")
    assert result.needed is True
    assert result.question is not None
    assert "best customers" in result.question.lower() or "metric" in result.question.lower()


def test_best_customers_with_metric_no_clarification(
    engine: ClarificationEngine,
) -> None:
    result = engine.assess("Show me the best customers by total spent.")
    assert result.needed is False


def test_top_customers_by_orders_no_clarification(engine: ClarificationEngine) -> None:
    result = engine.assess("Top customers by number of orders.")
    assert result.needed is False


def test_highest_customers_ambiguous(engine: ClarificationEngine) -> None:
    result = engine.assess("Which are the highest customers?")
    assert result.needed is True


def test_revenue_ambiguous(engine: ClarificationEngine) -> None:
    result = engine.assess("Show me recent revenue.")
    assert result.needed is True
    assert result.question is not None


def test_revenue_resolved_by_payments_no_clarification(
    engine: ClarificationEngine,
) -> None:
    result = engine.assess("Show revenue from completed payments.")
    assert result.needed is False


def test_revenue_resolved_by_sales_no_clarification(engine: ClarificationEngine) -> None:
    result = engine.assess("Show revenue from product sales.")
    assert result.needed is False


def test_empty_question_no_clarification(engine: ClarificationEngine) -> None:
    result = engine.assess("")
    assert result.needed is False


def test_whitespace_question_no_clarification(engine: ClarificationEngine) -> None:
    result = engine.assess("   ")
    assert result.needed is False


def test_clarification_dataclass_defaults() -> None:
    c = Clarification(needed=True, question="Clarify?", reason="ambiguous")
    assert c.needed is True
    assert c.question == "Clarify?"
    assert c.reason == "ambiguous"

    c2 = Clarification(needed=False)
    assert c2.needed is False
    assert c2.question is None
    assert c2.reason is None
