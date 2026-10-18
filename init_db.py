"""Idempotent database initialization for QueryMind.

Creates the dedicated database, a restricted application user, the six
e-commerce tables, and seeds realistic sample data.

Safety guarantees:
- Never drops an existing database or table.
- Never truncates or resets existing user data.
- Seeds data only when a table is empty (idempotent re-runs).
- Requires an admin connection URL (never hardcoded credentials).
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

DATABASE_NAME = "querymind_db"
APP_USER = "querymind_app"

# ---------------------------------------------------------------------- #
# DDL
# ---------------------------------------------------------------------- #
TABLE_DDL = {
    "categories": """
        CREATE TABLE IF NOT EXISTS categories (
            category_id INT AUTO_INCREMENT PRIMARY KEY,
            name VARCHAR(100) NOT NULL,
            description VARCHAR(255),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
    """,
    "customers": """
        CREATE TABLE IF NOT EXISTS customers (
            customer_id INT AUTO_INCREMENT PRIMARY KEY,
            first_name VARCHAR(50) NOT NULL,
            last_name VARCHAR(50) NOT NULL,
            email VARCHAR(255) NOT NULL UNIQUE,
            city VARCHAR(100),
            country VARCHAR(100),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
    """,
    "products": """
        CREATE TABLE IF NOT EXISTS products (
            product_id INT AUTO_INCREMENT PRIMARY KEY,
            name VARCHAR(200) NOT NULL,
            category_id INT,
            price DECIMAL(10,2) NOT NULL,
            sku VARCHAR(50) UNIQUE,
            stock_quantity INT NOT NULL DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (category_id) REFERENCES categories(category_id)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
    """,
    "orders": """
        CREATE TABLE IF NOT EXISTS orders (
            order_id INT AUTO_INCREMENT PRIMARY KEY,
            customer_id INT NOT NULL,
            order_date DATETIME NOT NULL,
            status ENUM('pending','paid','completed','shipped','cancelled','refunded')
                NOT NULL DEFAULT 'pending',
            total_amount DECIMAL(10,2) NOT NULL DEFAULT 0.00,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (customer_id) REFERENCES customers(customer_id),
            INDEX idx_orders_customer (customer_id),
            INDEX idx_orders_date (order_date),
            INDEX idx_orders_status (status)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
    """,
    "order_items": """
        CREATE TABLE IF NOT EXISTS order_items (
            order_item_id INT AUTO_INCREMENT PRIMARY KEY,
            order_id INT NOT NULL,
            product_id INT NOT NULL,
            quantity INT NOT NULL DEFAULT 1,
            unit_price DECIMAL(10,2) NOT NULL,
            FOREIGN KEY (order_id) REFERENCES orders(order_id),
            FOREIGN KEY (product_id) REFERENCES products(product_id),
            INDEX idx_order_items_order (order_id),
            INDEX idx_order_items_product (product_id)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
    """,
    "payments": """
        CREATE TABLE IF NOT EXISTS payments (
            payment_id INT AUTO_INCREMENT PRIMARY KEY,
            order_id INT NOT NULL,
            amount DECIMAL(10,2) NOT NULL,
            status ENUM('pending','completed','refunded','failed') NOT NULL DEFAULT 'pending',
            payment_date DATETIME NOT NULL,
            FOREIGN KEY (order_id) REFERENCES orders(order_id),
            INDEX idx_payments_order (order_id),
            INDEX idx_payments_status (status)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
    """,
}

# Seed order matters due to foreign keys.
SEED_ORDER = ["categories", "customers", "products", "orders", "order_items", "payments"]

SEED_DATA: dict[str, list[dict[str, Any]]] = {
    "categories": [
        {"name": "Electronics", "description": "Computers, phones, and accessories"},
        {"name": "Clothing", "description": "Apparel and footwear"},
        {"name": "Home & Kitchen", "description": "Household goods and appliances"},
        {"name": "Books", "description": "Print and digital books"},
        {"name": "Sports", "description": "Sporting goods and equipment"},
    ],
    "customers": [
        {"first_name": "Alice", "last_name": "Nguyen", "email": "alice.nguyen@example.com",
         "city": "Seattle", "country": "USA"},
        {"first_name": "Bob", "last_name": "Smith", "email": "bob.smith@example.com",
         "city": "Austin", "country": "USA"},
        {"first_name": "Carol", "last_name": "Martin", "email": "carol.martin@example.com",
         "city": "Toronto", "country": "Canada"},
        {"first_name": "David", "last_name": "Kim", "email": "david.kim@example.com",
         "city": "Vancouver", "country": "Canada"},
        {"first_name": "Eve", "last_name": "Lopez", "email": "eve.lopez@example.com",
         "city": "Mexico City", "country": "Mexico"},
        {"first_name": "Frank", "last_name": "Wu", "email": "frank.wu@example.com",
         "city": "Calgary", "country": "Canada"},
        {"first_name": "Grace", "last_name": "Osei", "email": "grace.osei@example.com",
         "city": "Nairobi", "country": "Kenya"},
        {"first_name": "Hannah", "last_name": "Petrov", "email": "hannah.petrov@example.com",
         "city": "Berlin", "country": "Germany"},
    ],
    "products": [
        {"name": "Laptop Pro 15", "category_id": 1, "price": 1499.99, "sku": "LP15-001",
         "stock_quantity": 42},
        {"name": "Wireless Mouse", "category_id": 1, "price": 29.99, "sku": "WM-002",
         "stock_quantity": 150},
        {"name": "Mechanical Keyboard", "category_id": 1, "price": 89.50, "sku": "MK-003",
         "stock_quantity": 80},
        {"name": "USB-C Hub", "category_id": 1, "price": 45.00, "sku": "UCH-004",
         "stock_quantity": 120},
        {"name": "Cotton T-Shirt", "category_id": 2, "price": 19.99, "sku": "CTS-005",
         "stock_quantity": 200},
        {"name": "Denim Jeans", "category_id": 2, "price": 59.99, "sku": "DJ-006",
         "stock_quantity": 90},
        {"name": "Coffee Maker", "category_id": 3, "price": 79.99, "sku": "CM-007",
         "stock_quantity": 60},
        {"name": "Blender", "category_id": 3, "price": 49.99, "sku": "BL-008",
         "stock_quantity": 55},
        {"name": "Science Fiction Novel", "category_id": 4, "price": 14.99, "sku": "SFN-009",
         "stock_quantity": 300},
        {"name": "Yoga Mat", "category_id": 5, "price": 24.99, "sku": "YM-010",
         "stock_quantity": 100},
    ],
    "orders": [
        {"customer_id": 1, "order_date": "2024-01-10 09:12:00",
         "status": "completed", "total_amount": 1529.98},
        {"customer_id": 2, "order_date": "2024-01-15 14:30:00",
         "status": "completed", "total_amount": 89.50},
        {"customer_id": 1, "order_date": "2024-02-05 11:05:00",
         "status": "completed", "total_amount": 149.97},
        {"customer_id": 3, "order_date": "2024-02-12 16:40:00",
         "status": "shipped", "total_amount": 249.98},
        {"customer_id": 4, "order_date": "2024-03-01 10:15:00",
         "status": "completed", "total_amount": 79.99},
        {"customer_id": 2, "order_date": "2024-03-10 12:00:00",
         "status": "cancelled", "total_amount": 19.99},
        {"customer_id": 5, "order_date": "2024-03-18 08:45:00",
         "status": "completed", "total_amount": 119.97},
        {"customer_id": 1, "order_date": "2024-04-02 19:20:00",
         "status": "completed", "total_amount": 45.00},
        {"customer_id": 6, "order_date": "2024-04-10 13:10:00",
         "status": "pending", "total_amount": 29.99},
        {"customer_id": 7, "order_date": "2024-04-15 17:00:00",
         "status": "completed", "total_amount": 59.98},
        {"customer_id": 8, "order_date": "2024-05-01 09:00:00",
         "status": "refunded", "total_amount": 199.98},
        {"customer_id": 3, "order_date": "2024-05-08 14:30:00",
         "status": "completed", "total_amount": 24.99},
    ],
    "order_items": [
        {"order_id": 1, "product_id": 1, "quantity": 1, "unit_price": 1499.99},
        {"order_id": 1, "product_id": 2, "quantity": 1, "unit_price": 29.99},
        {"order_id": 2, "product_id": 3, "quantity": 1, "unit_price": 89.50},
        {"order_id": 3, "product_id": 5, "quantity": 2, "unit_price": 19.99},
        {"order_id": 3, "product_id": 2, "quantity": 3, "unit_price": 29.99},
        {"order_id": 4, "product_id": 4, "quantity": 2, "unit_price": 45.00},
        {"order_id": 4, "product_id": 10, "quantity": 2, "unit_price": 24.99},
        {"order_id": 5, "product_id": 7, "quantity": 1, "unit_price": 79.99},
        {"order_id": 6, "product_id": 5, "quantity": 1, "unit_price": 19.99},
        {"order_id": 7, "product_id": 6, "quantity": 1, "unit_price": 59.99},
        {"order_id": 7, "product_id": 5, "quantity": 3, "unit_price": 19.99},
        {"order_id": 8, "product_id": 4, "quantity": 1, "unit_price": 45.00},
        {"order_id": 9, "product_id": 2, "quantity": 1, "unit_price": 29.99},
        {"order_id": 10, "product_id": 6, "quantity": 1, "unit_price": 59.99},
        {"order_id": 11, "product_id": 1, "quantity": 1, "unit_price": 1499.99},
        {"order_id": 11, "product_id": 3, "quantity": 1, "unit_price": 89.50},
        {"order_id": 12, "product_id": 10, "quantity": 1, "unit_price": 24.99},
    ],
    "payments": [
        {"order_id": 1, "amount": 1529.98, "status": "completed",
         "payment_date": "2024-01-10 09:15:00"},
        {"order_id": 2, "amount": 89.50, "status": "completed",
         "payment_date": "2024-01-15 14:35:00"},
        {"order_id": 3, "amount": 149.97, "status": "completed",
         "payment_date": "2024-02-05 11:10:00"},
        {"order_id": 4, "amount": 249.98, "status": "pending",
         "payment_date": "2024-02-12 16:45:00"},
        {"order_id": 5, "amount": 79.99, "status": "completed",
         "payment_date": "2024-03-01 10:20:00"},
        {"order_id": 6, "amount": 0.00, "status": "failed",
         "payment_date": "2024-03-10 12:05:00"},
        {"order_id": 7, "amount": 119.97, "status": "completed",
         "payment_date": "2024-03-18 08:50:00"},
        {"order_id": 8, "amount": 45.00, "status": "completed",
         "payment_date": "2024-04-02 19:25:00"},
        {"order_id": 9, "amount": 0.00, "status": "pending",
         "payment_date": "2024-04-10 13:15:00"},
        {"order_id": 10, "amount": 59.98, "status": "completed",
         "payment_date": "2024-04-15 17:05:00"},
        {"order_id": 11, "amount": 199.98, "status": "refunded",
         "payment_date": "2024-05-01 09:05:00"},
        {"order_id": 12, "amount": 24.99, "status": "completed",
         "payment_date": "2024-05-08 14:35:00"},
    ],
}


def _connect(admin_url: str) -> Engine:
    return create_engine(admin_url, pool_pre_ping=True, connect_args={"connect_timeout": 10})


def create_database_and_user(admin_url: str, app_password: str) -> None:
    """Create the database and restricted app user if they do not exist.

    Requires an admin connection URL with sufficient privileges. Never
    drops or alters existing databases/users beyond setting the app
    user's password and grants.
    """
    engine = _connect(admin_url)
    with engine.connect() as conn:
        conn.execute(text(f"CREATE DATABASE IF NOT EXISTS {DATABASE_NAME}"))
        conn.execute(text("COMMIT"))
        # Escape single quotes in the password for a MySQL string literal.
        # APP_USER is a constant; only app_password comes from caller input.
        safe_password = app_password.replace("'", "''")
        # Create the app user for both remote and localhost connections if missing.
        conn.execute(
            text(
                f"CREATE USER IF NOT EXISTS '{APP_USER}'@'%' "
                f"IDENTIFIED BY '{safe_password}'"
            )
        )
        conn.execute(
            text(
                f"CREATE USER IF NOT EXISTS '{APP_USER}'@'localhost' "
                f"IDENTIFIED BY '{safe_password}'"
            )
        )
        # Set/refresh the password and grants (idempotent).
        conn.execute(
            text(
                f"ALTER USER '{APP_USER}'@'%' IDENTIFIED BY '{safe_password}'"
            )
        )
        conn.execute(
            text(
                f"ALTER USER '{APP_USER}'@'localhost' IDENTIFIED BY '{safe_password}'"
            )
        )
        conn.execute(
            text(
                f"GRANT SELECT ON {DATABASE_NAME}.* "
                f"TO '{APP_USER}'@'%', '{APP_USER}'@'localhost'"
            )
        )
        conn.execute(text("COMMIT"))


def create_tables(admin_url: str) -> None:
    """Create the six application tables if they do not exist.

    Idempotent: uses CREATE TABLE IF NOT EXISTS and never drops.
    """
    engine = _connect(admin_url)
    with engine.connect() as conn:
        conn.execute(text(f"USE {DATABASE_NAME}"))
        for table in SEED_ORDER:
            conn.execute(text(TABLE_DDL[table]))
        conn.execute(text("COMMIT"))


def _table_empty(conn, table: str) -> bool:
    result = conn.execute(text(f"SELECT COUNT(*) FROM {table}"))
    return result.scalar() == 0


def _insert_rows(conn, table: str, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    columns = ", ".join(rows[0].keys())
    placeholders = ", ".join(f":{k}" for k in rows[0].keys())
    sql = text(f"INSERT INTO {table} ({columns}) VALUES ({placeholders})")
    for row in rows:
        conn.execute(sql, row)


def seed_data(admin_url: str) -> None:
    """Seed sample data only into empty tables.

    Idempotent: existing rows are never modified or duplicated.
    """
    engine = _connect(admin_url)
    with engine.connect() as conn:
        conn.execute(text(f"USE {DATABASE_NAME}"))
        for table in SEED_ORDER:
            if _table_empty(conn, table):
                _insert_rows(conn, table, SEED_DATA[table])
        conn.execute(text("COMMIT"))


def initialize(admin_url: str, app_password: str) -> None:
    """Run the full idempotent initialization."""
    create_database_and_user(admin_url, app_password)
    create_tables(admin_url)
    seed_data(admin_url)


def app_engine(app_url: str) -> Engine:
    """Return a SQLAlchemy engine for the restricted app user."""
    return create_engine(app_url, pool_pre_ping=True, connect_args={"connect_timeout": 10})
