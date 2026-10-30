import os

import psycopg
import pytest
from psycopg import errors

from order_api.db import initialise_database


def test_database_connection():
    with psycopg.connect(os.environ["DATABASE_URL"]) as connection:
        assert connection.execute("SELECT 1").fetchone() == (1,)


def test_schema_initialisation_is_idempotent():
    database_url = os.environ["DATABASE_URL"]

    initialise_database(database_url)
    initialise_database(database_url)

    with psycopg.connect(database_url) as connection:
        rows = connection.execute(
            """
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema = 'public'
            """
        ).fetchall()

    assert {"products", "orders", "order_lines"}.issubset({row[0] for row in rows})


def test_product_cannot_have_negative_stock():
    with (
        psycopg.connect(os.environ["DATABASE_URL"]) as connection,
        pytest.raises(errors.CheckViolation) as exc_info,
    ):
        connection.execute(
            "INSERT INTO products (sku, name, price_cents, stock) "
            "VALUES (%s, %s, %s, %s)",
            ("sku-1", "Product 1", 1999, -2),
        )

    assert exc_info.value.diag.constraint_name == "products_stock_non_negative"


def test_order_line_requires_existing_product_and_order(test_product):
    with (
        psycopg.connect(os.environ["DATABASE_URL"]) as connection,
        pytest.raises(errors.ForeignKeyViolation),
    ):
        connection.execute(
            "INSERT INTO order_lines (order_ref, sku, qty, price_cents) "
            "VALUES (%s, %s, %s, %s)",
            ("NO-SUCH-ORDER", "TEST-001", 1, 199),
        )


def test_order_status_must_be_known_value():
    with (
        psycopg.connect(os.environ["DATABASE_URL"]) as connection,
        pytest.raises(errors.CheckViolation),
    ):
        connection.execute(
            "INSERT INTO orders (order_ref, customer_id, total_cents, status) "
            "VALUES (%s, %s, %s, %s)",
            ("ORD-X", "CUST-1", 0, "SHIPPED"),
        )
