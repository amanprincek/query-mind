"""Clarification engine for ambiguous natural-language questions.

Deterministic heuristics decide whether a question needs clarification
before SQL generation. The intent is to ask only when the request is
genuinely ambiguous, and to avoid unnecessary questions when the intent
is clear.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Clarification:
    needed: bool
    question: str | None = None
    reason: str | None = None


class ClarificationEngine:
    """Detects genuinely ambiguous requests and produces clarification questions."""

    # Terms that make a ranking request ambiguous unless a metric is named.
    AMBIGUOUS_RANKING_TERMS = frozenset({
        "best", "top", "highest", "most", "largest", "greatest",
    })

    # Words that sufficiently specify a metric for customer ranking.
    CUSTOMER_METRIC_WORDS = frozenset({
        "spent", "spending", "order", "orders", "total", "purchase",
        "purchases", "revenue", "value",
    })

    # Words that sufficiently resolve "revenue" to a concrete meaning.
    REVENUE_RESOLVING_WORDS = frozenset({
        "payment", "payments", "paid", "completed", "sale", "sales",
        "product", "products", "order", "orders",
    })

    def __init__(self, default_time_window_days: int = 30) -> None:
        self.default_time_window_days = default_time_window_days

    def assess(self, question: str) -> Clarification:
        """Assess whether ``question`` needs clarification.

        Returns a :class:`Clarification` with ``needed=True`` and a
        specific question only when the request is genuinely ambiguous.
        """
        q = question.strip()
        if not q:
            return Clarification(needed=False)

        q_lower = q.lower()

        # "best/top customers" without a metric -> ambiguous.
        if self._is_customer_ranking(q_lower):
            if not self._metric_specified(q_lower):
                return Clarification(
                    needed=True,
                    question=(
                        "Do you mean the best customers by total amount spent, "
                        "by number of orders, or by another metric?"
                    ),
                    reason="Ambiguous metric for customer ranking.",
                )

        # "revenue" on its own is ambiguous between sales value and
        # collected payments unless the context resolves it.
        if self._is_revenue_query(q_lower) and not self._revenue_resolved(q_lower):
            return Clarification(
                needed=True,
                question=(
                    "Do you mean revenue from product sales value, "
                    "collected completed payments, or another metric?"
                ),
                reason="Ambiguous meaning of 'revenue'.",
            )

        # Time-window phrases like "recent orders" are handled with a
        # documented default window rather than a clarification question.
        return Clarification(needed=False)

    # ------------------------------------------------------------------ #
    # Heuristics
    # ------------------------------------------------------------------ #
    def _is_customer_ranking(self, q_lower: str) -> bool:
        return (
            "customer" in q_lower
            and any(term in q_lower for term in self.AMBIGUOUS_RANKING_TERMS)
        )

    def _metric_specified(self, q_lower: str) -> bool:
        return any(word in q_lower for word in self.CUSTOMER_METRIC_WORDS)

    def _is_revenue_query(self, q_lower: str) -> bool:
        return "revenue" in q_lower

    def _revenue_resolved(self, q_lower: str) -> bool:
        return any(word in q_lower for word in self.REVENUE_RESOLVING_WORDS)
