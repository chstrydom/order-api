import os

import psycopg

from order_api.db import initialise_database


def test_get_product_by_sku():
    database_url = os.environ["DATABASE_URL"]
    initialise_database(database_url)

    with psycopg.connect(database_url) as connection:
        connection.execute(
            """
            INSERT INTO products (sku, name, price_cents, stock)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (sku) DO UPDATE SET
                name = EXCLUDED.name,
                price_cents = EXCLUDED.price_cents,
                stock = EXCLUDED.stock
            """,
            ("sku-1", "Product 1", 1999, 10),
        )

    from order_api.products.repository import get_product_by_sku

    product = get_product_by_sku(database_url, "sku-1")

    assert product == {
        "sku": "sku-1",
        "name": "Product 1",
        "price_cents": 1999,
        "stock": 10,
    }


def test_get_product_by_unknown_sku_returns_none():
    database_url = os.environ["DATABASE_URL"]
    initialise_database(database_url)

    from order_api.products.repository import get_product_by_sku

    product = get_product_by_sku(database_url, "does-not-exist")

    assert product is None


def test_get_products_by_skus_returns_existing_products():
    database_url = os.environ["DATABASE_URL"]
    initialise_database(database_url)

    with psycopg.connect(database_url) as connection, connection.cursor() as cursor:
        cursor.executemany(
            """
                INSERT INTO products (sku, name, price_cents, stock)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (sku) DO UPDATE SET
                    name = EXCLUDED.name,
                    price_cents = EXCLUDED.price_cents,
                    stock = EXCLUDED.stock
                """,
            [
                ("sku-2", "Product 2", 2500, 5),
                ("sku-3", "Product 3", 3500, 8),
            ],
        )

    from order_api.products.repository import get_products_by_skus

    products = get_products_by_skus(
        database_url,
        ["sku-1", "sku-2", "sku-missing"],
    )

    assert products == [
        {"sku": "sku-1", "name": "Product 1", "price_cents": 1999, "stock": 10},
        {"sku": "sku-2", "name": "Product 2", "price_cents": 2500, "stock": 5},
    ]


def test_get_products_by_empty_sku_list_returns_empty_list():
    from order_api.products.repository import get_products_by_skus

    result = get_products_by_skus(
        os.environ["DATABASE_URL"],
        [],
    )

    assert result == []


def test_get_products_by_skus_handles_duplicate_skus():
    from order_api.products.repository import get_products_by_skus

    products = get_products_by_skus(
        os.environ["DATABASE_URL"],
        ["sku-1", "sku-1"],
    )

    assert len(products) == 1
    assert products[0]["sku"] == "sku-1"
