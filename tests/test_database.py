import os

import psycopg
import pytest
from psycopg import errors

from order_api.db import initialise_database


def test_database_connection():
    database_url = os.environ["DATABASE_URL"]

    with psycopg.connect(database_url) as connection, connection.cursor() as cursor:
        cursor.execute("SELECT 1")
        result = cursor.fetchone()

    assert result == (1,)


def test_schema_can_be_initialised():
    database_url = os.environ["DATABASE_URL"]

    initialise_database(database_url)

    with psycopg.connect(database_url) as connection, connection.cursor() as cursor:
        cursor.execute("""
                SELECT table_name
                FROM information_schema.tables
                WHERE table_schema = 'public'
            """)
        actual_tables = {row[0] for row in cursor.fetchall()}

    assert {"products", "orders", "order_lines"}.issubset(actual_tables)


def test_product_cannot_have_negative_stock():
    database_url = os.environ["DATABASE_URL"]

    initialise_database(database_url)

    with (
        psycopg.connect(database_url) as connection,
        pytest.raises(errors.CheckViolation) as exc_info,
    ):
        connection.execute(
            """
                INSERT INTO products (sku, name, price_cents, stock)
                VALUES (%s, %s, %s, %s)
                """,
            ("sku-1", "Product 1", 1999, -2),
        )

    assert exc_info.value.diag.constraint_name == "products_stock_non_negative"
