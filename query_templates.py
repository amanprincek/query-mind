"""Deterministic SQL templates for common e-commerce questions.

Explicit metric definitions (do not silently conflate these):

* Sales value     = SUM(order_items.quantity * products.price)
* Paid revenue    = SUM(payments.amount) where payments.status = 'completed'
* Refunds         = SUM(payments.amount) where payments.status = 'refunded'
* Order totals    = orders.total_amount (the order's recorded total)

Order totals and collected payment revenue are intentionally treated as
different concepts.
"""

from __future__ import annotations

from dataclasses import dataclass

DEFAULT_LIMIT = 5
RECENT_WINDOW_DAYS = 30


@dataclass(frozen=True)
class QueryTemplate:
    name: str
    description: str
    sql: str
    params: dict


_TEMPLATES: dict[str, QueryTemplate] = {}


def _register(
    name: str, description: str, sql: str, params: dict | None = None
) -> QueryTemplate:
    template = QueryTemplate(
        name=name,
        description=description,
        sql=sql,
        params=params or {},
    )
    _TEMPLATES[name] = template
    return template


# ---------------------------------------------------------------------- #
# Templates
# ---------------------------------------------------------------------- #
_register(
    "total_customers",
    "Total number of customers.",
    "SELECT COUNT(*) AS total_customers FROM customers;",
)

_register(
    "recent_orders",
    f"Orders placed within the default time window "
    f"({RECENT_WINDOW_DAYS} days), anchored to the latest order date.",
    f"""SELECT o.order_id, o.customer_id, o.order_date, o.status, o.total_amount
       FROM orders o
       WHERE o.order_date >= DATE_SUB(
             (SELECT MAX(order_date) FROM orders), INTERVAL {RECENT_WINDOW_DAYS} DAY
           )
       ORDER BY o.order_date DESC;""",
)

_register(
    "highest_selling_products",
    "Top products by sales value (quantity * unit price).",
    f"""SELECT p.product_id, p.name, p.category_id,
             SUM(oi.quantity * p.price) AS sales_value,
             SUM(oi.quantity) AS units_sold
        FROM order_items oi
        JOIN products p ON p.product_id = oi.product_id
        GROUP BY p.product_id, p.name, p.category_id
        ORDER BY sales_value DESC
        LIMIT {DEFAULT_LIMIT};""",
)

_register(
    "sales_by_category",
    "Total sales value by product category.",
    f"""SELECT c.category_id, c.name AS category,
             SUM(oi.quantity * p.price) AS sales_value
        FROM order_items oi
        JOIN products p ON p.product_id = oi.product_id
        JOIN categories c ON c.category_id = p.category_id
        GROUP BY c.category_id, c.name
        ORDER BY sales_value DESC;""",
)

_register(
    "total_orders_by_status",
    "Count of orders grouped by status.",
    """SELECT o.status, COUNT(*) AS order_count
       FROM orders o
       GROUP BY o.status
       ORDER BY order_count DESC;""",
)

_register(
    "customers_by_completed_purchases",
    "Customers ranked by total value of completed orders (paid revenue).",
    """SELECT c.customer_id, c.first_name, c.last_name, c.email,
             COUNT(o.order_id) AS completed_order_count,
             SUM(o.total_amount) AS total_completed_spent
        FROM customers c
        JOIN orders o ON o.customer_id = c.customer_id
        WHERE o.status = 'completed'
        GROUP BY c.customer_id, c.first_name, c.last_name, c.email
        ORDER BY total_completed_spent DESC;""",
)


def list_templates() -> list[QueryTemplate]:
    """Return all registered templates in definition order."""
    return list(_TEMPLATES.values())


def get_template(name: str) -> QueryTemplate | None:
    """Return a template by name, or None if not registered."""
    return _TEMPLATES.get(name)


# ---------------------------------------------------------------------- #
# Deterministic intent matching
# ---------------------------------------------------------------------- #
def match_template(question: str) -> QueryTemplate | None:
    """Return a matching template if the intent is clear, else None.

    Matching is keyword-based and intentionally conservative: it only
    returns a template when the question clearly maps to one, so the AI
    fallback handles genuinely novel phrasing.

    More specific intents are checked before generic ones so that, for
    example, "customers ranked by total completed purchases" is not
    mistaken for "total customers".
    """
    q = question.lower()

    def has_all(*words: str) -> bool:
        return all(w in q for w in words)

    def has_any(*words: str) -> bool:
        return any(w in q for w in words)

    # Recent orders.
    if has_any("recent orders", "latest orders", "newest orders") or (
        "orders" in q and has_any("recent", "latest", "newest")
    ):
        return get_template("recent_orders")

    # Highest-selling / top products.
    if has_any("highest-selling", "highest selling", "top selling",
               "best selling", "best-selling", "top products", "best products") or (
        "products" in q and has_any("highest", "top", "best", "selling", "sold")
    ):
        return get_template("highest_selling_products")

    # Sales by category.
    if has_any("sales by category", "sales by product category",
               "category sales", "revenue by category"):
        return get_template("sales_by_category")

    # Orders by status.
    if has_all("orders", "status") or has_any("orders by status",
                                              "order status"):
        return get_template("total_orders_by_status")

    # Customers ranked by completed purchases (checked before total_customers
    # because it also contains the words "total" and "customers").
    if has_any("customers by completed purchases", "completed purchases",
               "top customers by completed", "customers ranked by total"):
        return get_template("customers_by_completed_purchases")

    # Total customers.
    if has_all("total", "customers") or q.strip() in {
        "how many customers", "number of customers",
    }:
        return get_template("total_customers")

    return None
