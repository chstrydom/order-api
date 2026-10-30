import os

import psycopg
import pytest

from order_api.products.repository import get_product_by_sku, get_products_by_skus


@pytest.fixture
def seeded_products():
    with (
        psycopg.connect(os.environ["DATABASE_URL"]) as connection,
        connection.cursor() as cursor,
    ):
        cursor.executemany(
            """
            INSERT INTO products (sku, name, price_cents, stock)
            VALUES (%s, %s, %s, %s)
            """,
            [
                ("sku-1", "Product 1", 1999, 10),
                ("sku-2", "Product 2", 2500, 5),
                ("sku-3", "Product 3", 3500, 8),
            ],
        )


def test_get_product_by_sku(seeded_products):
    product = get_product_by_sku(os.environ["DATABASE_URL"], "sku-1")

    assert product == {
        "sku": "sku-1",
        "name": "Product 1",
        "price_cents": 1999,
        "stock": 10,
    }


def test_get_product_by_unknown_sku_returns_none():
    assert get_product_by_sku(os.environ["DATABASE_URL"], "does-not-exist") is None


def test_get_products_by_skus_returns_existing_products(seeded_products):
    products = get_products_by_skus(
        os.environ["DATABASE_URL"],
        ["sku-1", "sku-2", "sku-missing"],
    )

    assert products == [
        {"sku": "sku-1", "name": "Product 1", "price_cents": 1999, "stock": 10},
        {"sku": "sku-2", "name": "Product 2", "price_cents": 2500, "stock": 5},
    ]


def test_get_products_by_empty_sku_list_returns_empty_list():
    assert get_products_by_skus(os.environ["DATABASE_URL"], []) == []


def test_get_products_by_skus_handles_duplicate_skus(seeded_products):
    products = get_products_by_skus(os.environ["DATABASE_URL"], ["sku-1", "sku-1"])

    assert len(products) == 1
    assert products[0]["sku"] == "sku-1"
